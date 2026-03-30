import pdfplumber
import fitz  # pymupdf


def extract_text(pdf_path: str) -> str:
    """PDF에서 영역별로 구분하여 텍스트 추출.
    머리말, 본문, 테이블, 꼬리말을 위치 기반으로 분리하고
    위치 정보를 포함하여 반환."""
    all_blocks = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            page_height = page.height
            page_width = page.width

            # 머리말/꼬리말 영역 기준 (최소 50px, 최대 페이지 8%)
            header_boundary = max(50, page_height * 0.08)
            footer_boundary = page_height - max(50, page_height * 0.08)

            # 1. 테이블 영역 수집
            tables = page.find_tables()
            table_bboxes = []  # 테이블이 차지하는 영역
            table_blocks = []

            for t_idx, table in enumerate(tables):
                bbox = table.bbox  # (x0, y0, x1, y1)
                table_bboxes.append(bbox)
                rows = table.extract()
                if not rows:
                    continue

                # 테이블 내용을 마크다운 형식으로
                lines = []
                for r_idx, row in enumerate(rows):
                    cells = [str(c).strip() if c else "" for c in row]
                    line = " | ".join(cells)
                    lines.append(line)
                    # 첫 행 뒤에 구분선 (헤더)
                    if r_idx == 0:
                        lines.append(" | ".join(["---"] * len(cells)))

                table_blocks.append({
                    "type": "table",
                    "page": page_idx + 1,
                    "y_pos": bbox[1],
                    "bbox": bbox,
                    "content": "\n".join(lines),
                    "row_count": len(rows),
                    "col_count": len(rows[0]) if rows else 0,
                })

            # 2. 텍스트 워드 단위로 추출 (위치 정보 포함)
            words = page.extract_words(
                x_tolerance=3,
                y_tolerance=3,
                keep_blank_chars=True,
                extra_attrs=["top", "bottom", "x0", "x1"],
            )

            # 테이블 영역에 속하는 워드 제외
            non_table_words = []
            for w in words:
                w_center_y = (w["top"] + w["bottom"]) / 2
                w_center_x = (w["x0"] + w["x1"]) / 2
                in_table = False
                for bbox in table_bboxes:
                    if (bbox[0] - 5 <= w_center_x <= bbox[2] + 5 and
                        bbox[1] - 5 <= w_center_y <= bbox[3] + 5):
                        in_table = True
                        break
                if not in_table:
                    non_table_words.append(w)

            # 3. 워드를 줄 단위로 그룹핑 (y 좌표 기준)
            lines = _group_words_to_lines(non_table_words)

            # 4. 각 줄을 영역별로 분류
            for line_text, line_y in lines:
                if not line_text.strip():
                    continue

                if line_y < header_boundary:
                    region = "header"
                elif line_y > footer_boundary:
                    region = "footer"
                else:
                    region = "body"

                all_blocks.append({
                    "type": region,
                    "page": page_idx + 1,
                    "y_pos": line_y,
                    "content": line_text.strip(),
                })

            # 5. 테이블 블록 추가
            all_blocks.extend(table_blocks)

    # 페이지 순서 → y 위치 순서로 정렬
    all_blocks.sort(key=lambda b: (b["page"], b["y_pos"]))

    # 구조화된 텍스트 생성
    output = _format_blocks(all_blocks)
    return output


def extract_table_row_layout(pdf_path: str) -> list:
    """PDF 테이블에서 같은 행에 있는 셀들의 레이아웃을 추출.
    반환: [{"row_y": float, "cells": ["셀1텍스트", "셀2텍스트", ...]}, ...]
    이 정보로 row_group을 자동 부여할 수 있음."""
    rows_info = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.find_tables()
                for table in tables:
                    extracted = table.extract()
                    if not extracted:
                        continue
                    bbox = table.bbox
                    row_height = (bbox[3] - bbox[1]) / max(len(extracted), 1)

                    for r_idx, row in enumerate(extracted):
                        cells = [str(c).strip() if c else "" for c in row]
                        # 빈 셀이 아닌 셀이 2개 이상인 행만 (라벨+값 쌍이 있는 행)
                        non_empty = [c for c in cells if c]
                        if len(non_empty) >= 2:
                            rows_info.append({
                                "row_y": bbox[1] + r_idx * row_height,
                                "cells": cells,
                                "non_empty_count": len(non_empty),
                            })
    except Exception:
        pass
    return rows_info


def _group_words_to_lines(words: list, y_tolerance: float = 5) -> list:
    """워드를 y좌표 기준으로 줄 단위로 그룹핑."""
    if not words:
        return []

    # y좌표(top) 기준 정렬
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))

    lines = []
    current_line_words = [sorted_words[0]]
    current_y = sorted_words[0]["top"]

    for w in sorted_words[1:]:
        if abs(w["top"] - current_y) <= y_tolerance:
            current_line_words.append(w)
        else:
            # 현재 줄 완성
            current_line_words.sort(key=lambda w: w["x0"])
            text = " ".join(w["text"] for w in current_line_words)
            lines.append((text, current_y))
            current_line_words = [w]
            current_y = w["top"]

    # 마지막 줄
    if current_line_words:
        current_line_words.sort(key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in current_line_words)
        lines.append((text, current_y))

    return lines


def _format_blocks(blocks: list) -> str:
    """블록을 구조화된 텍스트로 포맷."""
    output_lines = []
    current_page = 0
    current_type = None

    for block in blocks:
        # 페이지 구분
        if block["page"] != current_page:
            current_page = block["page"]
            if output_lines:
                output_lines.append("")
            output_lines.append(f"[페이지 {current_page}]")
            current_type = None

        # 영역 변경 시 태그
        btype = block["type"]
        if btype != current_type:
            if btype == "header":
                output_lines.append("[머리말]")
            elif btype == "footer":
                output_lines.append("[꼬리말]")
            elif btype == "table":
                output_lines.append("[표]")
            elif btype == "body" and current_type in ("header", "table"):
                output_lines.append("[본문]")
            current_type = btype

        output_lines.append(block["content"])

    return "\n".join(output_lines)


def extract_text_simple(pdf_path: str) -> str:
    """단순 텍스트 추출 (fallback용)."""
    texts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                texts.append(text)
    return "\n".join(texts)


def generate_preview_image(pdf_path: str, output_path: str, page_num: int = 0) -> str:
    """PDF 첫 페이지를 PNG 이미지로 변환."""
    doc = fitz.open(pdf_path)
    if page_num >= len(doc):
        page_num = 0
    page = doc[page_num]
    mat = fitz.Matrix(2.0, 2.0)  # 2x 해상도
    pix = page.get_pixmap(matrix=mat)
    pix.save(output_path)
    doc.close()
    return output_path
