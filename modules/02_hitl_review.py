import streamlit as st
from core.db import supabase
from core.rag_engine import generate_embedding

def render():
    st.markdown('<div class="ace-badge ace-badge-olive">MODULE 02</div>', unsafe_allow_html=True)
    st.title("🧠 오답 리뷰 및 AI 신규 학습 (HITL)")
    st.markdown("챗봇이 답변 임계치 미달로 **상담사 연결(Fallback)** 코드를 반환한 사용자 미해결 질문 모니터링 및 자가진화 파이프라인입니다.")
    st.divider()

    # 상단 요약 메트릭
    res_pending = supabase.table("fallback_logs").select("*").eq("status", "pending").execute()
    res_resolved = supabase.table("fallback_logs").select("*").eq("status", "resolved").execute()

    pending_logs = res_pending.data if res_pending.data else []
    resolved_logs = res_resolved.data if res_resolved.data else []

    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("🔴 처리 대기 중 오답 건수", f"{len(pending_logs)}건")
    with m2:
        st.metric("🟢 개선 완료 모범 정답", f"{len(resolved_logs)}건")
    with m3:
        total = len(pending_logs) + len(resolved_logs)
        rate = (len(resolved_logs) / total * 100) if total > 0 else 100
        st.metric("📈 HITL 지식 커버리지율", f"{rate:.1f}%")

    st.divider()
    st.subheader("📋 검토 필요한 미해결 질문 목록")

    if pending_logs:
        for idx, log in enumerate(pending_logs):
            log_id = log.get("id")
            user_query = log.get("user_query") or "미상 질의"
            created_at = str(log.get("created_at") or "")[:19].replace("T", " ")

            with st.expander(f"🔴 [{created_at}] 사용자 질의: {user_query}", expanded=(idx == 0)):
                st.markdown(f"**사용자질문 원문:** `{user_query}`")
                st.caption("AI가 지식베이스 미비로 직접 대답하지 못하고 방어(Fallback)한 질문입니다.")

                # 모범 정답 입력란
                golden_answer = st.text_area(
                    "💡 최고 관리자 모범 정답(Golden Answer) 작성:",
                    placeholder="예: 야간 긴급 가사간병 서비스는 센터 사전 검토 후 최대 주 2회까지 지원 가능합니다.",
                    key=f"golden_{log_id}"
                )

                col1, col2 = st.columns([2, 1])
                with col1:
                    if st.button("🚀 AI 신규 지식으로 즉시 주입 및 학습 반영", key=f"btn_save_{log_id}"):
                        if golden_answer.strip():
                            with st.spinner("Q&A 지식 청크 생성 및 Vector DB 편입 중..."):
                                # 1. Q&A 텍스트 결합 청크 생성
                                combined_text = f"질문: {user_query}\n답변: {golden_answer.strip()}"
                                vec = generate_embedding(combined_text)

                                # 2. rag_documents 테이블에 즉각 편입
                                supabase.table("rag_documents").insert({
                                    "content": combined_text,
                                    "category": "수동학습(HITL)",
                                    "embedding": vec
                                }).execute()

                                # 3. fallback_logs 상태 업데이트
                                supabase.table("fallback_logs").update({
                                    "status": "resolved",
                                    "golden_answer": golden_answer.strip()
                                }).eq("id", log_id).execute()

                                st.success("✅ 모범 정답이 Vector DB에 각인되었으며 챗봇 지식이 고도화되었습니다!")
                                st.rerun()
                        else:
                            st.warning("⚠️ 모범 정답 내용을 작성한 후 학습 버튼을 클릭해 주세요.")

                with col2:
                    if st.button("❌ 단순 스팸/무시 처리", key=f"btn_ignore_{log_id}", type="secondary"):
                        supabase.table("fallback_logs").update({
                            "status": "resolved",
                            "golden_answer": "[관리자 무시 처리]"
                        }).eq("id", log_id).execute()
                        st.info("해결 완료(무시) 처리되었습니다.")
                        st.rerun()
    else:
        st.success("🎉 현재 모든 오답 로그가 리뷰 완료되었습니다. AI가 최상의 컨디션을 유지 중입니다.")

    st.divider()
    # 최근 처리 완료 내역 보기
    with st.expander("📚 최근 반영 완료된 HITL 모범 정답 기록 보기"):
        if resolved_logs:
            for r_log in resolved_logs[:10]:
                st.markdown(f"**Q:** `{r_log.get('user_query')}`")
                st.markdown(f"**A (Golden Answer):** {r_log.get('golden_answer')}")
                st.caption(f"처리일시: {str(r_log.get('created_at') or '')[:19]}")
                st.divider()
        else:
            st.caption("아직 완료된 HITL 기록이 없습니다.")
