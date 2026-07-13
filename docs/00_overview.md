# L40 Chatbot Templates - Overview

## Purpose
`nump_L40_chatbot_templates`는 L40 GPU 서버에서 돌리는 **한국어 서식(문서 양식) 자동 작성 시스템**이다. 두 개의 FastAPI 서버로 구성된다. (1) **서식 변환 서버**: HWPX/PDF/DOCX 서식 파일을 업로드하면 로컬 LLM으로 스키마(schema.json)를 추출하고 Jinja2 템플릿(template.j2)을 자동 생성해 재사용 가능한 서식으로 등록한다. (2) **챗봇 서버**: 사용자가 서식을 고르고 대화만 하면, LLM이 대화 내용에서 필드값을 뽑아 문서를 자동으로 채우고 우측 미리보기에 실시간 반영하며 PDF/DOCX/HTML로 내보낸다. LLM은 외부 API(Groq)에서 서버 내 Ollama(qwen3.5:27b) 로컬 모델로 마이그레이션되어, 외부 전송 없이 서버 안에서 처리된다.

## 현재 상태
2026-03-30 작업(2차 업데이트)을 끝으로 활성 개발 없음 — 휴면 상태.
그 시점 기준으로 서식 변환·챗봇·자동 채우기·내보내기(PDF/DOCX/HTML)·음성 입력·수식(KaTeX) 렌더링까지 동작하는 상태이며, 등록된 서식은 회의록과 교수 연구년 허가 신청서 2종이다. 두 서버는 같은 포트(8000)를 교대로 사용하고, 기관 방화벽 때문에 iptables로 80→8000 포워딩해 `http://165.132.223.32` 로 접속한다. (2026-06-24 작업은 CHO Wiki 표준 문서 구조를 GitHub 레포에 추가한 것으로, 서비스 코드 변경은 아니다.)

## Dashboard Metadata
- Project ID: `nump_L40_chatbot_templates`
- Category: `llm_service`
- Tier: C (휴면 / 최소 유지)
- GitHub: https://github.com/boldorite/nump_L40_chatbot_templates
- 마지막 실작업: 2026-03-30

## Known Locations
- `aisemi-l40` / `/home/aisemigpu/workcho/chatbot_with_template/L40_chatbot_with_template` / `deploy`
  - dev history의 서버(165.132.223.32, NVIDIA L40 48GB, Ubuntu) 및 경로와 일치함.
  - 챗봇 서버는 위 경로 하위 `chatbot/` 디렉터리에서 실행.
  - 이 프로젝트가 쓰는 LLM은 해당 서버의 Ollama(qwen3.5:27b-q8_0, 포트 11434)이며, machines.yml에 적힌 vLLM/NUMPMED serving과는 별개 프로세스다.

## Next Action
repo의 `docs/99_next_tasks.md` 기준 별도의 확정된 다음 작업 없음. 재개 시 실제 서버 폴더와 GitHub 동기화 여부 확인부터 할 것.
