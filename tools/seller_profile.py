#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit f3ea797). Edit it there, not here.
"""seller_profile.py — a free profile for each seller on the Board: what kind of x402 seller it is, from its own chain
numbers, its top three priorities, and the service that fits. Advice first.

Vilija, 2026-10-17, from her trusted-advisor work with CIOs: diagnose first ("what kind of CIO are you"), then the
priorities that type has, and only then the services that fit. Here the diagnosis is read off the Board's week of x402
payments on Base, so it is free, recomputable and the same rule for every seller.

    <out>/profile/index.html            the five types, and every profiled seller by type
    <out>/profile/<slug>/index.html     one seller's profile

The types (checked in this order; the first that fits is the seller's):
  quiet          fewer than QUIET real customers in the week
  one big client one payer is most of the money
  router-fed     robots (wallets that pay 20 or more sellers) are at least half of all its buyers
  closed loop    at least 40% come back, but fewer than 10% pay any other seller: one app's users, or the operator's own
  regulars       at least 30% come back on another day, and at least 30% also pay other sellers
  tries          fewer than 20% come back
  mixed          none of the above
A wallet is not a person: nothing here says who holds or runs one. Standard library only.
"""

import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board  # noqa: E402
import coverage_page as cp  # noqa: E402

QUIET = 5
SQUARE = "/square/teams/pre-pay-check/"

TYPES = {
    "quiet": ("Quiet", "Few buyers yet.",
              ["Be found: list the route in the registries agents read, with a clear description.",
               "Check the 402 offer: price, network and payTo as a buyer's agent will read them.",
               "Price against sellers like you: the Atlas shows what similar routes charge."],
              "Launch audit ($50)"),
    "one big client": ("One big client", "One payer is most of the money.",
                       ["Find more buyers, so one customer leaving is not the end of the business.",
                        "Show it is a real customer: routers and investors will ask whether it is you.",
                        "Learn what that client values, and offer it to others like it."],
                       "Demand proof report ($150)"),
    "router-fed": ("Fed by routers", "Most buyers are robots that pay many sellers: routers and aggregators.",
                   ["Prove delivery, because a router keeps sending only to sellers that answer well.",
                    "Win direct buyers who come for you, not only through a router.",
                    "Watch the router's share: one routing change can halve the traffic."],
                   "Launch audit and delivery checks ($50)"),
    "closed loop": ("Closed loop", "Buyers come back often, but almost none pay any other seller.",
                    ["Show who the buyers are: an app built on you, or your own traffic? Routers and investors will ask.",
                     "Open the door to outside buyers: list where agents look, and price for a first try.",
                     "Separate test and staging traffic from paid demand, so your numbers mean what they say."],
                    "Demand proof report ($150)"),
    "regulars": ("Real regulars", "Independent buyers who come back.",
                 ["Prove it: a graded report that the buyers are real helps with routers and investors.",
                  "Grow from the regulars: what they buy again is what to sell more of.",
                  "Keep the record clean, so due diligence finds what you say it will."],
                 "Demand proof report ($150)"),
    "tries": ("Many tries, few return", "Lots of first payments, few second ones.",
              ["Find out why buyers do not come back: test what a paid call actually returns.",
               "Fix the first experience: errors, slow answers, an offer that differs from the listing.",
               "Ask the few who returned what made them stay."],
              "Delivery test and launch audit ($50)"),
    "mixed": ("Mixed", "Some regulars, some tries, no single pattern yet.",
              ["Find which buyers return and what they buy, and build on that.",
               "Check delivery, so first-time buyers become second-time buyers.",
               "Show the real part of the demand clearly."],
              "Pre-pay check ($20)"),
}


def kind(r):
    """The seller's type, from its Board row."""
    c = r.get("customers") or 0
    if c < QUIET:
        return "quiet"
    if r.get("one_payer_most"):
        return "one big client"
    robots = r.get("robot_payers") or 0                # the Board counts robots apart from its customers
    if robots * 2 >= c + robots:
        return "router-fed"
    ret, ind = (r.get("returning") or 0) / c, (r.get("independent") or 0) / c
    if ret >= 0.4 and ind < 0.1:
        return "closed loop"
    if ret >= 0.3 and ind >= 0.3:
        return "regulars"
    if ret < 0.2:
        return "tries"
    return "mixed"


