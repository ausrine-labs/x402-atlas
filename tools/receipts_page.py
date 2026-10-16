#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit f23e999). Edit it there, not here.
"""receipts_page.py — /receipts/: what Infoharmoni Atlas has earned and paid, counted the way it counts everyone.

    receipts_page.py --out _site [--data receipts.json] [--flows-dir flows]

Vilija, 2026-10-16: a public receipts page, even with no sales yet. Money in is read from the day's flow files at our
seller addresses (receipts.json): each payer is sorted three ways, as tools/shop_ledger.py does: our own test wallet,
a robot (a wallet that paid 20 or more different sellers that day: it samples everyone), and everyone else, the only
ones who could be customers. Card sales and money out are listed by hand in receipts.json, each with its receipt.
Buyers and payees are named by role, never by name; running costs are not on the page. Standard library only.
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
import coverage_page as cp  # noqa: E402
import relationships  # noqa: E402

DATA = os.path.join(HERE, "receipts.json")
ROBOT = 20
EVM = re.compile(r"^0x[0-9a-f]{40}$")
TX = re.compile(r"^0x[0-9a-fA-F]{64}$")
SOL_SIG = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{64,90}$")      # a Solana transaction signature, base58
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXPLORER = {"Base": "https://basescan.org/tx/%s", "Solana": "https://solscan.io/tx/%s"}


def esc(x):
    return cp.esc(x)


def _amount(x):
    """A real amount of money: a finite number above zero, never a bool, NaN or infinity."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and 0 < x < float("inf")


