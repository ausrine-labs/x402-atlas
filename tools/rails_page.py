#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit abfcd4a). Edit it there, not here.
"""rails_page.py — /rails/: where AI agents pay, which rails we can read, and what changed.

    rails_page.py --out _site [--data rails.json] [--flows-dir flows]

Agent payments run on several rails. Some settle on a public chain, where the Atlas reads
every payment; others settle inside card networks and payment companies, where nobody
outside can. This page puts each rail in one of three zones (on a public chain, both,
inside networks and companies), says whether the Atlas reads it, shows the latest figure
each rail publishes about itself (dated, linked, marked as its own claim).

The rails and their claims are in rails.json, kept by hand: each week, with the market
brief, a dated line goes into a rail's changes (our own record; the page does not show it),
and a figure changes only with the page it came from. The Atlas's own numbers are not typed in: they are counted from the daily flow
files with the brief's own rules (brief.build), over the newest seven Base days held, with
the largest single payment named whenever it is more than half of a total.

Standard library only. A wallet is not a person; nothing here says who holds one.
"""

import argparse
import datetime
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import atlas_style  # noqa: E402
import brief  # noqa: E402
import coverage_page as cp  # noqa: E402

DATA = os.path.join(HERE, "rails.json")
DAYS = 7
SETTLES = {"chain": "On a public chain", "mixed": "Both", "off_chain": "Inside card networks and companies"}
SETTLES_SHORT = {"chain": "On-chain", "mixed": "Mixed", "off_chain": "Off-chain"}
SEE = {"daily": ("Read daily", "see-yes"),
       "windows": ("Read in 6-hour windows", "see-yes"),
       "not_yet": ("Public, not read", "see-not-yet"),
       "no": ("Not visible", "see-no")}
DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
BANNED = re.compile("verif", re.I)            # the Atlas never says it (design_test, free_tier_test)
FIGURE_MAX = 12                               # a figure is a few characters; its label says what it counts
BY_MAX = 40                                   # who runs the rail, in a few words


def esc(x):
    return cp.esc(x)


def _date_ok(d):
    """A real calendar date, 'YYYY-MM-DD', or a real month, 'YYYY-MM'."""
    d = str(d or "")
    if not DATE.match(d):
        return False
    try:
        datetime.date.fromisoformat(d if len(d) == 10 else d + "-01")
    except ValueError:
        return False
    return True


def when(d):
    """'2026-10-15' -> '15 Oct 2026'; '2026-02' -> 'Feb 2026'."""
    if len(d) == 7:
        return "%s %s" % (atlas_style.MONTHS[int(d[5:7]) - 1][:3], d[:4])
    return atlas_style.short_date(d)


