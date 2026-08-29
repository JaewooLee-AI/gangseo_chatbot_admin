# 강서나눔돌봄센터 AI 챗봇 최고 관리자용 RAG 통제반 대시보드

이 프로젝트는 **강서나눔돌봄센터** 최고 관리자가 AI 챗봇의 RAG 지식베이스, 법적 가드레일, 페르소나 및 실무진 접근 권한을 통합 통제하기 위해 구축된 파이썬 Streamlit 기반 백엔드 통제반입니다.

Stitch의 **Ace Hotel Chatbot Admin** 디자인 시스템(Pretendard 웹폰트, 따뜻한 오프화이트 `#FAFAF9` 배경, 짙은 차콜 `#1C1917` 및 오렌지 `#F97316` 포인트)과 **100% 한글 UI**가 적용되어 있습니다.

---

## 🚀 빠른 시작 (Quick Start)

### 1. 가상환경 및 패키지 설치

```bash
# 가상환경 생성 및 활성화 (선택)
python3 -m venv venv
source venv/bin/activate

# 의존성 패키지 설치
pip install -r requirements.txt
```

### 2. 환경 변수 / Supabase 연결 설정

`.streamlit/secrets.toml.example` 파일을 복사하여 `.streamlit/secrets.toml`을 생성합니다.

```toml
SUPABASE_URL = "https://your-supabase-project-id.supabase.co"
SUPABASE_KEY = "your-supabase-service-role-key"

# 최고 관리자 로그인(이메일 OTP) 전용 anon 키. service_role 키는 로그인 화면에서 사용하지 않는다.
SUPABASE_ANON_KEY = "your-supabase-anon-key"

QWEN_API_KEY = "sk-xxx"
OPENAI_API_KEY = "sk-xxx"
```

> **참고:** `.streamlit/secrets.toml`에 Supabase 설정이 없더라도, 애플리케이션은 **세션 기반 Mock DB 모드**로 자동 실행되어 즉시 UI 및 모든 기능을 테스트할 수 있습니다(이 모드에서는 로그인도 아무 이메일 + 6자리 숫자로 통과됩니다).

### 🔐 최고 관리자 로그인 (Streamlit Cloud 공개 배포 대응)

Streamlit Cloud에 배포하면 URL을 아는 누구나 접근할 수 있으므로, 이 대시보드는 `../gangseo_chatbot_cs`(담당자 전용 웹앱)와 동일한 **Supabase Auth 이메일 OTP** 방식으로 최상단에 로그인 게이트를 둡니다(`app.py`, `core/auth.py`).

- 담당자 웹앱의 `staff_users` 화이트리스트를 그대로 재사용하되, `is_admin` 컬럼이 `true`인 계정만 이 Streamlit 대시보드에 로그인할 수 있습니다(일반 CS 담당자와 최고 관리자 권한을 분리).
- `👥 직원 계정 관리` 모듈에서 신규 등록 시 "최고 관리자 권한 부여" 체크박스로, 또는 기존 명부의 `🔐 최고관리자` 체크박스로 권한을 즉시 부여/회수할 수 있습니다.
- OTP 발송/검증은 `SUPABASE_ANON_KEY`로 만든 임시 클라이언트로만 처리하고, `service_role` 키(`SUPABASE_KEY`)를 쓰는 전역 데이터 클라이언트와는 분리되어 있습니다.
- 로그인 상태는 `st.session_state`에만 저장됩니다. 즉 새로고침(F5)이나 새 탭에서는 다시 로그인해야 합니다(세션 지속을 위한 쿠키 저장소는 아직 붙이지 않음).

