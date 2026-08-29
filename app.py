import streamlit as st
import importlib
from core.style import inject_ace_hotel_css
from core.db import is_mock_db
from core.auth import send_otp, verify_otp

# 1. 페이지 기본 설정
st.set_page_config(
    page_title="강서나눔돌봄센터 AI RAG 통제반",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. Stitch Ace Hotel Chatbot Admin 테마 및 Pretendard 폰트 CSS 주입
inject_ace_hotel_css()

# 2-1. 최고 관리자 로그인 게이트 (이메일 OTP)
# 세션(브라우저 탭)에만 저장되며 새로고침 시 재로그인이 필요하다.
if "admin_email" not in st.session_state:
    st.session_state.admin_email = None
if "login_step" not in st.session_state:
    st.session_state.login_step = 1


def _render_login():
    st.markdown("""
    <div class="header-card" style="background-color: #FFFFFF !important; border: 1px solid #D6D3D1 !important; border-left: 6px solid #F97316 !important; padding: 1.25rem 1.5rem !important; border-radius: 8px !important; margin-bottom: 1.5rem !important; box-shadow: 0 2px 6px rgba(0,0,0,0.04) !important;">
        <h2 style="color: #1C1917 !important; font-size: 1.6rem !important; font-weight: 800 !important; margin: 0 0 0.3rem 0 !important;">🔐 강서나눔돌봄센터 최고 관리자 로그인</h2>
        <p style="color: #57534E !important; font-size: 0.95rem !important; margin: 0 !important; font-weight: 500 !important;">등록된 최고 관리자 이메일로 인증번호를 받아 로그인합니다.</p>
    </div>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        if is_mock_db:
            st.info("⚡ Mock DB 모드: 이메일 인증번호에 아무 6자리 숫자나 입력하면 로그인됩니다.")

        if st.session_state.login_step == 1:
            with st.form("admin_login_email_form"):
                email = st.text_input("최고 관리자 이메일")
                submitted = st.form_submit_button("인증번호 받기 →", type="primary", use_container_width=True)
            if submitted:
                res = send_otp(email)
                if res.get("error"):
                    st.error(res["error"])
                else:
                    st.session_state.pending_email = email.strip()
                    st.session_state.login_step = 2
                    st.rerun()
        else:
            st.caption(f"`{st.session_state.pending_email}` 로 발송된 인증번호를 입력하세요.")
            with st.form("admin_login_otp_form"):
                otp = st.text_input("인증번호", max_chars=10)
                verify = st.form_submit_button("시스템 로그인", type="primary", use_container_width=True)
            if st.button("← 이메일 다시 입력", use_container_width=True):
                st.session_state.login_step = 1
                st.rerun()
            if verify:
                res = verify_otp(st.session_state.pending_email, otp)
                if res.get("error"):
                    st.error(res["error"])
                else:
                    st.session_state.admin_email = res["email"]
                    st.session_state.login_step = 1
                    st.rerun()


if not st.session_state.admin_email:
    _render_login()
    st.stop()

# 3. 사이드바 라우팅 및 100% 한글 메뉴 정의
st.sidebar.markdown("""
<div style="padding: 0.5rem 0 1rem 0; border-bottom: 2px solid #1C1917; margin-bottom: 1rem;">
    <span class="ace-badge ace-badge-orange">SYSTEM CONTROL</span>
    <h2 style="font-size: 1.2rem; margin: 0.3rem 0 0 0; color: #1C1917;">🏛️ 강서나눔돌봄센터</h2>
    <p style="font-size: 0.8rem; color: #78716C; margin: 0;">AI RAG 통제반 v2.0</p>
</div>
""", unsafe_allow_html=True)

menu_options = [
    "📊 RAG 데이터 파이프라인",
    "🧠 HITL 오답 리뷰",
    "⚙️ AI 페르소나 및 보안 설정",
    "🔑 LLM API 관리",
    "👥 직원 계정 관리",
    "🤖 RAG 챗봇 시뮬레이터"
]

selected_menu = st.sidebar.radio(
    "통제반 메인 메뉴",
    menu_options,
    index=0
)

# 사이드바 하단 DB 연동 상태 표시
st.sidebar.divider()
if is_mock_db:
    st.sidebar.warning("⚡ **DB 상태:** Mock Session DB Mode\n(Supabase 키 설정 시 실DB 자동전환)")
else:
    st.sidebar.success("🟢 **DB 상태:** Supabase pgvector Live Connection")

st.sidebar.caption(f"👤 로그인: {st.session_state.admin_email}")
if st.sidebar.button("🚪 로그아웃", use_container_width=True):
    st.session_state.admin_email = None
    st.rerun()

st.sidebar.caption("© 2026 강서나눔돌봄센터. All rights reserved.")

# 4. 상단 공통 헤더 카드 (고대비 및 시가성 확보)
st.markdown("""
<div class="header-card" style="background-color: #FFFFFF !important; border: 1px solid #D6D3D1 !important; border-left: 6px solid #F97316 !important; padding: 1.25rem 1.5rem !important; border-radius: 8px !important; margin-bottom: 1.5rem !important; box-shadow: 0 2px 6px rgba(0,0,0,0.04) !important;">
    <h2 style="color: #1C1917 !important; font-size: 1.6rem !important; font-weight: 800 !important; margin: 0 0 0.3rem 0 !important; padding: 0 !important; display: block !important;">🤖 강서나눔돌봄센터 AI 챗봇 최고 관리자 통합 통제반</h2>
    <p style="color: #57534E !important; font-size: 0.95rem !important; margin: 0 !important; font-weight: 500 !important; display: block !important;">3-Tier 아키텍처 기반의 RAG 지식 통제, 컴플라이언스 가드레일 제어 및 Human-in-the-loop(HITL) 자가진화 대시보드입니다.</p>
</div>
""", unsafe_allow_html=True)

# 5. 선택된 메뉴에 따라 해당 비즈니스 모듈 동적 로드
module_mapping = {
    "📊 RAG 데이터 파이프라인": "modules.01_data_pipeline",
    "🧠 HITL 오답 리뷰": "modules.02_hitl_review",
    "⚙️ AI 페르소나 및 보안 설정": "modules.03_persona_settings",
    "🔑 LLM API 관리": "modules.04_llm_manager",
    "👥 직원 계정 관리": "modules.05_staff_auth",
    "🤖 RAG 챗봇 시뮬레이터": "modules.06_simulator"
}

if selected_menu in module_mapping:
    mod_name = module_mapping[selected_menu]
    mod = importlib.import_module(mod_name)
    mod.render()
