import streamlit as st
import re
import time
import datetime
from core.db import supabase
from core.rag_engine import (
    generate_embedding, generate_chat_answer, ANSWER_GAP_MARKER,
    normalize_query, extract_hitl_answer, hybrid_search, check_guardrail_intent,
    PERSONA_CATEGORIES, PERSONA_LABELS, detect_ambiguous_service,
)

def extract_contact_and_summary(message: str):
    """
    AI 분석을 시뮬레이션하여 발화 문장에서 연락처(전화번호/이메일) 및 핵심 문의 사항을 자동 추출합니다.
    """
    # 1. 전화번호 추출 패턴
    phone_pattern = r'(01[016789]-?\d{3,4}-?\d{4}|02-?\d{3,4}-?\d{4}|0[3-6][1-5]-?\d{3,4}-?\d{4})'
    phone_match = re.search(phone_pattern, message)
    contact = phone_match.group(0) if phone_match else "연락처 미기재 (원문 확인 필요)"

    # 2. 이메일 추출 패턴
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    email_match = re.search(email_pattern, message)
    if email_match and contact == "연락처 미기재 (원문 확인 필요)":
        contact = email_match.group(0)

    # 3. 성함 추출 시도
    name = "미상 어르신/신청자"
    if "어머니" in message or "어르신" in message:
        name = "보호자 (어르신 관련 문의)"
    elif "홍길동" in message:
        name = "홍길동"

    # 4. 핵심 요약 생성
    clean_text = message.replace(contact, "").strip()
    summary = clean_text[:60] + "..." if len(clean_text) > 60 else clean_text
    if not summary:
        summary = "담당자 직접 콜백 및 상담 요청"

    return name, contact, summary


# 담당자 웹앱의 분류/필터링 기능을 위한 문의 자동 분류 키워드 사전
INQUIRY_CATEGORY_KEYWORDS = {
    "요금문의": ["요금", "정산", "비용", "금액", "결제"],
    "서비스신청": ["신청", "지원 받고", "이용하고 싶", "예약"],
    "자격상담": ["자격", "대상", "등급", "수급자", "차상위"],
    "불만접수": ["불만", "항의", "화가", "실망", "잘못"],
}


# LLM이 근거 자료 부족을 스스로 인정할 때 쓰는 전형적인 표현들.
# 유사도 임계치는 통과했지만 실제로는 "모른다"는 답변인 경우를 감지하기 위함.
NO_ANSWER_PHRASES = [
    "명시되어 있지 않", "정확한 답변을 드리기 어렵", "확인이 어렵", "알 수 없습니다",
    "안내해 드리기 어렵", "찾을 수 없습니다", "참고 자료에는", "제공된 자료에는",
    "자료에 포함되어 있지 않",
]


def is_no_answer_response(answer: str) -> bool:
    """
    LLM 답변이 사실상(또는 일부라도) '모른다'는 취지인지 판별한다.
    1순위는 프롬프트로 지시한 고정 마커(ANSWER_GAP_MARKER) 탐지이며,
    NO_ANSWER_PHRASES 키워드 매칭은 마커를 빠뜨린 경우를 대비한 보조 수단이다.
    """
    return ANSWER_GAP_MARKER in answer or any(p in answer for p in NO_ANSWER_PHRASES)


def strip_gap_marker(answer: str) -> str:
    """사용자에게 노출하기 전, 내부 신호용 마커를 답변 텍스트에서 제거한다."""
    return answer.replace(ANSWER_GAP_MARKER, "").strip()


def classify_inquiry(message: str) -> str:
    """문의 원문 키워드를 바탕으로 담당자 웹앱에서 사용할 카테고리를 자동 분류한다."""
    for category, keywords in INQUIRY_CATEGORY_KEYWORDS.items():
        if any(k in message for k in keywords):
            return category
    return "일반문의"


# 컴플라이언스 가드레일 키워드 사전 (bot_settings의 block_* 토글과 연동)
MEDICAL_KEYWORDS = ["치매", "진단", "질병", "증상", "질환", "복용", "약물", "처방"]
LEGAL_KEYWORDS = ["소송", "고소", "위자료", "손해배상", "법적", "계약서", "노무", "해고"]
PRIVACY_KEYWORDS = ["주민등록번호", "주민번호", "계좌번호", "카드번호", "비밀번호"]

