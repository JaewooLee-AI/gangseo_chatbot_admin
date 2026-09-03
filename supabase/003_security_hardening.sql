-- ============================================================
-- Supabase Security Advisor 대응: Function Search Path Mutable
--
-- 대상: public.set_updated_at, public.set_resolved_at, public.match_documents
-- 문제: search_path가 고정되지 않은 함수는 호출 시점의 세션 search_path에
--       따라 의도치 않은 스키마의 동일 이름 객체를 참조할 수 있어(스키마 스푸핑),
--       공격자가 search_path를 조작해 악성 객체로 우회시킬 여지가 생긴다.
-- 조치: 함수별로 search_path를 명시적으로 고정한다.
--       - set_updated_at / set_resolved_at: 트리거 함수로 스키마 참조가 없어 '' 로 고정.
--       - match_documents: rag_documents 테이블(public 스키마)을 비한정 식별자로
--         참조할 것이므로 'public' 으로 고정(빈 문자열로 고정 시 조회가 깨짐).
--         이 함수는 이 저장소가 아닌 별도 Vercel 챗봇 저장소에서 관리되므로
--         본문은 건드리지 않고 search_path만 고정한다.
--
-- 실행 방법: Supabase Dashboard > SQL Editor 에 이 파일 전체를 붙여넣고 실행
-- 재실행해도 안전합니다(idempotent).
-- ============================================================

alter function public.set_updated_at() set search_path = '';
alter function public.set_resolved_at() set search_path = '';

alter function public.match_documents(vector, double precision, integer, text)
    set search_path = 'public';
