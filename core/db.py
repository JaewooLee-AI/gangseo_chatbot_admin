import os
import streamlit as st
import datetime
import uuid

# Supabase SDK 가져오기 시도
try:
    from supabase import create_client, Client
    HAS_SUPABASE_SDK = True
except ImportError:
    HAS_SUPABASE_SDK = False

class MockTableResponse:
    def __init__(self, data):
        self.data = data

class MockQueryBuilder:
    def __init__(self, table_name):
        self.table_name = table_name
        self.ensure_session_data()
        self.operation = None
        self.payload = None
        self.filters = []
        self.limit_count = None
        self.selected_cols = "*"

    def ensure_session_data(self):
        if "mock_db" not in st.session_state:
            st.session_state.mock_db = {
                "rag_documents": [
                    {
                        "id": str(uuid.uuid4()),
                        "content": "강서나눔돌봄센터 요금 정산 규정: 가사간병 방문 지원 서비스 시급은 기본 15,500원이며, 월 정산일은 매월 25일입니다.",
                        "category": "요금정산",
                        "created_at": datetime.datetime.now().isoformat()
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "content": "어르신 돌봄 자격 요건: 강서구 관내 만 65세 이상 기초생활수급자 및 차상위 계층 어르신을 우선 선정 대상으로 합니다.",
                        "category": "자격요건",
                        "created_at": datetime.datetime.now().isoformat()
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "content": "긴급 돌봄 서비스 신청 시 신분증 복사본과 소득증빙서류 1부를 센터 민원실로 제출해야 합니다.",
                        "category": "내부규정",
                        "created_at": datetime.datetime.now().isoformat()
                    }
                ],
                "fallback_logs": [
                    {
                        "id": str(uuid.uuid4()),
                        "content": None,
                        "user_query": "치매 어르신 야간 긴급 가사간병도 지원되나요?",
                        "status": "pending",
                        "golden_answer": None,
                        "created_at": (datetime.datetime.now() - datetime.timedelta(hours=2)).isoformat()
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "content": None,
                        "user_query": "센터 방문 정산 시 주차비 지원 여부 알 수 있나요?",
                        "status": "pending",
                        "golden_answer": None,
                        "created_at": (datetime.datetime.now() - datetime.timedelta(hours=5)).isoformat()
                    }
                ],
                "bot_settings": [
                    {
                        "id": 1,
                        "tone": "친절한 상담원",
                        "block_medical": True,
                        "block_legal": True,
                        "block_privacy": True,
                        "strictness_level": 5
                    }
                ],
                "staff_users": [
                    {
                        "id": str(uuid.uuid4()),
                        "staff_name": "김복지",
                        "email": "welfare.kim@gangseo.go.kr",
                        "department": "민원상담팀",
                        "is_active": True,
                        "created_at": (datetime.datetime.now() - datetime.timedelta(days=10)).isoformat()
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "staff_name": "이돌봄",
                        "email": "care.lee@gangseo.go.kr",
                        "department": "긴급돌봄팀",
                        "is_active": True,
                        "created_at": (datetime.datetime.now() - datetime.timedelta(days=5)).isoformat()
                    }
                ],
                "counselor_inquiries": [
                    {
                        "id": str(uuid.uuid4()),
                        "user_name": "박어르신",
                        "contact_info": "010-3456-7890",
                        "inquiry_summary": "주말 가사간병 방문 지원 가능 여부 및 요금 상담 요청",
                        "raw_message": "안녕하세요. 주말에 어머니 가사간병 방문 지원을 받고 싶은데 010-3456-7890으로 연락 바랍니다.",
                        "input_type": "text",
                        "category": "요금문의",
                        "status": "pending",
                        "admin_note": None,
                        "assigned_to": None,
                        "resolved_by": None,
                        "resolved_at": None,
                        "created_at": (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat(),
                        "updated_at": (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "user_name": "이민원",
                        "contact_info": "010-9876-5432",
                        "inquiry_summary": "장기요양 등급 신청 서류 관련 콜백 요청 (음성 남김)",
                        "raw_message": "(음성 녹음 발화) 등급 신청 서류를 센터로 보내야 하는지 궁금합니다. 010-9876-5432로 설명 전화 부탁해요.",
                        "input_type": "voice",
                        "category": "자격상담",
                        "status": "pending",
                        "admin_note": None,
                        "assigned_to": None,
                        "resolved_by": None,
                        "resolved_at": None,
                        "created_at": (datetime.datetime.now() - datetime.timedelta(hours=3)).isoformat(),
                        "updated_at": (datetime.datetime.now() - datetime.timedelta(hours=3)).isoformat()
                    }
                ],
                "llm_providers": [
                    {"vendor_id": "openai", "display_name": "OpenAI ChatGPT", "model_name": "gpt-4o",
                     "vault_secret_id": None, "is_active": False, "last_tested_at": None, "last_test_status": None,
                     "updated_at": datetime.datetime.now().isoformat()},
                    {"vendor_id": "claude", "display_name": "Anthropic Claude", "model_name": "claude-3-5-sonnet-20241022",
                     "vault_secret_id": None, "is_active": False, "last_tested_at": None, "last_test_status": None,
                     "updated_at": datetime.datetime.now().isoformat()},
                    {"vendor_id": "gemini", "display_name": "Google Gemini", "model_name": "gemini-3.1-flash-lite",
                     "vault_secret_id": None, "is_active": False, "last_tested_at": None, "last_test_status": None,
                     "updated_at": datetime.datetime.now().isoformat()},
                    {"vendor_id": "qwen", "display_name": "Alibaba Qwen", "model_name": "qwen-max",
                     "vault_secret_id": None, "is_active": False, "last_tested_at": None, "last_test_status": None,
                     "updated_at": datetime.datetime.now().isoformat()},
                ]
            }
        if "mock_vault_secrets" not in st.session_state:
            # 실DB의 vault.secrets를 모사하는 세션 내 임시 저장소 (평문 보관 - Mock 전용, 데모 목적)
            st.session_state.mock_vault_secrets = {}

    def select(self, columns="*"):
        self.operation = self.operation or "select"
        self.selected_cols = columns
        return self

    def eq(self, column, value):
        # 체인 순서(select/update/delete 이전 또는 이후)에 상관없이
        # 실제 supabase-py와 동일하게 execute() 시점에 필터를 일괄 적용한다.
        self.filters.append((column, value))
        return self

    def limit(self, count):
        self.limit_count = count
        return self

    def insert(self, record, count=None, returning="representation", upsert=False, default_to_null=True):
        # count/returning/upsert/default_to_null은 실제 supabase-py insert()와의
        # 시그니처 호환을 위해 받되, Mock 모드에서는 항상 전체 데이터를 반환한다.
        self.operation = "insert"
        self.payload = record
        return self

    def update(self, update_dict):
        self.operation = "update"
        self.payload = update_dict
        return self

    def upsert(self, record):
        self.operation = "upsert"
        self.payload = record
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def _apply_filters(self, rows):
        result = rows
        for column, value in self.filters:
            result = [item for item in result if item.get(column) == value]
        return result

    def _do_insert(self, record):
        if "id" not in record and self.table_name != "bot_settings":
            record["id"] = str(uuid.uuid4())
        if "created_at" not in record:
            record["created_at"] = datetime.datetime.now().isoformat()
        st.session_state.mock_db.setdefault(self.table_name, []).insert(0, record)
        return record

    def execute(self):
        table = st.session_state.mock_db.setdefault(self.table_name, [])

        if self.operation == "insert":
            records = self.payload if isinstance(self.payload, list) else [self.payload]
            inserted = [self._do_insert(dict(r)) for r in records]
            return MockTableResponse(inserted)

        if self.operation == "update":
            matched = self._apply_filters(table)
            for item in matched:
                # 실DB의 트리거(set_updated_at / set_resolved_at)를 Mock 모드에서도 동일하게 재현
                was_resolved = item.get("status") == "resolved"
                item.update(self.payload)
                if "updated_at" in item:
                    item["updated_at"] = datetime.datetime.now().isoformat()
                if item.get("status") == "resolved" and not was_resolved and "resolved_at" in item:
                    item["resolved_at"] = datetime.datetime.now().isoformat()
            return MockTableResponse(matched)

        if self.operation == "delete":
            matched = self._apply_filters(table)
            matched_ids = {id(item) for item in matched}
            st.session_state.mock_db[self.table_name] = [
                item for item in table if id(item) not in matched_ids
            ]
            return MockTableResponse(matched)

        if self.operation == "upsert":
            record = dict(self.payload)
            if self.table_name == "bot_settings":
                st.session_state.mock_db["bot_settings"] = [record]
                return MockTableResponse([record])
            rec_id = record.get("id")
            existing = next((item for item in table if item.get("id") == rec_id), None)
            if existing:
                existing.update(record)
                return MockTableResponse([existing])
            inserted = self._do_insert(record)
            return MockTableResponse([inserted])

        # 기본 select
        result = self._apply_filters(table)
        if self.limit_count is not None:
            result = result[: self.limit_count]
        return MockTableResponse(result)

class MockRPCBuilder:
    """
    실DB의 Postgres RPC(vault 기반 set_llm_api_key/get_llm_api_key)를
    세션 상태만으로 흉내 내는 Mock 구현.
    """
    def __init__(self, fn_name, params):
        self.fn_name = fn_name
        self.params = params or {}

    def execute(self):
        providers = st.session_state.mock_db.setdefault("llm_providers", [])
        vault = st.session_state.mock_vault_secrets

        if self.fn_name == "set_llm_api_key":
            vendor_id = self.params.get("p_vendor_id")
            api_key = self.params.get("p_api_key")
            provider = next((p for p in providers if p["vendor_id"] == vendor_id), None)
            if provider is None:
                provider = {"vendor_id": vendor_id, "display_name": vendor_id, "model_name": ""}
                providers.append(provider)

            secret_id = provider.get("vault_secret_id") or str(uuid.uuid4())
            vault[secret_id] = api_key
            provider["vault_secret_id"] = secret_id
            provider["is_active"] = True
            provider["updated_at"] = datetime.datetime.now().isoformat()
            return MockTableResponse(None)

        if self.fn_name == "get_llm_api_key":
            vendor_id = self.params.get("p_vendor_id")
            provider = next((p for p in providers if p["vendor_id"] == vendor_id), None)
            secret_id = provider.get("vault_secret_id") if provider else None
            return MockTableResponse(vault.get(secret_id) if secret_id else None)

        return MockTableResponse(None)


class MockSupabaseClient:
    def table(self, table_name):
        return MockQueryBuilder(table_name)

    def rpc(self, fn_name, params=None):
        # rpc()도 session_state 초기화가 필요하므로 더미 쿼리빌더를 한번 거쳐 seed를 보장한다.
        MockQueryBuilder("llm_providers")
        return MockRPCBuilder(fn_name, params)

def init_supabase_client():
    """
    Supabase 클라이언트 초기화 함수.
    secrets.toml 또는 환경 변수에서 URL과 Key를 읽어 연동하며,
    실패 시 세션 기반의 Mock Supabase 클라이언트를 반환합니다.
    """
    url = None
    key = None

    # 1. secrets.toml 확인 (안전 조회)
    try:
        url = st.secrets.get("SUPABASE_URL")
        key = st.secrets.get("SUPABASE_KEY")
    except Exception:
        pass

    # 2. 환경 변수 확인
    if not url or not key:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")

    # 3. Supabase SDK가 있고 URL/Key가 데모 값이 아닌 경우 실제 클라이언트 생성
    if HAS_SUPABASE_SDK and url and key and "your-supabase" not in url:
        try:
            client = create_client(url, key)
            return client, False # (client, is_mock)
        except Exception as e:
            st.warning(f"Supabase 실DB 연결 실패 (Mock 모드로 전환): {str(e)}")
            return MockSupabaseClient(), True
    else:
        return MockSupabaseClient(), True

# 글로벌 supabase 클라이언트 객체 생성
supabase, is_mock_db = init_supabase_client()