def why(r):
    """The numbers behind the type, in one sentence."""
    c = r.get("customers") or 0
    parts = ["%d paying customers this week" % c]
    if c:
        parts.append("%d came back on another day" % (r.get("returning") or 0))
        parts.append("%d also paid other sellers" % (r.get("independent") or 0))
        if r.get("robot_payers"):
            parts.append("%d are robots that pay many sellers" % r["robot_payers"])
    if r.get("top_payer_share_pct") is not None:
        parts.append("the biggest payer paid %g%% of the money" % r["top_payer_share_pct"])
    return "; ".join(parts) + "."


def profile(r):
    k = kind(r)
    name, short, priorities, offer = TYPES[k]
    return {"host": r["host"], "slug": board.slug(r["host"]), "kind": k, "type": name, "short": short, "why": why(r),
            "priorities": priorities, "offer": offer}


def seller_page(p, window, as_of, root, free):
    body = ('<span class="eyebrow"><a href="%s/profile/">Seller profiles</a></span><h1>%s</h1>'
            '<p class="oneline">%s: %s</p><p>%s</p>'
            '<h2>Its top three priorities</h2><ol>%s</ol>'
            '<h2>Where we could help</h2><p>%s, by the Pre-pay check team on Infoharmoni Square: every part graded by a member '
            'who did not do it, under the Square\'s <a href="%s/square/constitution/">constitution</a>. '
            '<a href="%s%s">Hire the team</a>, or ask a question first. The profile is free either way.</p>'
            '<p class="muted fine">Read from x402 payments on Base, %s to %s, by the same rule for every seller. A wallet is not '
            'a person; nothing here says who holds or runs one. If this reads wrong, '
            '<a href="%s/square/rooms/#general">tell us</a>.</p>'
            % (cp.esc(root), cp.esc(p["host"]), cp.esc(p["type"]), cp.esc(p["short"]), cp.esc(p["why"]),
               "".join("<li>%s</li>" % cp.esc(x) for x in p["priorities"]), cp.esc(p["offer"]), cp.esc(root), cp.esc(root),
               SQUARE, cp.esc(window.get("from", "")), cp.esc(window.get("to", "")), cp.esc(root)))
    return cp.page("%s: seller profile" % p["host"], body, as_of, "What kind of x402 seller %s is, and its priorities." % p["host"],
                   room="profile/%s" % p["slug"], root=root, free=free)


def index_page(ps, window, as_of, root, free):
    rows = []
    for k, (name, short, _p, offer) in TYPES.items():
        mine = [p for p in ps if p["kind"] == k]
        rows.append('<h2>%s <span class="muted">(%d)</span></h2><p>%s Where we help: %s.</p><p>%s</p>'
                    % (cp.esc(name), len(mine), cp.esc(short), cp.esc(offer),
                       ", ".join('<a href="%s/profile/%s/">%s</a>' % (cp.esc(root), cp.esc(p["slug"]), cp.esc(p["host"]))
                                 for p in mine) or '<span class="muted">none this week</span>'))
    body = ('<h1>What kind of x402 seller are you?</h1><p class="oneline">A free profile for every seller on the Board: its type, '
            'read from its own payments, and the three things that matter most for that type.</p>%s'
            '<p class="muted fine">Week of %s to %s, x402 on Base. The rule for each type is in seller_profile.py, the same for '
            'every seller.</p>' % ("".join(rows), cp.esc(window.get("from", "")), cp.esc(window.get("to", ""))))
    return cp.page("Seller profiles", body, as_of, "What kind of x402 seller each Board seller is, and its priorities.",
                   room="profile", root=root, free=free)


def build(out, b, root="", free=None):
    """Write the profiles for the Board `b` (board.compute or board.build). Returns the profiles."""
    root = root.rstrip("/")
    window = b.get("window") or {}
    as_of = window.get("to") or ""
    ps, seen = [], set()
    for r in b.get("sellers") or []:
        host = str(r.get("host") or "")
        if not host or host.lower() == str(r.get("wallet") or "").lower() or re.fullmatch(r"0x[0-9a-fA-F]{40}", host):
            continue                                   # a bare wallet has no name to profile
        p = profile(r)
        if p["slug"] in seen or not p["slug"]:
            continue
        seen.add(p["slug"])
        ps.append(p)
        cp.write(out, "profile/%s" % p["slug"], seller_page(p, window, as_of, root, free))
    cp.write(out, "profile", index_page(ps, window, as_of, root, free))
    pdir = os.path.join(out, "profile")                # a seller gone from the Board loses its profile
    for name in os.listdir(pdir):
        p = os.path.join(pdir, name)
        if name not in seen and os.path.isdir(p) and not os.path.islink(p) and os.path.exists(os.path.join(p, "index.html")):
            shutil.rmtree(p)
    return ps
