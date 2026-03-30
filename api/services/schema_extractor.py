import os
import json
import re
from datetime import datetime

import httpx

OLLAMA_BASE = os.getenv("LLM_BASE_URL", "http://localhost:11434").rstrip("/v1").rstrip("/")
MODEL = os.getenv("MODEL", "qwen3.5:27b-q8_0")

SPECIMEN_DETECTION_PROMPT = """아래 문서를 보고 판단하세요.

A) 빈 양식 서식 — 항목명만 있고 내용이 비어있음
B) 작성된 견본 — 실제 이름, 날짜, 수치 등 데이터가 채워져 있음

반드시 아래 JSON 형식만 반환하세요. 다른 텍스트 없이 JSON만:
{"is_specimen": true, "confidence": "high", "detected_real_data": ["이름", "날짜"]}"""

EXTRACTION_PROMPT_EMPTY = """당신은 한국어 공문서/서식 구조 분석 최고 전문가입니다.

## 입력 문서 구조 설명
문서는 영역별 태그로 구분되어 있습니다:
- [페이지 N]: 페이지 번호
- [머리말]: 문서 상단 (기관명, 로고, 문서번호 등)
- [본문]: 서식의 핵심 내용 (입력 필드, 표 등)
- [표]: 테이블 데이터 (| 로 구분된 행/열)
- [꼬리말]: 문서 하단 (서명란, 날짜, 수신처 등)

## 핵심 규칙 — 반드시 준수
1. 모든 영역([머리말], [본문], [표], [꼬리말])을 빠짐없이 분석하세요.
2. 문서의 **모든 입력 항목**을 빠짐없이 추출하세요. 하나라도 누락하면 안 됩니다.
3. 다음 항목들을 특히 주의하여 찾으세요:
   - [머리말]의 기관명, 문서번호, 제목
   - [표] 안의 모든 항목 (행/열 헤더 포함)
   - [본문]의 비상연락처, 연락처, 주소 등 부가 정보
   - [본문]의 업무 대체방안, 인수인계 관련 항목
   - [꼬리말]의 서명란, 날인란, 추천자/확인자란
   - [꼬리말]의 신청일, 신청인, 수신처 (예: "○○대학교 총장 귀하")
   - 첨부서류 목록
   - "해당 없음"으로 비워둘 수 있는 선택 항목
4. 섹션은 **의미적으로** 구분하세요 (테이블 선 굵기로 구분하지 마세요).
   예: "신청인 정보", "연구 계획", "비상연락처" 등 내용 주제가 바뀔 때만 새 섹션.
   같은 테이블 안에서 선 굵기만 다른 경우 같은 섹션으로 유지하세요.
5. [표] 태그 아래의 데이터는 type을 "table"로 하고 table_columns에 열 이름을 넣으세요.
6. 긴 서술 항목(목적, 내용, 사유, 계획 등)은 type을 "textarea"로 하세요.
7. 원본에서 같은 행에 나란히 배치된 필드들은 같은 "row_group" 번호를 부여하세요.
   예: 소속과 성명이 한 행에 있으면 둘 다 "row_group": 1,
       직급과 생년월일이 한 행에 있으면 둘 다 "row_group": 2.
   한 행에 단독으로 있는 필드는 row_group을 생략하세요.

## 출력 형식 (JSON만 반환, 마크다운 없이)
{
  "form_name": "서식의 공식 명칭",
  "form_id": "영문_의미_번역_소문자_언더스코어 (한글발음X, 의미번역O, 예: 교수연구년허가신청서→professor_research_year_application)",
  "description": "이 서식의 용도 (한국어, 1-2문장)",
  "prompt_prefix": "LLM이 이 서식을 작성할 때 따를 지시 문장",
  "sections": [
    {
      "section_name": "섹션명",
      "fields": [
        {
          "field_id": "영문_소문자",
          "label": "화면에 표시될 한국어 레이블",
          "type": "text|number|date|textarea|table",
          "required": true,
          "placeholder": "입력 예시 또는 도움말",
          "table_columns": ["컬럼1", "컬럼2"],
          "row_group": 1
        }
      ]
    }
  ],
  "has_table": false,
  "source": "empty"
}

table_columns는 type이 "table"일 때만 포함하세요."""

