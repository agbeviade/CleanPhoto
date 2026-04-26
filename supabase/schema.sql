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
-- Architecture: chaque ligne represente UN abonnement premium attache a
-- soit un user_id Supabase (apres login), soit un device_id anonyme
-- (modele BGMaster: pas de login requis, IAP sur l'appareil).
-- Le backend lit cette table avec service_role pour determiner si un user
-- est premium. Empeche le bypass via header X-Premium cote client.
create table if not exists public.subscriptions (
    id           bigserial primary key,
    user_id      uuid references auth.users(id) on delete cascade,
    device_id    text,                    -- UUID device anonyme (BGMaster style)
    is_premium   boolean not null default false,
    plan         text,                    -- 'monthly' | 'yearly' | 'lifetime'
    provider     text,                    -- 'revenuecat' | 'stripe' | 'iap_apple' | 'iap_google' | 'manual'
    receipt      text,                    -- token IAP / receipt ID
    expires_at   timestamptz,             -- null = lifetime ou pas premium
    updated_at   timestamptz not null default now(),
    created_at   timestamptz not null default now(),
    constraint subs_user_or_device check (user_id is not null or device_id is not null)
);

-- Un seul abonnement actif par user_id ou par device_id
create unique index if not exists subscriptions_user_uidx
    on public.subscriptions(user_id) where user_id is not null;
create unique index if not exists subscriptions_device_uidx
    on public.subscriptions(device_id) where device_id is not null and user_id is null;

create index if not exists subscriptions_premium_idx
    on public.subscriptions(coalesce(user_id::text, device_id))
    where is_premium = true;

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

-- Helper : marquer un user comme premium (depuis webhook RevenueCat/Stripe)
-- Exemple : select public.set_premium_user('xxx-uuid', 'monthly', '2026-12-31');
create or replace function public.set_premium_user(
    p_user_id uuid,
    p_plan text default 'monthly',
    p_expires_at timestamptz default null,
    p_provider text default 'manual',
    p_receipt text default null
) returns void
language plpgsql
security definer
as $$
begin
    insert into public.subscriptions (user_id, is_premium, plan, expires_at, provider, receipt, updated_at)
    values (p_user_id, true, p_plan, p_expires_at, p_provider, p_receipt, now())
    on conflict (user_id) do update set
        is_premium = true,
        plan = excluded.plan,
        expires_at = excluded.expires_at,
        provider = excluded.provider,
        receipt = excluded.receipt,
        updated_at = now();
end;
$$;

-- Helper : marquer un device anonyme comme premium (IAP Apple/Google sans login)
-- Exemple : select public.set_premium_device('229b7b48-a04a-...', 'monthly', '2026-12-31');
create or replace function public.set_premium_device(
    p_device_id text,
    p_plan text default 'monthly',
    p_expires_at timestamptz default null,
    p_provider text default 'iap_apple',
    p_receipt text default null
) returns void
language plpgsql
security definer
as $$
begin
    insert into public.subscriptions (device_id, is_premium, plan, expires_at, provider, receipt, updated_at)
    values (p_device_id, true, p_plan, p_expires_at, p_provider, p_receipt, now())
    on conflict (device_id) where device_id is not null and user_id is null
    do update set
        is_premium = true,
        plan = excluded.plan,
        expires_at = excluded.expires_at,
        provider = excluded.provider,
        receipt = excluded.receipt,
        updated_at = now();
end;
$$;

-- Migration douce: ajouter device_id si la table existait avec PK user_id
do $$
begin
    -- Si la PK actuelle est user_id, on doit migrer vers id bigserial
    if exists (
        select 1 from information_schema.table_constraints
        where table_name = 'subscriptions'
          and constraint_name = 'subscriptions_pkey'
          and constraint_type = 'PRIMARY KEY'
    ) and not exists (
        select 1 from information_schema.columns
        where table_name = 'subscriptions' and column_name = 'id'
    ) then
        alter table public.subscriptions drop constraint subscriptions_pkey;
        alter table public.subscriptions add column id bigserial primary key;
        alter table public.subscriptions add column if not exists device_id text;
        alter table public.subscriptions add column if not exists receipt text;
    end if;
end $$;

-- 4ter. Migration : ajout du systeme de packs hebdomadaires
-- Chaque pack a une taille (nombre d'images) et un quota consomme.
-- pack_size IS NULL = abonnement legacy illimite (compat retro)
alter table public.subscriptions add column if not exists pack_size int;
alter table public.subscriptions add column if not exists images_used int default 0;

-- Helper : marquer un user/device premium AVEC pack (replace v1 helpers)
-- Si nouveau pack achete, on reset images_used a 0.
create or replace function public.set_premium_user(
    p_user_id uuid,
    p_plan text default 'pack_10_week',
    p_expires_at timestamptz default null,
    p_provider text default 'geniuspay',
    p_receipt text default null,
    p_pack_size int default null
) returns void
language plpgsql
security definer
as $$
begin
    insert into public.subscriptions (
      user_id, is_premium, plan, expires_at, provider, receipt,
      pack_size, images_used, updated_at
    )
    values (
      p_user_id, true, p_plan, p_expires_at, p_provider, p_receipt,
      p_pack_size, 0, now()
    )
    on conflict (user_id) do update set
        is_premium = true,
        plan = excluded.plan,
        expires_at = excluded.expires_at,
        provider = excluded.provider,
        receipt = excluded.receipt,
        pack_size = excluded.pack_size,
        images_used = 0,  -- reset compteur a chaque nouveau pack
        updated_at = now();
end;
$$;

create or replace function public.set_premium_device(
    p_device_id text,
    p_plan text default 'pack_10_week',
    p_expires_at timestamptz default null,
    p_provider text default 'geniuspay',
    p_receipt text default null,
    p_pack_size int default null
) returns void
language plpgsql
security definer
as $$
begin
    insert into public.subscriptions (
      device_id, is_premium, plan, expires_at, provider, receipt,
      pack_size, images_used, updated_at
    )
    values (
      p_device_id, true, p_plan, p_expires_at, p_provider, p_receipt,
      p_pack_size, 0, now()
    )
    on conflict (device_id) where device_id is not null and user_id is null
    do update set
        is_premium = true,
        plan = excluded.plan,
        expires_at = excluded.expires_at,
        provider = excluded.provider,
        receipt = excluded.receipt,
        pack_size = excluded.pack_size,
        images_used = 0,
        updated_at = now();
end;
$$;

-- Helper : consommer 1 image d'un pack actif (FIFO sur expires_at).
-- Retourne le nombre d'images restantes dans le pack apres consommation,
-- ou -1 si aucun pack disponible (legacy unlimited renvoie 99999).
create or replace function public.consume_pack_image(
    p_user_id uuid default null,
    p_device_id text default null
) returns int
language plpgsql
security definer
as $$
declare
    v_id bigint;
    v_pack_size int;
    v_used int;
    v_remaining int;
begin
    -- Recherche la sub active pour cet user ou device
    select id, pack_size, images_used into v_id, v_pack_size, v_used
    from public.subscriptions
    where is_premium = true
      and (
        (p_user_id is not null and user_id = p_user_id) or
        (p_user_id is null and p_device_id is not null and device_id = p_device_id and user_id is null)
      )
      and (expires_at is null or expires_at > now())
    order by expires_at asc nulls last
    limit 1;

    if v_id is null then
        return -1;  -- pas de sub active
    end if;

    -- Legacy unlimited (pack_size NULL) : pas de decrement, illimite
    if v_pack_size is null then
        return 99999;
    end if;

    -- Quota epuise
    if v_used >= v_pack_size then
        return 0;
    end if;

    update public.subscriptions
    set images_used = images_used + 1, updated_at = now()
    where id = v_id;

    v_remaining := v_pack_size - v_used - 1;
    return v_remaining;
end;
$$;

-- 4bis. Table des paiements (GeniusPay - tracking + idempotency)
-- Chaque ligne = une transaction GeniusPay. Idempotency par reference (unique).
-- Le webhook met a jour le status et active la subscription quand status=success.
create table if not exists public.payments (
    id              bigserial primary key,
    reference       text not null unique,        -- MTX-... (GeniusPay)
    provider        text not null default 'geniuspay',
    user_id         uuid references auth.users(id) on delete set null,
    device_id       text,
    plan            text,                        -- 'monthly' | 'lifetime'
    amount          integer not null,            -- en plus petite unite (XOF = unite directe)
    currency        text not null default 'XOF',
    status          text not null default 'pending',  -- pending | completed | failed | expired
    checkout_url    text,
    raw_response    jsonb,                       -- copie de la reponse GeniusPay (debug)
    raw_webhook     jsonb,                       -- copie du payload webhook recu
    created_at      timestamptz not null default now(),
    completed_at    timestamptz,
    constraint payments_user_or_device check (user_id is not null or device_id is not null)
);

create index if not exists payments_device_idx on public.payments(device_id);
create index if not exists payments_user_idx on public.payments(user_id);
create index if not exists payments_status_idx on public.payments(status, created_at desc);

alter table public.payments enable row level security;

drop policy if exists "users read own payments" on public.payments;
create policy "users read own payments"
  on public.payments for select
  using (auth.uid() = user_id);

drop policy if exists "service role full access payments" on public.payments;
create policy "service role full access payments"
  on public.payments for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

-- 5. Storage bucket (a executer aussi via Storage UI ou CLI)
-- Dans Supabase Studio > Storage > Create bucket "souvenir" (PUBLIC)
-- Folders attendus dans le bucket: uploads/, outputs/

-- 5. Storage policies (lecture publique des outputs)
-- A configurer dans Storage > Policies > "souvenir" bucket:
--   Policy 1: "Public read" - SELECT to anon role
--   Policy 2: "Service write" - INSERT/UPDATE/DELETE to service_role
