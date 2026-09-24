-- ============================================================
-- fallback_logs.golden_answer 컬럼 추가
--
-- 배경: 운영 DB의 fallback_logs는 schema.sql보다 먼저 만들어져
--       (id, user_query, ai_response, status, created_at) 구성이었다.
--       schema.sql은 "create table if not exists"라 이미 있는 테이블에 golden_answer를
--       추가하지 못했고, 관리자 HITL 화면(02_hitl_review.py)의 "모범 정답 주입"과
--       "무시 처리"가 모두 이 컬럼에 쓰기 때문에 운영에서 한 번도 성공하지 못했다
--       (확인 시점 대기 142건, 처리 0건 — 2026-09-24).
--
-- ai_response는 코드 어디에서도 쓰지 않지만, 기존 데이터를 보존하기 위해 지우지 않는다.
--
-- 실행 방법: Supabase Dashboard > SQL Editor 에 이 파일 전체를 붙여넣고 실행
-- 재실행해도 안전합니다(idempotent).
-- ============================================================

alter table fallback_logs add column if not exists golden_answer text;

-- PostgREST가 새 컬럼을 바로 인식하도록 스키마 캐시를 갱신한다.
notify pgrst, 'reload schema';
