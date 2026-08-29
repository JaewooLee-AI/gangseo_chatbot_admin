import datetime
import streamlit as st
import requests
from core.db import supabase


def _health_check(canonical_vendor: str, api_key: str, model_name: str):
    """
    벤더별 실제 엔드포인트에 최소 요청을 보내 인증/연결 상태를 검증한다.
    반환값: (http_status_code 또는 None(네트워크 오류), 상세 메시지)
    """
    try:
        if canonical_vendor == "openai":
            resp = requests.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=8,
            )
        elif canonical_vendor == "claude":
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model_name,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=8,
            )
        elif canonical_vendor == "gemini":
            resp = requests.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                timeout=8,
            )
        elif canonical_vendor == "qwen":
            resp = requests.get(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=8,
            )
        else:
            return None, "지원되지 않는 벤더입니다."
        return resp.status_code, resp.text[:300]
    except requests.exceptions.RequestException as e:
        return None, str(e)


def _load_provider_state(canonical_vendor: str):
    """llm_providers 테이블에서 저장된 모델명/키 등록 여부/최근 테스트 결과를 조회한다."""
    res = supabase.table("llm_providers").select("*").eq("vendor_id", canonical_vendor).execute()
    return res.data[0] if res.data else None


def _save_llm_api_key(canonical_vendor: str, api_key: str):
    """Supabase Vault에 API 키를 암호화 저장(신규 생성 또는 교체)한다."""
    supabase.rpc("set_llm_api_key", {"p_vendor_id": canonical_vendor, "p_api_key": api_key}).execute()


def _update_provider_meta(canonical_vendor: str, model_name: str, test_status: str):
    """모델명/최근 테스트 시각/결과를 llm_providers 테이블에 기록한다."""
    supabase.table("llm_providers").update({
        "model_name": model_name,
        "last_tested_at": datetime.datetime.now().isoformat(),
        "last_test_status": test_status,
    }).eq("vendor_id", canonical_vendor).execute()


