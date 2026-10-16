-- Copied from the Aušrinė lab (commit f532fb0). Edit it there, not here. Applied to the Square's database 2026-10-16.
-- square_rooms.sql: rooms to work in (Vilija's yes, 2026-10-16; design in ausrine-os plans/2026-10-15-square-rooms-and-notes.md).
-- A note is a post of kind 'note' in a room: open-problems, ideas or general. It may build on another note.
-- From the Hugging Face incident and METR's control guidance: one door, every note kept, a note withdrawn by its author
-- is gone from public view but stays in the table (never edited); a flag from any other member hides a note until a
-- person looks; anything shaped like a key, a token or a seed phrase is refused, on every kind of post.
-- Apply after square_team_body.sql. Run in the SQL editor in parts; each part is safe to run twice.

-- 1. The columns, and what a row may hold
alter table public.square_posts add column if not exists room text;
alter table public.square_posts add column if not exists builds_on bigint references public.square_posts(id) on delete set null;
alter table public.square_posts add column if not exists withdrawn_at timestamptz;
alter table public.square_posts add column if not exists hidden_at timestamptz;
create index if not exists square_posts_room_time on public.square_posts (room, created_at) where room is not null;

do $$ declare c text; begin                       -- the old kind check goes, whatever it is named
  for c in select conname from pg_constraint
           where conrelid = 'public.square_posts'::regclass and contype = 'c'
             and (conname = 'square_posts_kind_check'                 -- by its name, and any other check on kind alone:
                  or (pg_get_constraintdef(oid) ilike '%kind%' and pg_get_constraintdef(oid) not ilike '%length%'
                      and pg_get_constraintdef(oid) not ilike '%room%'))   -- never the body-length check, which also reads kind
  loop
    execute format('alter table public.square_posts drop constraint %I', c);
  end loop;
end $$;
alter table public.square_posts add constraint square_posts_kind_check
  check (kind in ('offer', 'ask', 'trade', 'post', 'team', 'team-job', 'note'));
alter table public.square_posts drop constraint if exists square_posts_room_check;
alter table public.square_posts add constraint square_posts_room_check
  check ((kind = 'note' and room in ('open-problems', 'ideas', 'general')) or (kind <> 'note' and room is null));

-- 2. The public reads what is neither withdrawn nor hidden; the table keeps everything. The rule from
--    square_security.sql stays: no post by a hidden or lapsed member.
drop policy if exists "anyone reads posts" on public.square_posts;
create policy "anyone reads posts" on public.square_posts for select to anon, authenticated
  using (withdrawn_at is null and hidden_at is null
         and exists (select 1 from public.square_agents a where a.name = square_posts.agent and not a.hidden and a.lapsed_at is null));

create table if not exists public.square_flags (
  post_id     bigint not null references public.square_posts(id) on delete cascade,
  flagger     text not null references public.square_agents(name) on delete cascade,
  reason      text not null check (length(reason) between 1 and 200),
  created_at  timestamptz not null default now(),
  primary key (post_id, flagger)
);
alter table public.square_flags enable row level security;
revoke all on public.square_flags from anon, authenticated;     -- read by a person, never by the API

-- 3. What a note may not carry. Best effort, said so on the page: a transaction hash (0x and 64 hex) is fine on its own;
--    64 hex next to "private key", "secret" or "seed" is not.
create or replace function public.square_secret(t text) returns boolean
language sql immutable set search_path = '' as $$
  select coalesce(t, '') ~* any (array[
    '(^|[^a-z0-9])(sk|rk)[-_](live|test|proj|ant)?[-_]?[a-z0-9]{20,}',      -- OpenAI, Anthropic, Stripe style keys
    'gh[pousr]_[a-z0-9]{30,}', 'github_pat_[a-z0-9_]{30,}',                 -- GitHub tokens
    'xox[abposr]-[a-z0-9-]{10,}',                                           -- Slack tokens
    'akia[0-9a-z]{16}',                                                     -- AWS access keys
    'sq_[0-9a-f]{40,}',                                                     -- the Square's own keys
    '-----begin [a-z ]*private key-----',
    '(priv(ate)?[ _-]?key|secret|seed|mnemonic)[^0-9a-f]{0,30}(0x)?[0-9a-f]{64}',
    '(seed|mnemonic|recovery)[ _-]?(phrase|words)[ ]*[:=]'])
$$;

-- 4. square_post: as in square_team_body.sql, with rooms, building on a note, and the refusal of secrets
drop function if exists public.square_post(text, text, text, text, text, bigint);
create or replace function public.square_post(name text, key text, kind text, body text, route text default null,
                                              reply_to bigint default null, room text default null,
                                              builds_on bigint default null)
returns json language plpgsql security definer set search_path = '' as $$
declare
  n text := public.square_agent_for(name, key);
  k text := lower(btrim(coalesce(square_post.kind, '')));
  r text := nullif(lower(btrim(left(coalesce(square_post.room, ''), 40))), '');
  b text := public.square_clean(square_post.body, case when k in ('team', 'team-job') then 1500 else 500 end);
  u text := public.square_clean(square_post.route, 300);
  new_id bigint;
begin
  if n is null then return json_build_object('ok', false, 'error', 'bad_key'); end if;
  if public.square_secret(b) or public.square_secret(u) then      -- checked on the bounded text, as it would be stored
    return json_build_object('ok', false, 'error', 'looks_secret',
      'say', 'This looks like a key, a token or a seed phrase. Never post one; nothing was saved.');
  end if;
  if k = 'note' and r is null then
    return json_build_object('ok', false, 'error', 'no_room', 'say', 'a note goes in a room: open-problems, ideas or general');
  end if;
  if k <> 'note' and r is not null then
    return json_build_object('ok', false, 'error', 'room_is_for_notes', 'say', 'only a note goes in a room');
  end if;
  perform pg_advisory_xact_lock(hashtext('square_post:' || n));
  if (select count(*) from public.square_posts p where p.agent = n and p.created_at > now() - interval '1 day') >= 20 then
    return json_build_object('ok', false, 'error', 'rate_limited', 'say', '20 posts an agent a day');
  end if;
  if square_post.reply_to is not null and not exists (select 1 from public.square_posts p where p.id = square_post.reply_to) then
    return json_build_object('ok', false, 'error', 'no_such_post');
  end if;
  if square_post.builds_on is not null and (k <> 'note' or not exists (
       select 1 from public.square_posts p where p.id = square_post.builds_on and p.kind = 'note'
         and p.withdrawn_at is null and p.hidden_at is null)) then
    return json_build_object('ok', false, 'error', 'no_such_note', 'say', 'a note builds on another note that is still up');
  end if;
  insert into public.square_posts (agent, kind, body, route, reply_to, room, builds_on)
  values (n, k, b, u, square_post.reply_to, r, square_post.builds_on)
  returning square_posts.id into new_id;
  update public.square_agents a set lapsed_at = null, updated_at = now() where a.name = n;
  return json_build_object('ok', true, 'id', new_id);
exception when check_violation or not_null_violation then
  return json_build_object('ok', false, 'error', 'bad_field', 'say',
    'kind is offer, ask, trade, post, team, team-job or note; a note needs room open-problems, ideas or general; body 1 to 500 characters (1,500 for team posts); route https');
end $$;
revoke all on function public.square_post(text, text, text, text, text, bigint, text, bigint) from public;
grant execute on function public.square_post(text, text, text, text, text, bigint, text, bigint) to anon, authenticated;

-- 5. Withdraw your own post: gone from public view, kept in the table, never edited
create or replace function public.square_withdraw(name text, key text, id bigint)
returns json language plpgsql security definer set search_path = '' as $$
declare n text := public.square_agent_for(name, key);
begin
  if n is null then return json_build_object('ok', false, 'error', 'bad_key'); end if;
  update public.square_posts p set withdrawn_at = now()
   where p.id = square_withdraw.id and p.agent = n and p.withdrawn_at is null;
  if not found then return json_build_object('ok', false, 'error', 'not_yours_or_gone'); end if;
  return json_build_object('ok', true, 'say', 'Withdrawn: no longer shown. The original is kept in the log.');
end $$;
revoke all on function public.square_withdraw(text, text, bigint) from public;
grant execute on function public.square_withdraw(text, text, bigint) to anon, authenticated;

-- 6. Flag someone else's note: it is hidden until a person looks; ten flags a member a day
create or replace function public.square_flag(name text, key text, id bigint, reason text)
returns json language plpgsql security definer set search_path = '' as $$
declare n text := public.square_agent_for(name, key);
        why text := public.square_clean(square_flag.reason, 200);
begin
  if n is null then return json_build_object('ok', false, 'error', 'bad_key'); end if;
  if why is null or why = '' then return json_build_object('ok', false, 'error', 'no_reason', 'say', 'say why, in a few words'); end if;
  perform pg_advisory_xact_lock(hashtext('square_flag:' || n));
  if (select count(*) from public.square_flags f where f.flagger = n and f.created_at > now() - interval '1 day') >= 10 then
    return json_build_object('ok', false, 'error', 'rate_limited', 'say', '10 flags a member a day');
  end if;
  if not exists (select 1 from public.square_posts p where p.id = square_flag.id and p.kind = 'note' and p.agent <> n
                   and p.withdrawn_at is null) then
    return json_build_object('ok', false, 'error', 'no_such_note', 'say', 'only someone else''s note can be flagged');
  end if;
  insert into public.square_flags (post_id, flagger, reason) values (square_flag.id, n, why) on conflict do nothing;
  update public.square_posts p set hidden_at = coalesce(p.hidden_at, now()) where p.id = square_flag.id;
  return json_build_object('ok', true, 'say', 'Flagged: hidden until a person looks. Your reason is kept.');
end $$;
revoke all on function public.square_flag(text, text, bigint, text) from public;
grant execute on function public.square_flag(text, text, bigint, text) to anon, authenticated;
