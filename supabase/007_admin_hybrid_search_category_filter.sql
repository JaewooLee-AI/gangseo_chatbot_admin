-- ============================================================
-- admin_match_documents 카테고리(페르소나) 필터 추가
--
-- 배경: 지식베이스가 이미 페르소나 축으로 구성되어 있는데(종사자용/이용자용 ×
--       장애인활동지원/가사서비스), 검색은 항상 전체를 대상으로 하고 있었다.
--       실측 결과 "치매 어르신도 서비스 받을 수 있나요?"(이용자 문의)에서 LLM에
--       전달되는 컨텍스트 5건 중 4건이 종사자용 문서로 채워졌다. 즉 이용자 문의에
--       직원용 문서를 근거로 답하고 있었다.
--       사용자가 진입 시점에 자신의 상황(이용 희망/취업 희망)을 선택하면 검색
--       공간을 1/3~1/5로 줄여 이런 페르소나 혼동을 결정론적으로 제거할 수 있다.
--
-- filter_categories가 null이거나 빈 배열이면 기존과 동일하게 전체를 검색한다
-- (사용자가 카테고리를 고르지 않았거나, 필터 검색이 실패해 전체로 확장하는 경우).
--
-- 주의: 기본값 있는 파라미터를 추가하면 기존 3-파라미터 버전과 오버로드가 되어
--       PostgREST가 호출을 모호하다고 거부한다. 반드시 기존 함수를 먼저 삭제한다.
--
-- 실행 방법: Supabase Dashboard > SQL Editor 에 이 파일 전체를 붙여넣고 실행
-- 재실행해도 안전합니다(idempotent).
-- ============================================================

drop function if exists admin_match_documents(vector, text, int);

create or replace function admin_match_documents(
    query_embedding vector(1536),
    query_text text default '',
    match_count int default 30,
    filter_categories text[] default null
)
returns table (
    id uuid,
    content text,
    category varchar,
    similarity double precision,
    match_source text
)
language sql
stable
set search_path = 'public'
as $$
    with vector_candidates as (
        select
            rd.id,
            rd.content,
            rd.category,
            1 - (rd.embedding <=> query_embedding) as similarity,
            'vector'::text as match_source
        from rag_documents rd
        where rd.embedding is not null
          and (
                filter_categories is null
                or cardinality(filter_categories) = 0
                or rd.category = any(filter_categories)
              )
        order by rd.embedding <=> query_embedding
        limit match_count
    ),
    keyword_candidates as (
        select
            rd.id,
            rd.content,
            rd.category,
            word_similarity(query_text, rd.content) as similarity,
            'keyword'::text as match_source
        from rag_documents rd
        where query_text <> ''
          and query_text <% rd.content
          and (
                filter_categories is null
                or cardinality(filter_categories) = 0
                or rd.category = any(filter_categories)
              )
        order by word_similarity(query_text, rd.content) desc
        limit 10
    )
    select * from vector_candidates
    union all
    select k.* from keyword_candidates k
    where not exists (select 1 from vector_candidates v where v.id = k.id);
$$;

grant execute on function admin_match_documents(vector, text, int, text[])
    to anon, authenticated, service_role;
