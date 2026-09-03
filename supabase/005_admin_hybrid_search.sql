-- ============================================================
-- 관리자 대시보드 전용 서버사이드 하이브리드 검색(벡터 + 트라이그램 키워드) RPC
--
-- 배경: 지금까지 관리자 시뮬레이터(06_simulator.py)는 rag_documents 전체를
--       매 질의마다 클라이언트로 내려받아 파이썬에서 브루트포스로 코사인 유사도를
--       계산했다. 문제점:
--       - 문서가 늘어날수록 전량 스캔 + 네트워크 전송 비용이 커져 확장성이 없다.
--       - 스키마에 이미 있는 ivfflat 인덱스(rag_documents_embedding_idx)를 전혀
--         활용하지 못한다.
--       - 순수 의미(semantic) 검색이라 "3구간"처럼 특정 숫자/고유값 질의에 취약해,
--         앱 코드에 정규식 하드코딩(\d+구간)으로 임시 대응해 왔다.
--
-- 이 함수는 이 저장소(admin dashboard) 전용으로 새로 만든다. 003에서 다룬
-- match_documents는 별도 Vercel 챗봇 저장소 소관이므로 건드리지 않는다.
--
-- 실행 방법: Supabase Dashboard > SQL Editor 에 이 파일 전체를 붙여넣고 실행
-- 재실행해도 안전합니다(idempotent).
-- ============================================================

create extension if not exists pg_trgm;

create index if not exists rag_documents_content_trgm_idx
    on rag_documents using gin (content gin_trgm_ops);

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
            similarity(rd.content, query_text) as similarity,
            'keyword'::text as match_source
        from rag_documents rd
        where query_text <> '' and rd.content % query_text
        order by similarity(rd.content, query_text) desc
        limit 10
    )
    select * from vector_candidates
    union all
    select k.* from keyword_candidates k
    where not exists (select 1 from vector_candidates v where v.id = k.id);
$$;

grant execute on function admin_match_documents(vector, text, int) to anon, authenticated, service_role;