def render_llm_card(vendor_id: str, vendor_icon: str, vendor_name: str, default_model: str,
                     env_key_name: str, canonical_vendor: str):
    """
    LLM API 구성 카드 UI를 렌더링합니다.
    - Title: ✨ Google Gemini 스타일 헤더
    - 모델명: 수정 가능한 입력 창 (기본값 e.g. gemini-3.1-flash-lite)
    - 🔒 API Key: 비밀번호 마스킹 및 플레이스홀더 텍스트. 저장 시 평문이 아닌
      Supabase Vault(암호화 저장소)에 저장되고, llm_providers 테이블에는
      그 secret에 대한 포인터(vault_secret_id)만 남는다.
    - ✅ 등록된 키가 있습니다. / ⚠️ 등록된 키가 없습니다. 상태 메시지
    - [Vendor Name] 연결 테스트 버튼 (테스트 성공 시에만 Vault에 키를 저장)

    vendor_id: 이 페이지 내 Streamlit 위젯 key 충돌 방지용 접두어
               (동일 카드가 03_persona_settings.py에서도 재사용되므로 "_set" 접미사가 붙을 수 있음)
    canonical_vendor: DB(llm_providers)/헬스체크 라우팅에 쓰이는 실제 벤더 식별자
               ("openai" | "claude" | "gemini" | "qwen")
    """
    card_key_prefix = f"llm_api_{vendor_id}"

    # DB(Vault)에 저장된 상태 로드: 모델명, 키 등록 여부, 최근 테스트 결과
    provider_state = _load_provider_state(canonical_vendor)
    has_registered_key = bool(provider_state and provider_state.get("vault_secret_id"))
    saved_model_name = provider_state.get("model_name") if provider_state else default_model

    if f"{card_key_prefix}_model" not in st.session_state:
        st.session_state[f"{card_key_prefix}_model"] = saved_model_name or default_model

    # secrets.toml에 로컬로 넣어둔 키가 있다면(과거 방식과의 호환) 최초 1회 대체 후보로 사용
    local_secret_key = ""
    try:
        local_secret_key = st.secrets.get(env_key_name, "") or ""
    except Exception:
        pass

    # 카드 컨테이너 시작
    with st.container():
        # 헤더 타이틀 (e.g. ✨ Google Gemini)
        st.markdown(f"""
        <div style="margin-bottom: 1rem;">
            <h2 style="font-size: 1.8rem; font-weight: 800; color: #0F172A; margin: 0; display: flex; align-items: center; gap: 0.5rem;">
                <span>{vendor_icon}</span> <span>{vendor_name}</span>
            </h2>
        </div>
        """, unsafe_allow_html=True)

        # 1. 모델명 수정 입력란
        st.markdown("<p style='font-weight: 600; font-size: 0.95rem; margin-bottom: 0.3rem; color: #1C1917;'>모델명</p>", unsafe_allow_html=True)
        model_name = st.text_input(
            "모델명",
            value=st.session_state[f"{card_key_prefix}_model"],
            key=f"{card_key_prefix}_model_input",
            label_visibility="collapsed"
        )
        st.session_state[f"{card_key_prefix}_model"] = model_name

        st.markdown("<div style='height: 0.8rem;'></div>", unsafe_allow_html=True)

        # 2. 🔒 API Key 입력란
        st.markdown("<p style='font-weight: 600; font-size: 0.95rem; margin-bottom: 0.3rem; color: #1C1917;'>🔒 API Key</p>", unsafe_allow_html=True)
        api_key_val = st.text_input(
            "API Key",
            type="password",
            placeholder="저장된 키가 있으면 비워두고 저장...",
            key=f"{card_key_prefix}_key_input",
            label_visibility="collapsed"
        )

        st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)

        # 3. 등록된 키 유무 상태 문구 (Vault 기준)
        if has_registered_key:
            st.markdown("<p style='color: #16A34A; font-weight: 600; font-size: 0.95rem; margin: 0.4rem 0 1rem 0;'>✅ Vault에 암호화된 키가 등록되어 있습니다.</p>", unsafe_allow_html=True)
        elif local_secret_key:
            st.markdown("<p style='color: #CA8A04; font-weight: 600; font-size: 0.95rem; margin: 0.4rem 0 1rem 0;'>🟡 secrets.toml 키만 있고 Vault에는 미등록 — 연결 테스트 시 자동으로 Vault에 저장됩니다.</p>", unsafe_allow_html=True)
        else:
            st.markdown("<p style='color: #DC2626; font-weight: 600; font-size: 0.95rem; margin: 0.4rem 0 1rem 0;'>⚠️ 등록된 키가 없습니다.</p>", unsafe_allow_html=True)

        if provider_state and provider_state.get("last_tested_at"):
            status_icon = "🟢" if provider_state.get("last_test_status") == "success" else "🔴"
            st.caption(f"{status_icon} 최근 테스트: {str(provider_state['last_tested_at'])[:19].replace('T', ' ')} ({provider_state.get('last_test_status')})")

        # 4. 연결 테스트 버튼
        test_btn = st.button(f"{vendor_name} 연결 테스트", key=f"{card_key_prefix}_test_btn", type="secondary")

        # 버튼 클릭 처리
        if test_btn:
            if api_key_val.strip():
                active_key = api_key_val.strip()
            elif has_registered_key:
                active_key = supabase.rpc("get_llm_api_key", {"p_vendor_id": canonical_vendor}).execute().data or ""
            else:
                active_key = local_secret_key.strip()

            if not active_key:
                st.warning(f"⚠️ {vendor_name} API Key를 입력하시거나 사전에 등록해 주세요.")
            else:
                with st.spinner(f"{vendor_name} ({model_name}) 엔드포인트에 실제 연결 테스트 중..."):
                    status_code, detail = _health_check(canonical_vendor, active_key, model_name)
                    test_status = "success" if status_code == 200 else "failed"

                    if status_code == 200:
                        # 새로 입력된 키가 있을 때만 Vault에 저장(교체)한다.
                        if api_key_val.strip():
                            _save_llm_api_key(canonical_vendor, api_key_val.strip())
                        _update_provider_meta(canonical_vendor, model_name, test_status)

                        st.success(f"""
                        🟢 **연결 성공 (HTTP 200 OK)**
                        - **모델명:** `{model_name}`
                        - **인증 상태:** Verified OK
                        - **키 저장 위치:** Supabase Vault (암호화)
                        """)
                        st.toast(f"{vendor_name} 연결 성공!", icon="🟢")
                        st.rerun()
                    elif status_code is None:
                        _update_provider_meta(canonical_vendor, model_name, test_status)
                        st.error(f"""
                        🔴 **연결 실패 (네트워크 오류)**
                        - **모델명:** `{model_name}`
                        - **원인:** {detail}
                        """)
                    else:
                        _update_provider_meta(canonical_vendor, model_name, test_status)
                        st.error(f"""
                        🔴 **연결 실패 (HTTP {status_code})**
                        - **모델명:** `{model_name}`
                        - **응답 내용:** {detail}
                        """)

