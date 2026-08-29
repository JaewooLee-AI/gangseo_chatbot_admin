-- ============================================================
-- 강서나눔돌봄센터 AI 챗봇 통합 Supabase 스키마
--
-- 대상 애플리케이션:
--   1) RAG 최고관리자 대시보드 (Streamlit, 이 저장소) — service_role 키로 접속 권장
--   2) 공개 사용자용 챗봇 (Vercel, 별도 저장소) — anon 키로 접속
--   3) 담당자 전용 처리 웹앱 (Vercel, 개발 예정) — anon 키 + Supabase Auth(이메일 OTP)로 접속
--
-- 실행 방법: Supabase Dashboard > SQL Editor 에 전체 스크립트를 붙여넣고 실행
-- 이 스크립트는 재실행해도 안전하도록(idempotent) 작성되었습니다.
-- ============================================================

create extension if not exists vector;
create extension if not exists pgcrypto;

-- ------------------------------------------------------------
-- 1. RAG 지식베이스
-- ------------------------------------------------------------
create table if not exists rag_documents (
    id uuid primary key default gen_random_uuid(),
    content text not null,
    embedding vector(1536),
    category varchar(50) not null,
    created_at timestamptz not null default now()
);

create index if not exists rag_documents_embedding_idx
    on rag_documents using ivfflat (embedding vector_cosine_ops) with (lists = 100);
create index if not exists rag_documents_category_idx on rag_documents (category);

-- ------------------------------------------------------------
-- 2. HITL 미해결 오답 로그
-- ------------------------------------------------------------
create table if not exists fallback_logs (
    id uuid primary key default gen_random_uuid(),
    user_query text not null,
    status varchar(20) not null default 'pending' check (status in ('pending', 'resolved')),
    golden_answer text,
    created_at timestamptz not null default now()
);

create index if not exists fallback_logs_status_idx on fallback_logs (status);

-- ------------------------------------------------------------
-- 3. 챗봇 동적 프롬프트 설정 (단일 레코드)
-- ------------------------------------------------------------
create table if not exists bot_settings (
    id int primary key default 1,
    tone varchar(50) not null default '친절한 상담원',
    block_medical boolean not null default true,
    block_legal boolean not null default true,
    block_privacy boolean not null default true,
    strictness_level int not null default 5 check (strictness_level between 1 and 5),
    constraint bot_settings_singleton check (id = 1)
);

insert into bot_settings (id) values (1) on conflict (id) do nothing;

-- ------------------------------------------------------------
-- 4. 직원 화이트리스트 (담당자 전용 웹앱 접근 권한)
-- ------------------------------------------------------------
create table if not exists staff_users (
    id uuid primary key default gen_random_uuid(),
    staff_name varchar(100) not null,
    email varchar(255) not null unique,
    department varchar(50),
    is_active boolean not null default true,
    is_admin boolean not null default false,
    created_at timestamptz not null default now()
);

-- 기존에 department 컬럼 없이 생성되어 있던 경우를 위한 안전 보강
alter table staff_users add column if not exists department varchar(50);
alter table staff_users add column if not exists is_active boolean not null default true;
-- is_admin = true인 계정만 이 Streamlit 최고관리자 대시보드에 로그인할 수 있다(담당자 웹앱 접근 권한과는 별개).
alter table staff_users add column if not exists is_admin boolean not null default false;

