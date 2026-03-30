# L40_template_by_nump.md
# 작성자: 넘프 (서식 변환 담당)
# 용도: Claude Code 작업지시서 — L40 Ubuntu 서버에서 서식 변환 웹앱 구축
# LLM: 로컬 Ollama + Qwen3.5 35B Q6 양자화
# GPU: NVIDIA L40
# OS: Ubuntu Server
# 최종 수정: 2026-03-30

---

## 이 파일의 역할

L40 GPU가 장착된 Ubuntu 서버에서 Claude Code를 이용해 서식 변환 웹앱을 구축하는 작업지시서.
Windows 데모 환경에서 검증된 코드를 Linux 서버에 그대로 재현하되,
**Groq API 대신 로컬 Ollama + Qwen3.5 35B Q6**을 사용한다.

**장점:**
- API 호출 비용 없음 (완전 무료)
- 네트워크 불필요 (오프라인 동작)
- L40 48GB VRAM → Qwen3.5 35B Q6 (~26GB) 충분히 구동
- 데이터가 외부로 나가지 않음 (보안)

**넘프 ←→ 챗봇 개발자 역할 분리:**
```
넘프 (이 파일 사용)
  → L40 서버에서 서식 변환 웹앱 구축
  → 서식 파일들을 schema.json + template.j2 로 변환
  → 변환된 템플릿 패키지를 챗봇 개발자에게 전달

챗봇 개발자 (template_and_chatbot_integration.md 사용)
  → 전달받은 템플릿을 기존 챗봇에 통합
  → [서식#N] 호출 기능 구현
```

---

## 서버 환경 전제조건

```
GPU: NVIDIA L40 (48GB VRAM)
OS: Ubuntu 22.04+ Server
CUDA: 12.x
Python: 3.11+
Ollama: 설치 필요
모델: qwen3.5:35b-q6_K (Qwen3.5 35B Q6 양자화, ~26GB VRAM)
```

---

## 0단계: 서버 환경 설정 (Claude Code 실행 전 수동)

### Ollama 설치 + 모델 다운로드

```bash
# Ollama 설치
curl -fsSL https://ollama.com/install.sh | sh

# Ollama 서비스 시작
sudo systemctl enable ollama
sudo systemctl start ollama

# Qwen3.5 35B Q6 모델 다운로드 (~26GB)
ollama pull qwen3.5:35b-q6_K

# 모델 확인
ollama list
# qwen3.5:35b-q6_K    26GB

# 테스트
curl http://localhost:11434/api/generate -d '{"model":"qwen3.5:35b-q6_K","prompt":"hello","stream":false}' | head -c 200
```

### LibreOffice 설치 (DOCX→PDF 변환용)

```bash
sudo apt-get update
sudo apt-get install -y libreoffice libmagic1
```

### Python 환경

```bash
sudo apt-get install -y python3.11 python3.11-venv python3-pip
```

---

## 적용 대상

서식이 많은 모든 조직. 도메인 특화 코드 없음.

```
학교       → 가정통신문, 출결확인서, 현장학습 신청서
관공서     → 민원신청서, 보조금신청서, 공문 양식
의료기관   → 진료의뢰서, 동의서, 기록지
법무       → 계약서, 소장, 위임장
회계       → 지출결의서, 세금계산서, 정산보고서
건설·제조  → 작업일지, 안전점검표, 납품확인서
```

---

## 기술 스택

### 백엔드
- **Python 3.11+**
- **FastAPI** + **uvicorn**
- **OpenAI Python SDK** — Ollama OpenAI 호환 API 클라이언트
- **로컬 LLM** — Ollama + Qwen3.5 35B Q6 (L40 48GB)
- **pdfplumber** — PDF 텍스트/테이블 추출
- **pymupdf (fitz)** — 프리뷰 이미지 생성 + PDF 내보내기
- **python-magic** — 파일 형식 자동 판별 (Linux 네이티브)
- **LibreOffice** — DOCX→PDF 변환 (HWPX는 미지원)
- **Jinja2** — HTML 템플릿 렌더링
- **Pydantic v2**
- **python-docx** — DOCX 내보내기

### 프론트엔드
- 단일 `index.html` (vanilla JS + TailwindCSS CDN)
- 빌드 불필요

---

## 파일 구조