# RAG 엄격도(1~5단계)를 코사인 유사도 임계치로 환산
# Gemini(gemini-embedding-001) 실측 기준: 무관한 질문 0.51~0.55, 실제 정답 문서 0.72~0.74로
# 절대 유사도 값 자체가 임베딩 모델마다 다른 분포를 가지므로, 이 값은 Gemini 기준으로 보정한 것이다.
# 다른 임베딩 제공자(OpenAI 등)로 전환 시 재보정이 필요할 수 있다.
STRICTNESS_THRESHOLD = {1: 0.50, 2: 0.55, 3: 0.60, 4: 0.65, 5: 0.70}

# HITL(관리자 검증 모범 정답)로 등록된 지식은 이미 사람이 확인한 고신뢰 답변이므로,
# 일반 strictness 임계치보다 훨씬 높은 값으로 "거의 동일 질문"만 즉시 캐시 반환한다.
# 오탐(다른 질문에 엉뚱한 검증 답변을 그대로 노출)을 막기 위한 보수적인 값이다.
HITL_CACHE_THRESHOLD = 0.85

# 컨텍스트 포함 임계치. "답변을 할지 말지"를 정하는 게이트(STRICTNESS_THRESHOLD)와
# "어떤 문서를 LLM에게 근거로 줄지"를 정하는 기준은 목적이 다르다. 둘 다 게이트 값으로
# 처리하면, 게이트를 겨우 통과한 질문에서 정작 필요한 문서가 컨텍스트에서 빠진다.
# (실측: '활동지원사로 일하고 싶어요' 질의에서 정답인 '입사 필요 서류'(0.644)가
#  0.70 컷에 걸려 제외되고, 주소/문의처 문서만 LLM에 전달되어 오답이 나갔다.)
CONTEXT_THRESHOLD = 0.55

# fallback_logs.failure_type 값: 오답 리뷰(Module 02)에서 실패 원인별 분포를 보고
# 어떤 개선(질의 정규화 튜닝/지식 보강/가드레일 조정 등)이 가장 시급한지 데이터 기반으로
# 판단할 수 있도록, 로그 적재 시점에 원인을 함께 태깅한다.
FAILURE_TYPE_NO_MATCH = "no_match"                # 임계치를 넘는 문서를 아예 찾지 못함 (지식 공백)
FAILURE_TYPE_LOW_CONFIDENCE = "low_confidence"    # 문서는 찾았지만 LLM이 근거 부족을 자인함
FAILURE_TYPE_HUMAN_REQUESTED = "human_requested"  # 담당자 연결을 원했으나 연락처 미기재


def check_guardrail_block(prompt: str, settings: dict):
    """
    bot_settings의 컴플라이언스 토글에 따라 해당 주제 질의를 차단한다.
    차단 대상이면 (True, 사유텍스트)를, 아니면 (False, None)을 반환한다.

    2단계 판정:
      1) 키워드 사전으로 후보를 싸게 걸러낸다(대부분의 질문은 여기서 통과 → LLM 호출 없음).
      2) 키워드가 걸린 질문만 LLM이 실제 '의도'를 판정한다.
    키워드 포함 여부만으로 차단하면 "치매 어르신도 서비스 이용 가능한가요?" 같은 정상적인
    서비스 자격 문의까지 막혀(실측: 정상 질문 6건 중 5건 오차단) 핵심 고객 문의가 유실된다.
    """
    checks = (
        ("block_medical", MEDICAL_KEYWORDS, "medical",
         "🏥 의료/질병 진단 관련 문의는 컴플라이언스 가드레일에 의해 차단되었습니다."),
        ("block_legal", LEGAL_KEYWORDS, "legal",
         "⚖️ 법률/노무 상담 관련 문의는 컴플라이언스 가드레일에 의해 차단되었습니다."),
        ("block_privacy", PRIVACY_KEYWORDS, "privacy",
         "🔒 개인정보 수집이 필요한 문의는 컴플라이언스 가드레일에 의해 차단되었습니다."),
    )

    for toggle, keywords, topic, reason in checks:
        if settings.get(toggle, True) and any(k in prompt for k in keywords):
            if check_guardrail_intent(prompt, topic):
                return True, reason
    return False, None


def apply_tone(text: str, tone: str) -> str:
    """설정된 어조(Tone)에 맞추어 응답 문구를 보정한다."""
    if tone == "어르신 맞춤형 (쉽고 느린 톤)":
        return f"{text}\n\n*(쉽고 느린 톤으로 다시 한번 천천히 안내드립니다. 이해가 어려우시면 센터로 편하게 전화 주세요.)*"
    if tone == "사무적인 행정관":
        return f"{text}\n\n(담당 부서 확인 후 정확한 행정 절차에 따라 재안내될 수 있습니다.)"
    return text


