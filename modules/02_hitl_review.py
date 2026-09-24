import streamlit as st
from core.db import supabase, is_mock_db
from core.rag_engine import generate_embedding, generate_embedding_strict


def _explain_failure(err: Exception) -> str:
    """처리 실패 원인을 관리자가 조치할 수 있는 문장으로 바꾼다."""
    if "golden_answer" in str(err):
        return ("fallback_logs 테이블에 golden_answer 컬럼이 없습니다. "
                "Supabase SQL Editor에서 supabase/010_fallback_logs_golden_answer.sql을 실행해 주세요.")
    return str(err)


def _resolve_log(log_id, golden_answer: str):
    supabase.table("fallback_logs").update({
        "status": "resolved",
        "golden_answer": golden_answer,
    }).eq("id", log_id).execute()

# 06_simulator.py가 fallback_logs 적재 시 함께 남기는 failure_type 값의 표시 라벨.
# 값이 없는 레거시 로그(migration 004 적용 이전 데이터)는 "미분류"로 표기한다.
FAILURE_TYPE_LABELS = {
    "no_match": "🔍 지식 공백 (문서 자체가 없음)",
    "low_confidence": "🤔 근거 불충분 (문서는 찾았으나 확신 못함)",
    "human_requested": "📞 담당자 직접요청 (연락처 미기재)",
}


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
    st.subheader("🧭 실패유형 분포 (대기 중 기준)")
    st.caption("어떤 원인의 오답이 가장 많은지를 보고, 지식베이스 보강/질의 정규화 튜닝/가드레일 조정 중 무엇을 우선할지 판단하는 데 활용하세요.")
    if pending_logs:
        type_counts = {}
        for log in pending_logs:
            type_counts[log.get("failure_type")] = type_counts.get(log.get("failure_type"), 0) + 1
        type_cols = st.columns(len(type_counts))
        for col, (ftype, count) in zip(type_cols, sorted(type_counts.items(), key=lambda x: -x[1])):
            col.metric(FAILURE_TYPE_LABELS.get(ftype, "❔ 미분류(레거시 로그)"), f"{count}건")
    else:
        st.caption("대기 중인 오답 로그가 없어 집계할 항목이 없습니다.")

    st.divider()
    st.subheader("📋 검토 필요한 미해결 질문 목록")

    if pending_logs:
        for idx, log in enumerate(pending_logs):
            log_id = log.get("id")
            user_query = log.get("user_query") or "미상 질의"
            created_at = str(log.get("created_at") or "")[:19].replace("T", " ")

            with st.expander(f"🔴 [{created_at}] 사용자 질의: {user_query}", expanded=(idx == 0)):
                ftype_label = FAILURE_TYPE_LABELS.get(log.get("failure_type"), "❔ 미분류(레거시 로그)")
                st.markdown(f"**사용자질문 원문:** `{user_query}`  ·  **실패유형:** {ftype_label}")
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
                                # 한쪽만 반영되지 않도록 순서를 정한다: ① 임베딩 → ② 로그 처리 → ③ 지식 편입.
                                # 예전에는 지식을 먼저 넣고 로그를 갱신했는데, 로그 갱신이 실패하면
                                # (운영 DB에 golden_answer 컬럼이 없어 실제로 매번 실패했다) 지식만 들어가고
                                # 목록에는 그대로 남아 같은 답을 중복 주입할 수 있었다.
                                combined_text = f"질문: {user_query}\n답변: {golden_answer.strip()}"
                                try:
                                    # Mock 모드에는 실제 키가 없으므로 결정론적 벡터를 쓴다(데모 전용).
                                    vec = generate_embedding(combined_text) if is_mock_db else generate_embedding_strict(combined_text)
                                    _resolve_log(log_id, golden_answer.strip())
                                except Exception as e:
                                    st.error(f"🚨 처리하지 못했습니다(아무것도 저장되지 않음): {_explain_failure(e)}")
                                    st.stop()
                                try:
                                    supabase.table("rag_documents").insert({
                                        "content": combined_text,
                                        "category": "수동학습(HITL)",
                                        "embedding": vec,
                                        "doc_type": "A_사실",
                                    }).execute()
                                except Exception as e:
                                    supabase.table("fallback_logs").update({"status": "pending"}).eq("id", log_id).execute()
                                    st.error(f"🚨 지식 편입에 실패해 처리를 되돌렸습니다: {e}")
                                    st.stop()

                                st.success("✅ 모범 정답이 Vector DB에 각인되었으며 챗봇 지식이 고도화되었습니다!")
                                st.rerun()
                        else:
                            st.warning("⚠️ 모범 정답 내용을 작성한 후 학습 버튼을 클릭해 주세요.")

                with col2:
                    if st.button("❌ 단순 스팸/무시 처리", key=f"btn_ignore_{log_id}", type="secondary"):
                        try:
                            _resolve_log(log_id, "[관리자 무시 처리]")
                        except Exception as e:
                            st.error(f"🚨 처리하지 못했습니다: {_explain_failure(e)}")
                            st.stop()
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
