import streamlit as st
import importlib
from core.db import supabase

# importlib으로 render_llm_card 동적 로드
llm_mod = importlib.import_module("modules.04_llm_manager")
render_llm_card = llm_mod.render_llm_card

def render():
    st.markdown('<div class="ace-badge ace-badge-charcoal">MODULE 03</div>', unsafe_allow_html=True)
    st.title("⚙️ AI 설정 통제반 (Dynamic Prompting & LLM API 구성)")
    st.markdown("챗봇의 **페르소나/가드레일 설정**과 **LLM API 모델명 구성 및 연동 테스트**를 통합하여 제어합니다.")
    st.divider()

    tab_persona, tab_llm = st.tabs(["⚙️ AI 페르소나 & 보안 가드레일", "🔑 LLM API 구성 & 모델 설정"])

    with tab_persona:
        # DB에서 현재 설정값 로드
        settings_res = supabase.table("bot_settings").select("*").eq("id", 1).execute()
        current = settings_res.data[0] if settings_res.data else {}

        with st.form("persona_settings_form"):
            # 1. 톤앤매너 설정
            st.subheader("1. 톤앤매너 (Tone & Manner) 제어")
            st.caption("강서나눔돌봄센터 챗봇의 기본 페르소나와 호칭, 대화 스타일을 정의합니다.")
            
            tones = ["친절한 상담원", "사무적인 행정관", "어르신 맞춤형 (쉽고 느린 톤)"]
            current_tone = current.get("tone", "친절한 상담원")
            default_index = tones.index(current_tone) if current_tone in tones else 0
            
            selected_tone = st.selectbox(
                "🗣️ AI의 기본 응대 어조를 선택하세요",
                tones,
                index=default_index,
                help="어르신 맞춤형 선택 시 큰 글씨와 쉬운 단어 위주로 프롬프트가 동적 변경됩니다."
            )

            st.divider()

            # 2. 컴플라이언스 가드레일
            st.subheader("2. 컴플라이언스 (법적 방어) 가드레일 설정")
            st.caption("스위치 활성화(On) 시 해당 전문 영역 질의에 대해 AI가 지레짐작 답변하는 것을 차단하고 센터 직접 문의로 이관합니다.")

            c1, c2, c3 = st.columns(3)
            with c1:
                block_med = st.toggle("🏥 의료/질병 진단 차단", value=current.get("block_medical", True))
                st.caption("치매, 약복용, 질환 진단 문의 자동 차단")
            with c2:
                block_law = st.toggle("⚖️ 법률/노무 상담 차단", value=current.get("block_legal", True))
                st.caption("수급 자격 법적 분쟁, 노무 계약 질의 차단")
            with c3:
                block_pii = st.toggle("🔒 개인정보 요구 차단", value=current.get("block_privacy", True))
                st.caption("주민번호, 계좌번호 등 민감정보 수집 차단")

            st.divider()

            # 3. RAG 엄격도 슬라이더
            st.subheader("3. RAG 엄격도 (유사도 임계치 코사인 거리 제어)")
            st.caption("지식베이스 참조 범위를 제어하여 할루시네이션(환각) 리스크를 수학적으로 관리합니다.")

            current_strictness = current.get("strictness_level", 5)
            strictness = st.slider(
                "🎚️ 엄격도 조절 슬라이더 (1단계 ~ 5단계)",
                min_value=1,
                max_value=5,
                value=current_strictness,
                help="5단계: 지식베이스 외부 답변 절대 금지 / 1단계: 유연한 일반 상식 답변 일부 허용"
            )

            strictness_guides = {
                1: "🟡 **Level 1 (유연):** 배경지식 및 범용 AI 알고리즘을 융합하여 유연하게 응답합니다.",
                2: "🟡 **Level 2 (보통):** 문맥 유사도가 약간 떨어져도 연관된 지식을 포함하여 답변합니다.",
                3: "🟢 **Level 3 (균형):** 실무 응대와 정확성의 균형을 맞춘 표준 설정입니다.",
                4: "🟠 **Level 4 (주의):** 지식베이스와 높은 유사도를 보이는 문서만 참조합니다.",
                5: "🔴 **Level 5 (엄격 - 권장):** 지식베이스에 명확한 출처가 없으면 단호하게 [상담사 연결 필요]로 이관합니다."
            }
            st.info(strictness_guides.get(strictness, ""))

            st.divider()

            submit_settings = st.form_submit_button("💾 설정 저장 및 즉시 배포 (Update Prompts)")

        if submit_settings:
            supabase.table("bot_settings").upsert({
                "id": 1,
                "tone": selected_tone,
                "block_medical": block_med,
                "block_legal": block_law,
                "block_privacy": block_pii,
                "strictness_level": strictness
            }).execute()

            st.success("✅ AI 페르소나 및 가드레일 설정이 저장되었습니다. 외부 Vercel 앱에서 즉시 반영됩니다.")
            st.balloons()

    with tab_llm:
        st.subheader("🔑 LLM API 구성 및 모델 설정")
        st.caption("첨부 UI 스펙에 맞춰 각 LLM 벤더별 **모델명 수정**, **API Key 저장** 및 **작동 테스트**를 지원합니다.")
        st.divider()

        col1, col2 = st.columns(2, gap="large")

        with col1:
            render_llm_card(
                vendor_id="gemini_set",
                vendor_icon="✨",
                vendor_name="Google Gemini",
                default_model="gemini-3.1-flash-lite",
                env_key_name="GEMINI_API_KEY",
                canonical_vendor="gemini"
            )
            st.divider()
            render_llm_card(
                vendor_id="qwen_set",
                vendor_icon="🐉",
                vendor_name="Alibaba Qwen",
                default_model="qwen-max",
                env_key_name="QWEN_API_KEY",
                canonical_vendor="qwen"
            )

        with col2:
            render_llm_card(
                vendor_id="openai_set",
                vendor_icon="🤖",
                vendor_name="OpenAI ChatGPT",
                default_model="gpt-4o",
                env_key_name="OPENAI_API_KEY",
                canonical_vendor="openai"
            )
            st.divider()
            render_llm_card(
                vendor_id="claude_set",
                vendor_icon="🧠",
                vendor_name="Anthropic Claude",
                default_model="claude-3-5-sonnet-20241022",
                env_key_name="CLAUDE_API_KEY",
                canonical_vendor="claude"
            )