def load(path=DATA):
    """receipts.json, checked; a bad file stops the page with a ValueError."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise ValueError("receipts.json is not an object")
    base = [str(a).lower() for a in (d.get("seller_addresses") or {}).get("base") or []]
    if not base or not all(EVM.match(a) for a in base):
        raise ValueError("receipts.json needs our Base seller addresses")
    sol = (d.get("seller_addresses") or {}).get("solana") or []
    if not all(isinstance(a, str) and re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", a) for a in sol):
        raise ValueError("Solana seller addresses must be base58 wallets")
    own = [str(a).lower() for a in d.get("own_test_wallets") or []]
    if not all(EVM.match(a) for a in own):
        raise ValueError("own_test_wallets must be Base addresses")
    for o in d.get("out") or []:
        if not (isinstance(o, dict) and DAY.match(str(o.get("date"))) and o.get("chain") in EXPLORER
                and (TX if o.get("chain") == "Base" else SOL_SIG).match(str(o.get("tx") or ""))
                and _amount(o.get("amount_usdc")) and o.get("to") and o.get("for")):
            raise ValueError("every payment out needs a date, chain, amount, to (a role), for and its tx")
    for s in d.get("card_sales") or []:
        if not (isinstance(s, dict) and DAY.match(str(s.get("date"))) and _amount(s.get("amount_usd"))
                and s.get("buyer") and s.get("what") and s.get("receipt")):
            raise ValueError("every card sale needs a date, amount, buyer (a role), what and its receipt")
    return {"base": set(base), "solana": set(sol), "own": set(own), "out": d.get("out") or [],
            "card_sales": d.get("card_sales") or [], "card_checked": str(d.get("card_sales_checked") or "")}


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and 0 <= x < float("inf")


def money_in(flows_dir, r, unread=None):
    """Per day read, payments into our seller addresses: {day: {"customers"|"robots"|"ours": [payments, usdc, payers]}};
    a day read with no payment to us is there, empty, so the page says which days were read."""
    out = {}
    for path in sorted(glob.glob(os.path.join(flows_dir or "", "flows-*.json"))):
        name = os.path.basename(path)
        sol = name.startswith("flows-sol-")
        day = name[10:20] if sol else name[6:16]
        if not DAY.match(day):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            # the same check every flow reader makes (relationships._day_problem), and a day short of 24 hours is partial
            why = (relationships._day_problem(d, day) if not sol else
                   None if isinstance(d, dict) and d.get("date") == day and isinstance(d.get("edges"), list) else "not a day file")
            if not why and (str(d.get("chain") or "").lower() == "solana") != sol:   # the file's own chain must match its name
                why = "its chain does not match its name"
            if why or (not sol and _num(d.get("hours")) and d["hours"] < 24):   # Solana is read in windows: its days may be shorter
                raise ValueError(why or "a partial day")
            edges = d["edges"]
        except (OSError, ValueError, AttributeError):
            if unread is not None:                    # said on the page: totals never look complete when they are not
                unread.append(day)
            continue
        out.setdefault(day, {})
        sellers_of = {}
        for e in edges:
            if isinstance(e, dict) and isinstance(e.get("from"), str) and isinstance(e.get("to"), str) and _num(e.get("n_x402")) and e["n_x402"] > 0:
                f = e["from"] if sol else e["from"].lower()
                sellers_of.setdefault(f, set()).add(e["to"] if sol else e["to"].lower())
        ours = r["solana"] if sol else r["base"]
        for e in edges:
            if not (isinstance(e, dict) and isinstance(e.get("from"), str) and isinstance(e.get("to"), str)):
                continue
            to = e["to"] if sol else e["to"].lower()
            n, u = e.get("n_x402"), e.get("usdc_x402")
            if to not in ours or not (_num(n) and _num(u)) or n <= 0:
                continue
            f = e["from"] if sol else e["from"].lower()
            kind = "ours" if f in r["own"] else "robots" if len(sellers_of.get(f, ())) >= ROBOT else "customers"
            row = out.setdefault(day, {}).setdefault(kind, [0, 0.0, set()])
            row[0] += int(n)
            row[1] += float(u)
            row[2].add(f)
    return out


def _usd(x):
    """Exact to the tenth of a cent: $0.004, $1.001, $29.00."""
    t = "{:,.3f}".format(round(x, 3))
    return "$" + (t[:-1] if t.endswith("0") else t)


def body(r, days, as_of, unread=()):
    tot = {k: [0, 0.0, set()] for k in ("customers", "robots", "ours")}
    for d in days.values():
        for k, v in d.items():
            tot[k][0] += v[0]
            tot[k][1] += v[1]
            tot[k][2] |= v[2]
    span = ("%s to %s" % (atlas_style.short_date(min(days)), atlas_style.short_date(max(days)))) if days else "no days held"
    card = sum(s["amount_usd"] for s in r["card_sales"])
    paid_out = sum(o["amount_usdc"] for o in r["out"])
    p = ['<div class="rc"><p class="eyebrow">Infoharmoni Atlas</p><h1>Our receipts</h1>',
         '<p class="rc-lede">What we have earned and paid, counted the way we count everyone else: payments in are read from '
         'the chain at our seller addresses every morning; card sales and payments out are listed with their receipts. '
         'Buyers and payees are named by role, never by name.</p>',
         '<dl class="rc-kpi"><div><dt>from customers, %s</dt><dd>%s</dd></div><div><dt>card sales, all time</dt><dd>%s</dd></div>'
         '<div><dt>paid out by the agent, all time</dt><dd>%s</dd></div></dl>'
         % (esc(span), esc(_usd(tot["customers"][1])), esc(_usd(card)), esc(_usd(paid_out)))]
    if unread:
        p.append('<p class="rc-warn">Not counted: the day file%s for %s could not be read, so the totals above leave %s out.</p>'
                 % ("s" if len(set(unread)) > 1 else "", esc(", ".join(atlas_style.short_date(d) for d in sorted(set(unread)))),
                    "them" if len(set(unread)) > 1 else "it"))
    if days and not any(days.values()):
        p.append('<p class="muted">No payment reached our addresses on the days read.</p>')
    p.append('<h2>Money in, on the chain</h2><p class="muted">x402 payments to our seller addresses, by day. A robot is a wallet '
             'that paid %d or more different sellers that day; it samples everyone and is not shopping for us. Our own test '
             'wallet is shown apart, so it never counts as a sale.</p>' % ROBOT)
    if days:
        p.append('<div class="tw"><table><tr><th>day</th><th class="n">customers</th><th class="n">robots</th>'
                 '<th class="n">our own tests</th></tr>')
        for day in sorted(days, reverse=True):                      # every day read, a quiet one as dashes
            cells = []
            for k in ("customers", "robots", "ours"):
                v = days[day].get(k)
                cells.append('<td class="n">%s</td>' % ("%s · %d payment%s" % (esc(_usd(v[1])), v[0], "" if v[0] == 1 else "s") if v else "—"))
            p.append('<tr><td>%s</td>%s</tr>' % (esc(atlas_style.short_date(day)), "".join(cells)))
        p.append("</table></div>")
    else:
        p.append('<p class="muted">No day files are held for this build; the next morning\'s build reads them again.</p>')
    p.append('<h2>Card sales</h2>')
    if r["card_sales"]:
        p.append('<ul class="rc-list">%s</ul>' % "".join('<li><b>%s</b> %s: %s to %s <span class="muted">(%s)</span></li>'
                 % (esc(atlas_style.short_date(s["date"])), esc(_usd(s["amount_usd"])), esc(s["what"]), esc(s["buyer"]), esc(s["receipt"]))
                 for s in sorted(r["card_sales"], key=lambda s: s["date"], reverse=True)))
    else:
        p.append('<p>None yet (Pro, seller statements and the Brief, checked %s).</p>' % esc(atlas_style.short_date(r["card_checked"])) if r["card_checked"]
                 else '<p>None yet.</p>')
    p.append('<h2>Money out, paid by the agent</h2>')
    if r["out"]:
        p.append('<ul class="rc-list">%s</ul>' % "".join(
            '<li><b>%s</b> %s USDC on %s to %s, for %s. <a href="%s" rel="nofollow noopener">Receipt</a></li>'
            % (esc(atlas_style.short_date(o["date"])), esc("{:,.3f}".format(o["amount_usdc"]).rstrip("0").rstrip(".")), esc(o["chain"]),
               esc(o["to"]), esc(o["for"]), esc(EXPLORER[o["chain"]] % o["tx"]))
            for o in sorted(r["out"], key=lambda o: o["date"], reverse=True)))
    else:
        p.append('<p>None yet.</p>')
    p.append('<h2>How this is made</h2><p>The same day files the Atlas publishes, read at our own addresses. Every payment out '
             'is approved by a person, one at a time, before it moves. Nothing here is typed in except the receipts above, '
             'each of which anyone can open.</p></div>')
    return "".join(p)


def build(out, data=DATA, flows_dir=None, site="", free=None):
    r = load(data)
    unread = []
    days = money_in(flows_dir, r, unread) if flows_dir else {}
    as_of = max(days) if days else datetime.date.today().isoformat()
    html_text = cp.page("Our receipts", body(r, days, as_of, unread), as_of,
                        "What Infoharmoni Atlas has earned and paid, read from the chain at its own addresses.",
                        room="receipts", root=site.rstrip("/"), free=free)
    if re.search("ver" + "ified", html_text, re.I):
        raise ValueError("the page would use the word the Atlas never says")
    cp.write(out, "receipts", html_text)
    return {"days": len(days), "unread": sorted(set(unread)), "customers_usdc": round(sum(d.get("customers", [0, 0.0])[1] for d in days.values()), 6)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--flows-dir", default=None)
    ap.add_argument("--site", default="")
    a = ap.parse_args()
    print("receipts:", build(a.out, a.data, a.flows_dir, a.site))


if __name__ == "__main__":
    main()
