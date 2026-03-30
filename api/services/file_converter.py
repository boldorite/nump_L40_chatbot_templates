import subprocess
import shutil
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def convert_to_pdf(input_path: str, output_dir: str) -> str:
    """HWPX / DOCX / DOC → PDF 변환. PDF는 그대로 반환."""
    input_path = Path(input_path)
    if input_path.suffix.lower() == ".pdf":
        return str(input_path)

    # LibreOffice 설치 여부 확인
    libreoffice_path = shutil.which("libreoffice") or shutil.which("soffice")
    if not libreoffice_path:
        raise Exception(
            "LibreOffice가 설치되어 있지 않습니다. "
            "HWPX/DOCX 파일을 변환하려면 LibreOffice를 설치하거나, "
            "PDF로 변환 후 업로드해주세요."
        )

    result = subprocess.run(
        [
            libreoffice_path,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            output_dir,
            str(input_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise Exception(f"변환 실패: {result.stderr}")

    pdf_path = Path(output_dir) / (input_path.stem + ".pdf")
    if not pdf_path.exists():
        raise Exception("변환된 PDF를 찾을 수 없습니다")
    return str(pdf_path)


def extract_text_from_hwpx(file_path: str) -> str:
    """HWPX 파일에서 직접 텍스트 추출. 네임스페이스 무관하게 모든 텍스트 추출."""
    texts = []
    try:
        with zipfile.ZipFile(file_path) as z:
            # section 파일들을 정렬하여 순서대로 처리
            section_files = sorted([
                n for n in z.namelist()
                if ("section" in n.lower() or "Section" in n) and n.endswith(".xml")
            ])
            for name in section_files:
                with z.open(name) as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    # 네임스페이스 제거 후 텍스트 추출
                    _extract_all_text(root, texts)

            # header/footer도 추출 시도
            for name in z.namelist():
                if ("header" in name.lower() or "footer" in name.lower()) and name.endswith(".xml"):
                    try:
                        with z.open(name) as f:
                            tree = ET.parse(f)
                            _extract_all_text(tree.getroot(), texts)
                    except Exception:
                        pass
    except Exception:
        pass
    return "\n".join(texts)


def _extract_all_text(element, texts: list):
    """XML 요소에서 네임스페이스 무관하게 모든 텍스트 추출."""
    # 태그에서 네임스페이스 제거하여 확인
    tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

    # 메타데이터/스타일 태그 건너뛰기
    skip_tags = {"style", "script", "charPr", "paraPr", "tblPr", "tcPr", "cellSpacing", "cellMargin"}
    if tag.lower() in skip_tags:
        return

    if element.text and element.text.strip():
        texts.append(element.text.strip())

    for child in element:
        _extract_all_text(child, texts)

    if element.tail and element.tail.strip():
        texts.append(element.tail.strip())


def extract_text_from_docx(file_path: str) -> str:
    """DOCX 파일에서 텍스트 추출. 본문 + 테이블 + 헤더/푸터 포함."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    texts = []
    try:
        with zipfile.ZipFile(file_path) as z:
            # 본문 + 테이블
            xml_files = ["word/document.xml"]
            # 헤더/푸터 추가
            for name in z.namelist():
                if name.startswith("word/header") or name.startswith("word/footer"):
                    xml_files.append(name)

            for xml_file in xml_files:
                if xml_file not in z.namelist():
                    continue
                with z.open(xml_file) as f:
                    tree = ET.parse(f)
                    root = tree.getroot()

                    # 단락(paragraph) 단위로 텍스트 수집
                    for para in root.iter(f"{{{ns}}}p"):
                        para_texts = []
                        for run in para.iter(f"{{{ns}}}t"):
                            if run.text:
                                para_texts.append(run.text)
                        if para_texts:
                            texts.append("".join(para_texts))

                    # 테이블 셀 내 텍스트 (이미 위에서 추출되지만 구분 표시)
                    for tbl in root.iter(f"{{{ns}}}tbl"):
                        row_texts = []
                        for row in tbl.iter(f"{{{ns}}}tr"):
                            cell_texts = []
                            for cell in row.iter(f"{{{ns}}}tc"):
                                cell_text = []
                                for t in cell.iter(f"{{{ns}}}t"):
                                    if t.text:
                                        cell_text.append(t.text)
                                cell_texts.append("".join(cell_text))
                            if cell_texts:
                                row_texts.append(" | ".join(cell_texts))
                        if row_texts:
                            texts.append("[표]")
                            texts.extend(row_texts)
    except Exception:
        pass
    # 중복 제거 (paragraph 순회에서 테이블 내 텍스트도 나올 수 있음)
    return "\n".join(texts)
