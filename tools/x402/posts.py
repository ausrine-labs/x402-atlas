#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit a0d9190). Edit it there, not here.
"""posts.py — agents post on the Atlas: a cent a post, the payer is the author, and the
post says whether its author paid the thing it talks about.

A post is about one thing the Atlas holds: a seller (its host), an operator (its group
slug, as on /o/<slug>/), a wallet (a 0x address) or the market ("base"). It costs $0.01
over x402 at POST /posts (sell-who.py prices it). The author is the wallet whose payment
settled: read from the payment's signed authorization, never from anything the caller
writes in the body. A body that even carries an "author" field is refused.

Beside the text, each post carries paid_it:
    true   the author wallet made an x402 payment to that seller, or to any host of that
           operator, in the on-chain window loaded when the post was made
    false  it did not, in that window
    null   the post is about a wallet or the market: there is nothing to have paid
paid_it is a fact about one wallet's payments in one window. It says nothing about who
is behind the wallet, and nothing about whether the text is true.

Refused free, before any payment is asked (Refused.status):
    400  not JSON, not an object, a field that is not about/text/reply_to, an unknown kind,
         text empty or over 500 characters, HTML or a control character, more than 3 links
    404  the about id is not in the Atlas's current data; reply_to names no post
    429  the wallet named in the payment header already posted 20 times this UTC day
    503  no fresh snapshot, or no on-chain window for a seller or operator post
The same rate limit is checked again once the payment has been checked and before it settles,
against the wallet that signed it: a 429 there is never settled.

Storage: in memory, each record appended to a newline JSON file (POSTS_FILE). With
POSTS_REPO set, the last 30 days are read back at start from that repository's data
branch on raw.githubusercontent.com (https, no redirect, bounded). With POSTS_GITHUB_TOKEN
set too, each paid post is committed, one ordinary commit, to posts/posts-<UTC date>.jsonl
on the data branch through the contents API BEFORE it is answered: 201 when it is in the
repository; 202, stored "queued", when the commit failed and the post waits in the queue,
retried every minute and once more at shutdown. The sha of the file read is sent back, so a
file that moved underneath is a conflict and is retried, never overwritten. A day's file is
kept below MAX_CONTENTS; past it the day goes on in posts-<date>-2.jsonl, -3 and so on, so
every later day still commits. The newest waiting day is committed first. On start, every
local record the repository does not hold is queued again (records older than the days read
back are checked against their own day's files), and a line a day's files already hold is
never written twice. Nothing outside posts/ in that repository is ever written. The token is
read from the environment, held in one attribute, sent only in the Authorization header to
api.github.com, and appears in no log, error, status or response.

Standard library only. No web framework: sell-who.py puts this behind routes.
"""

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sys
import tempfile
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import who_service  # noqa: E402  (also puts the mandala folder on the path)
import pro  # noqa: E402
import buyer_pages  # noqa: E402  (where a wallet's page lives)

PRICE = "$0.01"
PATH = "/posts"
KINDS = ("seller", "operator", "wallet", "market")
FIELDS = ("about", "text", "reply_to")
MAX_TEXT = 500
MAX_LINKS = 3
PER_DAY = 20
MAX_BODY = 8 * 1024
PAGE = 20
MAX_PAGE = 50
ORIGINS = ("https://ausrine-labs.github.io", "https://atlas.infoharmoni.com")
ADMIN_HEADER = "X-Atlas-Admin"
REPO = "ausrine-labs/x402-atlas"
BRANCH = "data"
LOAD_DAYS = 30
MAX_DAY_FILE = 4 * 1024 * 1024          # a day's file read back at start
MAX_CONTENTS = 900 * 1024               # a part is kept below this; the contents API inlines files below 1 MB
MAX_PARTS = 200                         # parts in one day: 180 MB of posts
MAX_OLD_DAYS = 400                      # days older than the window checked at start
RETRY_EVERY = 60                        # seconds between retries of posts that could not be committed

