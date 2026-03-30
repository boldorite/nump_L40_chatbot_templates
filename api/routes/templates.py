import os
import json
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))


@router.get("/templates")
async def list_templates():
    """전체 서식 목록."""
    registry = _load_registry()
    forms = []
    for num, info in sorted(registry["forms"].items(), key=lambda x: int(x[0])):
        forms.append({"form_number": int(num), **info})
    return forms


@router.get("/templates/{num}")
async def get_template(num: int):
    """특정 서식 상세."""
    registry = _load_registry()
    info = registry["forms"].get(str(num))
    if not info:
        raise HTTPException(status_code=404, detail="서식을 찾을 수 없습니다")

    schema_path = DATA_DIR / info["schema_path"]
    template_path = DATA_DIR / info["template_path"]

    schema = {}
    if schema_path.exists():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

    template_str = ""
    if template_path.exists():
        template_str = template_path.read_text(encoding="utf-8")

    return {
        "form_number": num,
        **info,
        "schema": schema,
        "template": template_str,
    }


@router.put("/templates/{num}")
async def update_template(num: int, body: dict):
    """서식 수정."""
    registry = _load_registry()
    if str(num) not in registry["forms"]:
        raise HTTPException(status_code=404, detail="서식을 찾을 수 없습니다")

    info = registry["forms"][str(num)]
    schema_path = DATA_DIR / info["schema_path"]

    if "schema" in body:
        schema = body["schema"]
        schema["updated_at"] = datetime.now().isoformat()
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if "template" in body:
        template_path = DATA_DIR / info["template_path"]
        template_path.write_text(body["template"], encoding="utf-8")

    info["updated_at"] = datetime.now().isoformat()
    if "form_name" in body:
        info["form_name"] = body["form_name"]
    _save_registry(registry)

    return {"status": "updated", "form_number": num}


@router.delete("/templates/{num}")
async def delete_template(num: int):
    """서식 삭제."""
    registry = _load_registry()
    if str(num) not in registry["forms"]:
        raise HTTPException(status_code=404, detail="서식을 찾을 수 없습니다")

    info = registry["forms"].pop(str(num))
    _save_registry(registry)

    # 파일 삭제
    form_dir = DATA_DIR / "templates" / info["form_id"]
    if form_dir.exists():
        import shutil
        shutil.rmtree(form_dir)

    return {"status": "deleted", "form_number": num}


@router.patch("/templates/{num}/number")
async def change_form_number(num: int, body: dict):
    """서식 번호 변경."""
    new_num = body.get("new_number")
    if not new_num:
        raise HTTPException(status_code=400, detail="new_number 필드가 필요합니다")

    registry = _load_registry()
    if str(num) not in registry["forms"]:
        raise HTTPException(status_code=404, detail="서식을 찾을 수 없습니다")
    if str(new_num) in registry["forms"]:
        raise HTTPException(status_code=409, detail=f"서식 번호 {new_num}은(는) 이미 사용 중입니다")

    info = registry["forms"].pop(str(num))
    registry["forms"][str(new_num)] = info

    # schema.json 내 form_number도 갱신
    schema_path = DATA_DIR / info["schema_path"]
    if schema_path.exists():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["form_number"] = new_num
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    _save_registry(registry)
    return {"status": "updated", "old_number": num, "new_number": new_num}


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