### 3. Streamlit 통제반 실행

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501`로 접속합니다.

---

## 🗄️ Supabase 스키마 셋업

전체 DDL 스크립트는 [`supabase/schema.sql`](./supabase/schema.sql) 에 있습니다. Supabase Dashboard > SQL Editor에 해당 파일 내용을 그대로 붙여넣어 실행하면, 5개 핵심 테이블(pgvector 인덱스 포함), 자동 타임스탬프 트리거, RLS 정책까지 한 번에 구성됩니다. 이미 일부 테이블이 존재해도 안전하게 재실행할 수 있습니다(idempotent).

### 핵심 테이블 구성

| 테이블 | 역할 |
| :---- | :---- |
| `rag_documents` | RAG 지식베이스 청크 + `embedding vector(1536)` |
| `fallback_logs` | HITL 미해결 오답 로그 |
| `bot_settings` | 페르소나/가드레일/엄격도 동적 설정 (단일 레코드) |
| `staff_users` | 직원 화이트리스트 (`department`, `is_active` 포함) |
| `counselor_inquiries` | 챗봇 → 담당자 전달 문의. `category`(자동분류), `assigned_to`/`resolved_by`(담당자 FK), `resolved_at`/`updated_at`(자동 트리거) 포함 |
| `llm_providers` | LLM 벤더별 모델명/최근 테스트 결과 + **Vault 암호화 secret에 대한 포인터**(`vault_secret_id`). 원문 키는 이 테이블에 저장되지 않음 |

### 🔐 LLM API 키 저장 (Supabase Vault)

LLM API 키 원문은 어떤 일반 테이블에도 평문으로 저장하지 않고, Supabase가 기본 제공하는 **Vault**(pgsodium 기반 암호화 저장소)에 저장합니다.

- `llm_providers` 테이블은 `vault_secret_id`(uuid)만 들고 있고, 원문 키는 `vault.secrets`에 암호화되어 있습니다.
- `set_llm_api_key(vendor_id, api_key)` — 키를 Vault에 생성/교체(rotate)합니다.
- `get_llm_api_key(vendor_id)` — 복호화된 키를 반환합니다.
- 두 함수 모두 `security definer`로 만들어졌고 **`service_role`에게만 실행 권한(GRANT)** 이 있습니다. `anon`/`authenticated`는 이 함수를 호출할 수 없고, `llm_providers` 테이블도 RLS만 켜져 있고 정책이 없어(default deny) 절대 조회할 수 없습니다.
- 이 Streamlit 대시보드(`04_llm_manager.py`)는 "연결 테스트"가 실제로 성공(HTTP 200)했을 때만 입력한 키를 Vault에 저장합니다 — 테스트를 통과하지 못한 키는 저장하지 않습니다.
- 추후 Vercel 챗봇 백엔드가 `service_role` 키로 `supabase.rpc('get_llm_api_key', { p_vendor_id: 'openai' })`를 호출하면 요청 시점에 복호화된 키를 받아 LLM API를 호출할 수 있습니다. **service_role 키는 절대 브라우저/클라이언트 번들에 노출되면 안 되며, 서버 사이드(API Route/Edge Function)에서만 사용해야 합니다.**

> ⚠️ Vault는 Supabase 프로젝트에 기본 활성화되어 있지만, 아주 오래된 프로젝트라면 Dashboard → Project Settings → Vault 에서 먼저 활성화해야 `supabase/schema.sql`의 Vault 관련 구문(`vault.secrets`, `vault.create_secret` 등)이 정상 동작합니다.

### 아키텍처와 키 관리 (중요)

3개의 클라이언트가 하나의 Supabase 프로젝트를 공유하는 구조이므로, 앱마다 다른 키를 사용해야 합니다.

- **이 Streamlit 최고관리자 대시보드**: `service_role` 키 사용 권장 (RLS를 완전히 우회하여 모든 테이블 전체 CRUD 필요). Supabase Dashboard > Settings > API에서 발급받아 `.streamlit/secrets.toml`의 `SUPABASE_KEY`에 설정합니다. `anon` 키로도 접속은 되지만, RLS 정책상 직원 관련 조회/처리 및 지식베이스 쓰기 등이 차단됩니다.
- **공개 사용자용 챗봇 (Vercel)**: `anon` 키 사용. `rag_documents`/`bot_settings` 읽기, `fallback_logs`/`counselor_inquiries` 접수(insert)만 가능하도록 RLS로 제한되어 있습니다.
- **담당자 전용 처리 웹앱 (Vercel, 개발 예정)**: `anon` 키 + Supabase Auth(이메일 OTP) 사용. 로그인한 이메일이 `staff_users`에 등록되어 있어야 `counselor_inquiries` 조회/처리(update)가 가능합니다.

#### ⚠️ anon 키로 INSERT할 때 주의: `return=minimal` 필수

`fallback_logs`/`counselor_inquiries`는 anon에게 INSERT만 허용하고 SELECT는 허용하지 않습니다. 이 상태에서 "삽입 후 삽입된 행을 그대로 돌려받는" 기본 동작(`Prefer: return=representation`, supabase-js의 `.insert().select()`, supabase-py의 `insert()` 기본값)을 쓰면 **"new row violates row-level security policy" 오류가 발생합니다** — INSERT 자체는 허용되지만, RETURNING을 위해 방금 넣은 행을 SELECT하려는 시도가 RLS에 막히기 때문입니다.

- **supabase-js**: `.insert(data)` 만 호출하고 `.select()`를 체이닝하지 않으면 기본값이 `return=minimal`이라 안전합니다.
- **supabase-py**: `insert(data, returning="minimal")`로 명시해야 합니다 (`06_simulator.py`에 적용된 방식과 동일).

향후 Vercel 챗봇이 `fallback_logs`에 오답을 기록할 때도 동일하게 `returning="minimal"`(또는 `.select()` 미체이닝)을 사용해야 합니다.

---

## 📱 6대 핵심 비즈니스 모듈 안내

1. **📊 RAG 데이터 파이프라인**: PDF/TXT/Excel 문서 업로드, 카테고리 필수 지정, `st.data_editor` 수동 청크 결합 및 원클릭 Re-embed.
2. **🧠 HITL 오답 리뷰**: AI가 답변하지 못하고 Fallback(상담사 이관) 처리한 사용자 질문에 관리자가 모범 정답(Golden Answer)을 작성하여 즉시 RAG 지식으로 자가진화.
3. **⚙️ AI 페르소나 및 보안 설정**: 톤앤매너(친절한 상담원, 어르신 맞춤형 등), 컴플라이언스 가드레일(의료/질병 진단, 법률, 개인정보 차단), RAG 엄격도(Level 1~5) 동적 프롬프팅.
4. **🔑 멀티 LLM 관리**: Alibaba Qwen, OpenAI, Anthropic Claude, Google Gemini API 키 등록 및 Health Check 핑 테스트.
5. **👥 직원 계정 관리**: Vercel CS 실무 웹앱용 이메일 화이트리스트 등록/회수 (Passwordless OTP), 담당자 전달 문의 카테고리별 조회 및 처리 담당자 지정/완료 처리.
6. **🤖 RAG 챗봇 시뮬레이터**: 실시간 대화 테스트, 가드레일 자동 차단 시뮬레이션, STT 음성 인식 발화 테스트, TTS 음성 출력 시뮬레이션, 담당자 전달 메시지 자동 분류(요금문의/서비스신청/자격상담/불만접수 등) 후 Supabase 접수.
