-- ============================================================
-- fallback_logs 실패유형 태깅
--
-- 목적: 오답 리뷰(HITL, Module 02) 화면에서 챗봇이 "왜" 답을 못 했는지
--       (지식 공백 / 근거 불충분 / 담당자 직접 요청)를 분류해, 어떤 개선이
--       가장 시급한지 데이터 기반으로 우선순위를 정할 수 있게 한다.
--
-- 실행 방법: Supabase Dashboard > SQL Editor 에 이 파일 전체를 붙여넣고 실행
-- 재실행해도 안전합니다(idempotent).
-- ============================================================

alter table fallback_logs
    add column if not exists failure_type varchar(30);

alter table fallback_logs
    drop constraint if exists fallback_logs_failure_type_check;

alter table fallback_logs
    add constraint fallback_logs_failure_type_check
    check (failure_type is null or failure_type in ('no_match', 'low_confidence', 'human_requested'));

create index if not exists fallback_logs_failure_type_idx on fallback_logs (failure_type);
