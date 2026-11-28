-- Connect contact messages to the email script (SETUP.md step 3), the no-copy way.
-- Run in Supabase (project "Eglur Daily": SQL Editor > New query > paste this > Run).
--
-- Run it only AFTER the updated Apps Script is deployed (step 2): the old script would
-- treat a message as a waitlist sign-up.
--
-- It finds the waitlist's existing webhook and gives contact_messages one with the same
-- address, all inside the database, so the secret token is never copied, pasted or shown.
-- Safe to run again. It appears under Database > Webhooks as "send-message-to-inbox".
do $$
declare
  args text[];
begin
  select string_to_array(encode(t.tgargs, 'escape'), '\000') into args
  from pg_trigger t
  join pg_proc p on p.oid = t.tgfoid
  join pg_namespace pn on pn.oid = p.pronamespace
  where t.tgrelid = 'public.waitlist'::regclass
    and pn.nspname = 'supabase_functions' and p.proname = 'http_request'
    and encode(t.tgargs, 'escape') like 'https://script.google.com/%'
  limit 1;

  if args is null then
    raise exception 'Could not find the waitlist''s webhook to the Google script. Create the webhook in the dashboard instead (SETUP.md, step 3).';
  end if;

  drop trigger if exists "send-message-to-inbox" on public.contact_messages;
  execute format(
    'create trigger "send-message-to-inbox" after insert on public.contact_messages '
    'for each row execute function supabase_functions.http_request(%L, %L, %L, %L, %L)',
    args[1], 'POST', '{"Content-type":"application/json"}', '{}', '5000');
  raise notice 'Connected: contact messages now go to the same Google script as the waitlist.';
end $$;
