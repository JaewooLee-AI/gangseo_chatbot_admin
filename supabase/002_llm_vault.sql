-- ============================================================
-- LLM API 키 보안 저장 (Supabase Vault)
--
-- 전제 조건: supabase/schema.sql을 먼저 실행해서 rag_documents, fallback_logs,
-- bot_settings, staff_users, counselor_inquiries 테이블과 set_updated_at() 함수가
-- 이미 만들어져 있어야 합니다 (이 파일은 그 함수를 재사용합니다).
--
-- 설계 원칙:
--   - LLM API 키 원문은 절대 일반 테이블 컬럼에 평문으로 저장하지 않는다.
--   - Supabase Vault(pgsodium 기반, 프로젝트에 기본 활성화)의 vault.secrets에
--     암호화 저장하고, llm_providers 테이블은 그 secret에 대한 "포인터(uuid)"만 가진다.
--   - 원문 복호화는 SECURITY DEFINER 함수(get_llm_api_key)를 통해서만 가능하며,
--     이 함수의 실행 권한은 service_role에게만 부여한다.
--     -> anon/authenticated 역할은 애초에 원문 키에 접근할 방법이 없다.
--   - 이 Streamlit 관리자 대시보드(service_role)가 키를 등록/테스트하고,
--     추후 만들 Vercel 챗봇 백엔드도 service_role 키로 get_llm_api_key()를 호출해
--     요청 시점에만 복호화된 키를 가져와 LLM API를 호출해야 한다.
--     (service_role 키는 절대 브라우저/클라이언트에 노출되면 안 되며, 서버 환경에서만 사용)
--
-- 실행 방법: Supabase Dashboard > SQL Editor 에 이 파일 전체를 붙여넣고 실행
-- 재실행해도 안전합니다(idempotent).
-- ============================================================

create table if not exists llm_providers (
    vendor_id varchar(30) primary key,
    display_name varchar(50) not null,
    model_name varchar(100) not null default '',
    vault_secret_id uuid references vault.secrets(id) on delete set null,
    is_active boolean not null default false,
    last_tested_at timestamptz,
    last_test_status varchar(20),
    updated_at timestamptz not null default now()
);

insert into llm_providers (vendor_id, display_name, model_name) values
    ('openai', 'OpenAI ChatGPT', 'gpt-4o'),
    ('claude', 'Anthropic Claude', 'claude-3-5-sonnet-20241022'),
    ('gemini', 'Google Gemini', 'gemini-3.1-flash-lite'),
    ('qwen', 'Alibaba Qwen', 'qwen-max')
on conflict (vendor_id) do nothing;

drop trigger if exists trg_llm_providers_updated_at on llm_providers;
create trigger trg_llm_providers_updated_at
    before update on llm_providers
    for each row execute function set_updated_at();

-- llm_providers는 service_role 전용: RLS만 켜두고 정책은 하나도 만들지 않는다
-- (= anon/authenticated는 이 테이블에 어떤 방식으로도 접근 불가, service_role만 RLS 우회로 접근)
alter table llm_providers enable row level security;

-- 키 등록/교체: 기존 secret이 있으면 업데이트, 없으면 새로 생성 후 연결
create or replace function set_llm_api_key(p_vendor_id varchar, p_api_key text)
returns void
language plpgsql
security definer
set search_path = public, vault
as $$
declare
    v_secret_id uuid;
begin
    select vault_secret_id into v_secret_id from llm_providers where vendor_id = p_vendor_id;

    if v_secret_id is not null then
        perform vault.update_secret(v_secret_id, p_api_key);
        update llm_providers
            set is_active = true, updated_at = now()
            where vendor_id = p_vendor_id;
    else
        v_secret_id := vault.create_secret(p_api_key, p_vendor_id || '_llm_api_key', p_vendor_id || ' LLM API Key');
        update llm_providers
            set vault_secret_id = v_secret_id, is_active = true, updated_at = now()
            where vendor_id = p_vendor_id;
    end if;
end;
$$;

-- 복호화된 키 조회: service_role만 호출 가능 (아래 REVOKE/GRANT 참고)
create or replace function get_llm_api_key(p_vendor_id varchar)
returns text
language sql
security definer
set search_path = public, vault
as $$
    select ds.decrypted_secret
    from llm_providers lp
    join vault.decrypted_secrets ds on ds.id = lp.vault_secret_id
    where lp.vendor_id = p_vendor_id;
$$;

-- 주의: Supabase는 새 함수 생성 시 anon/authenticated/service_role에게
-- EXECUTE 권한을 "PUBLIC 경유"가 아니라 각 역할에 개별적으로 자동 부여한다.
-- 따라서 `revoke ... from public`만으로는 anon/authenticated의 실행 권한이 제거되지 않으며,
-- 반드시 아래처럼 역할명을 직접 지정해서 revoke해야 한다.
revoke all on function set_llm_api_key(varchar, text) from public, anon, authenticated;
revoke all on function get_llm_api_key(varchar) from public, anon, authenticated;
grant execute on function set_llm_api_key(varchar, text) to service_role;
grant execute on function get_llm_api_key(varchar) to service_role;