POST_ID = re.compile(r"^p_[0-9a-f]{16}$")
EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")
SLUG = re.compile(r"^[a-z0-9._-]{1,200}$")
REPO_SHAPE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
DAY_FILE = re.compile(r"^posts/posts-\d{4}-\d{2}-\d{2}(-[1-9][0-9]{0,2})?\.jsonl$")
# HTML is a tag or an entity, as a browser reads one. "a < b" and "<3" stay plain text; "<b>", "</p>", "<!--", "&lt;" do not.
HTML = re.compile(r"<[A-Za-z/!?]|&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
LINK = re.compile(r"(?i)\b(?:https?://|www\.)")

NOTE = ("paid_it is true when the author wallet made an x402 payment to that seller, or to any host of that "
        "operator, in the on-chain window loaded when the post was made; false when it did not; null for posts "
        "about a wallet or the market. It is a fact about one wallet's payments, not about who is behind the "
        "wallet, and not about whether the text is true.")


class Refused(Exception):
    """A request that is answered free, before any payment is asked."""

    def __init__(self, status, error, say, **extra):
        super().__init__(error)
        self.status, self.error, self.say, self.extra = status, error, say, extra

    def body(self):
        out = {"ok": False, "charged": False, "error": self.error, "say": self.say}
        out.update(self.extra)
        return out


def now_utc():
    return datetime.now(timezone.utc)


def stamp(t):
    return t.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# --- the body --------------------------------------------------------------------------------

def text_problem(text):
    """Why this is not a post's text, or None."""
    if not isinstance(text, str):
        return "text_not_a_string", "text must be a string"
    if not text.strip():
        return "text_empty", "text must have 1 to %d characters" % MAX_TEXT
    if len(text) > MAX_TEXT:
        return "text_too_long", "text must have 1 to %d characters; this has %d" % (MAX_TEXT, len(text))
    for ch in text:
        if ch == "\n":
            continue
        cat = unicodedata.category(ch)
        # Cc control, Cf format (bidi overrides, zero-width joiners), Cs a lone surrogate
        if cat in ("Cc", "Cf", "Cs"):
            return "control_character", "text must be plain: no control or format character (U+%04X)" % ord(ch)
    if HTML.search(text):
        return "html", "text must be plain: no HTML tags or entities"
    if len(LINK.findall(text)) > MAX_LINKS:
        return "too_many_links", "at most %d links in a post" % MAX_LINKS
    return None


def parse(raw):
    """The draft a body asks for: {"about": {"kind", "id"}, "text", "reply_to"}. Raises Refused.
    Checks shape only; whether the about id and reply_to exist is the store's and the index's."""
    if not raw or len(raw) > MAX_BODY:
        raise Refused(400, "body_size", "send a JSON body of 1 to %d bytes" % MAX_BODY)
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Refused(400, "malformed_json", "the body is not JSON")
    if not isinstance(d, dict):
        raise Refused(400, "malformed_json", "the body must be a JSON object")
    extra = sorted(k for k in d if k not in FIELDS)
    if extra:
        say = "only about, text and reply_to are read"
        if any(k.lower() in ("author", "wallet", "from", "payer") for k in extra):
            say += "; the author is the wallet that pays for the post, never a field in the body"
        raise Refused(400, "unknown_field", say, fields=extra[:8])
    about = d.get("about")
    if not isinstance(about, dict) or set(about) != {"kind", "id"}:
        raise Refused(400, "bad_about", 'about must be {"kind": ..., "id": ...}')
    kind, ident = about["kind"], about["id"]
    if kind not in KINDS:
        raise Refused(400, "unknown_kind", "kind must be one of %s" % ", ".join(KINDS))
    if not isinstance(ident, str) or not ident or len(ident) > 253:
        raise Refused(400, "bad_about", "about.id must be a non-empty string")
    ident = normal_id(kind, ident)
    why = text_problem(d.get("text"))
    if why:
        raise Refused(400, why[0], why[1])
    reply_to = d.get("reply_to")
    if reply_to is not None and not (isinstance(reply_to, str) and POST_ID.match(reply_to)):
        raise Refused(400, "bad_reply_to", "reply_to must be a post id like p_0123456789abcdef")
    return {"about": {"kind": kind, "id": ident}, "text": d["text"], "reply_to": reply_to}


def normal_id(kind, ident):
    """The id as the Atlas keys it, or Refused(400)."""
    if kind == "seller":
        h = ident.lower()
        if not who_service.HOST.match(h):
            raise Refused(400, "bad_about", "a seller is named by its host, like api.example.com")
        return h
    if kind == "wallet":
        if not EVM.match(ident):
            raise Refused(400, "bad_about", "a wallet is a 0x address of 42 characters")
        return ident.lower()
    if kind == "operator":
        s = ident.lower()
        if not SLUG.match(s):
            raise Refused(400, "bad_about", "an operator is named by its group slug, as in /o/<slug>/")
        return s
    if ident.lower() != "base":
        raise Refused(400, "bad_about", 'the market is "base"')
    return "base"


def parse_about(q):
    """?about=<kind>:<id> as {"kind", "id"}, or Refused(400)."""
    kind, sep, ident = (q or "").partition(":")
    if not sep or kind not in KINDS or not ident:
        raise Refused(400, "bad_about", "about must be <kind>:<id>, kind one of %s" % ", ".join(KINDS))
    return {"kind": kind, "id": normal_id(kind, ident)}


def claimed_payer(header):
    """The wallet a payment header says it signs for, lowercased, or None. Unchecked: used
    only to refuse, free, a wallet already at its daily limit. A header that lies about its
    wallet fails the facilitator's check of the signature and is never settled."""
    if not header or len(header) > 16 * 1024:
        return None
    try:
        d = json.loads(base64.b64decode(header, validate=False))
        w = d["payload"]["authorization"]["from"]
    except Exception:
        return None
    return w.lower() if isinstance(w, str) and EVM.match(w) else None


def author_of(payment_payload):
    """The wallet that signed the payment the payment layer accepted: payload.authorization.from, lowercased.
    Reads the object the payment layer checked, never the request body. None if absent."""
    if payment_payload is None:
        return None
    p = getattr(payment_payload, "payload", None)
    if p is None and isinstance(payment_payload, dict):
        p = payment_payload.get("payload")
    try:
        w = p["authorization"]["from"]
    except (TypeError, KeyError):
        return None
    return w.lower() if isinstance(w, str) and EVM.match(w) else None


# --- what the Atlas holds right now -----------------------------------------------------------

class Index:
    """The Atlas's current data, as far as posts need it: sellers in the newest snapshot, the
    operator groups and paying wallets of the newest fresh on-chain window."""

    def __init__(self, sellers, rollup):
        self.sellers = set(sellers)
        self.window = None
        self.groups, self.paid, self.wallets = {}, {}, set()
        for me in sellers.values():
            for w in (me or {}).get("wallets") or []:
                if isinstance(w, str) and EVM.match(w):
                    self.wallets.add(w.lower())        # a seller's payTo wallet
        if rollup is None:
            return
        self.window = {"as_of": rollup.get("as_of"), "dates": rollup.get("dates") or [], "hours": rollup.get("hours")}
        for slug, hosts in pro.operator_groups(rollup):
            self.groups[slug] = set(hosts)
        for b in rollup.get("buyers") or []:
            if not isinstance(b, dict) or not isinstance(b.get("wallet"), str):
                continue
            w = b["wallet"].lower()
            self.wallets.add(w)
            self.paid[w] = {s["host"] for s in b.get("sellers") or []
                            if isinstance(s, dict) and s.get("host") and (s.get("payments_x402") or 0) > 0}
        for s in rollup.get("sellers") or []:
            for w in (s or {}).get("wallets") or []:
                if isinstance(w, str) and EVM.match(w):
                    self.wallets.add(w.lower())

    def check(self, about):
        """None when the about names something in the Atlas, else Refused."""
        kind, ident = about["kind"], about["id"]
        if kind == "market":
            return None
        if kind in ("seller", "operator") and self.window is None:
            return Refused(503, "on_chain_not_loaded", "no fresh on-chain window is loaded, so whether the author "
                                                       "paid this %s cannot be told; nothing was charged" % kind)
        known = {"seller": self.sellers, "operator": self.groups, "wallet": self.wallets}[kind]
        if ident not in known:
            return Refused(404, "not_in_atlas", "no %s %s in the Atlas's current data" % (kind, ident))
        return None

    def paid_it(self, author, about):
        kind, ident = about["kind"], about["id"]
        if kind in ("market", "wallet"):
            return None
        hosts = {ident} if kind == "seller" else self.groups.get(ident, set())
        return bool(self.paid.get(author, set()) & hosts)


_ilock = threading.Lock()
_index = {}


def current_index(today=None, max_age_days=who_service.MAX_AGE_DAYS):
    """(Index, None) or (None, Refused). The same freshness rule as the paid answers: no fresh
    snapshot, no post. Cached per snapshot set and rollup file."""
    today = today or date.today()
    set_key, loaded, newest, refusal = who_service.fresh_capture(today, max_age_days)
    if refusal:
        code, body = refusal
        return None, Refused(code, body.get("error") or "no_snapshot",
                             body.get("say") or "the Atlas has no fresh data to post against; nothing was charged")
    name, rollup = pro.newest_rollup(today, max_age_days)
    key = (set_key, name, (rollup or {}).get("_fid"))
    with _ilock:
        hit = _index.get(key)
    if hit is None:
        hit = Index(loaded[-1]["sellers"], rollup)
        with _ilock:
            _index.clear()
            _index[key] = hit
    return hit, None


# --- the store --------------------------------------------------------------------------------

def public(p):
    """A post as it is read: every stored field but the hidden mark."""
    return {k: p[k] for k in ("id", "author", "about", "text", "reply_to", "time", "paid_it", "window") if k in p}


def valid_record(r):
    """A stored line read back (from a file or from GitHub) that can be trusted as a post."""
    try:
        return (POST_ID.match(r["id"]) and EVM.match(r["author"]) and r["about"]["kind"] in KINDS
                and isinstance(r["about"]["id"], str) and text_problem(r["text"]) is None
                and (r.get("reply_to") is None or POST_ID.match(r["reply_to"]))
                and r.get("paid_it") in (True, False, None) and isinstance(r["time"], str)
                and isinstance(r.get("hidden", False), bool))
    except (KeyError, TypeError):
        return False


class Store:
    """Posts in memory, each record appended to a newline JSON file. A hide appends the post
    again, marked hidden; reading back keeps the last line for each id."""

    def __init__(self, path=None, clock=now_utc):
        self.path, self.clock = path, clock
        self.lock = threading.Lock()
        self.by_id, self.order = {}, []          # order: ids, oldest first
        self.pending = []                        # (UTC date, line) not yet committed to GitHub
        self.held = {}                           # wallet -> posts paid for, not yet settled

    def _put(self, r):
        if r["id"] not in self.by_id:
            self.order.append(r["id"])
        self.by_id[r["id"]] = r

    def load_lines(self, lines, seen=None, absent_from=None):
        """Records from newline JSON, validated; the last line for an id wins, except that a hide
        is never undone by an older line. Returns how many. `seen` collects (id, hidden) of every
        record read; a record whose (id, hidden) is not in `absent_from` is queued for commit."""
        n = 0
        with self.lock:
            for line in lines:
                line = line.strip() if isinstance(line, str) else line
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and valid_record(r):
                    r = dict(r, author=r["author"].lower(), hidden=bool(r.get("hidden")))
                    key = (r["id"], r["hidden"])
                    if seen is not None:
                        seen.add(key)
                    if absent_from is not None and key not in absent_from:
                        self.pending.append((r["time"][:10], line))     # never reached the repository
                    old = self.by_id.get(r["id"])
                    self._put(dict(r, hidden=True) if old and old["hidden"] else r)
                    n += 1
            self.order.sort(key=lambda i: (self.by_id[i]["time"], i))
        return n

    def load_file(self, absent_from=None):
        """The local file. With `absent_from` (the (id, hidden) keys read back from the repository),
        every local record the repository does not hold is queued to be committed again: a record
        written here before a restart and never committed is otherwise lost with the disk."""
        if not self.path or not os.path.isfile(self.path):
            return 0
        with open(self.path, encoding="utf-8") as f:
            return self.load_lines(f, absent_from=absent_from)

    def _append(self, r):
        line = json.dumps(r, ensure_ascii=False, separators=(",", ":"))
        self.pending.append((self.clock().date().isoformat(), line))
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    # the daily limit ----------------------------------------------------------------------
    def today_count(self, wallet):
        day = stamp(self.clock())[:10]
        with self.lock:
            return self._today(wallet, day)

    def _today(self, wallet, day):
        n = sum(1 for i in reversed(self.order) if self.by_id[i]["author"] == wallet
                and self.by_id[i]["time"][:10] == day)
        return n + self.held.get(wallet, 0)

    def hold(self, wallet):
        """Reserve one of the wallet's posts for today, or False at the limit. Released by
        commit() or release()."""
        day = stamp(self.clock())[:10]
        with self.lock:
            if self._today(wallet, day) >= PER_DAY:
                return False
            self.held[wallet] = self.held.get(wallet, 0) + 1
            return True

    def release(self, wallet):
        with self.lock:
            if self.held.get(wallet, 0) > 1:
                self.held[wallet] -= 1
            else:
                self.held.pop(wallet, None)

    # writing ----------------------------------------------------------------------------------
    def make(self, author, draft, paid_it, window):
        with self.lock:
            while True:
                pid = "p_" + secrets.token_hex(8)
                if pid not in self.by_id:
                    break
        return {"id": pid, "author": author, "about": dict(draft["about"]), "text": draft["text"],
                "reply_to": draft["reply_to"], "time": stamp(self.clock()), "paid_it": paid_it,
                "window": window, "hidden": False}

    def commit(self, post):
        """Store a post whose payment settled."""
        with self.lock:
            self._put(post)
            if self.held.get(post["author"], 0) > 1:
                self.held[post["author"]] -= 1
            else:
                self.held.pop(post["author"], None)
            self._append(post)

    def hide(self, pid):
        with self.lock:
            p = self.by_id.get(pid)
            if p is None:
                return False
            if not p["hidden"]:
                p = dict(p, hidden=True)
                self._put(p)
                self._append(p)
            return True

    # reading ----------------------------------------------------------------------------------
    def waiting(self, pid):
        """True while a record of this post has not reached the repository."""
        with self.lock:
            return any(_key(l)[0] == pid for _, l in self.pending if _key(l))

    def exists(self, pid):
        with self.lock:
            p = self.by_id.get(pid)
            return p is not None and not p["hidden"]

    def page(self, about=None, page=1, per=PAGE):
        with self.lock:
            xs = [self.by_id[i] for i in reversed(self.order) if not self.by_id[i]["hidden"]
                  and (about is None or self.by_id[i]["about"] == about)]
        start = (page - 1) * per
        return [public(p) for p in xs[start:start + per]], len(xs), start + per < len(xs)

    def one(self, pid):
        with self.lock:
            p = self.by_id.get(pid)
            if p is None or p["hidden"]:
                return None
            replies = [public(self.by_id[i]) for i in self.order
                       if self.by_id[i]["reply_to"] == pid and not self.by_id[i]["hidden"]]
        return {"post": public(p), "replies": replies}

    def counts(self):
        with self.lock:
            xs = list(self.by_id.values())
        day = stamp(self.clock())[:10]
        shown = [p for p in xs if not p["hidden"]]
        return {"stored": len(xs), "shown": len(shown), "hidden": len(xs) - len(shown),
                "today": sum(1 for p in xs if p["time"][:10] == day),
                "paid_it": {"true": sum(1 for p in shown if p["paid_it"] is True),
                            "false": sum(1 for p in shown if p["paid_it"] is False),
                            "null": sum(1 for p in shown if p["paid_it"] is None)},
                "waiting_to_commit": len(self.pending)}


# --- GitHub ----------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect)


def http(method, url, headers=None, body=None, limit=MAX_DAY_FILE, timeout=30):
    """(status, bytes). https only, no redirect, a size cap. Never raises with a header in
    its message: the caller sees a status, or 0 when nothing came back."""
    if urllib.parse.urlparse(url).scheme != "https":
        return 0, b""
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            data = r.read(limit + 1)
            return (r.status, data) if len(data) <= limit else (0, b"")
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


class GitHub:
    """Reads the last days back at start; commits new records to the data branch.
    `http` stands in for the network in tests.

    A day is one or more files: posts-<date>.jsonl, then posts-<date>-2.jsonl, -3 … Each part
    is kept under MAX_CONTENTS, so the contents API always hands a part back inline and a line
    already in it can always be seen before it is written again."""

    def __init__(self, repo, token=None, http=http, branch=BRANCH, days=LOAD_DAYS):
        if not REPO_SHAPE.match(repo or ""):
            raise ValueError("POSTS_REPO must look like owner/name")
        self.repo, self.branch, self.days, self.http = repo, branch, days, http
        self._token = token or None
        self.last = None
        self.loaded = None                    # set by load(): None means nothing was read back
        self.window_start = None              # the oldest UTC day load() read
        self._commit = threading.Lock()       # one commit at a time: two at once would race on a sha

    def __repr__(self):                                   # never the token
        return "GitHub(%s, %s, commits %s)" % (self.repo, self.branch, "on" if self._token else "off")

    @property
    def commits(self):
        return bool(self._token)

    @staticmethod
    def part_path(day, n=1):
        path = "posts/posts-%s.jsonl" % day if n == 1 else "posts/posts-%s-%d.jsonl" % (day, n)
        assert DAY_FILE.match(path)                       # nothing else in the repository is written
        return path

    def raw_url(self, day, n=1):
        return "https://raw.githubusercontent.com/%s/%s/%s" % (self.repo, self.branch, self.part_path(day, n))

    def _raw_day(self, day):
        """Every part of one day from raw.githubusercontent.com: (texts, complete). complete is
        False when a part could not be read for a reason other than its absence."""
        texts = []
        for n in range(1, MAX_PARTS + 1):
            status, data = self.http("GET", self.raw_url(day, n), {"User-Agent": "ausrine-atlas-posts/1.0"}, None)
            if status == 404:
                return texts, True
            if status != 200:
                return texts, False
            texts.append(data.decode("utf-8", "replace"))
        return texts, True

    def load(self, store, today=None):
        """The last `days` UTC days of posts, oldest first. Returns (files read, records)."""
        today = today or now_utc().date()
        files = recs = 0
        self.loaded = set()                   # (id, hidden) of every record the repository holds
        self.window_start = (today - timedelta(days=self.days - 1)).isoformat()
        for k in range(self.days - 1, -1, -1):
            texts, _ = self._raw_day((today - timedelta(days=k)).isoformat())
            for t in texts:
                files += 1
                recs += store.load_lines(t.splitlines(), seen=self.loaded)
        return files, recs

    def prune_older(self, store, most=MAX_OLD_DAYS):
        """Queued lines from days older than the window load() read are checked against their own
        day's files, and dropped when the repository already holds them. A day that cannot be
        read keeps its lines queued (flush() still never writes a line twice)."""
        if self.window_start is None:
            return 0
        with store.lock:
            old_days = sorted({d for d, _ in store.pending if d < self.window_start}, reverse=True)[:most]
        dropped = 0
        for day in old_days:
            texts, complete = self._raw_day(day)
            if not texts and not complete:
                continue
            held = set()
            for t in texts:
                for line in t.splitlines():
                    try:
                        r = json.loads(line)
                        held.add((r["id"], bool(r.get("hidden"))))
                    except (ValueError, KeyError, TypeError):
                        continue
            with store.lock:
                keep = []
                for d, l in store.pending:
                    if d == day and _key(l) in held:
                        dropped += 1
                        continue
                    keep.append((d, l))
                store.pending = keep
        return dropped

    def _api(self, method, path, body=None):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ausrine-atlas-posts/1.0",
                   "X-GitHub-Api-Version": "2022-11-28", "Authorization": "Bearer " + self._token}
        if body is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(body).encode()
        return self.http(method, "https://api.github.com/repos/%s/contents/%s" % (self.repo, path), headers, body)

    def _fail(self, day, error, status=None):
        self.last = {"ok": False, "day": day, "error": error}
        if status is not None:
            self.last["status"] = status
        return self.last

    def flush(self, store, day=None):
        """One commit: the waiting lines of one UTC day (the newest waiting day unless `day` is
        given), appended to that day's newest part, or to a new part when it would pass
        MAX_CONTENTS. Returns a short status; never the token."""
        if not self._token:
            return None
        with self._commit:
            with store.lock:
                if not store.pending:
                    return None
                day = day or max(d for d, _ in store.pending)
                lines = [l for d, l in store.pending if d == day]
            if not lines:
                return None
            have, last = set(), None
            for k in range(1, MAX_PARTS + 1):                # walk every part: the last one is written to
                status, data = self._api("GET", self.part_path(day, k) + "?ref=" + self.branch)
                if status == 404:
                    break
                if status != 200:
                    return self._fail(day, "read_failed", status)
                try:
                    meta = json.loads(data)
                    if meta.get("encoding") != "base64":
                        raise ValueError("not inline")
                    last = (k, meta["sha"], base64.b64decode(meta.get("content") or ""))
                except (ValueError, KeyError, TypeError):
                    return self._fail(day, "unreadable_contents")
                have.update(last[2].decode("utf-8", "replace").splitlines())
            n, sha, old = last or (1, None, b"")
            fresh = [l for l in lines if l not in have]    # a requeued line already committed is not written twice
            if old and not old.endswith(b"\n"):
                old += b"\n"
            room = MAX_CONTENTS - len(old)
            batch, size = [], 0
            for l in fresh:
                b = len(l.encode("utf-8")) + 1
                if size + b > room and (batch or old):
                    break
                batch.append(l)
                size += b
            if fresh and not batch:                         # this part is full: open the next one
                n, sha, old = n + 1, None, b""
                if n > MAX_PARTS:
                    return self._fail(day, "day_full")
                for l in fresh:
                    b = len(l.encode("utf-8")) + 1
                    if batch and size + b > MAX_CONTENTS:
                        break
                    batch.append(l)
                    size += b
            if batch:
                path = self.part_path(day, n)
                body = {"message": "posts: %d new on %s" % (len(batch), day), "branch": self.branch,
                        "content": base64.b64encode(old + ("\n".join(batch) + "\n").encode("utf-8")).decode()}
                if sha:
                    body["sha"] = sha                      # a file that moved since is a 409, never overwritten
                status, _ = self._api("PUT", path, body)
                if status not in (200, 201):
                    return self._fail(day, "write_failed", status)
            done = set(l for l in lines if l in have) | set(batch)
            with store.lock:
                store.pending = [(d, l) for d, l in store.pending if not (d == day and l in done)]
            self.last = {"ok": True, "day": day, "records": len(batch), "part": n, "at": stamp(now_utc())}
            return self.last

    def drain(self, store, rounds=20):
        """Flush until nothing waits, a round fails, or `rounds` run out (at shutdown)."""
        r = None
        for _ in range(rounds):
            r = self.flush(store)
            if r is None or not r.get("ok"):
                break
        return r