-- ------------------------------------------------------------
-- 5. 담당자 전달 문의 (챗봇 -> 담당자 웹앱 핵심 워크플로우)
-- ------------------------------------------------------------
create table if not exists counselor_inquiries (
    id uuid primary key default gen_random_uuid(),
    user_name varchar(100),
    contact_info varchar(100),
    inquiry_summary text,
    raw_message text not null,
    input_type varchar(20) not null default 'text' check (input_type in ('text', 'voice')),
    category varchar(30) not null default '미분류'
        check (category in ('미분류', '요금문의', '서비스신청', '자격상담', '불만접수', '일반문의', '기타')),
    status varchar(20) not null default 'pending' check (status in ('pending', 'in_progress', 'resolved')),
    admin_note text,
    assigned_to uuid references staff_users(id) on delete set null,
    resolved_by uuid references staff_users(id) on delete set null,
    resolved_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- 기존에 구버전 스키마로 생성되어 있던 경우를 위한 안전 보강
alter table counselor_inquiries add column if not exists category varchar(30) not null default '미분류';
alter table counselor_inquiries add column if not exists assigned_to uuid references staff_users(id) on delete set null;
alter table counselor_inquiries add column if not exists resolved_by uuid references staff_users(id) on delete set null;
alter table counselor_inquiries add column if not exists resolved_at timestamptz;
alter table counselor_inquiries add column if not exists updated_at timestamptz not null default now();

create index if not exists counselor_inquiries_status_idx on counselor_inquiries (status);
create index if not exists counselor_inquiries_category_idx on counselor_inquiries (category);
create index if not exists counselor_inquiries_created_at_idx on counselor_inquiries (created_at desc);
create index if not exists counselor_inquiries_assigned_to_idx on counselor_inquiries (assigned_to);

-- updated_at 자동 갱신
create or replace function set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_counselor_inquiries_updated_at on counselor_inquiries;
create trigger trg_counselor_inquiries_updated_at
    before update on counselor_inquiries
    for each row execute function set_updated_at();

-- status가 resolved로 바뀌는 순간 resolved_at 자동 기록
create or replace function set_resolved_at()
returns trigger as $$
begin
    if new.status = 'resolved' and old.status is distinct from 'resolved' then
        new.resolved_at = now();
    end if;
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_counselor_inquiries_resolved_at on counselor_inquiries;
create trigger trg_counselor_inquiries_resolved_at
    before update on counselor_inquiries
    for each row execute function set_resolved_at();

-- ============================================================
-- 6. Row Level Security
--
-- 설계 원칙:
--   - anon(공개) 키: 공개 챗봇이 지식/설정을 "읽고", 오답/문의를 "접수(insert)"만 할 수 있음
--   - authenticated(로그인한 직원): 화이트리스트에 등록된 이메일만 문의를 조회/처리할 수 있음
--   - service_role 키: RLS를 완전히 우회하므로, 이 Streamlit 최고관리자 대시보드는
--     반드시 service_role 키를 사용해야 모든 테이블에 대한 전체 CRUD가 가능합니다.
--     (anon 키만 사용할 경우 아래 정책 범위를 벗어난 쓰기/조회는 차단됩니다.)
-- ============================================================
alter table rag_documents enable row level security;
alter table fallback_logs enable row level security;
alter table bot_settings enable row level security;
alter table staff_users enable row level security;
alter table counselor_inquiries enable row level security;

-- rag_documents: 공개 읽기 허용, 쓰기는 service_role 전용(정책 없음 = 기본 차단)
drop policy if exists "rag_documents_public_read" on rag_documents;
create policy "rag_documents_public_read" on rag_documents
    for select using (true);

-- bot_settings: 공개 챗봇이 매 요청마다 조회하므로 읽기 허용, 쓰기는 service_role 전용
drop policy if exists "bot_settings_public_read" on bot_settings;
create policy "bot_settings_public_read" on bot_settings
    for select using (true);

-- fallback_logs: 챗봇(anon)이 미해결 질의를 접수, 직원(authenticated)만 조회/처리
drop policy if exists "fallback_logs_public_insert" on fallback_logs;
create policy "fallback_logs_public_insert" on fallback_logs
    for insert with check (true);

drop policy if exists "fallback_logs_staff_select" on fallback_logs;
create policy "fallback_logs_staff_select" on fallback_logs
    for select using (auth.role() = 'authenticated');

drop policy if exists "fallback_logs_staff_update" on fallback_logs;
create policy "fallback_logs_staff_update" on fallback_logs
    for update using (auth.role() = 'authenticated');

-- counselor_inquiries: 챗봇(anon)이 문의를 접수, 화이트리스트 직원만 조회/처리
drop policy if exists "counselor_inquiries_public_insert" on counselor_inquiries;
create policy "counselor_inquiries_public_insert" on counselor_inquiries
    for insert with check (true);

drop policy if exists "counselor_inquiries_staff_select" on counselor_inquiries;
create policy "counselor_inquiries_staff_select" on counselor_inquiries
    for select using (
        exists (
            select 1 from staff_users s
            where s.email = auth.jwt() ->> 'email' and s.is_active = true
        )
    );

drop policy if exists "counselor_inquiries_staff_update" on counselor_inquiries;
create policy "counselor_inquiries_staff_update" on counselor_inquiries
    for update using (
        exists (
            select 1 from staff_users s
            where s.email = auth.jwt() ->> 'email' and s.is_active = true
        )
    );

-- staff_users: 담당자 웹앱 로그인 후 본인 화이트리스트 레코드만 조회 가능
drop policy if exists "staff_users_self_select" on staff_users;
create policy "staff_users_self_select" on staff_users
    for select using (email = auth.jwt() ->> 'email');

