-- Website contact form: run once in Supabase, project "Eglur Daily"
-- (SQL Editor > New query > paste this > Run). Safe to run again.
--
-- What it does:
--   1. A table for messages sent from www.eglurtech.com/contact.
--   2. The website's public key may only ADD a message. It can't read, change or delete any.
--      You read messages in your inbox, the "Messages" sheet, or here in the dashboard.
--   3. A brake on floods: at most 3 messages an hour from one email address, 30 an hour and
--      150 a day in total. Past that, the form tells people to try again later.

create table if not exists public.contact_messages (
  id            bigint generated always as identity primary key,
  created_at    timestamptz not null default now(),
  name          text not null check (length(btrim(name)) between 1 and 120 and name !~ '[[:cntrl:]]'),
  email         text not null check (length(email) between 5 and 254 and email !~ '[[:cntrl:]]'
                                     and email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  organisation  text not null default '' check (length(organisation) <= 160 and organisation !~ '[[:cntrl:]]'),
  topic         text not null default '' check (topic in ('', 'conversation', 'design-partner', 'other')),
  message       text not null check (length(btrim(message)) between 1 and 5000),
  from_page     text not null default '' check (from_page ~ '^[a-z0-9-]{0,40}$')
);
create index if not exists contact_messages_created_at on public.contact_messages (created_at);

alter table public.contact_messages enable row level security;
drop policy if exists "website can send messages" on public.contact_messages;
create policy "website can send messages" on public.contact_messages for insert to anon with check (true);
-- No select, update or delete policies: the public key can't read or change anything.

-- Allow exactly one thing: the website adding a message, with these columns only.
revoke all on table public.contact_messages from anon, authenticated;
grant usage on schema public to anon;
grant insert (name, email, organisation, topic, message, from_page) on public.contact_messages to anon;

-- The brake. It lives in a schema the website can't reach, and only runs as part of an insert.
create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create or replace function private.contact_messages_throttle()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if (select count(*) from public.contact_messages
        where lower(email) = lower(new.email) and created_at > now() - interval '1 hour') >= 3 then
    raise sqlstate 'PT429' using message = 'Too many messages from this address. Try again later.';
  end if;
  if (select count(*) from public.contact_messages where created_at > now() - interval '1 hour') >= 30
     or (select count(*) from public.contact_messages where created_at > now() - interval '1 day') >= 150 then
    raise sqlstate 'PT429' using message = 'The contact form is busy. Try again later.';
  end if;
  return new;
end;
$$;
revoke all on function private.contact_messages_throttle() from public, anon, authenticated;

drop trigger if exists contact_messages_throttle on public.contact_messages;
create trigger contact_messages_throttle
  before insert on public.contact_messages
  for each row execute function private.contact_messages_throttle();