```
nump_demo/
├── main.py                       ← FastAPI 진입점, 라우터 등록
├── requirements.txt
├── .env                          ← Ollama 설정
├── api/
│   ├── routes/
│   │   ├── upload.py             ← 단일 업로드 + 분석
│   │   ├── batch.py              ← 일괄 처리 + 중단/재개
│   │   ├── templates.py          ← 템플릿 CRUD
│   │   ├── preview.py            ← HTML 프리뷰 생성
│   │   └── export.py             ← ZIP 내보내기 + 개별 저장 (PDF/DOCX/HTML)
│   └── services/
│       ├── file_detector.py      ← 형식 판별 (magic + 확장자 fallback)
│       ├── file_converter.py     ← LibreOffice 변환 + HWPX/DOCX 직접 추출
│       ├── pdf_parser.py         ← PDF 영역별 파싱 (머리말/본문/표/꼬리말)
│       ├── schema_extractor.py   ← AI 2단계 추출 (로컬 Ollama/Qwen3.5)
│       └── template_renderer.py  ← HTML Jinja2 템플릿 생성/렌더링
├── data/
│   ├── uploads/
│   ├── templates/
│   │   └── {form_id}/
│   │       ├── schema.json
│   │       ├── template.j2
│   │       └── preview.png
│   ├── registry.json
│   └── batch_sessions/
└── static/
    └── index.html
```

---

## 환경 변수 (.env)

```
# 로컬 Ollama (Groq API 대신)
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
MODEL=qwen3.5:35b-q6_K

# 서식 관리
DATA_DIR=./data
MAX_FILE_SIZE_MB=50
MAX_BATCH_FILES=200
BATCH_SESSION_TTL_DAYS=30
```

---

## 핵심 변경점: Groq API → 로컬 Ollama

### schema_extractor.py 변경

Windows 데모에서는 Groq API를 사용했지만, L40 서버에서는 로컬 Ollama를 사용한다.
**변경할 부분은 client 초기화만:**

```python
# 기존 (Groq API)
# client = OpenAI(
#     api_key=os.getenv("GROQ_API_KEY"),
#     base_url="https://api.groq.com/openai/v1",
#     timeout=60,
# )
# MODEL = os.getenv("MODEL", "qwen/qwen3-32b")

# 변경 (로컬 Ollama)
client = OpenAI(
    api_key=os.getenv("LLM_API_KEY", "ollama"),
    base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
    timeout=120,  # 로컬 LLM은 응답이 느릴 수 있음
)
MODEL = os.getenv("MODEL", "qwen3.5:35b-q6_K")
```

**나머지 코드는 동일** — OpenAI 호환 API이므로 프롬프트, 파싱, 2단계 검증 모두 그대로 작동.

### Qwen3.5 thinking 모드 비활성화

Qwen3.5는 기본적으로 thinking 모드가 켜져 있어 JSON 응답 전에 추론 과정을 출력할 수 있음.
`/no_think` 토큰으로 비활성화 (이미 코드에 구현됨):

```python
def _call_llm(system_prompt, user_content, max_tokens=4096):
    if "qwen" in MODEL.lower():
        user_content = "/no_think\n" + user_content
    ...
```

### 타임아웃 설정

로컬 LLM은 Groq보다 느림. 타임아웃을 넉넉하게:
- Groq: 60초
- **로컬 Ollama: 120초**

L40에서 Qwen3.5 35B Q6 예상 성능:
- 2단계 추출 (입력 3000토큰 + 출력 4000토큰): ~15~30초
- 견본 감지 (입력 3000토큰 + 출력 256토큰): ~3~5초

---

## 표준 출력 포맷 (챗봇 개발자와 공유되는 핵심 규격)

**이 포맷은 반드시 지켜야 한다.**

### schema.json

```json
{
  "form_number": 1,
  "form_name": "서식 명칭",
  "form_id": "english_meaning_based_id",
  "description": "이 서식의 용도 (1-2문장)",
  "prompt_prefix": "이 서식 작성을 위해 LLM에게 전달되는 지시 문장",
  "required_fields": ["field_id_1", "field_id_2"],
  "sections": [
    {
      "section_name": "섹션명",
      "fields": [
        {
          "field_id": "영문_소문자",
          "label": "화면에 표시될 레이블",
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
  "source": "empty|specimen",
  "original_filename": "원본파일.pdf",
  "model": "qwen3.5:35b-q6_K"
}
```

### template.j2 (HTML Jinja2)

HTML 형식. 주요 구조:
- `<div class="form-header">` — 서식 제목, 작성일, 문서번호
- `<div class="section">` — 섹션별 구분 (의미 기반)
- `<table class="form-table">` — 필드 라벨/값 테이블 (min-height 적용)
- `<table class="data-table">` — 데이터 테이블 (type=table)
- closing 영역 — 서명/수신처/신청일/첨부 (테이블 밖)