EXTRACTION_PROMPT_SPECIMEN = """당신은 한국어 공문서/서식 구조 분석 최고 전문가입니다.
이 문서에는 실제 데이터가 채워져 있습니다.

## 입력 문서 구조 설명
문서는 영역별 태그로 구분되어 있습니다:
- [페이지 N]: 페이지 번호
- [머리말]: 문서 상단 (기관명, 로고, 문서번호 등)
- [본문]: 서식의 핵심 내용 (입력 필드, 표 등)
- [표]: 테이블 데이터 (| 로 구분된 행/열)
- [꼬리말]: 문서 하단 (서명란, 날짜, 수신처 등)

## 핵심 규칙 — 반드시 준수
1. 실제 데이터(이름, 날짜, 수치 등)는 완전히 무시하고, 오직 서식의 **구조**만 분석하세요.
2. 문서의 **모든 입력 항목**을 빠짐없이 추출하세요. 하나라도 누락하면 안 됩니다.
3. 다음 항목들을 특히 주의하여 찾으세요:
   - 표(테이블) 안의 모든 항목 (행/열 헤더 포함)
   - 비상연락처, 연락처, 주소 등 부가 정보
   - 서명란, 날인란, 추천자/확인자란
   - 첨부서류 목록
   - 업무 대체방안, 인수인계 관련 항목
   - "해당 없음"으로 비워둘 수 있는 선택 항목
   - 문서 하단의 신청일, 신청인, 수신처
4. 해석 방법:
   - "홍길동" → 이름 입력 필드
   - "2025-03-29" → 날짜 입력 필드
   - "전자기학, 대체 강의자 수배 완료" → textarea 입력 필드
   - "02-000-9999" → 전화번호 입력 필드
5. 섹션은 **의미적으로** 구분하세요 (테이블 선 굵기로 구분하지 마세요).
   같은 테이블 안에서 선 굵기만 다른 경우 같은 섹션으로 유지하세요.
6. 원본에서 같은 행에 나란히 배치된 필드들은 같은 "row_group" 번호를 부여하세요.
   예: 소속과 성명이 한 행이면 둘 다 "row_group": 1.
   단독 행 필드는 row_group 생략.

## 출력 형식 (JSON만 반환, 마크다운 없이)
{
  "form_name": "서식의 공식 명칭",
  "form_id": "영문_의미_번역_소문자_언더스코어 (한글발음X, 의미번역O, 예: 교수연구년허가신청서→professor_research_year_application)",
  "description": "이 서식의 용도 (한국어, 1-2문장)",
  "prompt_prefix": "LLM이 이 서식을 작성할 때 따를 지시 문장",
  "sections": [
    {
      "section_name": "섹션명",
      "fields": [
        {
          "field_id": "영문_소문자",
          "label": "화면에 표시될 한국어 레이블",
          "type": "text|number|date|textarea|table",
          "required": true,
          "placeholder": "입력 예시 또는 도움말",
          "table_columns": ["컬럼1", "컬럼2"],
          "row_group": 1
        }
      ]
    }
  ],
  "has_table": false,
  "source": "specimen"
}

table_columns는 type이 "table"일 때만, row_group은 같은 행 필드일 때만 포함하세요."""

VERIFICATION_PROMPT = """당신은 서식 구조 검증 전문가입니다.

아래에 원본 문서 텍스트와, 그로부터 추출한 schema JSON이 있습니다.
원본 문서를 한 줄씩 읽으며, schema에 **빠진 항목**이 있는지 검증하세요.

## 검증 체크리스트
- 문서의 모든 입력란/기입란이 schema의 field로 존재하는가?
- 표(테이블)의 모든 열이 table_columns에 있는가?
- 서명란, 확인란, 추천자란이 있는가?
- 비상연락처, 주소, 전화번호 등 부가정보가 있는가?
- 업무 대체방안, 인수인계 항목이 있는가?
- 첨부서류 항목이 있는가?
- 신청일, 신청인, 수신처가 있는가?

## 지시사항
- 빠진 항목이 있으면 해당 항목을 올바른 section에 추가한 **완성된 전체 schema JSON**을 반환하세요.
- 빠진 항목이 없으면 기존 schema를 그대로 반환하세요.
- JSON만 반환. 설명 텍스트 없이."""


def _call_llm(system_prompt: str, user_content: str, max_tokens: int = 4096) -> str:
    # Ollama 네이티브 API (think: false로 thinking 비활성화)
    for fmt in ["json", ""]:
        try:
            payload = {
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt + ("" if fmt else "\n\n반드시 JSON만 반환하세요.")},
                    {"role": "user", "content": user_content},
                ],
                "stream": False,
                "think": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.7,
                },
            }
            if fmt:
                payload["format"] = fmt

            resp = httpx.post(
                f"{OLLAMA_BASE}/api/chat",
                json=payload,
                timeout=120.0,
            )
            resp.raise_for_status()
            text = resp.json().get("message", {}).get("content", "")
            print(f"[LLM] format={fmt!r}, response length={len(text)}")
            if text and text.strip():
                return text
        except Exception as e:
            print(f"[LLM] format={fmt!r}, error: {e}")
            continue

    return ""


