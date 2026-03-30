import zipfile
from pathlib import Path

try:
    import magic
    HAS_MAGIC = True
except Exception:
    HAS_MAGIC = False

# 확장자 기반 매핑 (fallback)
EXT_MAP = {
    ".pdf": ("pdf", "application/pdf", "PDF"),
    ".hwpx": ("convert", "application/vnd.hancom.hwpx", "HWPX (한글)"),
    ".docx": ("convert", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Word (DOCX)"),
    ".doc": ("convert", "application/msword", "Word (DOC)"),
}

MIME_TYPE_MAP = {
    "application/pdf": "pdf",
    "application/vnd.hancom.hwpx": "convert",
    "application/zip": "check_zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "convert",
    "application/msword": "convert",
}


def detect_file_type(file_path: str) -> dict:
    """파일 형식 판별. magic 사용 가능하면 바이너리 시그니처, 아니면 확장자 기반."""
    ext = Path(file_path).suffix.lower()

    # magic 라이브러리 시도
    if HAS_MAGIC:
        try:
            mime = magic.from_file(file_path, mime=True)
            file_type = MIME_TYPE_MAP.get(mime)
            if file_type == "check_zip":
                file_type = _check_zip_contents(file_path)
            if file_type:
                label_map = {
                    "application/pdf": "PDF",
                    "application/vnd.hancom.hwpx": "HWPX (한글)",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word (DOCX)",
                    "application/msword": "Word (DOC)",
                }
                return {
                    "type": file_type,
                    "mime": mime,
                    "label": label_map.get(mime, mime),
                    "needs_conversion": file_type == "convert",
                }
        except Exception:
            pass

    # 확장자 기반 fallback
    if ext in EXT_MAP:
        ftype, mime, label = EXT_MAP[ext]
        # ZIP 기반 포맷은 내부 확인
        if ext in (".hwpx", ".docx"):
            zip_type = _check_zip_contents(file_path)
            if zip_type:
                ftype = zip_type
        return {
            "type": ftype,
            "mime": mime,
            "label": label,
            "needs_conversion": ftype == "convert",
        }

    return {
        "type": "unsupported",
        "mime": f"unknown ({ext})",
        "label": "지원하지 않는 형식",
        "needs_conversion": False,
    }


def _check_zip_contents(file_path: str) -> str | None:
    try:
        with zipfile.ZipFile(file_path) as z:
            names = z.namelist()
            if any("Contents/section" in n for n in names):
                return "convert"  # HWPX
            if "word/document.xml" in names:
                return "convert"  # DOCX
    except Exception:
        pass
    return None