### registry.json

```json
{
  "forms": {
    "1": {
      "form_name": "서식 명칭",
      "form_id": "form_id_value",
      "schema_path": "templates/form_id/schema.json",
      "template_path": "templates/form_id/template.j2",
      "preview_path": "templates/form_id/preview.png",
      "source": "empty",
      "original_filename": "원본파일.pdf",
      "model": "qwen3.5:35b-q6_K",
      "created_at": "2026-03-30T10:00:00",
      "updated_at": "2026-03-30T10:00:00"
    }
  }
}
```

---

## 주요 기능 목록

### 완료된 기능 (Windows 데모에서 검증됨)
- [x] FastAPI 백엔드 전체 API 엔드포인트
- [x] PDF 영역별 구분 추출 (머리말/본문/표/꼬리말)
- [x] HWPX/DOCX 직접 텍스트 추출 + LibreOffice fallback
- [x] AI 2단계 스키마 추출 (1차 추출 → 2차 검증)
- [x] HTML 기반 template.j2 (min-height, closing 필드 분리)
- [x] 단일 업로드 + 일괄 처리 (중단/재개 + 프로그레스 바)
- [x] 서식 CRUD + 내보내기 ZIP + 개별 저장 (PDF/DOCX/HTML)
- [x] row_group (AI 생성 시 적용 + 한국 공문서 패턴 자동 매칭)
- [x] form_id 의미 기반 영문 번역
- [x] 견본 서식 자동 감지
- [x] 원본 파일명 + 사용 모델 자동 저장/표시
- [x] JSON 파싱 개선 (균형 중괄호, field_id 유효성 검증)

### L40 서버에서 기대되는 개선
- Qwen3.5 35B > Qwen3 32B → 한국어 서식 이해력 향상 예상
- 로컬 실행 → 네트워크 지연 없음, 무제한 호출
- Q6 양자화 → 품질 손실 최소 (FP16 대비 ~99%)

---

## API 엔드포인트

```
POST   /api/upload                    단일 파일 업로드 및 분석
POST   /api/batch/start               일괄 업로드
GET    /api/batch/list                미완료 배치 목록
GET    /api/batch/{id}/dashboard      대시보드
GET    /api/batch/{id}/current        현재 확인 대기
POST   /api/batch/{id}/confirm        등록
POST   /api/batch/{id}/skip           건너뛰기
POST   /api/batch/{id}/pause          중단
POST   /api/batch/{id}/resume         재개
DELETE /api/batch/{id}                삭제

GET    /api/templates                 서식 목록
GET    /api/templates/{num}           서식 상세
PUT    /api/templates/{num}           수정
DELETE /api/templates/{num}           삭제

GET    /api/preview/{num}/original    원본 이미지
GET    /api/preview/{num}/rendered    HTML 프리뷰

GET    /api/export/package            전체 ZIP
POST   /api/export/{num}/save         개별 저장 (PDF/DOCX/HTML)
GET    /api/export/{num}/download/{fmt} 개별 다운로드
```

---

## UI/UX 요구사항

- 한국어 UI
- 모든 버튼: 아이콘 + 텍스트 동시 표시
- 글자 크기 15px 이상, 버튼 높이 44px 이상
- 삭제 시 확인 다이얼로그
- 중단 시 "완료된 N개는 이미 저장되었습니다" 안내
- 견본 서식 감지 시 개인정보 안내
- 서식 프리뷰: iframe으로 HTML 렌더링
- 서식 목록: 출처(파일명) + 모델명 + 생성일 표시
- 개별 저장 버튼: PDF / DOCX / HTML

---

## 실행 방법

```bash
# 1. Ollama + 모델 확인
ollama list  # qwen3.5:35b-q6_K 확인
curl http://localhost:11434/v1/models  # API 응답 확인

# 2. 프로젝트 디렉토리 생성
mkdir -p nump_demo && cd nump_demo

# 3. Python 가상환경
python3.11 -m venv venv
source venv/bin/activate

# 4. 의존성 설치
pip install -r requirements.txt

# 5. LibreOffice 확인
which libreoffice  # /usr/bin/libreoffice

# 6. .env 설정 확인
cat .env
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_API_KEY=ollama
# MODEL=qwen3.5:35b-q6_K

# 7. 실행
python main.py
# → http://서버IP:8000

# 8. 외부 접속 허용 시
# main.py의 uvicorn.run에서 host="0.0.0.0" 확인 (기본값)
# 방화벽: sudo ufw allow 8000
```

