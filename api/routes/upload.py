import os
import uuid
import json
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from api.services.file_detector import detect_file_type
from api.services.file_converter import convert_to_pdf, extract_text_from_hwpx, extract_text_from_docx
from api.services.pdf_parser import extract_text, generate_preview_image
from api.services.schema_extractor import detect_specimen, extract_schema
from api.services.template_renderer import generate_jinja_template

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "50")) * 1024 * 1024


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """단일 파일 업로드 및 분석."""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="파일 크기가 제한을 초과합니다")

    # 파일 저장
    file_id = str(uuid.uuid4())[:8]
    upload_dir = DATA_DIR / "uploads"
    ext = Path(file.filename).suffix
    saved_path = upload_dir / f"{file_id}{ext}"
    saved_path.write_bytes(content)

    try:
        # 1. 파일 형식 판별
        file_info = detect_file_type(str(saved_path))
        if file_info["type"] == "unsupported":
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 파일 형식입니다: {file_info['mime']}",
            )

        # 2. 텍스트 추출 (파일 형식에 따라 다른 방법)
        text = ""
        pdf_path = None

        if file_info["type"] == "pdf":
            pdf_path = str(saved_path)
            text = extract_text(pdf_path)
        elif file_info["needs_conversion"]:
            # HWPX/DOCX: 직접 텍스트 추출 시도
            ext_lower = ext.lower()
            if ext_lower == ".hwpx":
                text = extract_text_from_hwpx(str(saved_path))
            elif ext_lower in (".docx", ".doc"):
                text = extract_text_from_docx(str(saved_path))

            # 직접 추출 실패 시 LibreOffice 변환 시도 (HWPX는 LibreOffice 미지원이므로 제외)
            if not text.strip() and ext_lower != ".hwpx":
                try:
                    pdf_path = convert_to_pdf(str(saved_path), str(upload_dir))
                    text = extract_text(pdf_path)
                except Exception as conv_err:
                    raise HTTPException(
                        status_code=400,
                        detail=f"파일 변환 실패: {str(conv_err)}"
                    )

        if not text.strip():
            raise HTTPException(
                status_code=400, detail="문서에서 텍스트를 추출할 수 없습니다"
            )

        # 4. 견본 여부 감지
        specimen_result = detect_specimen(text)
        is_specimen = specimen_result.get("is_specimen", False)

        # 5. 스키마 추출
        schema = extract_schema(text, is_specimen)

        # 6. 서식 번호 할당
        registry = _load_registry()
        form_number = _next_form_number(registry)
        schema["form_number"] = form_number

        # 7. 템플릿 디렉토리 생성 및 저장
        form_dir = DATA_DIR / "templates" / schema["form_id"]
        form_dir.mkdir(parents=True, exist_ok=True)

        schema_path = form_dir / "schema.json"
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        template_str = generate_jinja_template(schema)
        template_path = form_dir / "template.j2"
        template_path.write_text(template_str, encoding="utf-8")

        # 8. 프리뷰 이미지 생성 (PDF가 있을 때만)
        preview_path = str(form_dir / "preview.png")
        if pdf_path:
            try:
                generate_preview_image(pdf_path, preview_path)
            except Exception:
                pass

        # 9. 레지스트리 업데이트
        now = datetime.now().isoformat()
        registry["forms"][str(form_number)] = {
            "form_name": schema["form_name"],
            "form_id": schema["form_id"],
            "schema_path": f"templates/{schema['form_id']}/schema.json",
            "template_path": f"templates/{schema['form_id']}/template.j2",
            "preview_path": f"templates/{schema['form_id']}/preview.png",
            "source": schema.get("source", "empty"),
            "original_filename": file.filename,
            "model": os.getenv("MODEL", "unknown"),
            "created_at": now,
            "updated_at": now,
        }
        _save_registry(registry)

        return JSONResponse(
            {
                "status": "success",
                "form_number": form_number,
                "form_name": schema["form_name"],
                "form_id": schema["form_id"],
                "is_specimen": is_specimen,
                "specimen_info": specimen_result if is_specimen else None,
                "schema": schema,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"처리 중 오류: {str(e)}")


def _load_registry() -> dict:
    path = DATA_DIR / "registry.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"forms": {}}


def _save_registry(registry: dict):
    path = DATA_DIR / "registry.json"
    path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _next_form_number(registry: dict) -> int:
    if not registry["forms"]:
        return 1
    return max(int(k) for k in registry["forms"].keys()) + 1