def render():
    st.markdown('<div class="ace-badge ace-badge-orange">MODULE 04</div>', unsafe_allow_html=True)
    st.title("🔑 LLM API 관리")
    st.caption("각 LLM 벤더별 **모델명 지정**, **API Key 등록** 및 **정상 작동 연결 테스트**를 수행하는 관리자 전용 통제반입니다.")
    st.divider()

    # 2개 컬럼 카드 그리드 레이아웃
    col1, col2 = st.columns(2, gap="large")

    with col1:
        render_llm_card(
            vendor_id="gemini",
            vendor_icon="✨",
            vendor_name="Google Gemini",
            default_model="gemini-3.1-flash-lite",
            env_key_name="GEMINI_API_KEY",
            canonical_vendor="gemini"
        )
        st.write("")
        render_llm_card(
            vendor_id="qwen",
            vendor_icon="🐉",
            vendor_name="Alibaba Qwen",
            default_model="qwen-max",
            env_key_name="QWEN_API_KEY",
            canonical_vendor="qwen"
        )

    with col2:
        render_llm_card(
            vendor_id="openai",
            vendor_icon="🤖",
            vendor_name="OpenAI ChatGPT",
            default_model="gpt-4o",
            env_key_name="OPENAI_API_KEY",
            canonical_vendor="openai"
        )
        st.write("")
        render_llm_card(
            vendor_id="claude",
            vendor_icon="🧠",
            vendor_name="Anthropic Claude",
            default_model="claude-3-5-sonnet-20241022",
            env_key_name="CLAUDE_API_KEY",
            canonical_vendor="claude"
        )

    st.divider()
    with st.expander("📖 LLM API 관리 안내"):
        st.markdown("""
        - **모델명 관리:** 사용자는 각 LLM 벤더 카드의 '모델명' 입력란을 수정하여 기본 모델(예: `gemini-3.1-flash-lite`, `gpt-4o`)을 변경할 수 있습니다.
        - **API Key 관리:** 연결 테스트가 성공하면 입력한 키가 **Supabase Vault**에 암호화되어 저장됩니다 (평문은 어떤 테이블에도 남지 않습니다). `.streamlit/secrets.toml`에 넣어둔 키는 최초 테스트 시 자동으로 Vault에 이관됩니다.
        - **연결 테스트:** `{Vendor Name} 연결 테스트` 버튼을 클릭하면 실제 엔드포인트 헬스체크 및 정상 작동 여부를 수초 내에 검증합니다.
        - **Vercel 챗봇에서 사용:** 별도 백엔드가 `service_role` 키로 Postgres 함수 `get_llm_api_key('openai')`(RPC)를 호출하면 복호화된 키를 받아 LLM API를 호출할 수 있습니다. anon 키로는 이 함수를 호출할 수 없습니다.
        """)
