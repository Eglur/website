-- Connect contact messages to the email script (SETUP.md step 3), the no-copy way.
-- Run in Supabase (project "Eglur Daily": SQL Editor > New query > paste this > Run).
--
-- Run it only AFTER the updated Apps Script is deployed (step 2): the old script would
-- treat a message as a waitlist sign-up.
--
-- It finds the waitlist's existing webhook and gives contact_messages one with the same
-- address, headers and parameters (that's where the secret token usually sits), all inside
-- the database, so the token is never copied, pasted or shown.
-- Safe to run again. It appears under Database > Webhooks as "send-message-to-inbox".
do $$
declare
  raw bytea;
  args text[] := '{}';
  p int;
begin
  select t.tgargs into raw
  from pg_trigger t
  join pg_proc pr on pr.oid = t.tgfoid
  join pg_namespace pn on pn.oid = pr.pronamespace
  where t.tgrelid = 'public.waitlist'::regclass
    and pn.nspname = 'supabase_functions' and pr.proname = 'http_request'
    and encode(t.tgargs, 'escape') like 'https://script.google.com/%'
  limit 1;

  if raw is null then
    raise exception 'Could not find the waitlist''s webhook to the Google script. Create the webhook in the dashboard instead (SETUP.md, step 3).';
  end if;

  -- the arguments are stored as text separated by zero bytes: url, method, headers, params, timeout
  loop
    p := position('\x00'::bytea in raw);
    exit when p = 0;
    args := args || convert_from(substring(raw from 1 for p - 1), 'UTF8');
    raw := substring(raw from p + 1);
  end loop;
  if coalesce(array_length(args, 1), 0) < 4 then
    raise exception 'The waitlist''s webhook looks different from expected. Create the webhook in the dashboard instead (SETUP.md, step 3).';
  end if;

  drop trigger if exists "send-message-to-inbox" on public.contact_messages;
  execute format(
    'create trigger "send-message-to-inbox" after insert on public.contact_messages '
    'for each row execute function supabase_functions.http_request(%L, %L, %L, %L, %L)',
    args[1], args[2], args[3], args[4], '5000');
  raise notice 'Connected: contact messages now go to the same Google script as the waitlist.';
end $$;
