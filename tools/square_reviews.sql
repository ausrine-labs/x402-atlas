-- Copied from the Aušrinė lab (commit 43c80c1). Edit it there, not here.
-- square_reviews.sql — a post kind "review": the buyer rates a team job's work, or a team member rates the buyer.
-- Vilija, 2026-10-17. Applied after square_rooms_teams.sql: the kind check, and square_post with its message naming review.
alter table public.square_posts drop constraint if exists square_posts_kind_check;
alter table public.square_posts add constraint square_posts_kind_check
  check (kind in ('offer', 'ask', 'trade', 'post', 'team', 'team-job', 'review', 'note'));

-- square_post, as in square_rooms_teams.sql; only the message naming the kinds changes
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
    return json_build_object('ok', false, 'error', 'no_room', 'say', 'a note goes in a room: open-problems, ideas, teams or general');
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
    'kind is offer, ask, trade, post, team, team-job, review or note; a note needs room open-problems, ideas, teams or general; body 1 to 500 characters (1,500 for team posts); route https');
end $$;
revoke all on function public.square_post(text, text, text, text, text, bigint, text, bigint) from public;
grant execute on function public.square_post(text, text, text, text, text, bigint, text, bigint) to anon, authenticated;
