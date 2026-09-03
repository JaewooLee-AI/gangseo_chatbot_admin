-- ============================================================
-- admin_match_documents 키워드 후보군 매칭 로직 수정
--
-- 문제: 005에서 만든 keyword_candidates는 similarity(content, query_text)와 %
--       연산자를 사용했는데, 이는 두 문자열의 트라이그램 "집합 전체"를 비교하는
--       방식이라 query_text가 content(긴 복합 문자열)의 일부에 불과할 때는 비율이
--       희석된다. 실측 결과, "3시간30분 이용"이 content 안에 정확히 포함되어
--       있는데도 similarity()가 기본 임계치(0.3)를 넘지 못해 키워드 후보가 아예
--       반환되지 않는 문제를 확인했다.
-- 해결: "짧은 질의가 긴 본문 어딘가에 등장하는지"를 찾는 데 특화된 pg_trgm의
--       word_similarity() / <% 연산자로 교체한다. 005에서 만든 GIN 트라이그램
--       인덱스(gin_trgm_ops)는 <% 연산자도 함께 가속하므로 별도 인덱스는 불필요하다.
--
-- 실행 방법: Supabase Dashboard > SQL Editor 에 이 파일 전체를 붙여넣고 실행
-- 재실행해도 안전합니다(idempotent).
-- ============================================================

create or replace function admin_match_documents(
    query_embedding vector(1536),
    query_text text default '',
    match_count int default 30
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
        where query_text <> '' and query_text <% rd.content
        order by word_similarity(query_text, rd.content) desc
        limit 10
    )
    select * from vector_candidates
    union all
    select k.* from keyword_candidates k
    where not exists (select 1 from vector_candidates v where v.id = k.id);
$$;

grant execute on function admin_match_documents(vector, text, int) to anon, authenticated, service_role;
