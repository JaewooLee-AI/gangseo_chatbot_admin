import streamlit as st
import pandas as pd
from core.db import supabase, is_mock_db

def render():
    st.markdown('<div class="ace-badge ace-badge-olive">MODULE 05</div>', unsafe_allow_html=True)
    st.title("👥 직원 계정 및 접수 문의 관리")
    st.markdown("Vercel CS 웹앱 접근용 **직원 화이트리스트 계정** 관리 및 챗봇에서 이관된 **담당자 전달 메시지/콜백 접수건**을 조회하고 처리합니다.")
    st.divider()

    tab_inquiry, tab_staff = st.tabs(["📥 미처리 담당자 전달 메시지 관리 (Supabase 접수건)", "👥 직원 화이트리스트 계정 관리"])

    # ==========================================================
    # TAB 1: 미처리 담당자 전달 메시지/접수 문의 조회 및 처리
    # ==========================================================
    with tab_inquiry:
        st.subheader("📥 챗봇 전달 메시지 및 콜백 접수 현황")
        st.caption("챗봇 이용 중 대화가 만족스럽지 않거나 직접 문의를 남긴 사용자의 AI 추출 연락처 및 문의 내용입니다.")

        # Supabase `counselor_inquiries` 테이블 조회
        res_pending = supabase.table("counselor_inquiries").select("*").eq("status", "pending").execute()
        res_resolved = supabase.table("counselor_inquiries").select("*").eq("status", "resolved").execute()

        pending_inquiries = res_pending.data if res_pending.data else []
        resolved_inquiries = res_resolved.data if res_resolved.data else []

        # 상단 현황 메트릭
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("🔴 미처리 접수 건수", f"{len(pending_inquiries)}건")
        with m2:
            st.metric("🟢 상담 처리 완료", f"{len(resolved_inquiries)}건")
        with m3:
            total_cnt = len(pending_inquiries) + len(resolved_inquiries)
            st.metric("📱 전체 접수 누적", f"{total_cnt}건")

        st.divider()

        # 담당자 웹앱과 동일하게 카테고리 기준 조회/필터링 지원
        staff_res = supabase.table("staff_users").select("id, staff_name").execute()
        staff_list = staff_res.data if staff_res.data else []
        staff_name_by_id = {s["id"]: s["staff_name"] for s in staff_list}

        category_options = ["전체", "미분류", "요금문의", "서비스신청", "자격상담", "불만접수", "일반문의", "기타"]
        selected_category_filter = st.selectbox("📂 카테고리로 필터링", category_options, key="inquiry_category_filter")

        if selected_category_filter != "전체":
            pending_inquiries = [i for i in pending_inquiries if i.get("category", "미분류") == selected_category_filter]

        if pending_inquiries:
            st.markdown("### 📋 미처리 접수 목록 (우선 연락 필요)")

            for idx, item in enumerate(pending_inquiries):
                # .get(key, default)는 값이 명시적으로 None인 경우(컬럼은 있으나 NULL)에는
                # 기본값을 적용하지 않으므로, 문자열 슬라이싱 등에서 죽지 않도록 `or`로 한 번 더 보정한다.
                inquiry_id = item.get("id")
                user_name = item.get("user_name") or "미상 신청자"
                contact_info = item.get("contact_info") or "연락처 미기재"
                summary = item.get("inquiry_summary") or "요약 없음"
                raw_msg = item.get("raw_message") or ""
                input_type = item.get("input_type") or "text"
                category = item.get("category") or "미분류"
                created_at = str(item.get("created_at") or "")[:19].replace("T", " ")

                type_badge = "🎙️ 음성 녹음" if input_type == "voice" else "💬 텍스트"

                with st.expander(f"🔴 [{created_at}] [{category}] [{type_badge}] {user_name} ({contact_info}) - {summary[:30]}...", expanded=(idx == 0)):
                    st.markdown(f"**👤 신청자/보호자:** `{user_name}`")
                    st.markdown(f"**📞 AI 추출 연락처:** `{contact_info}`")
                    st.markdown(f"**📂 문의 분류:** `{category}`")
                    st.markdown(f"**📝 AI 문의 요약:** {summary}")
                    # 원문에는 접수번호와 접수 직전 챗봇 대화가 여러 줄로 담겨 온다(운영 웹 /api/tickets).
                    # 마크다운 인용(>)은 첫 문단만 인용되고 줄바꿈이 합쳐지므로 줄바꿈을 보존해 표시한다.
                    st.markdown("**💬 원문 발화 메시지:**")
                    st.text(raw_msg)
                    st.caption(f"접수 유형: {type_badge} | 접수 일시: {created_at}")

                    st.divider()

                    # 처리 입력 폼
                    admin_note = st.text_input("📝 처리 조치 메모 (예: 10:30 전화 통화 완료 및 가사간병 신청서 안내함)", key=f"note_{inquiry_id}")

                    if staff_list:
                        resolver_options = {s["staff_name"]: s["id"] for s in staff_list}
                        resolver_name = st.selectbox(
                            "👤 처리 담당자 선택",
                            list(resolver_options.keys()),
                            key=f"resolver_{inquiry_id}"
                        )
                    else:
                        resolver_options = {}
                        resolver_name = None
                        st.caption("⚠️ 등록된 직원이 없어 처리 담당자를 지정할 수 없습니다. 아래 '직원 화이트리스트 계정 관리' 탭에서 먼저 등록해 주세요.")

                    c_btn1, c_btn2 = st.columns([1.5, 1])
                    with c_btn1:
                        if st.button("✅ 상담 및 콜백 처리 완료 (Status: Resolved)", key=f"btn_resolve_{inquiry_id}", type="primary"):
                            update_payload = {
                                "status": "resolved",
                                "admin_note": admin_note if admin_note.strip() else "상담 완료 처리됨"
                            }
                            if resolver_name:
                                update_payload["resolved_by"] = resolver_options[resolver_name]

                            supabase.table("counselor_inquiries").update(update_payload).eq("id", inquiry_id).execute()

                            st.success(f"✅ [{user_name} / {contact_info}] 님의 건이 처리 완료로 변경되었습니다.")
                            st.rerun()

                    with c_btn2:
                        if st.button("🗑️ 단순 테스트건 삭제", key=f"btn_del_inquiry_{inquiry_id}", type="secondary"):
                            supabase.table("counselor_inquiries").delete().eq("id", inquiry_id).execute()
                            st.info("삭제되었습니다.")
                            st.rerun()

        else:
            st.success("🎉 현재 처리 대기 중인 담당자 전달 메시지가 없습니다.")

        st.divider()

        # 완료된 접수 기록 보기
        with st.expander("📚 상담 완료 처리된 이력 보기"):
            if resolved_inquiries:
                df_resolved = pd.DataFrame(resolved_inquiries)
                if "category" not in df_resolved.columns:
                    df_resolved["category"] = "미분류"
                df_resolved["resolved_by_name"] = df_resolved.get("resolved_by", pd.Series(dtype=object)).map(
                    lambda sid: staff_name_by_id.get(sid, "-") if sid else "-"
                )
                st.dataframe(
                    df_resolved[['created_at', 'category', 'user_name', 'contact_info', 'inquiry_summary', 'admin_note', 'resolved_by_name']],
                    use_container_width=True,
                    column_config={
                        "created_at": "접수일시",
                        "category": "분류",
                        "user_name": "신청자",
                        "contact_info": "연락처",
                        "inquiry_summary": "문의요약",
                        "admin_note": "처리메모",
                        "resolved_by_name": "처리 담당자"
                    }
                )
            else:
                st.caption("아직 완료된 접수 이력이 없습니다.")

    # ==========================================================
    # TAB 2: 직원 화이트리스트 계정 관리
    # ==========================================================
    with tab_staff:
        col_add, col_list = st.columns([1, 1.4], gap="large")

        with col_add:
            st.subheader("➕ 신규 실무자 화이트리스트 등록")
            with st.form("staff_registration_form", clear_on_submit=True):
                new_name = st.text_input("직원 성명", placeholder="예: 홍길동")
                new_email = st.text_input("직원 이메일 (인증코드 발송용)", placeholder="example@gangseo.go.kr")

                dept = st.selectbox("소속 부서/팀", ["민원상담팀", "요금정산팀", "긴급돌봄팀", "센터관리팀"])
                grant_admin = st.checkbox("🔐 이 Streamlit 최고 관리자 대시보드 로그인 권한도 부여", value=False)

                submit_staff = st.form_submit_button("✅ 화이트리스트 계정 추가")

            if submit_staff:
                if new_name.strip() and new_email.strip():
                    if "@" not in new_email:
                        st.error("🚨 올바른 이메일 형식이 아닙니다.")
                    else:
                        try:
                            check_res = supabase.table("staff_users").select("*").eq("email", new_email.strip()).execute()
                            if check_res.data:
                                st.warning("⚠️ 이미 화이트리스트에 등록된 이메일 주소입니다.")
                            else:
                                # CS 웹앱 로그인용 Supabase Auth 계정을 함께 생성한다.
                                # email_confirm=True로 만들어야 직원의 "첫" 로그인부터 바로
                                # 6자리(또는 프로젝트 설정에 따라 8자리) 인증 코드 메일을 받는다.
                                # 이걸 생략하면 Supabase가 미확인 계정으로 취급해 첫 로그인 시엔
                                # 코드 없이 확인 링크만 담긴 이메일을 보내 버린다.
                                if not is_mock_db:
                                    try:
                                        supabase.auth.admin.create_user({
                                            "email": new_email.strip(),
                                            "email_confirm": True,
                                        })
                                    except Exception as auth_err:
                                        # 이미 Auth 계정이 있는 경우(과거 로그인 시도 등)는 정상 진행
                                        if "already been registered" not in str(auth_err).lower():
                                            raise

                                supabase.table("staff_users").insert({
                                    "staff_name": new_name.strip(),
                                    "email": new_email.strip(),
                                    "department": dept,
                                    "is_admin": grant_admin
                                }).execute()
                                st.success(f"✅ '{new_name}' ({new_email}) 직원이 화이트리스트에 성공적으로 등록되었습니다. (로그인 계정도 함께 생성됨)")
                                st.rerun()
                        except Exception as e:
                            st.error(f"등록 실패: {str(e)}")
                else:
                    st.warning("직원 성명과 이메일을 모두 입력해 주세요.")

        with col_list:
            st.subheader("📋 현재 등록된 실무 담당자 명부")
            
            res = supabase.table("staff_users").select("id, staff_name, email, department, is_admin, created_at").execute()
            staff_data = res.data if res.data else []

            if staff_data:
                df_staff = pd.DataFrame(staff_data)
                if "department" not in df_staff.columns:
                    df_staff["department"] = "-"
                if "is_admin" not in df_staff.columns:
                    df_staff["is_admin"] = False
                df_staff["is_admin"] = df_staff["is_admin"].fillna(False)
                df_staff.insert(0, "삭제", False)

                st.markdown(f"**총 등록 인원:** `{len(df_staff)}명`")
                st.caption("최고 관리자 권한(Streamlit 로그인)은 체크박스로 즉시 변경되며, 삭제는 아래 버튼으로 별도 처리합니다.")

                edited_df = st.data_editor(
                    df_staff[['삭제', 'staff_name', 'email', 'department', 'is_admin', 'created_at']],
                    use_container_width=True,
                    hide_index=True,
                    disabled=['staff_name', 'email', 'department', 'created_at'],
                    column_config={
                        "삭제": st.column_config.CheckboxColumn("삭제", help="삭제할 계정을 선택하세요", default=False),
                        "staff_name": st.column_config.TextColumn("직원 성명", width="medium"),
                        "email": st.column_config.TextColumn("인증 이메일 주소", width="large"),
                        "department": st.column_config.TextColumn("소속 부서/팀", width="small"),
                        "is_admin": st.column_config.CheckboxColumn("🔐 최고관리자", help="이 Streamlit 대시보드 로그인 권한"),
                        "created_at": st.column_config.TextColumn("등록 일시", width="small")
                    },
                    key="staff_editor"
                )

                changed_admin_rows = edited_df[edited_df["is_admin"] != df_staff["is_admin"]]
                if not changed_admin_rows.empty and st.button("💾 최고관리자 권한 변경사항 저장", use_container_width=True):
                    for _, row in changed_admin_rows.iterrows():
                        supabase.table("staff_users").update({"is_admin": bool(row["is_admin"])}).eq("email", row["email"]).execute()
                    st.success(f"✅ {len(changed_admin_rows)}건의 최고관리자 권한이 변경되었습니다.")
                    st.rerun()

                st.divider()
                st.subheader("🚫 접근 권한 즉시 회수")

                selected_emails = edited_df[edited_df["삭제"]]['email'].tolist()

                if st.button(f"🔥 체크한 계정 삭제 및 권한 회수 ({len(selected_emails)}건)", type="primary", disabled=not selected_emails):
                    try:
                        for delete_email in selected_emails:
                            supabase.table("staff_users").delete().eq("email", delete_email).execute()

                            # Supabase Auth 계정도 함께 삭제(대칭 처리). 화이트리스트 삭제만으로도
                            # RLS상 데이터 접근은 이미 차단되므로, 이 단계가 실패해도 무시하고 진행한다.
                            if not is_mock_db:
                                try:
                                    auth_users = supabase.auth.admin.list_users()
                                    target_user = next((u for u in auth_users if u.email == delete_email), None)
                                    if target_user:
                                        supabase.auth.admin.delete_user(target_user.id)
                                except Exception as auth_err:
                                    st.warning(f"⚠️ '{delete_email}' 화이트리스트는 삭제되었으나 로그인 계정 삭제 중 문제가 발생했습니다: {str(auth_err)}")

                        st.success(f"✅ {len(selected_emails)}건의 계정 접근 권한이 영구적으로 회수되었습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"권한 회수 처리 중 오류 발생: {str(e)}")

            else:
                st.info("현재 등록된 화이트리스트 직원 계정이 없습니다.")
