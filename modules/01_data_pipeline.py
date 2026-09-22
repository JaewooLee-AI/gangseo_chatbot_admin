import streamlit as st
import pandas as pd
from core.db import supabase
from core.rag_engine import extract_text_from_file, extract_excel_rows, chunk_text, generate_embedding

def render():
    st.markdown('<div class="ace-badge ace-badge-orange">MODULE 01</div>', unsafe_allow_html=True)
    st.title("📊 RAG 데이터 파이프라인 및 시각화")
    st.caption("신규 문서를 업로드하여 벡터 DB에 색인하고, 자동 분할된 데이터 청크(Chunk)를 엑셀처럼 수동 결합 및 재학습(Re-embed)할 수 있습니다.")
    st.divider()

    col_upload, col_edit = st.columns([1, 1.4], gap="large")

    # 1. 파일 업로드 및 메타데이터 강제 지정 영역
    with col_upload:
        st.subheader("📌 신규 지식 문서 업로드")
        st.write("지식 오염 방지를 위해 문서 업로드 시 **카테고리 메타데이터**를 반드시 지정해야 합니다.")

        with st.form("upload_form", clear_on_submit=False):
            category_options = ["선택 안 함", "요금정산", "자격요건", "내부규정", "일반안내"]
            selected_category = st.selectbox(
                "📌 메타데이터 카테고리 선택 (PDF/TXT 필수 · Excel은 시트명으로 자동 대체)",
                category_options
            )

            uploaded_file = st.file_uploader(
                "문서 업로드 (PDF, TXT, Excel/XLSX)",
                type=["pdf", "txt", "xlsx", "xls"],
                help="PDF, TXT, Excel 파일을 선택하여 텍스트 및 임베딩을 색인합니다."
            )

            chunk_size = st.slider("청크(Chunk) 분할 크기 (글자 수, PDF/TXT에만 적용)", min_value=100, max_value=800, value=300, step=50)

            replace_existing = st.checkbox(
                "🔁 전체 교체 (해당 카테고리의 기존 청크를 삭제하고 새로 삽입)",
                value=True,
                help="확정본을 재업로드할 때 켜두면 예전 값과 새 값이 뒤섞여 검색되는 것을 막습니다. "
                     "같은 카테고리에 여러 문서를 이어붙이는 경우에만 끄세요.",
            )

            submit_upload = st.form_submit_button("🚀 문서 학습 및 벡터 DB 색인 실행")

        if submit_upload:
            if uploaded_file is None:
                st.warning("⚠️ 학습할 파일을 먼저 선택해 주세요.")
            else:
                is_excel = uploaded_file.name.split(".")[-1].lower() in ["xlsx", "xls"]
                if not is_excel and selected_category == "선택 안 함":
                    st.error("🚨 필수 항목 누락: 메타데이터 카테고리를 반드시 지정해야 합니다.")
                else:
                    with st.spinner(f"'{uploaded_file.name}' 문서 텍스트 추출 및 1536차원 벡터 임베딩 중..."):
                        file_bytes = uploaded_file.read()

                        if is_excel:
                            # 엑셀은 이미 행 단위로 정리된 지식이므로 문자 수 기반 청킹을 건너뛰고
                            # 1행 = 1청크로 임베딩하며, 시트명을 카테고리로 그대로 사용한다.
                            rows = extract_excel_rows(file_bytes)
                            used_categories = sorted({r["category"] for r in rows})

                            if replace_existing and used_categories:
                                # 재업로드 시 예전 청크가 남아 새 값과 뒤섞여 검색되는 것을 막기 위해,
                                # 새로 들어온 카테고리(시트)에 한해서만 기존 행을 지우고 다시 넣는다
                                # (다른 시트/카테고리 데이터는 건드리지 않는다).
                                supabase.table("rag_documents").delete().in_("category", used_categories).execute()

                            inserted_count = 0
                            for row in rows:
                                vec = generate_embedding(row["content"])
                                supabase.table("rag_documents").insert({
                                    "content": row["content"],
                                    "category": row["category"],
                                    "embedding": vec,
                                    "doc_type": row["doc_type"],
                                    "verification": row["verification"],
                                }).execute()
                                inserted_count += 1
                            st.success(f"✅ {len(used_categories)}개 시트 카테고리({', '.join(used_categories)})로 총 {inserted_count}개의 지식 청크가 성공적으로 색인되었습니다!")
                            st.balloons()
                        else:
                            extracted_raw_text = extract_text_from_file(file_bytes, uploaded_file.name)

                            if extracted_raw_text.startswith("지원되지 않는") or extracted_raw_text.startswith("PDF 읽기 오류"):
                                st.error(extracted_raw_text)
                            else:
                                chunks = chunk_text(extracted_raw_text, chunk_size=chunk_size)

                                inserted_count = 0
                                for chunk in chunks:
                                    vec = generate_embedding(chunk)
                                    supabase.table("rag_documents").insert({
                                        "content": chunk,
                                        "category": selected_category,
                                        "embedding": vec
                                    }).execute()
                                    inserted_count += 1

                                st.success(f"✅ [{selected_category}] 분류로 총 {inserted_count}개의 지식 청크가 성공적으로 색인되었습니다!")
                                st.balloons()

    # 2. 색인 데이터 시각화 및 st.data_editor를 이용한 수동 결합/재학습
    with col_edit:
        st.subheader("🔍 지식베이스 청크(Chunk) 관리 및 수동 편집")
        st.caption("의미가 끊어진 청크를 수동 수정하거나 직관적으로 편집한 뒤 원클릭 재학습(Re-embed)할 수 있습니다.")

        # DB에서 청크 데이터 조회
        response = supabase.table("rag_documents").select("id, category, content, created_at").limit(100).execute()
        raw_data = response.data if response.data else []

        if raw_data:
            df = pd.DataFrame(raw_data)
            # 순서 정리 후, data_editor의 edited_rows가 위치(포지션) 기준으로
            # 매핑되도록 인덱스를 0..n-1로 재설정한다.
            if "created_at" in df.columns:
                df = df.sort_values(by="created_at", ascending=False)
            df = df.reset_index(drop=True)
            id_by_position = df["id"].tolist()

            st.markdown(f"**현재 등록된 지식 청크 수:** `{len(df)}개`")

            # 카테고리는 더 이상 고정 목록이 아니라 실제 색인된 시트명/카테고리를 기준으로 동적으로 구성한다.
            category_editor_options = sorted(set(df["category"].dropna().tolist()) | {"수동학습(HITL)"})

            # st.data_editor로 인메모리 수동 편집 허용
            edited_df = st.data_editor(
                df,
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "id": st.column_config.TextColumn("청크 ID", disabled=True, width="small"),
                    "category": st.column_config.SelectboxColumn(
                        "카테고리",
                        options=category_editor_options,
                        required=True,
                        width="medium"
                    ),
                    "content": st.column_config.TextColumn("텍스트 청크 내용", width="large", required=True),
                    "created_at": st.column_config.TextColumn("생성일시", disabled=True, width="small")
                },
                key="rag_chunk_editor"
            )

            col_btn1, col_btn2 = st.columns([1.5, 1])
            with col_btn1:
                if st.button("🔄 수정된 데이터 원클릭 재학습 (Re-embed)"):
                    with st.spinner("변경된 청크만 재임베딩하여 DB에 동기화 중입니다..."):
                        editor_state = st.session_state.get("rag_chunk_editor", {})
                        edited_rows = editor_state.get("edited_rows", {})
                        added_rows = editor_state.get("added_rows", [])
                        deleted_rows = editor_state.get("deleted_rows", [])

                        changed_count = 0

                        # 1. 기존 행 중 실제로 수정된 행만 재임베딩
                        for pos_str, changes in edited_rows.items():
                            pos = int(pos_str)
                            if pos >= len(id_by_position):
                                continue
                            row_id = id_by_position[pos]
                            merged_row = df.iloc[pos].to_dict()
                            merged_row.update(changes)
                            content = merged_row.get("content")
                            category = merged_row.get("category")
                            if pd.notna(content) and pd.notna(category):
                                new_vec = generate_embedding(str(content))
                                supabase.table("rag_documents").upsert({
                                    "id": row_id,
                                    "content": str(content),
                                    "category": str(category),
                                    "embedding": new_vec
                                }).execute()
                                changed_count += 1

                        # 2. 신규로 추가된 행 삽입
                        for new_row in added_rows:
                            content = new_row.get("content")
                            category = new_row.get("category")
                            if content and category:
                                vec = generate_embedding(str(content))
                                supabase.table("rag_documents").insert({
                                    "content": str(content),
                                    "category": str(category),
                                    "embedding": vec
                                }).execute()
                                changed_count += 1

                        # 3. 삭제된 행 DB 반영
                        for pos in deleted_rows:
                            if pos < len(id_by_position):
                                supabase.table("rag_documents").delete().eq("id", id_by_position[pos]).execute()
                                changed_count += 1

                        if changed_count > 0:
                            st.success(f"✅ 총 {changed_count}건의 변경 사항(수정/추가/삭제)을 재학습 반영했습니다.")
                        else:
                            st.info("변경된 내용이 없어 재학습을 건너뛰었습니다.")
                        st.rerun()

            with col_btn2:
                if st.button("🗑️ 선택 청크 초기화/새로고침", type="secondary"):
                    st.rerun()

        else:
            st.info("💡 현재 등록된 지식베이스 청크 데이터가 없습니다. 좌측에서 문서를 업로드해 주세요.")
