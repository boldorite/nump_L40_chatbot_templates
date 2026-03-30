import os
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from api.services.template_renderer import render_template

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))


@router.get("/preview/{num}/original")
async def preview_original(num: int):
    """원본 파일 프리뷰 이미지."""
    registry = _load_registry()
    info = registry["forms"].get(str(num))
    if not info:
        raise HTTPException(status_code=404, detail="서식을 찾을 수 없습니다")

    preview_path = DATA_DIR / info.get("preview_path", "")
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="프리뷰 이미지가 없습니다")

    return FileResponse(str(preview_path), media_type="image/png")


@router.get("/preview/{num}/rendered")
async def preview_rendered(num: int):
    """렌더링된 템플릿 프리뷰 (샘플 데이터)."""
    registry = _load_registry()
    info = registry["forms"].get(str(num))
    if not info:
        raise HTTPException(status_code=404, detail="서식을 찾을 수 없습니다")

    schema_path = DATA_DIR / info["schema_path"]
    template_path = DATA_DIR / info["template_path"]

    if not schema_path.exists() or not template_path.exists():
        raise HTTPException(status_code=404, detail="템플릿 파일이 없습니다")

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    template_str = template_path.read_text(encoding="utf-8")

    # 빈 서식 데이터 생성 (closing 필드는 제외하여 default 값 표시)
    from api.services.template_renderer import _is_closing_field
    sample_data = {"form_name": schema.get("form_name", "")}
    for section in schema.get("sections", []):
        for field in section.get("fields", []):
            if _is_closing_field(field):
                continue  # closing 필드는 template의 default 값 사용
            fid = field["field_id"]
            ftype = field.get("type", "text")
            if ftype == "table":
                sample_data[fid] = []
            else:
                sample_data[fid] = ""

    rendered = render_template(template_str, sample_data)
    return HTMLResponse(rendered)


def _load_registry() -> dict:
    path = DATA_DIR / "registry.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"forms": {}}
