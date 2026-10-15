-- AIM: AI Manager. Database setup for your own Supabase project.
-- The installer fills in your email (the one you sign in with on the phone) and copies this file to the clipboard.
-- By hand: replace the email placeholder below with your email, then paste into Supabase -> SQL Editor -> New query -> Run.
-- Every table is locked by row-level security to that one email; the publishable key in the page grants nothing else.

-- AIM: tables, access rules and photo storage.
-- Paste all of this into Supabase -> SQL Editor -> New query, then press Run.
-- Only that email (after confirming it) can read or write.
-- The computer uses the secret key, which bypasses these rules, and never leaves the computer.

create table if not exists public.messages (
  id          text primary key,
  sender      text not null check (sender in ('claude', 'me')),
  kind        text not null default 'reply',
  text        text not null default '',
  ts          bigint not null,
  seen        boolean,
  seen_at     timestamptz,
  reply_to    text,
  images      text[],
  created_at  timestamptz not null default now()
);
create index if not exists messages_ts_idx on public.messages (ts desc);

create table if not exists public.control (
  id          text primary key,
  data        jsonb not null default '{}'::jsonb,
  updated_at  timestamptz not null default now()
);

alter table public.messages enable row level security;
alter table public.control  enable row level security;

drop policy if exists "aim owner messages" on public.messages;
create policy "aim owner messages" on public.messages
  for all to authenticated
  using ((auth.jwt() ->> 'email') = '__OWNER_EMAIL__')
  with check ((auth.jwt() ->> 'email') = '__OWNER_EMAIL__');

drop policy if exists "aim owner control" on public.control;
create policy "aim owner control" on public.control
  for all to authenticated
  using ((auth.jwt() ->> 'email') = '__OWNER_EMAIL__')
  with check ((auth.jwt() ->> 'email') = '__OWNER_EMAIL__');

-- Live updates on the phone
do $$
begin
  begin alter publication supabase_realtime add table public.messages; exception when duplicate_object then null; end;
  begin alter publication supabase_realtime add table public.control;  exception when duplicate_object then null; end;
end $$;

-- Private photo storage
insert into storage.buckets (id, name, public)
values ('aim-photos', 'aim-photos', false)
on conflict (id) do nothing;

drop policy if exists "aim owner photos" on storage.objects;
create policy "aim owner photos" on storage.objects
  for all to authenticated
  using (bucket_id = 'aim-photos' and (auth.jwt() ->> 'email') = '__OWNER_EMAIL__')
  with check (bucket_id = 'aim-photos' and (auth.jwt() ->> 'email') = '__OWNER_EMAIL__');

insert into public.control (id, data) values
  ('settings', '{"mode": "on"}'),
  ('status',   '{"state": "off"}'),
  ('watcher',  '{}')
on conflict (id) do nothing;


-- Every computer session that turns the line on starts a new conversation; old ones stay, with a name.

alter table public.messages add column if not exists conv text;
create index if not exists messages_conv_ts_idx on public.messages (conv, ts desc);

create table if not exists public.conversations (
  id          text primary key,
  title       text not null default '',
  project     text,
  created_at  timestamptz not null default now()
);
alter table public.conversations enable row level security;

drop policy if exists "aim owner conversations" on public.conversations;
create policy "aim owner conversations" on public.conversations
  for all to authenticated
  using ((auth.jwt() ->> 'email') = '__OWNER_EMAIL__')
  with check ((auth.jwt() ->> 'email') = '__OWNER_EMAIL__');

do $$
begin
  begin alter publication supabase_realtime add table public.conversations; exception when duplicate_object then null; end;
end $$;