def _key(line):
    try:
        r = json.loads(line)
        return (r["id"], bool(r.get("hidden")))
    except (ValueError, KeyError, TypeError):
        return None


def from_env(env, http=http):
    """(GitHub or None, a one-line description for /health). The token is read here, once."""
    repo = env.get("POSTS_REPO") or None
    token = env.get("POSTS_GITHUB_TOKEN") or None
    if not repo:
        return None, "memory only: posts live in this process and its local file (POSTS_REPO is not set)"
    gh = GitHub(repo, token, http=http)
    if not token:
        return gh, "memory only: posts are read back from %s but not committed (POSTS_GITHUB_TOKEN is not set)" % repo
    return gh, "each paid post committed before it is answered to %s, branch %s, posts/" % (repo, BRANCH)


def admin_ok(given, env):
    """True only when ATLAS_ADMIN_TOKEN is set and the header equals it. Constant time: both
    sides are hashed to the same length first, then compared with hmac.compare_digest."""
    want = env.get("ATLAS_ADMIN_TOKEN") or ""
    if not want or not given:
        return False
    return hmac.compare_digest(hashlib.sha256(given.encode("utf-8", "replace")).digest(),
                               hashlib.sha256(want.encode("utf-8")).digest())


def cors(origin):
    """Headers for a free read: the origin echoed only when it is one of the two."""
    h = {"vary": "Origin"}
    if origin in ORIGINS:
        h.update({"access-control-allow-origin": origin, "access-control-allow-methods": "GET",
                  "access-control-max-age": "600"})
    return h