---

## requirements.txt

```
fastapi
uvicorn
openai
pdfplumber
pymupdf
python-magic
jinja2
pydantic>=2.0
python-multipart
aiofiles
python-dotenv
python-docx
```

**참고:** Linux에서는 `python-magic-bin` 대신 `python-magic` 사용 (libmagic이 시스템에 설치됨).
`weasyprint`, `htmldocx`는 불필요 (pymupdf, python-docx로 대체).

---

## Groq → Ollama 마이그레이션 체크리스트

Claude Code가 코드를 생성할 때 아래 사항을 반영해야 한다:

1. **schema_extractor.py**
   - `client` 초기화: `base_url=LLM_BASE_URL`, `api_key=LLM_API_KEY`
   - `MODEL`: `.env`의 `MODEL` 값 사용
   - `timeout`: 120초 (로컬 LLM은 느림)
   - Qwen thinking 비활성화: `/no_think` 토큰 유지

2. **.env**
   - `GROQ_API_KEY` → `LLM_API_KEY=ollama`
   - `base_url` → `http://localhost:11434/v1`
   - `MODEL` → `qwen3.5:35b-q6_K`

3. **file_detector.py**
   - `python-magic-bin` → `python-magic` (Linux 네이티브)
   - fallback 로직 유지 (안전장치)

4. **file_converter.py**
   - LibreOffice 경로: `/usr/bin/libreoffice` (Linux 기본)
   - Windows 경로 분기 제거 가능

5. **requirements.txt**
   - `python-magic-bin` → `python-magic`
   - `weasyprint`, `htmldocx` 제거

---

## VRAM 사용량 예상

```
Qwen3.5 35B Q6_K: ~26GB VRAM
Ollama 오버헤드:   ~1GB
총 VRAM 사용:     ~27GB / 48GB (L40)
여유 VRAM:        ~21GB (다른 모델 동시 로드 가능)
```

동시 요청 처리:
- Ollama 기본: 1개 요청 순차 처리
- `OLLAMA_NUM_PARALLEL=2` 환경변수로 2개 동시 처리 가능 (VRAM 여유 시)

---

## 성능 튜닝 (선택)

```bash
# Ollama 동시 처리 수 늘리기
export OLLAMA_NUM_PARALLEL=2

# 컨텍스트 길이 늘리기 (긴 서식 처리 시)
# Modelfile 생성
cat > Modelfile << 'EOF'
FROM qwen3.5:35b-q6_K
PARAMETER num_ctx 16384
EOF
ollama create qwen3.5-16k -f Modelfile

# .env에서 모델명 변경
# MODEL=qwen3.5-16k
```

---

## ZIP 패키지로 배포 시 실행 방법

이 MD파일과 함께 `nump_demo/` 폴더가 ZIP으로 제공됩니다.

```bash
# 1. ZIP 풀기
unzip L40_nump_package.zip
cd L40_nump_package

# 2. Ollama + 모델 준비 (미설치 시)
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable ollama && sudo systemctl start ollama
ollama pull qwen3.5:35b-q6_K

# 3. LibreOffice (미설치 시)
sudo apt-get install -y libreoffice libmagic1

# 4. Claude Code에게 지시:
#    "L40_template_by_nump.md를 읽고, nump_demo/ 코드에서
#     schema_extractor.py의 client를 Ollama용으로 수정하고,
#     .env를 L40용으로 수정하고,
#     requirements.txt에서 python-magic-bin을 python-magic으로 바꾸고,
#     실행해줘"

# 5. 수동으로 하려면:
cd nump_demo
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# .env 수정 후
python main.py
```

### Claude Code에게 전달할 한 줄 지시:

```
L40_template_by_nump.md를 CLAUDE.md로 사용하고, nump_demo/ 코드를
Groq API 대신 로컬 Ollama(http://localhost:11434/v1, 모델 qwen3.5:35b-q6_K)를
사용하도록 수정한 뒤 실행해줘.
```

---

## 향후 개선 사항

1. **모델 업그레이드** — Qwen3.5 72B (FP16 필요, 2x L40 또는 A100)
2. **vLLM 전환** — 더 높은 동시 처리량 필요 시
3. **서식 편집 UI** — 웹앱에서 schema 직접 수정
4. **OCR 지원** — 스캔 PDF 처리 (Tesseract)
5. **HTTPS** — nginx 리버스 프록시 + Let's Encrypt
