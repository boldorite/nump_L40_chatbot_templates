import os
import uuid
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Literal

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from api.services.file_detector import detect_file_type
from api.services.file_converter import convert_to_pdf, extract_text_from_hwpx, extract_text_from_docx
from api.services.pdf_parser import extract_text, generate_preview_image
from api.services.schema_extractor import detect_specimen, extract_schema
from api.services.template_renderer import generate_jinja_template

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
MAX_BATCH_FILES = int(os.getenv("MAX_BATCH_FILES", "200"))
SESSIONS_DIR = DATA_DIR / "batch_sessions"


@dataclass
class BatchFile:
    file_id: str
    original_name: str
    saved_path: str
    status: Literal[
        "pending", "converting", "analyzing", "ready", "registered", "skipped", "error"
    ] = "pending"
    pdf_path: str | None = None
    schema: dict | None = None
    form_number: int | None = None
    is_specimen: bool = False
    error_message: str | None = None


@dataclass
class BatchSession:
    batch_id: str
    files: list[BatchFile] = field(default_factory=list)
    current_index: int = 0
    status: Literal["running", "paused", "completed"] = "running"
    created_at: str = ""
    last_updated: str = ""

    @property
    def completed_files(self):
        return [f for f in self.files if f.status == "registered"]

    @property
    def incomplete_files(self):
        return [
            f
            for f in self.files
            if f.status in ("pending", "converting", "analyzing", "ready", "skipped", "error")
        ]

    def save(self):
        self.last_updated = datetime.now().isoformat()
        path = SESSIONS_DIR / f"{self.batch_id}.json"
        data = {
            "batch_id": self.batch_id,
            "files": [asdict(f) for f in self.files],
            "current_index": self.current_index,
            "status": self.status,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, batch_id: str) -> "BatchSession":
        path = SESSIONS_DIR / f"{batch_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="배치 세션을 찾을 수 없습니다")
        data = json.loads(path.read_text(encoding="utf-8"))
        session = cls(
            batch_id=data["batch_id"],
            current_index=data["current_index"],
            status=data["status"],
            created_at=data["created_at"],
            last_updated=data["last_updated"],
        )
        session.files = [BatchFile(**f) for f in data["files"]]
        return session


@router.post("/batch/start")
async def batch_start(files: list[UploadFile] = File(...)):
    """일괄 업로드, batch_id 반환."""
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=400, detail=f"최대 {MAX_BATCH_FILES}개까지 업로드 가능합니다"
        )

    batch_id = str(uuid.uuid4())[:8]
    upload_dir = DATA_DIR / "uploads"
    batch_files = []

    for f in files:
        file_id = str(uuid.uuid4())[:8]
        ext = Path(f.filename).suffix
        saved_path = upload_dir / f"{file_id}{ext}"
        content = await f.read()
        saved_path.write_bytes(content)
        batch_files.append(
            BatchFile(file_id=file_id, original_name=f.filename, saved_path=str(saved_path))
        )

    session = BatchSession(
        batch_id=batch_id,
        files=batch_files,
        created_at=datetime.now().isoformat(),
    )
    session.save()

    # 자동으로 첫 파일 처리 시작
    _process_next(session)

    return JSONResponse(
        {
            "batch_id": batch_id,
            "total_files": len(batch_files),
            "status": session.status,
        }
    )


@router.get("/batch/list")
async def batch_list():
    """미완료 배치 목록."""
    sessions = []
    for path in SESSIONS_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["status"] != "completed":
            completed = sum(1 for f in data["files"] if f["status"] == "registered")
            sessions.append(
                {
                    "batch_id": data["batch_id"],
                    "total": len(data["files"]),
                    "completed": completed,
                    "remaining": len(data["files"]) - completed,
                    "status": data["status"],
                    "created_at": data["created_at"],
                    "last_updated": data["last_updated"],
                }
            )
    return sessions


@router.get("/batch/{batch_id}/dashboard")
async def batch_dashboard(batch_id: str):
    """완료/미완료 분리 뷰 데이터."""
    session = BatchSession.load(batch_id)
    return {
        "batch_id": batch_id,
        "status": session.status,
        "total": len(session.files),
        "completed": [asdict(f) for f in session.completed_files],
        "incomplete": [asdict(f) for f in session.incomplete_files],
        "current_index": session.current_index,
    }


@router.get("/batch/{batch_id}/current")
async def batch_current(batch_id: str):
    """현재 확인 대기 중인 파일."""
    session = BatchSession.load(batch_id)
    ready_files = [f for f in session.files if f.status == "ready"]
    if not ready_files:
        return {"status": "no_ready_files", "message": "확인 대기 중인 파일이 없습니다"}
    f = ready_files[0]
    return {
        "file_id": f.file_id,
        "original_name": f.original_name,
        "is_specimen": f.is_specimen,
        "schema": f.schema,
    }