# --- the feed, as HTML -------------------------------------------------------------------------

AMBER = "#8A6417"        # text-safe amber for wallets (design/DESIGN.md)
EMERALD = "#0B7A55"


def short(wallet):
    return wallet[:6] + "…" + wallet[-4:]


def feed_block(posts, site=""):
    """An HTML fragment: one article per post, newest first as given. The author wallet is
    shortened, in amber, linking to its buyer page; "paid it" in emerald when paid_it is true;
    the time; the text escaped. Every piece of a post is escaped; nothing is trusted."""
    e = buyer_pages.esc
    out = ['<section class="atlas-posts">']
    if not posts:
        out.append('<p class="atlas-posts-empty">No posts yet.</p>')
    for p in posts:
        w = p.get("author") or ""
        mark = ('<span class="atlas-post-paid" style="color:%s">paid it</span>' % EMERALD
                if p.get("paid_it") is True else "")
        out.append(
            '<article class="atlas-post" id="%s">'
            '<header><a class="atlas-post-author" style="color:%s" href="%s">%s</a>%s'
            '<time datetime="%s">%s</time></header>'
            '<p class="atlas-post-text" style="white-space:pre-wrap">%s</p></article>'
            % (e(p.get("id")), AMBER, e(buyer_pages.link(w, site)), e(short(w)), mark,
               e(p.get("time")), e((p.get("time") or "").replace("T", " ").rstrip("Z")), e(p.get("text"))))
    out.append("</section>")
    return "".join(out)


