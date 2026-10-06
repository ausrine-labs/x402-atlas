#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit f04f064). Edit it there, not here.
"""coverage_page.py — the small shared parts of the four coverage pages.

/live/, /where/, /leaders/ and /prices/ each expose a body function (data in, an
HTML fragment out) so the restyled site shell can adopt them, and a writer that
wraps the fragment in the house shell (atlas_style: the shared stylesheet, header,
footer and nav), white paper, sellers emerald, wallets amber, as design/DESIGN.md
says. It loads no script from anywhere.

Also here: the words the Atlas never uses, and how a host that contains one is
shown instead. Standard library only.
"""

import html
import math
import os
import re
import tempfile
import urllib.parse

import market  # the product's name
import tiers  # the free tier's switch, TOP and locked line

# The Atlas never says this word in any form (map_page.py keeps the same rule). A host
# that contains it is shown by its shortened wallet and gets no link.
BANNED = re.compile(r"verif", re.I)
# Other companies' own terms. Plain words only, on every page (Vilija, 2026-09-27).
OTHERS_TERMS = re.compile(r"\b(cosign\w*|karma|submolts?|picks|scouts)\b", re.I)

# The coverage bodies' own classes (seller, wallet, num, notice, charts) are styled in the one
# house stylesheet, scoped under .cov; this page carries no style of its own.