@router.post("/batch/{batch_id}/confirm")
async def batch_confirm(batch_id: str, schema_update: dict | None = None):
    """현재 파일 등록 (schema 수정 가능)."""
    session = BatchSession.load(batch_id)
    ready_files = [f for f in session.files if f.status == "ready"]
    if not ready_files:
        raise HTTPException(status_code=400, detail="확인 대기 중인 파일이 없습니다")

    bf = ready_files[0]
    schema = schema_update if schema_update else bf.schema

    # 레지스트리 로드 및 번호 할당
    registry = _load_registry()
    form_number = _next_form_number(registry)
    schema["form_number"] = form_number
    bf.form_number = form_number

    # 저장
    form_dir = DATA_DIR / "templates" / schema["form_id"]
    form_dir.mkdir(parents=True, exist_ok=True)
    (form_dir / "schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    template_str = generate_jinja_template(schema)
    (form_dir / "template.j2").write_text(template_str, encoding="utf-8")

    if bf.pdf_path:
        generate_preview_image(bf.pdf_path, str(form_dir / "preview.png"))

    now = datetime.now().isoformat()
    registry["forms"][str(form_number)] = {
        "form_name": schema["form_name"],
        "form_id": schema["form_id"],
        "schema_path": f"templates/{schema['form_id']}/schema.json",
        "template_path": f"templates/{schema['form_id']}/template.j2",
        "preview_path": f"templates/{schema['form_id']}/preview.png",
        "source": schema.get("source", "empty"),
        "original_filename": bf.original_name,
        "model": os.getenv("MODEL", "unknown"),
        "created_at": now,
        "updated_at": now,
    }
    _save_registry(registry)

    bf.status = "registered"
    bf.schema = schema
    session.save()

    # 다음 파일 처리
    _process_next(session)

    return {"status": "registered", "form_number": form_number}


@router.post("/batch/{batch_id}/skip")
async def batch_skip(batch_id: str):
    """현재 파일 건너뛰기."""
    session = BatchSession.load(batch_id)
    ready_files = [f for f in session.files if f.status == "ready"]
    if not ready_files:
        raise HTTPException(status_code=400, detail="건너뛸 파일이 없습니다")

    ready_files[0].status = "skipped"
    session.save()
    _process_next(session)
    return {"status": "skipped"}


@router.post("/batch/{batch_id}/pause")
async def batch_pause(batch_id: str):
    """작업 중단 + 세션 저장."""
    session = BatchSession.load(batch_id)
    session.status = "paused"
    session.save()
    completed = len(session.completed_files)
    remaining = len(session.incomplete_files)
    return {
        "status": "paused",
        "message": f"작업을 중단했습니다. 완료된 {completed}개는 이미 저장되었습니다. 나머지 {remaining}개는 언제든 이어서 진행할 수 있습니다.",
    }


@router.post("/batch/{batch_id}/resume")
async def batch_resume(batch_id: str):
    """중단된 작업 재개."""
    session = BatchSession.load(batch_id)
    session.status = "running"
    session.save()
    _process_next(session)
    return {
        "status": "running",
        "remaining": len(session.incomplete_files),
    }


@router.get("/batch/{batch_id}/summary")
async def batch_summary(batch_id: str):
    """최종 결과 요약."""
    session = BatchSession.load(batch_id)
    return {
        "batch_id": batch_id,
        "total": len(session.files),
        "registered": len([f for f in session.files if f.status == "registered"]),
        "skipped": len([f for f in session.files if f.status == "skipped"]),
        "errors": len([f for f in session.files if f.status == "error"]),
        "files": [asdict(f) for f in session.files],
    }


@router.delete("/batch/{batch_id}")
async def batch_delete(batch_id: str):
    """미완료 배치 삭제."""
    path = SESSIONS_DIR / f"{batch_id}.json"
    if path.exists():
        path.unlink()
    return {"status": "deleted"}


def _process_next(session: BatchSession):
    """다음 pending 파일을 처리."""
    if session.status != "running":
        return

    pending = [f for f in session.files if f.status == "pending"]
    if not pending:
        # 모든 파일 처리 완료 확인
        if not any(f.status in ("converting", "analyzing") for f in session.files):
            session.status = "completed"
            session.save()
        return

    bf = pending[0]
    try:
        bf.status = "converting"
        session.save()

        # 파일 형식 판별
        file_info = detect_file_type(bf.saved_path)
        if file_info["type"] == "unsupported":
            bf.status = "error"
            bf.error_message = f"지원하지 않는 형식: {file_info['mime']}"
            session.save()
            _process_next(session)
            return

        # 텍스트 추출 (파일 형식에 따라)
        text = ""
        ext_lower = Path(bf.saved_path).suffix.lower()

        if file_info["type"] == "pdf":
            bf.pdf_path = bf.saved_path
            text = extract_text(bf.pdf_path)
        elif file_info["needs_conversion"]:
            # HWPX/DOCX: 직접 텍스트 추출 시도
            if ext_lower == ".hwpx":
                text = extract_text_from_hwpx(bf.saved_path)
            elif ext_lower in (".docx", ".doc"):
                text = extract_text_from_docx(bf.saved_path)
            # 직접 추출 실패 시 LibreOffice (HWPX 제외)
            if not text.strip() and ext_lower != ".hwpx":
                try:
                    bf.pdf_path = convert_to_pdf(bf.saved_path, str(DATA_DIR / "uploads"))
                    text = extract_text(bf.pdf_path)
                except Exception:
                    pass
        else:
            bf.pdf_path = bf.saved_path
            text = extract_text(bf.pdf_path)

        bf.status = "analyzing"
        session.save()

        if not text.strip():
            bf.status = "error"
            bf.error_message = "텍스트를 추출할 수 없습니다"
            session.save()
            _process_next(session)
            return

        specimen_result = detect_specimen(text)
        bf.is_specimen = specimen_result.get("is_specimen", False)

        schema = extract_schema(text, bf.is_specimen)
        bf.schema = schema
        bf.status = "ready"
        session.save()

    except Exception as e:
        bf.status = "error"
        bf.error_message = str(e)
        session.save()
        _process_next(session)


def _load_registry() -> dict:
    path = DATA_DIR / "registry.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"forms": {}}


def _save_registry(registry: dict):
    path = DATA_DIR / "registry.json"
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")


def _next_form_number(registry: dict) -> int:
    if not registry["forms"]:
        return 1
    return max(int(k) for k in registry["forms"].keys()) + 1
