-- Template: the installer replaces the token placeholder below with a random token made for you. Never publish your real token.
-- AIM voice: lets the iPhone shortcut "Claude" send one message WITHOUT opening the app and wait for the reply,
-- so Siri can read it aloud.  Paste into Supabase -> SQL Editor -> New query, then Run.
-- The token below only allows these two functions (send a message to your own chat, wait for the next reply).
-- To revoke: change the token here, run it again, and change it in the shortcut.

insert into public.control (id, data) values ('voice', '{"token": "__VOICE_TOKEN__"}')
on conflict (id) do update set data = excluded.data, updated_at = now();

-- 1) send what you said; remembers when and into which chat
create or replace function public.voice_say(p_token text, p_text text) returns bigint
language plpgsql security definer set search_path = public as $$
declare v_ts bigint; v_conv text;
begin
  if p_token is distinct from (select data->>'token' from public.control where id = 'voice') then
    raise exception 'forbidden';
  end if;
  v_ts := (extract(epoch from clock_timestamp()) * 1000)::bigint;
  select data->>'conv' into v_conv from public.control where id = 'current';
  insert into public.messages (id, sender, kind, text, ts, seen, conv)
  values ('mv' || v_ts, 'me', 'command', left(coalesce(p_text, ''), 1000), v_ts, false, v_conv);
  update public.control
    set data = data || jsonb_build_object('last_ts', v_ts, 'conv', v_conv), updated_at = now()
    where id = 'voice';
  return v_ts;
end $$;

-- 2) wait (up to about 50 seconds) for the first reply after that message and return it as plain text
create or replace function public.voice_wait(p_token text) returns text
language plpgsql security definer set search_path = public set statement_timeout = '58s' as $$
declare v_since bigint; v_conv text; v_reply text; i int := 0;
begin
  if p_token is distinct from (select data->>'token' from public.control where id = 'voice') then
    raise exception 'forbidden';
  end if;
  select coalesce((data->>'last_ts')::bigint, 0), data->>'conv' into v_since, v_conv
    from public.control where id = 'voice';
  loop
    select text into v_reply from public.messages
      where sender = 'claude' and kind in ('reply', 'question') and ts > v_since and conv is not distinct from v_conv
      order by ts desc limit 1;
    exit when v_reply is not null or i >= 50;
    perform pg_sleep(1);
    i := i + 1;
  end loop;
  if v_reply is null then
    return 'No reply in time. Check that the line is on.';
  end if;
  return left(regexp_replace(v_reply, '[*_`#>]+', '', 'g'), 1500);
end $$;

-- 3) the address of an iPhone app the user asked to open (empty if none); read once, then cleared
create or replace function public.voice_open(p_token text) returns text
language plpgsql security definer set search_path = public as $$
declare v text;
begin
  if p_token is distinct from (select data->>'token' from public.control where id = 'voice') then
    raise exception 'forbidden';
  end if;
  select data->>'open_url' into v from public.control where id = 'voice';
  update public.control set data = data - 'open_url' where id = 'voice' and data ? 'open_url';
  return coalesce(v, '');
end $$;

revoke all on function public.voice_open(text) from public;
grant execute on function public.voice_open(text) to anon, authenticated;

revoke all on function public.voice_say(text, text) from public;
revoke all on function public.voice_wait(text) from public;
grant execute on function public.voice_say(text, text) to anon, authenticated;
grant execute on function public.voice_wait(text) to anon, authenticated;