def esc(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def slug(x):
    """The same rule seller_pages.slug and buyer_pages.slug keep."""
    return re.sub(r"[^a-z0-9._-]", "-", str(x).lower())[:200]


def short(w):
    return w[:6] + "…" + w[-4:] if len(w) > 14 else w


def money(x):
    x = x or 0.0
    if x >= 100:
        return "$%s" % "{:,.0f}".format(x)
    if x >= 0.01 or x == 0:
        return "$%s" % "{:,.2f}".format(x)
    return "$%s" % ("%.6f" % x).rstrip("0")


def num(n, one, many=None):
    return "%s %s" % ("{:,}".format(n), one if n == 1 else (many or one + "s"))


def seller_html(host, site="", wallet=""):
    """A seller's name in emerald, linking to its Atlas page. A host holding a banned
    word is shown as its shortened wallet, unlinked."""
    if BANNED.search(host or ""):
        return '<span class="seller">%s</span>' % esc(short(wallet) if wallet else "a seller")
    return '<span class="seller"><a href="%s/s/%s/">%s</a></span>' % (esc(site), esc(slug(host)), esc(host))


def wallet_html(wallet, site="", has_page=False):
    """A wallet, shortened, in amber; a link to its buyer page when there is one."""
    if has_page:
        return '<span class="wallet addr"><a href="%s/b/%s/" title="%s">%s</a></span>' % (
            esc(site), esc(slug(wallet)), esc(wallet), esc(short(wallet)))
    return '<span class="wallet addr" title="%s">%s</span>' % (esc(wallet), esc(short(wallet)))


def percentile(values, p):
    """The p-th percentile (0..100) by linear interpolation between closest ranks — the
    usual spreadsheet and numpy default. None for no values."""
    xs = sorted(values)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return xs[int(k)]
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def classified_chains(rollup):
    """The chains whose pull told x402-settled payments apart from other transfers. A rollup
    can mix them: Base split, Solana not. Newer rollups say so (classified_chains); for an
    older one, a chain counts when anything on it carries an x402 payment, or when the rollup
    is classified and covers one chain only."""
    r = rollup or {}
    if isinstance(r.get("classified_chains"), list):
        return set(r["classified_chains"])
    if not r.get("classified"):
        return set()
    sellers, buyers = r.get("sellers") or [], r.get("buyers") or []
    chains = {x.get("chain", "Base") for x in sellers + buyers}
    if len(chains) <= 1:
        return chains or {"Base"}
    return ({x.get("chain", "Base") for x in sellers if x.get("on_chain_payments_x402")} |
            {x.get("chain", "Base") for x in buyers if x.get("payments_x402")})


def split(row, classified):
    """Whether this seller's or buyer's figures are x402-settled: its own chain decides.
    `classified` is classified_chains()' set (or a plain bool, for one-chain callers)."""
    if isinstance(classified, (set, frozenset, list, tuple)):
        return row.get("chain", "Base") in classified
    return bool(classified)


def paid_by_chain(s, classified):
    """{chain: (usdc, payments)} for one rollup seller. A host paid on two chains carries
    each chain's figures apart (by_chain); each counts x402-settled payments where its own
    pull told them apart and every transfer where it did not. A row without by_chain (an
    older rollup) is one chain, its own."""
    rows = s.get("by_chain")
    if not isinstance(rows, dict) or not rows:
        rows = {s.get("chain", "Base"): {"usdc": s.get("on_chain_usdc"), "payments": s.get("on_chain_payments"),
                                         "usdc_x402": s.get("on_chain_usdc_x402"),
                                         "payments_x402": s.get("on_chain_payments_x402")}}
    out = {}
    for chain, v in rows.items():
        if split({"chain": chain}, classified):
            out[chain] = (v.get("usdc_x402") or 0.0, v.get("payments_x402") or 0)
        else:
            out[chain] = (v.get("usdc") or 0.0, v.get("payments") or 0)
    return out


def paid(s, classified):
    """A rollup seller's paid figures over every chain it was paid on, each chain by its own
    rule (paid_by_chain). Returns (usdc, payments)."""
    parts = paid_by_chain(s, classified).values()
    return round(sum(u for u, _ in parts), 6), sum(n for _, n in parts)


def chains_of(rollup):
    r = rollup or {}
    chains = {x.get("chain", "Base") for x in (r.get("sellers") or []) + (r.get("buyers") or [])}
    for s in r.get("sellers") or []:
        chains.update((s.get("by_chain") or {}).keys())
    return sorted(chains)


EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")


def evm(w):
    """An EVM address (0x and forty hex digits), lowercased; None for anything else,
    a Solana address among them."""
    return w.lower() if isinstance(w, str) and EVM.match(w) else None


def basis(classified, chains):
    """What a paid figure counts, in plain words, for the chains a page covers."""
    chains = list(chains) or ["Base"]
    yes = [c for c in chains if c in classified]
    no = [c for c in chains if c not in classified]
    if not no:
        return "x402-settled USDC"
    if not yes:
        return "USDC to seller wallets (the pull did not split out x402)"
    return "x402-settled USDC on %s; on %s, all USDC to seller wallets (that pull did not split out x402)" % (
        ", ".join(yes), ", ".join(no))


def site_path(site):
    """Links stay on the page's own origin: only the path of `site` is kept, so the same page
    works at the root of a domain and under /x402-atlas on another."""
    return urllib.parse.urlparse(site or "").path.rstrip("/")


def page(title, body, as_of, desc="", room="", root="", free=None):
    """A coverage page in the house shell (atlas_style): the shared stylesheet, header and footer.
    root is the site's path (site_path), so every link stays on the page's own origin; room is
    the page's folder, for its canonical address; free the tier (tiers.py), for the footer's line."""
    import atlas_style
    ctx = {"root": root, "css": root + "/atlas.css", "title": esc("%s · %s" % (title, market.BRAND)),
           "desc": esc(desc or title), "canon": esc("%s/%s/" % (root, room) if room else root + "/")}
    return (atlas_style.HEAD % ctx + '<main id="main"><div class="cov">' + body + "</div>"
            '<p class="muted asof">%s · %s · as of <span class="dated">%s</span></p></main>'
            % (esc(market.BRAND), esc(market.BRAND_WHAT), esc(as_of))
            + atlas_style.footer(root, esc(atlas_style.ISSUES), esc(as_of), free=bool(free)))


def top(data):
    """How many rows a table shows: every one the page was given, or tiers.TOP in the free tier."""
    return tiers.TOP if data.get("free") else None


def cut(rows, data):
    """(the rows shown, how many there were)."""
    n = top(data)
    return (rows[:n] if n else rows), len(rows)


def shown_line(shown, total, what):
    """Under a cut table: how many of how many are shown. Nothing when nothing was cut."""
    if total <= shown:
        return ""
    return '<p class="muted">The %d %s of %s are shown.</p>' % (shown, what, "{:,}".format(total))


def write(out, room, html_text, extra=None):
    """Write out/<room>/index.html (and any extra files beside it) atomically."""
    d = os.path.join(out, room)
    os.makedirs(d, exist_ok=True)
    files = dict(extra or {}, **{"index.html": html_text})
    for name, text in files.items():
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)                  # mkstemp makes it private; a page is for everyone to read
        os.replace(tmp, os.path.join(d, name))
    return os.path.join(d, "index.html")
