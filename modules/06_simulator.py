import streamlit as st
import re
import time
import datetime
from core.db import supabase
from core.rag_engine import (
    generate_embedding, calculate_cosine_similarity, parse_embedding,
    generate_chat_answer, ANSWER_GAP_MARKER,
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


def check_guardrail_block(prompt: str, settings: dict):
    """
    bot_settings의 컴플라이언스 토글에 따라 해당 주제 질의를 강제 차단한다.
    차단 대상이면 (True, 사유텍스트)를, 아니면 (False, None)을 반환한다.
    """
    if settings.get("block_medical", True) and any(k in prompt for k in MEDICAL_KEYWORDS):
        return True, "🏥 의료/질병 진단 관련 문의는 컴플라이언스 가드레일에 의해 차단되었습니다."
    if settings.get("block_legal", True) and any(k in prompt for k in LEGAL_KEYWORDS):
        return True, "⚖️ 법률/노무 상담 관련 문의는 컴플라이언스 가드레일에 의해 차단되었습니다."
    if settings.get("block_privacy", True) and any(k in prompt for k in PRIVACY_KEYWORDS):
        return True, "🔒 개인정보 수집이 필요한 문의는 컴플라이언스 가드레일에 의해 차단되었습니다."
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
                        {"user_query": prompt, "status": "pending"}, returning="minimal"
                    ).execute()
                    response_text = "불편을 드려 죄송합니다. 담당자가 확인 후 연락드릴 수 있도록 **성함과 연락처(예: 010-XXXX-XXXX)**를 함께 남겨주시거나, 상단의 **[📞 담당자에게 직접 메시지 전달하기]** 를 이용해 주세요."

            else:
                # 0. 컴플라이언스 가드레일 우선 검사 (bot_settings 반영)
                is_blocked, block_reason = check_guardrail_block(prompt, current_setting)

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
                        user_vec = generate_embedding(prompt)
                        docs_res = supabase.table("rag_documents").select("content, category, embedding").execute()
                        docs = docs_res.data if docs_res.data else []

                        matches = []
                        for doc in docs:
                            # pgvector 컬럼은 실DB에서 문자열로 반환되므로 길이 비교 전에 파싱해야 한다.
                            doc_vec = parse_embedding(doc.get("embedding"))
                            if doc_vec and len(doc_vec) == len(user_vec):
                                sim = calculate_cosine_similarity(user_vec, doc_vec)
                                matches.append((sim, doc.get("content"), doc.get("category")))

                        matches.sort(key=lambda x: x[0], reverse=True)

                        strictness = current_setting.get("strictness_level", 5)
                        threshold = STRICTNESS_THRESHOLD.get(strictness, 0.70)

                        if matches and matches[0][0] >= threshold:
                            # 임계치를 넘는 상위 문서(최대 5개)를 컨텍스트로 모아 LLM이 자연어 답변을 합성하게 한다.
                            # 행 단위(원자적) 청킹 이후에는 복합 질문 하나에 필요한 사실이 3개를 넘는 경우가 있어
                            # top-3로는 근거가 밀려날 수 있다(실측: 유사도 0.7344 청크가 top-3 밖으로 밀린 사례).
                            top_matches = [m for m in matches[:5] if m[0] >= threshold]

                            # "1구간", "8구간"처럼 사용자가 특정 값을 콕 집어 물으면, 벡터 유사도만으로는
                            # 근거가 안 밀리기 어렵다(본인부담금 15개 구간처럼 서로 거의 같은 구조의 행이 많으면
                            # 유사도 차이가 0.02~0.03 안에서 뒤섞여 원하는 구간이 top-5 밖으로 밀릴 수 있다).
                            # 질문에 명시된 구간 번호가 있으면 순위와 무관하게 정확매칭으로 강제 포함한다.
                            exact_terms = set(re.findall(r"\d+구간", prompt))
                            if exact_terms:
                                already = {m[1] for m in top_matches}
                                for m in matches:
                                    if m[1] not in already and any(term in m[1] for term in exact_terms):
                                        top_matches.append(m)
                                        already.add(m[1])

                            context_chunks = [m[1] for m in top_matches]
                            source_categories = ", ".join(sorted({m[2] for m in top_matches}))
                            top_score = top_matches[0][0]

                            gemini_provider = supabase.table("llm_providers").select("model_name").eq("vendor_id", "gemini").execute().data
                            gemini_model = (gemini_provider[0]["model_name"] if gemini_provider else None) or "gemini-3.1-flash-lite"

                            tone = current_setting.get("tone", "친절한 상담원")
                            llm_answer = generate_chat_answer(prompt, context_chunks, tone, gemini_model)

                            if llm_answer and is_no_answer_response(llm_answer):
                                # 유사도 임계치는 통과했지만 LLM이 스스로(질문의 일부라도) "근거 자료에 없다"고
                                # 밝힌 경우. 정상 답변처럼 보여주지 않고 HITL 검토 대상(fallback_logs)으로 등록한다.
                                clean_answer = strip_gap_marker(llm_answer)
                                supabase.table("fallback_logs").insert(
                                    {"user_query": prompt, "status": "pending"}, returning="minimal"
                                ).execute()
                                response_text = (
                                    f"{clean_answer}\n\n"
                                    "🚨 **[상담사 연결 권장]** 지식베이스에서 확실한 근거를 찾지 못해 관리자 검토 목록에 등록했습니다. "
                                    "빠른 확인이 필요하시면 **[📞 담당자에게 직접 메시지 전달하기]** 를 이용해 주세요."
                                )
                            elif llm_answer:
                                response_text = f"{llm_answer}\n\n**[출처]:** [{source_categories}] (유사도 Score: {top_score:.2f} / 기준 {threshold:.2f})"
                            else:
                                # LLM 응답 생성 실패 시(키 미등록/API 오류) 원문 청크로 안전하게 대체
                                top_match = matches[0]
                                response_text = f"{top_match[1]}\n\n**[출처]:** [{top_match[2]}] (유사도 Score: {top_match[0]:.2f} / 기준 {threshold:.2f})"
                        else:
                            # 임계치 이상 문서가 하나도 없는, 가장 흔한 지식 공백 케이스.
                            # 이것도 HITL 검토 대상으로 남겨야 오답 리뷰(Module 02)에서 놓치지 않는다.
                            supabase.table("fallback_logs").insert(
                                {"user_query": prompt, "status": "pending"}, returning="minimal"
                            ).execute()
                            response_text = (
                                "🚨 **[상담사 연결 권장]** 현재 엄격도 설정 기준(유사도 "
                                f"{threshold:.2f} 이상)을 충족하는 지식베이스 정보를 찾지 못했습니다.\n"
                                "상단의 **[📞 담당자에게 직접 메시지 전달하기]** 버튼을 통해 성함과 연락처를 남겨주시면 담당자가 즉시 확인 후 상담을 진행해 드립니다."
                            )

                response_text = apply_tone(response_text, current_setting.get("tone", "친절한 상담원"))

            st.markdown(response_text)
            st.session_state.messages.append({"role": "assistant", "content": response_text})
