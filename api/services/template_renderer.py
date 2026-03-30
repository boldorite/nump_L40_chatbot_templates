from jinja2 import Environment, BaseLoader

# 테이블 밖으로 빠져야 하는 필드 (closing 영역)
# field_id 매칭용
CLOSING_ID_KEYWORDS = [
    "signature", "applicant_signature", "recipient",
    "submission_date", "attached", "stamp",
]
# label 매칭용 (정확한 단어 매칭)
CLOSING_LABEL_EXACT = [
    "서명", "날인", "수신처", "귀하", "신청일", "작성일",
    "신청인", "첨부서류", "첨부", "서명/인",
]


def _is_closing_field(field: dict) -> bool:
    """필드가 closing 영역(테이블 밖)에 놓여야 하는지 판단."""
    fid = field.get("field_id", "").lower()
    label = field.get("label", "")

    # field_id에 키워드 포함
    for kw in CLOSING_ID_KEYWORDS:
        if kw in fid:
            return True

    # label이 정확히 매칭되거나 포함
    for kw in CLOSING_LABEL_EXACT:
        if kw == label or kw in label:
            # "인" 단독은 너무 광범위하므로 제외 (날인, 서명/인 등만 매칭)
            return True

    # "귀하"로 끝나는 label (예: "연세대학교 총장 귀하")
    if label.endswith("귀하"):
        return True

    return False