def detect_specimen(content: str) -> dict:
    result = _call_llm(
        SPECIMEN_DETECTION_PROMPT,
        f"문서 내용:\n{content[:3000]}",
        max_tokens=256,
    )
    try:
        return _parse_json(result)
    except Exception:
        # 기본값: 빈 양식으로 간주
        return {"is_specimen": False, "confidence": "low", "detected_real_data": []}


def extract_schema(content: str, is_specimen: bool) -> dict:
    # === 1단계: 초기 추출 ===
    prompt = EXTRACTION_PROMPT_SPECIMEN if is_specimen else EXTRACTION_PROMPT_EMPTY
    result = _call_llm(prompt, f"문서 내용:\n{content}")
    schema = _parse_json(result)

    # === 2단계: 검증 및 보완 ===
    try:
        verify_input = (
            f"## 원본 문서 텍스트:\n{content}\n\n"
            f"## 추출된 schema:\n{json.dumps(schema, ensure_ascii=False, indent=2)}"
        )
        verified_result = _call_llm(VERIFICATION_PROMPT, verify_input)
        verified_schema = _parse_json(verified_result)

        # 검증 결과가 유효하면 사용
        if verified_schema.get("sections"):
            schema = verified_schema
    except Exception:
        pass  # 검증 실패 시 1단계 결과 유지

    # field_id 유효성 검증 + required_fields 자동 생성
    required = []
    seen_ids = set()
    for section in schema.get("sections", []):
        for field in section.get("fields", []):
            # field_id 정리
            fid = _sanitize_field_id(field.get("field_id", "field"))
            # 중복 방지
            base_fid = fid
            counter = 2
            while fid in seen_ids:
                fid = f"{base_fid}_{counter}"
                counter += 1
            seen_ids.add(fid)
            field["field_id"] = fid

            if field.get("required"):
                required.append(fid)
    schema["required_fields"] = required

    # AI가 row_group을 생성했으면 유지 (선택적 레이아웃 힌트)
    _auto_assign_row_groups(schema)

    # 타임스탬프
    now = datetime.now().isoformat()
    schema["created_at"] = now
    schema["updated_at"] = now

    return schema


def _auto_assign_row_groups(schema: dict):
    """AI가 row_group을 생성하지 않았을 때, 한국 공문서에서 흔한 패턴만 매칭.
    textarea, table, signature은 항상 단독 행."""
    has_any = False
    for section in schema.get("sections", []):
        for field in section.get("fields", []):
            if field.get("row_group") is not None:
                has_any = True
                break
    if has_any:
        return

    SOLO_TYPES = {"textarea", "table", "signature"}
    PAIR_RULES = [
        ("affiliation", "name"), ("department", "name"), ("department", "applicant"),
        ("position", "birth"), ("rank", "birth"),
        ("visit_country", "visit_institution"), ("visit_location", "institution"),
        ("country", "institution"),
        ("emergency_name", "emergency_relation"),
        ("emergency_contact_name", "emergency_contact_relationship"),
        ("address", "phone"), ("emergency_address", "emergency_phone"),
    ]

    rg_counter = 1
    for section in schema.get("sections", []):
        fields = section.get("fields", [])
        paired = set()
        for i in range(len(fields)):
            if i in paired:
                continue
            fi = fields[i]
            if fi.get("type") in SOLO_TYPES:
                continue
            fid_i = fi.get("field_id", "").lower()

            for j in range(i + 1, min(i + 2, len(fields))):
                if j in paired:
                    continue
                fj = fields[j]
                if fj.get("type") in SOLO_TYPES:
                    continue
                fid_j = fj.get("field_id", "").lower()

                for kw_a, kw_b in PAIR_RULES:
                    if (kw_a in fid_i and kw_b in fid_j) or (kw_b in fid_i and kw_a in fid_j):
                        fi["row_group"] = rg_counter
                        fj["row_group"] = rg_counter
                        rg_counter += 1
                        paired.add(i)
                        paired.add(j)
                        break


def _parse_json(raw: str) -> dict:
    clean = re.sub(r"```json|```", "", raw).strip()
    # 균형 잡힌 중괄호 찾기 (greedy 대신)
    depth = 0
    start = -1
    for i, ch in enumerate(clean):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(clean[start:i+1])
                except json.JSONDecodeError:
                    start = -1
                    continue
    return json.loads(clean)


def _sanitize_field_id(field_id: str) -> str:
    """field_id를 유효한 Python 변수명으로 변환."""
    # 영문/숫자/밑줄만 허용, 나머지 제거
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", field_id)
    # 숫자로 시작하면 접두사 추가
    if sanitized and sanitized[0].isdigit():
        sanitized = "f_" + sanitized
    return sanitized.lower().strip("_") or "field"
