-- Eglur Daily waitlist: run once in Supabase (SQL Editor > New query > Run).
-- The website may only ADD rows. Nobody can read them with the public key; you read them in the Supabase dashboard.
create table if not exists public.waitlist (
  id           bigint generated always as identity primary key,
  created_at   timestamptz not null default now(),
  email        text not null check (length(email) between 5 and 254 and email like '%@%'),
  area         text not null check (length(area) between 2 and 120),
  topics       text[] not null default '{}' check (cardinality(topics) <= 20),
  topics_other text not null default '' check (length(topics_other) <= 500),
  places       text not null default '' check (length(places) <= 500),
  people       text not null default '' check (length(people) <= 500),
  frequency    text not null default 'daily' check (frequency in ('daily', 'weekly')),
  unique (email)
);
alter table public.waitlist enable row level security;
drop policy if exists "website can add sign-ups" on public.waitlist;
create policy "website can add sign-ups" on public.waitlist for insert to anon with check (true);
-- No select, update or delete policies: the public key can't read or change anything.