def generate_jinja_template(schema: dict) -> str:
    """schema.json으로부터 HTML template.j2 자동 생성."""
    form_name = schema.get("form_name", "서식")
    sections_html = []
    closing_fields = []  # 테이블 밖으로 빠질 필드들

    for section in schema.get("sections", []):
        table_fields = []
        section_closing = []

        for field in section.get("fields", []):
            if _is_closing_field(field):
                section_closing.append(field)
            else:
                table_fields.append(field)

        # 테이블 필드가 있으면 섹션 생성
        if table_fields:
            fields_html = []

            # row_group별로 그룹핑
            grouped = _group_fields_by_row(table_fields)

            for group in grouped:
                if len(group) == 1:
                    # 단독 행
                    field = group[0]
                    fid = field["field_id"]
                    label = field["label"]
                    ftype = field.get("type", "text")

                    if ftype == "table":
                        cols = field.get("table_columns", [])
                        fields_html.append(_build_table_html(fid, label, cols))
                    elif ftype == "textarea":
                        fields_html.append(f"""      <tr>
        <th class="field-label" colspan="4">{label}</th>
      </tr>
      <tr>
        <td class="field-value-textarea" colspan="4">{{{{ {fid} | default('') }}}}</td>
      </tr>""")
                    elif ftype == "date":
                        fields_html.append(f"""      <tr>
        <th class="field-label">{label}</th>
        <td class="field-value-date" colspan="3">{{{{ {fid} | default('') }}}}</td>
      </tr>""")
                    else:
                        fields_html.append(f"""      <tr>
        <th class="field-label">{label}</th>
        <td class="field-value" colspan="3">{{{{ {fid} | default('') }}}}</td>
      </tr>""")
                else:
                    # 복수 필드 한 행 (row_group)
                    fields_html.append(_build_multi_field_row(group))

            section_html = f"""  <div class="section">
    <div class="section-title">{section['section_name']}</div>
    <table class="form-table">
{chr(10).join(fields_html)}
    </table>
  </div>"""
            sections_html.append(section_html)

        # closing 필드 수집
        closing_fields.extend(section_closing)

    # closing 영역 HTML 생성 — closing 필드가 있는 것만 출력
    closing_html = ""
    if closing_fields:
        closing_parts = []

        # 첨부서류
        attach_fields = [f for f in closing_fields if any(kw in f["field_id"].lower() or kw in f["label"] for kw in ["attach", "첨부"])]
        for f in attach_fields:
            closing_parts.append(f'<p class="closing-text">※ {f["label"]}: {{{{ {f["field_id"]} | default(\'　\') }}}}</p>')

        # 날짜 (신청일/작성일)
        date_fields = [f for f in closing_fields if any(kw in f["field_id"].lower() or kw in f["label"] for kw in ["submission_date", "신청일", "작성일", "application_date"])]

        # 신청인/서명 필드
        sig_fields = [f for f in closing_fields if any(kw in f["field_id"].lower() or kw in f["label"] for kw in ["signature", "서명", "날인", "applicant_signature"])]
        applicant_fields = [f for f in closing_fields if any(kw in f["field_id"].lower() or kw in f["label"] for kw in ["신청인", "applicant"]) and f not in sig_fields]

        # 수신처
        recip_fields = [f for f in closing_fields if any(kw in f["field_id"].lower() or kw in f["label"] for kw in ["recipient", "수신", "귀하"])]

        # "신청합니다" 문구는 신청인/수신처 필드가 있을 때만
        has_application = bool(applicant_fields or recip_fields or any("신청" in f.get("label", "") for f in date_fields))

        if has_application:
            closing_parts.append("""
<div class="closing-statement">
  <p>본인은 관련 규정에 따라 위와 같이 신청합니다.</p>""")
            if date_fields:
                df = date_fields[0]
                closing_parts.append(f'  <p class="closing-date">{{{{ {df["field_id"]} | default(\'　　년　　월　　일\') }}}}</p>')
            else:
                closing_parts.append('  <p class="closing-date">　　년　　월　　일</p>')
            closing_parts.append("</div>")
        elif date_fields:
            # 신청서가 아니면 날짜만 표시
            df = date_fields[0]
            closing_parts.append(f"""
<div class="closing-statement">
  <p class="closing-date">{{{{ {df["field_id"]} | default('') }}}}</p>
</div>""")

        # 서명란 — 필드 label을 그대로 사용 (신청인/작성자/위원장 등)
        if sig_fields:
            sf = sig_fields[0]
            # label에서 역할 추출 (예: "추천자 서명" → "추천자", "신청인 서명" → "신청인")
            sig_label = sf.get("label", "")
            role = sig_label.replace("서명", "").replace("날인", "").replace("또는", "").replace("인", "").replace("/", "").strip() or "작성자"
            closing_parts.append(f"""
<div class="closing-signature">
  <span>{role}</span>
  <span class="sig-name">{{{{ {sf["field_id"]} | default('　　　　') }}}}</span>
  <span>(인)</span>
</div>""")
        elif applicant_fields:
            af = applicant_fields[0]
            closing_parts.append(f"""
<div class="closing-signature">
  <span>{af["label"]}</span>
  <span class="sig-name">{{{{ {af["field_id"]} | default('　　　　') }}}}</span>
  <span>(인)</span>
</div>""")

        # 수신처 — 있을 때만
        if recip_fields:
            rf = recip_fields[0]
            closing_parts.append(f'<div class="closing-recipient">{{{{ {rf["field_id"]} | default(\'○○○○ 귀하\') }}}}</div>')

        closing_html = "\n".join(closing_parts)

    template = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
  @page {{ margin: 20mm; }}
  body {{
    font-family: 'Malgun Gothic', '맑은 고딕', sans-serif;
    font-size: 13px;
    color: #222;
    max-width: 800px;
    margin: 0 auto;
    padding: 30px;
  }}
  .form-header {{
    text-align: center;
    border-bottom: 3px double #333;
    padding-bottom: 15px;
    margin-bottom: 20px;
  }}
  .form-header h1 {{
    font-size: 22px;
    font-weight: bold;
    margin: 0 0 8px 0;
    letter-spacing: 2px;
  }}
  .form-header .meta {{
    font-size: 12px;
    color: #666;
  }}
  .section {{
    margin-bottom: 18px;
  }}
  .section-title {{
    font-size: 14px;
    font-weight: bold;
    background: #f0f0f0;
    padding: 6px 10px;
    border-left: 4px solid #4a5568;
    margin-bottom: 0;
  }}
  .form-table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 5px;
    border: 1px solid #aaa;
  }}
  .form-table th, .form-table td {{
    border: 1px solid #aaa;
    padding: 7px 10px;
    text-align: left;
    vertical-align: top;
  }}
  .form-table th.field-label {{
    background: #f8f8f8;
    font-weight: bold;
    width: 20%;
    font-size: 12px;
    white-space: nowrap;
  }}
  .form-table td.field-value {{
    font-size: 13px;
    min-height: 32px;
    height: auto;
    word-break: break-word;
  }}
  .form-table td.field-value-textarea {{
    font-size: 13px;
    min-height: 100px;
    height: auto;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  .form-table td.field-value-date {{
    font-size: 13px;
    min-height: 32px;
    height: auto;
  }}
  .data-table {{
    width: 100%;
    border-collapse: collapse;
  }}
  .data-table th {{
    background: #e8edf2;
    font-size: 12px;
    font-weight: bold;
    text-align: center;
    padding: 6px 8px;
    border: 1px solid #aaa;
  }}
  .data-table td {{
    padding: 5px 8px;
    border: 1px solid #aaa;
    font-size: 12px;
    text-align: center;
  }}
  .closing-text {{
    font-size: 12px;
    color: #555;
    margin-top: 15px;
  }}
  .closing-statement {{
    text-align: center;
    margin-top: 30px;
    font-size: 14px;
    line-height: 2;
  }}
  .closing-date {{
    font-size: 15px;
    font-weight: bold;
    margin-top: 10px;
  }}
  .closing-signature {{
    text-align: right;
    margin-top: 20px;
    padding-right: 40px;
    font-size: 14px;
  }}
  .closing-signature .sig-name {{
    font-size: 16px;
    font-weight: bold;
    margin: 0 15px;
    border-bottom: 1px solid #333;
    padding-bottom: 2px;
  }}
  .closing-recipient {{
    text-align: center;
    margin-top: 30px;
    font-size: 16px;
    font-weight: bold;
    letter-spacing: 3px;
  }}
  .signature-area {{
    display: flex;
    justify-content: flex-end;
    gap: 40px;
    margin-top: 30px;
    padding-right: 30px;
  }}
  .signature-box {{
    text-align: center;
  }}
  .signature-box .label {{
    font-size: 12px;
    margin-bottom: 5px;
  }}
  .signature-box .line {{
    width: 100px;
    border-bottom: 1px solid #333;
    height: 40px;
  }}
</style>
</head>
<body>

<div class="form-header">
  <h1>{{{{ form_name | default('{form_name}') }}}}</h1>
  <div class="meta">작성일: {{{{ created_date | default('') }}}} &nbsp;&nbsp; 문서번호: {{{{ doc_number | default('') }}}}</div>
</div>

{chr(10).join(sections_html)}

{closing_html}

</body>
</html>"""

    return template


def _group_fields_by_row(fields: list) -> list:
    """row_group이 같은 필드끼리 묶어서 반환. 비연속 row_group도 올바르게 처리."""
    from collections import OrderedDict

    # row_group별로 수집
    rg_map = OrderedDict()
    no_group = []
    result_order = []  # 원래 순서 유지용

    for field in fields:
        rg = field.get("row_group")
        if rg is not None:
            if rg not in rg_map:
                rg_map[rg] = []
                result_order.append(("group", rg))
            rg_map[rg].append(field)
        else:
            result_order.append(("single", field))

    # 원래 순서대로 그룹 조립
    groups = []
    seen_groups = set()
    for item_type, item in result_order:
        if item_type == "group":
            if item not in seen_groups:
                seen_groups.add(item)
                group = rg_map[item]
                # 2필드씩 분할 (3필드 이상이면 행 나눔)
                for i in range(0, len(group), 2):
                    groups.append(group[i:i+2])
        else:
            groups.append([item])

    return groups


def _build_multi_field_row(fields: list) -> str:
    """2필드를 한 행에 배치. | 라벨1 | 값1 | 라벨2 | 값2 |"""
    cells = []
    for field in fields:
        fid = field["field_id"]
        label = field["label"]
        ftype = field.get("type", "text")
        td_class = "field-value-date" if ftype == "date" else "field-value"
        cells.append(f'<th class="field-label" style="width:15%">{label}</th>')
        cells.append(f'<td class="{td_class}" style="width:35%">{{{{ {fid} | default(\'\') }}}}</td>')

    # 2필드 미만이면 colspan으로 채움
    if len(fields) == 1:
        return f"""      <tr>
        {cells[0]}
        <td class="field-value" colspan="3">{{{{ {fields[0]["field_id"]} | default('') }}}}</td>
      </tr>"""

    return f"""      <tr>
        {"".join(cells)}
      </tr>"""


def _build_table_html(fid: str, label: str, cols: list) -> str:
    """테이블 필드를 HTML로 변환."""
    if not cols:
        cols = ["항목", "내용"]

    header_cells = "\n        ".join([f'<th>{c}</th>' for c in cols])

    safe_cols = []
    for c in cols:
        safe = c.replace(" ", "_").replace("/", "_")
        safe_cols.append(safe)

    row_cells = "\n          ".join([f'<td>{{{{ row.{c} | default(\'\') }}}}</td>' for c in safe_cols])

    return f"""      <tr>
        <th class="field-label" colspan="4">{label}</th>
      </tr>
      <tr>
        <td colspan="4" style="padding:0;">
          <table class="data-table">
            <thead>
              <tr>
                {header_cells}
              </tr>
            </thead>
            <tbody>
              {{% if {fid} %}}
              {{% for row in {fid} %}}
              <tr>
                {row_cells}
              </tr>
              {{% endfor %}}
              {{% else %}}
              <tr>
                {"".join([f'<td>&nbsp;</td>' for _ in cols])}
              </tr>
              {{% endif %}}
            </tbody>
          </table>
        </td>
      </tr>"""


def render_template(template_str: str, data: dict) -> str:
    """Jinja2 템플릿에 데이터를 넣어 렌더링."""
    env = Environment(loader=BaseLoader())
    template = env.from_string(template_str)
    return template.render(**data)