def load(path=DATA):
    """The rails, checked: every rail has its zone, its mark, what the Atlas sees of it, and a dated claim
    with an https source; no text uses the word the Atlas never uses. A bad file stops the page with a
    ValueError, never a guess."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    if BANNED.search(raw):
        raise ValueError("rails.json uses a word the Atlas never uses")
    d = json.loads(raw)
    rails = d.get("rails") if isinstance(d, dict) else None
    if not isinstance(rails, list) or not rails:
        raise ValueError("rails.json has no rails")
    seen = set()
    for r in rails:
        if not isinstance(r, dict):
            raise ValueError("a rail is not an object")
        for k in ("id", "name", "by", "kind", "who", "moves", "settles", "we_see", "claim", "changes"):
            if k not in r:
                raise ValueError("rail %r has no %s" % (r.get("id"), k))
        if r["id"] in seen:
            raise ValueError("rail %r twice" % r["id"])
        seen.add(r["id"])
        if not isinstance(r["by"], str) or not 0 < len(r["by"]) <= BY_MAX:
            raise ValueError("rail %r: by is who runs it, 1 to %d characters" % (r["id"], BY_MAX))
        if r["settles"] not in SETTLES or r["we_see"] not in SEE:
            raise ValueError("rail %r: settles %r, we_see %r" % (r["id"], r["settles"], r["we_see"]))
        if r["we_see"] in ("daily", "windows") and r["settles"] != "chain":
            raise ValueError("rail %r: the Atlas can only read a public chain" % r["id"])
        c = r["claim"]
        if not isinstance(c, dict) or not str(c.get("source", "")).startswith("https://") or not _date_ok(c.get("date")) \
                or not c.get("text") or not isinstance(c.get("self_reported"), bool):
            raise ValueError("rail %r: a claim needs text, a date, an https source and self_reported" % r["id"])
        if "figure" in c and (not isinstance(c["figure"], str) or not 0 < len(c["figure"]) <= FIGURE_MAX
                              or not c.get("figure_label")):
            raise ValueError("rail %r: a figure is 1 to %d characters, with a label" % (r["id"], FIGURE_MAX))
        if not isinstance(r["changes"], list):
            raise ValueError("rail %r: changes is a list" % r["id"])
        for ch in r["changes"]:
            if not isinstance(ch, dict) or not _date_ok(ch.get("date")) or not ch.get("text"):
                raise ValueError("rail %r: a change needs a date and a text" % r["id"])
    return rails


def window(flows_dir, days=DAYS):
    """The newest `days` Base days held in flows_dir: (first, last), or None."""
    held = sorted(os.path.basename(p)[6:16] for p in glob.glob(os.path.join(flows_dir, "flows-????-??-??.json")))
    if not held:
        return None
    last = datetime.date.fromisoformat(held[-1])
    first = max(datetime.date.fromisoformat(held[0]), last - datetime.timedelta(days=days - 1))
    return first.isoformat(), last.isoformat()


def measured(flows_dir):
    """What the Atlas counted itself, with the brief's rules: Base x402 money to listed sellers over the
    newest seven days, and Solana money the known processors settled on the days read. None without files."""
    if not flows_dir or not os.path.isdir(flows_dir):
        return None
    w = window(flows_dir)
    if not w:
        return None
    b = brief.build(flows_dir, w[0], w[1])
    days = sorted(b["window"]["days"])            # the days whose files the brief could read, not the file names
    if not days:
        return None
    missing = [d for d in b["window"]["days_missing"] if days[0] < d < days[-1]]
    base = b["money"]["total"]
    sol = b.get("solana")
    return {"from": days[0], "to": days[-1], "days": len(days), "missing": missing,
            "base": {"usdc": base["usdc"], "payments": base["payments"], "sellers": base["sellers_paid"],
                     "largest": base["largest_edge"]},
            "solana": None if not sol else {"usdc": sol["total"]["usdc"], "payments": sol["total"]["payments"],
                                            "days": len(sol["days"]), "largest": sol["total"]["largest_edge"]}}


def money(x):
    return "${:,.0f}".format(x) if x >= 100 else "${:,.2f}".format(x)


def _largest_line(t):
    le = t.get("largest")
    if le and le.get("over_half"):
        return (' One payment was %s%% of it; without it, %s.'
                % (esc(le["share_pct"]), esc(money(le["usdc_without_it"]))))
    return ""


def _span(m):
    """'8 to 14 Oct 2026', or across months '28 Sep to 4 Oct 2026'."""
    a, b = datetime.date.fromisoformat(m["from"]), datetime.date.fromisoformat(m["to"])
    if a == b:
        return when(m["to"])
    first = "%d" % a.day if (a.year, a.month) == (b.year, b.month) else when(m["from"])[:-5]
    return "%s to %s" % (first, when(m["to"]))


def _short(d):
    """'2026-10-15' -> '15 Oct'; a month stays 'Feb 2026'."""
    return when(d) if len(d) == 7 else when(d)[:-5]


def stats(m, rails):
    """One strip of figures: what the Atlas counted on Base last week, and how many rails it can read."""
    read = sum(1 for r in rails if SEE[r["we_see"]][1] == "see-yes")
    cells = []
    if m:
        b, s = m["base"], m["solana"]
        cells += [('<b class="acc">%s</b>' % esc(money(b["usdc"])), "x402 on Base, %s" % _span(m)),
                  ("<b>%s</b>" % esc("{:,}".format(b["payments"])), "payments"),
                  ("<b>%s</b>" % esc("{:,}".format(b["sellers"])), "sellers paid")]
        if s:
            cells.append(("<b>%s</b>" % esc(money(s["usdc"])), "x402 on Solana, %d days read" % s["days"]))
    cells.append(("<b>%d<small>/%d</small></b>" % (read, len(rails)), "rails the Atlas reads"))
    out = ['<dl class="rkpi">'] + ['<div><dt>%s</dt><dd>%s</dd></div>' % (esc(label), v) for v, label in cells] + ['</dl>']
    if m:
        out.append('<p class="rnote">Counted by the Atlas from the chain: every payment to sellers listed in Coinbase\'s '
                   'registry, over %d days.%s%s%s</p>'
                   % (m["days"], (" No file could be read for %s: not counted." % esc(", ".join(when(d) for d in m["missing"])))
                      if m.get("missing") else "",
                      _largest_line(b), (" On Solana:" + _largest_line(s)) if s and _largest_line(s) else ""))
    else:
        out.append('<p class="rnote">The Atlas\'s own counts appear here when the daily files are read.</p>')
    return "".join(out)


def bar(rails):
    """How much of the market can be seen: one segment per rail, read / public / not visible."""
    order = {"see-yes": 0, "see-not-yet": 1, "see-no": 2}
    seg = sorted(rails, key=lambda r: order[SEE[r["we_see"]][1]])
    n = {k: sum(1 for r in rails if SEE[r["we_see"]][1] == k) for k in order}
    return ('<div class="rbar" role="img" aria-label="%d rails read by the Atlas, %d public but not read, %d not visible">%s</div>'
            '<p class="rkey"><span><i class="see-yes"></i>Read by the Atlas <b>%d</b></span>'
            '<span><i class="see-not-yet"></i>Public, not read yet <b>%d</b></span>'
            '<span><i class="see-no"></i>Not visible from outside <b>%d</b></span></p>'
            % (n["see-yes"], n["see-not-yet"], n["see-no"],
               "".join('<span class="%s" title="%s"></span>' % (SEE[r["we_see"]][1], esc(r["name"])) for r in seg),
               n["see-yes"], n["see-not-yet"], n["see-no"]))


def table(rails):
    """Every rail, one line each, grouped by where its payments settle."""
    out = ['<div class="rscroll"><table class="rtab"><thead><tr><th>Rail</th><th class="rk">Type</th><th>Atlas</th>'
           '<th class="num">Latest figure</th><th class="rd">As of</th></tr></thead>']
    for z in ("chain", "mixed", "off_chain"):
        group = [r for r in rails if r["settles"] == z]
        if not group:
            continue
        out.append('<tbody><tr class="grp"><th colspan="5">%s <span>%d</span></th></tr>' % (esc(SETTLES[z]), len(group)))
        for r in group:
            c = r["claim"]
            label, cls = SEE[r["we_see"]]
            fig = ('<b>%s</b><span>%s</span>' % (esc(c["figure"]), esc(c["figure_label"])) if c.get("figure")
                   else '<b class="rnone">&mdash;</b><span>no figures published</span>')
            out.append('<tr><td><b>%s</b><span>%s</span></td><td class="rk">%s</td>'
                       '<td><span class="rst %s"><i></i>%s</span></td><td class="num rfig">%s</td>'
                       '<td class="rd"><a href="%s" rel="nofollow noopener">%s</a><span>%s</span></td></tr>'
                       % (esc(r["name"]), esc(r["by"]), esc(r["kind"][:1].upper() + r["kind"][1:]), cls, esc(label), fig,
                          esc(c["source"]), esc(when(c["date"])),
                          "self-reported" if c["self_reported"] else "third party"))
        out.append('</tbody>')
    out.append('</table></div>')
    return "".join(out)


def body(rails, m):
    return ('<div class="rails"><p class="rkick">Payment rails &middot; updated weekly</p><h1>Where AI agents pay</h1>'
            '<p class="rlede">Some rails settle on a public chain, where we read every payment. Others settle inside card '
            'networks and payment companies, where nobody outside can count them.</p>'
            + stats(m, rails)
            + '<h2 class="rhead">Visibility</h2>' + bar(rails)
            + '<h2 class="rhead">All rails</h2>' + table(rails)
            + '<h2 class="rhead">Method</h2><p class="rread">We read only public chains, every morning. For a rail that '
            'settles inside a card network or a payment company, we show what has been published about it, dated and '
            'linked, and say whose figure it is. Figures from different rails count different things over different '
            'periods: they are not one market added up.</p></div>')


def build(out, data=DATA, flows_dir=None, site="", free=None):
    rails = load(data)
    m = measured(flows_dir)
    as_of = (m or {}).get("to") or datetime.date.today().isoformat()
    html_text = cp.page("Where AI agents pay", body(rails, m), as_of,
                        "The rails AI agents pay on: which settle on a public chain we read, which can't be seen, and what each publishes.",
                        room="rails", root=site.rstrip("/"), free=free)
    if BANNED.search(html_text):
        raise ValueError("the page would use a word the Atlas never uses")
    cp.write(out, "rails", html_text)
    return {"rails": len(rails), "measured": m}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--flows-dir", default=None, help="the daily flow files (flows-<date>.json, flows-sol-<date>.json)")
    ap.add_argument("--site", default="", help="where the Atlas is served, for links (default: relative to the root)")
    a = ap.parse_args()
    r = build(a.out, a.data, a.flows_dir, a.site)
    print("rails: %d rails, measured %s" % (r["rails"], "yes" if r["measured"] else "no"))


if __name__ == "__main__":
    main()
