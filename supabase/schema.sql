-- ============================================================
-- Souvenir AI - Supabase schema
-- A executer dans le SQL Editor de Supabase Studio
-- ============================================================

-- 1. Table des restaurations (log + historique cloud)
create table if not exists public.restorations (
    id           bigserial primary key,
    job_id       text not null unique,
    user_id      uuid references auth.users(id) on delete cascade,
    device_id    text,                 -- ID anonyme app (UUID v4 cote client)
    is_premium   boolean default false,
    before_url   text,
    after_url    text,
    processing_ms integer,
    size_bytes   integer,
    pipeline     text,
    created_at   timestamptz not null default now()
);

create index if not exists restorations_user_idx on public.restorations(user_id);
create index if not exists restorations_device_idx on public.restorations(device_id, created_at desc);
create index if not exists restorations_created_idx on public.restorations(created_at desc);

-- Migration douce si la table existait deja
alter table public.restorations add column if not exists device_id text;
alter table public.restorations add column if not exists is_premium boolean default false;

-- 2. RLS : un utilisateur ne voit que ses propres restaurations
alter table public.restorations enable row level security;

drop policy if exists "users read own restorations" on public.restorations;
create policy "users read own restorations"
  on public.restorations for select
  using (auth.uid() = user_id);

drop policy if exists "service role full access" on public.restorations;
create policy "service role full access"
  on public.restorations for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

-- 3. Vues: quota quotidien (24h glissantes)
create or replace view public.user_daily_quota as
select
    user_id,
    count(*)::int as restorations_today
from public.restorations
where created_at > now() - interval '24 hours'
  and is_premium = false
group by user_id;

create or replace view public.device_daily_quota as
select
    device_id,
    count(*)::int as restorations_today
from public.restorations
where created_at > now() - interval '24 hours'
  and is_premium = false
  and device_id is not null
group by device_id;

-- 4. Table des abonnements premium (source de verite pour is_premium)
-- Le backend lit cette table avec service_role pour determiner si un user
-- est premium. Empeche le bypass via header X-Premium cote client.
create table if not exists public.subscriptions (
    user_id      uuid primary key references auth.users(id) on delete cascade,
    is_premium   boolean not null default false,
    plan         text,                    -- 'monthly' | 'yearly' | 'lifetime'
    provider     text,                    -- 'revenuecat' | 'stripe' | 'manual'
    expires_at   timestamptz,             -- null = lifetime ou pas premium
    updated_at   timestamptz not null default now(),
    created_at   timestamptz not null default now()
);

create index if not exists subscriptions_premium_idx
    on public.subscriptions(user_id) where is_premium = true;

-- RLS : seul le service_role peut ecrire ; user peut lire son propre statut
alter table public.subscriptions enable row level security;

drop policy if exists "users read own subscription" on public.subscriptions;
create policy "users read own subscription"
  on public.subscriptions for select
  using (auth.uid() = user_id);

drop policy if exists "service role full access subs" on public.subscriptions;
create policy "service role full access subs"
  on public.subscriptions for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

-- Helper : marquer un user comme premium (a appeler depuis un webhook)
-- Exemple : select public.set_premium('xxx-uuid', 'monthly', '2026-12-31');
create or replace function public.set_premium(
    p_user_id uuid,
    p_plan text default 'monthly',
    p_expires_at timestamptz default null
) returns void
language plpgsql
security definer
as $$
begin
    insert into public.subscriptions (user_id, is_premium, plan, expires_at, updated_at)
    values (p_user_id, true, p_plan, p_expires_at, now())
    on conflict (user_id) do update set
        is_premium = true,
        plan = excluded.plan,
        expires_at = excluded.expires_at,
        updated_at = now();
end;
$$;

-- 5. Storage bucket (a executer aussi via Storage UI ou CLI)
-- Dans Supabase Studio > Storage > Create bucket "souvenir" (PUBLIC)
-- Folders attendus dans le bucket: uploads/, outputs/

-- 5. Storage policies (lecture publique des outputs)
-- A configurer dans Storage > Policies > "souvenir" bucket:
--   Policy 1: "Public read" - SELECT to anon role
--   Policy 2: "Service write" - INSERT/UPDATE/DELETE to service_role