def render():
    st.markdown('<div class="ace-badge ace-badge-charcoal">MODULE 06</div>', unsafe_allow_html=True)
    st.title("🤖 RAG 챗봇 시뮬레이터 (STT & TTS / 담당자 메시지 전달)")
    st.markdown("챗봇 대화 중 답변이 마음에 들지 않거나 **담당자 직접 전달**을 원하는 경우, **텍스트/음성 메시지**를 남기면 AI가 분석하여 Supabase에 접수하는 기능을 실시간 시뮬레이션합니다.")
    st.divider()

    # 현재 설정값 로드
    settings_res = supabase.table("bot_settings").select("*").eq("id", 1).execute()
    current_setting = settings_res.data[0] if settings_res.data else {
        "tone": "친절한 상담원", "block_medical": True, "block_legal": True, "block_privacy": True, "strictness_level": 5
    }

    # 진입 페르소나 선택: 사용자 웹앱의 진입 화면과 동일한 조건으로 검색 범위를 좁혀
    # 테스트할 수 있게 한다(타 페르소나 문서가 컨텍스트를 잠식하는 문제 검증용).
    persona_options = ["(선택 안 함 · 전체 검색)"] + [PERSONA_LABELS[k] for k in PERSONA_CATEGORIES]
    label_to_key = {PERSONA_LABELS[k]: k for k in PERSONA_CATEGORIES}
    chosen_label = st.selectbox(
        "🧭 문의 유형(진입 카테고리) 선택",
        persona_options,
        help="사용자 웹앱 진입 화면에서 선택하는 값과 동일합니다. 선택 시 해당 분야 문서 안에서만 검색합니다.",
    )
    st.session_state["sim_persona"] = label_to_key.get(chosen_label)

    # 채팅 세션 유지 로직
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "안녕하세요, 강서나눔돌봄센터 AI 챗봇입니다. 서비스 안내 외에도 대화 중 **[📞 담당자에게 메시지 남기기]** 버튼을 통해 언제든 직접 접수하실 수 있습니다."}
        ]

    # 상단 대화 내역 렌더링
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    st.divider()

    # ==========================================================
    # 담당자 메시지 직접 전달 (콜백 접수) 전용 모달/익스팬더 영역
    # ==========================================================
    with st.expander("📞 담당자에게 직접 메시지 전달하기 (상담사 1:1 메시지 접수)", expanded=False):
        st.caption("AI 대화가 만족스럽지 않거나 담당자의 직접 콜백이 필요한 경우 텍스트 또는 음성으로 메시지를 남겨주세요.")
        
        input_mode = st.radio("전달 방식 선택", ["💬 텍스트 메시지 전달", "🎙️ 음성 녹음 메시지 전달 (STT 시뮬레이션)"], horizontal=True)

        with st.form("counselor_inquiry_form", clear_on_submit=True):
            if input_mode == "💬 텍스트 메시지 전달":
                user_msg = st.text_area(
                    "전달할 문의 내용 및 연락처 작성",
                    placeholder="예: 주말 가사간병 방문 서비스 신청하고 싶습니다. 010-1234-5678로 연락 주세요."
                )
                input_type = "text"
            else:
                st.info("🎙️ 마이크를 통해 발화한 음성 데이터가 STT 텍스트로 전환되어 수신되었습니다.")
                user_msg = st.text_area(
                    "음성 인식 텍스트 (STT 변환 결과)",
                    value="(음성 녹음 발화) 등급 신청 관련 서류 제출 방법 설명 전화 부탁합니다. 연락처는 010-9876-5432입니다.",
                    help="음성 인식 결과를 수정하거나 즉시 전달할 수 있습니다."
                )
                input_type = "voice"

            submit_inquiry = st.form_submit_button("🚀 담당자에게 메시지 전달 (Supabase DB 저장)")

        if submit_inquiry:
            if user_msg.strip():
                with st.spinner("AI 분석 엔진이 메시지에서 연락처 및 문의 요약을 추출 중입니다..."):
                    time.sleep(1.0)
                    
                    # AI 추출 및 담당자 웹앱용 카테고리 자동 분류
                    name, contact, summary = extract_contact_and_summary(user_msg.strip())
                    category = classify_inquiry(user_msg.strip())

                    # Supabase `counselor_inquiries` 테이블에 기록!
                    # anon 역할은 이 테이블을 SELECT할 권한이 없으므로(RLS),
                    # 기본값인 return=representation을 쓰면 "삽입 후 되읽기"에서
                    # RLS 위반으로 실패한다. 실제 값을 돌려받을 필요가 없으므로
                    # returning="minimal"로 삽입만 수행한다.
                    supabase.table("counselor_inquiries").insert({
                        "user_name": name,
                        "contact_info": contact,
                        "inquiry_summary": summary,
                        "raw_message": user_msg.strip(),
                        "input_type": input_type,
                        "category": category,
                        "status": "pending"
                    }, returning="minimal").execute()

                    # 대화창에 어시스턴트 안내 추가
                    confirm_text = f"""
                    ✅ **[담당자 메시지 전달 완료]**
                    메시지가 성공적으로 접수되어 담당자 대시보드(Supabase DB)에 기록되었습니다.
                    - **AI 추출 연락처:** `{contact}`
                    - **문의 분류:** `{category}`
                    - **문의 요약:** {summary}
                    - **접수 형태:** `{'🎙️ 음성' if input_type == 'voice' else '💬 텍스트'}`
                    
                    담당자가 확인 후 입력하신 연락처로 신속히 안내 드리겠습니다.
                    """
                    st.session_state.messages.append({"role": "user", "content": f"[담당자 메시지 전달 요청] {user_msg.strip()}"})
                    st.session_state.messages.append({"role": "assistant", "content": confirm_text})
                    
                    st.success("✅ 담당자에게 메시지가 성공적으로 전달되었습니다! (Supabase 저장 완료)")
                    st.rerun()
            else:
                st.warning("⚠️ 전달할 메시지 내용을 입력해 주세요.")

    # 일반 대화 입력창
    if prompt := st.chat_input("질문을 입력하거나 담당자 연결을 요청하세요..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # "담당자 연결 요청" 뿐 아니라 "불만/민원 접수 의사"도 동일하게 담당자 이관 대상으로 취급한다.
        # (예: "청소를 안 하셨어요, 불만 접수할게요" 처럼 담당자/전화 등의 단어가 없어도 실제로는 사람 개입이 필요한 경우)
        # "담당자"/"상담원" 단어가 문장에 포함되기만 해도 담당자 이관으로 빠지면, "상담원에게 뭘
        # 알려줘야 하나요?" 같은 정보성 질문까지 RAG를 건너뛰게 되므로, 실제 연결 요청 표현으로 좁힌다.
        HUMAN_HANDOFF_PHRASES = [
            "담당자 연결", "담당자에게 연결", "담당자와 연결", "담당자 전화", "담당자에게 전화",
            "담당자 부탁", "담당자 콜백",
            "상담원 연결", "상담원에게 연결", "상담원과 연결", "상담원 전화", "상담원에게 전화",
            "상담원 부탁", "상담원 콜백",
            "전화해", "콜백",
        ]
        COMPLAINT_TRIGGER_KEYWORDS = ["불만", "항의", "접수할게요", "접수해주세요", "민원"]
        wants_human = (
            any(k in prompt for k in HUMAN_HANDOFF_PHRASES)
            or any(k in prompt for k in COMPLAINT_TRIGGER_KEYWORDS)
        )

        with st.chat_message("assistant"):
            if wants_human:
                name, contact, summary = extract_contact_and_summary(prompt)

                # 전화번호가 들어있는 경우 즉시 Supabase 자동 적재
                if contact != "연락처 미기재 (원문 확인 필요)":
                    category = classify_inquiry(prompt)
                    # 위와 동일한 이유로 returning="minimal" 사용 (anon은 SELECT 권한 없음)
                    supabase.table("counselor_inquiries").insert({
                        "user_name": name,
                        "contact_info": contact,
                        "inquiry_summary": summary,
                        "raw_message": prompt,
                        "input_type": "text",
                        "category": category,
                        "status": "pending"
                    }, returning="minimal").execute()

                    response_text = f"""
                    📞 **[담당자 접수 완료]**
                    입력하신 문장에서 연락처(`{contact}`)가 감지되어 담당자에게 즉시 전달(Supabase 적재)되었습니다.
                    - **요약:** {summary}

                    실무 담당자가 확인 후 빠른 시일 내에 연락드리겠습니다. 추가 문의가 있으시면 편하게 남겨주세요!
                    """
                else:
                    # 연락처가 없어 counselor_inquiries에는 적재할 수 없지만, 질문 자체가
                    # 유실되지 않도록 fallback_logs에라도 남겨 관리자가 검토할 수 있게 한다.
                    supabase.table("fallback_logs").insert(
                        {"user_query": prompt, "status": "pending", "failure_type": FAILURE_TYPE_HUMAN_REQUESTED},
                        returning="minimal"
                    ).execute()
                    response_text = "불편을 드려 죄송합니다. 담당자가 확인 후 연락드릴 수 있도록 **성함과 연락처(예: 010-XXXX-XXXX)**를 함께 남겨주시거나, 상단의 **[📞 담당자에게 직접 메시지 전달하기]** 를 이용해 주세요."

            else:
                # 0-1. 질의 정규화: 오탈자 교정 + 축약된 단문을 완전한 문장으로 보완한다.
                # 검색(임베딩) 직전에 항상 수행하며, 실패 시 원문이 그대로 반환되므로 안전하다.
                with st.spinner("질문을 분석하는 중..."):
                    # 방금 추가한 현재 사용자 메시지를 제외한, 그 이전까지의 대화가 "이전 맥락"이다.
                    prior_history = st.session_state.messages[:-1]
                    normalized_prompt = normalize_query(prompt, history=prior_history)

                if normalized_prompt != prompt:
                    st.caption(f"🔍 검색 질의 보정: \"{prompt}\" → \"{normalized_prompt}\"")

                # 0-2. 컴플라이언스 가드레일 검사 (bot_settings 반영)
                # 오탈자로 키워드 탐지가 회피되지 않도록 원문+보정문을 함께 검사한다.
                guardrail_check_text = f"{prompt} {normalized_prompt}"
                is_blocked, block_reason = check_guardrail_block(guardrail_check_text, current_setting)

                if is_blocked:
                    response_text = (
                        f"🚨 **[Fallback 발동]** {block_reason}\n"
                        "상세한 안내는 보건소나 센터(02-2065-1584)로 직접 문의 부탁드리며, "
                        "**[📞 담당자에게 직접 메시지 전달하기]** 를 통해 연락처를 남겨주시면 담당자가 안내해 드립니다."
                    )
                else:
                    # RAG 일반 응답 로직 (strictness_level → 코사인 유사도 임계치 반영)
                    with st.spinner("RAG 벡터 지식베이스 검색 중..."):
                        time.sleep(1.0)
                        user_vec = generate_embedding(normalized_prompt)
                        # 서버사이드 하이브리드 검색(RPC): 벡터 후보군(matches)은 기존과 동일하게
                        # 코사인 임계치 게이트에 사용하고, 키워드 후보군(keyword_matches)은
                        # "3구간"처럼 특정 값/고유명사 질의를 순위와 무관하게 구제하는 용도다.
                        selected_persona = st.session_state.get("sim_persona")
                        persona_categories = PERSONA_CATEGORIES.get(selected_persona) if selected_persona else None
                        matches, keyword_matches = hybrid_search(
                            normalized_prompt, user_vec, match_count=30, categories=persona_categories
                        )

                        # 페르소나 미선택 시, "얼마예요?"처럼 짧고 일반적인 질문은 활동지원/가사
                        # 두 서비스 문서가 비슷한 점수로 뒤섞여 근거가 빈약한 쪽으로 우연히 답이
                        # 나갈 수 있다(실측: 동일 질문인데 실행할 때마다 답변/폴백이 오감).
                        # 이 경우 추측하지 않고 어떤 서비스인지 먼저 되묻는다.
                        is_ambiguous_service = (not persona_categories) and detect_ambiguous_service(matches)

                        # 사용자가 상황을 잘못 골랐을 수 있으므로, 필터 검색이 게이트를 통과하지
                        # 못하면 전체 검색으로 한 번 더 시도한다(하드 필터로 답을 잃지 않게 하는 안전장치).
                        gate_threshold = STRICTNESS_THRESHOLD.get(current_setting.get("strictness_level", 5), 0.70)
                        if persona_categories and not (matches and matches[0][0] >= gate_threshold):
                            wide_matches, wide_keywords = hybrid_search(normalized_prompt, user_vec, match_count=30)
                            if wide_matches and wide_matches[0][0] >= gate_threshold:
                                matches, keyword_matches = wide_matches, wide_keywords
                                st.caption("🧭 선택하신 분야에서 답을 찾지 못해 전체 분야로 확장해 검색했습니다.")

                        # HITL 시맨틱 캐시: 관리자가 이미 검증한 모범 정답과 거의 동일한 질문이면,
                        # LLM 재호출 없이 검증 답변을 즉시 반환한다(속도/비용 절감 + 정답 신뢰도 보장).
                        hitl_cache_hit = next(
                            (m for m in matches if m[0] >= HITL_CACHE_THRESHOLD and m[2] == "수동학습(HITL)"),
                            None,
                        )

                        strictness = current_setting.get("strictness_level", 5)
                        threshold = STRICTNESS_THRESHOLD.get(strictness, 0.70)

                        if is_ambiguous_service:
                            response_text = (
                                "어떤 서비스에 대해 궁금하신가요? \"장애인활동지원\" 또는 \"가사서비스\"라고 "
                                "말씀해 주시면 더 정확하게 안내해 드릴게요."
                            )
                        elif hitl_cache_hit:
                            cached_answer = extract_hitl_answer(hitl_cache_hit[1])
                            response_text = (
                                f"{cached_answer}\n\n"
                                f"**[출처]:** 관리자 검증 답변 (HITL 캐시 · 유사도 {hitl_cache_hit[0]:.2f})"
                            )
                        elif (matches and matches[0][0] >= threshold) or keyword_matches:
                            # 벡터 임계치를 통과했는지 여부와 별개로 진입한다: "3구간"처럼 벡터 유사도만으로는
                            # 임계치를 넘는 문서가 하나도 없어도, pg_trgm 키워드 검색이 정확 매칭 문서를
                            # 찾아왔다면 그것만으로도 답변을 시도한다(과거엔 벡터 게이트를 통과한 경우에만
                            # 키워드 후보를 "보조로" 끼워 넣었을 뿐, 벡터가 전부 실패하면 키워드 매칭이
                            # 있어도 구제하지 못했다).
                            vector_gate_passed = bool(matches and matches[0][0] >= threshold)

                            # 임계치를 넘는 상위 문서(최대 5개)를 컨텍스트로 모아 LLM이 자연어 답변을 합성하게 한다.
                            # 행 단위(원자적) 청킹 이후에는 복합 질문 하나에 필요한 사실이 3개를 넘는 경우가 있어
                            # top-3로는 근거가 밀려날 수 있다(실측: 유사도 0.7344 청크가 top-3 밖으로 밀린 사례).
                            # 컨텍스트 포함 기준은 게이트보다 느슨하게 잡는다(단, 게이트보다
                            # 엄격해지지 않도록 min으로 묶는다).
                            ctx_threshold = min(threshold, CONTEXT_THRESHOLD)
                            top_matches = [m for m in matches if m[0] >= ctx_threshold][:5]

                            # "1구간", "8구간"처럼 사용자가 특정 값을 콕 집어 물으면, 벡터 유사도만으로는
                            # 근거가 안 밀리기 어렵다(본인부담금 15개 구간처럼 서로 거의 같은 구조의 행이 많으면
                            # 유사도 차이가 0.02~0.03 안에서 뒤섞여 원하는 구간이 top-5 밖으로 밀릴 수 있다).
                            # hybrid_search()가 pg_trgm 키워드 유사도로 찾아온 보조 후보군을 순위와
                            # 무관하게 강제 포함한다(과거의 \d+구간 정규식 하드코딩을 일반화한 것).
                            if keyword_matches:
                                already = {m[1] for m in top_matches}
                                for m in keyword_matches:
                                    if m[1] not in already:
                                        top_matches.append(m)
                                        already.add(m[1])

                            context_chunks = [m[1] for m in top_matches]
                            source_categories = ", ".join(sorted({m[2] for m in top_matches}))
                            # 키워드 매칭 값은 트라이그램 유사도라 코사인 임계치와 스케일이 달라
                            # "기준 대비 점수"로 표시하면 오해를 줄 수 있으므로, 벡터 게이트 통과 여부에
                            # 따라 출처 표기 방식을 분리한다.
                            top_score = top_matches[0][0] if top_matches else 0.0

                            gemini_provider = supabase.table("llm_providers").select("model_name").eq("vendor_id", "gemini").execute().data
                            gemini_model = (gemini_provider[0]["model_name"] if gemini_provider else None) or "gemini-3.1-flash-lite"

                            tone = current_setting.get("tone", "친절한 상담원")
                            # 컨텍스트에 접수 폼 명세(B_접수)나 미검증 내용이 섞였는지 알려,
                            # 답변 톤을 각각 "접수 안내" / "확인 필요" 로 조정하게 한다.
                            has_intake = any(m[3] == "B_접수" for m in top_matches if len(m) > 3)
                            has_unverified = any(m[4] == "고객확인필요" for m in top_matches if len(m) > 4)
                            # 정규화된 질의를 사용한다: "그럼 2구간은요?" 같은 원문 그대로 넘기면
                            # LLM이 무엇을 묻는지 다시 헷갈릴 수 있으므로, 이미 맥락이 풀린 독립형
                            # 질문으로 답변을 생성해야 자연스럽다.
                            llm_answer = generate_chat_answer(
                                normalized_prompt, context_chunks, tone, gemini_model,
                                has_intake=has_intake, has_unverified=has_unverified,
                            )

                            if llm_answer and is_no_answer_response(llm_answer):
                                # 유사도 임계치는 통과했지만 LLM이 스스로(질문의 일부라도) "근거 자료에 없다"고
                                # 밝힌 경우. 정상 답변처럼 보여주지 않고 HITL 검토 대상(fallback_logs)으로 등록한다.
                                clean_answer = strip_gap_marker(llm_answer)
                                supabase.table("fallback_logs").insert(
                                    {"user_query": prompt, "status": "pending", "failure_type": FAILURE_TYPE_LOW_CONFIDENCE},
                                    returning="minimal"
                                ).execute()
                                response_text = (
                                    f"{clean_answer}\n\n"
                                    "🚨 **[상담사 연결 권장]** 지식베이스에서 확실한 근거를 찾지 못해 관리자 검토 목록에 등록했습니다. "
                                    "빠른 확인이 필요하시면 **[📞 담당자에게 직접 메시지 전달하기]** 를 이용해 주세요."
                                )
                            elif llm_answer:
                                if vector_gate_passed:
                                    response_text = f"{llm_answer}\n\n**[출처]:** [{source_categories}] (유사도 Score: {top_score:.2f} / 기준 {threshold:.2f})"
                                else:
                                    # 벡터 임계치는 못 넘었지만 키워드(트라이그램) 검색으로 구제된 경우.
                                    # 트라이그램 점수는 코사인 임계치와 스케일이 달라 나란히 표기하면 오해를 주므로 분리한다.
                                    response_text = f"{llm_answer}\n\n**[출처]:** [{source_categories}] (키워드 검색 매칭 · 벡터 유사도 기준 미달)"
                            else:
                                # LLM 응답 생성 실패 시(키 미등록/API 오류) 원문 청크로 안전하게 대체
                                top_match = top_matches[0] if top_matches else matches[0]
                                if vector_gate_passed:
                                    response_text = f"{top_match[1]}\n\n**[출처]:** [{top_match[2]}] (유사도 Score: {top_match[0]:.2f} / 기준 {threshold:.2f})"
                                else:
                                    response_text = f"{top_match[1]}\n\n**[출처]:** [{top_match[2]}] (키워드 검색 매칭 · 벡터 유사도 기준 미달)"
                        else:
                            # 임계치 이상 문서가 하나도 없는, 가장 흔한 지식 공백 케이스.
                            # 이것도 HITL 검토 대상으로 남겨야 오답 리뷰(Module 02)에서 놓치지 않는다.
                            supabase.table("fallback_logs").insert(
                                {"user_query": prompt, "status": "pending", "failure_type": FAILURE_TYPE_NO_MATCH},
                                returning="minimal"
                            ).execute()
                            response_text = (
                                "🚨 **[상담사 연결 권장]** 현재 엄격도 설정 기준(유사도 "
                                f"{threshold:.2f} 이상)을 충족하는 지식베이스 정보를 찾지 못했습니다.\n"
                                "상단의 **[📞 담당자에게 직접 메시지 전달하기]** 버튼을 통해 성함과 연락처를 남겨주시면 담당자가 즉시 확인 후 상담을 진행해 드립니다."
                            )

                response_text = apply_tone(response_text, current_setting.get("tone", "친절한 상담원"))

            st.markdown(response_text)
            st.session_state.messages.append({"role": "assistant", "content": response_text})