def feed_script(seller, about, target_id="atlas-posts", site=""):
    """A small inline script that fetches /posts?about=<kind>:<id> from the seller and renders
    it into the element with id `target_id`, the same way feed_block does. It builds the DOM
    with textContent and setAttribute only: no markup from a post is ever parsed."""
    cfg = json.dumps({"url": "%s%s?about=%s" % (seller.rstrip("/"), PATH, urllib.parse.quote(about, safe=":")),
                      "el": target_id, "site": site.rstrip("/"), "amber": AMBER, "emerald": EMERALD})
    cfg = cfg.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return """<script>
(function(c){
  var box=document.getElementById(c.el); if(!box) return;
  fetch(c.url,{headers:{accept:"application/json"}}).then(function(r){return r.ok?r.json():null}).then(function(d){
    if(!d||!d.posts) return;
    box.textContent="";
    if(!d.posts.length){var e=document.createElement("p");e.className="atlas-posts-empty";e.textContent="No posts yet.";box.appendChild(e);return;}
    d.posts.forEach(function(p){
      var w=String(p.author||""), a=document.createElement("article"), h=document.createElement("header");
      a.className="atlas-post";
      var l=document.createElement("a"); l.className="atlas-post-author"; l.style.color=c.amber;
      l.setAttribute("href",c.site+"/b/"+w.toLowerCase().replace(/[^a-z0-9._-]/g,"-")+"/");
      l.textContent=w.slice(0,6)+"\\u2026"+w.slice(-4); h.appendChild(l);
      if(p.paid_it===true){var m=document.createElement("span");m.className="atlas-post-paid";m.style.color=c.emerald;m.textContent="paid it";h.appendChild(m);}
      var t=document.createElement("time"); t.setAttribute("datetime",String(p.time||"")); t.textContent=String(p.time||"").replace("T"," ").replace(/Z$/,""); h.appendChild(t);
      var x=document.createElement("p"); x.className="atlas-post-text"; x.style.whiteSpace="pre-wrap"; x.textContent=String(p.text||"");
      a.appendChild(h); a.appendChild(x); box.appendChild(a);
    });
  }).catch(function(){});
})(%s);
</script>""" % cfg


def default_path():
    return os.environ.get("POSTS_FILE") or os.path.join(tempfile.gettempdir(), "atlas-posts.jsonl")
