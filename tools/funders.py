#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 893b6af). Edit it there, not here.
"""funders.py — who first sent USDC to each payer in a rows file: the second hop.

    BASE_RPC_URL=... funders.py --rows rows.csv --out funders.csv [--lookback-days 30]
    funders.py --check funders.csv

rows.py writes the USDC payments in and out of chosen seller wallets. An analyst who reads them asks the
next question: where did each payer's money come from, and was it the seller that sent it? This reads a
rows file, takes the payers (every counterparty of an 'in' row with x402 True), and for each payer finds
the FIRST USDC Transfer into it inside the lookback before its first payment in the file.

  window     from the first block at or after (the time of the payer's first x402 payment minus the
             lookback) up to that payment; in the payment's own block only a transfer with a lower log
             index counts. A payer sending to itself is skipped.
  funder     the sender of the earliest transfer in the window
  sent total everything that funder sent to ANY payer of the file, inside those payers' windows
  payer count  how many of the file's payers this funder was the first funder of
  kind       'seller' when the funder is one of the file's seller wallets (the rows' wallet column);
             else 'shared' when it funded 3 or more payers, else 'single'; a payer with no transfer
             in its window is 'unseen' and its funder fields are empty

Next to the CSV it writes <out>-summary.json: per seller, its payers, how many were funded by a seller
wallet, how many share a funder, and the top 5 funders with their shares of the seller's x402 USDC,
then the same with the largest funder taken out. Write both to a working folder and copy the CSV into
rows/: the deploy build refuses anything in rows/ that is not a CSV of this shape.

This says which wallet sent the first transfer. It says nothing about who is behind either wallet.
The reads are chain_flows': the same RPC, block search, size refusal and halving the daily build uses.
Standard library only.
"""
import argparse
import collections
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain_flows as cf  # noqa: E402
import rows  # noqa: E402

FIELDS = ["payer", "first_payment_block", "funder", "funding_block", "funding_time_utc", "funding_tx_hash",
          "funding_log_index", "funding_usdc", "funder_sent_total_usdc", "funder_payer_count",
          "funder_is_seller", "funder_kind"]
SHARED_MIN = 3          # a funder of this many of the file's payers is 'shared'
TOP = 5                 # funders listed per seller in the summary
PROGRESS_EVERY = 100    # chunks between progress lines


def units(s):
    """The base units in a six-decimal string rows.usdc wrote: "1.500000" -> 1500000."""
    return int(s.replace(".", ""))


def kind_of(n_payers, is_seller):
    if is_seller:
        return "seller"
    return "shared" if n_payers >= SHARED_MIN else "single"


def read_rows(path):
    """The rows of a rows.py file as dicts, once rows.py's own check has passed them."""
    why = rows.check_file(path)
    if why:
        raise ValueError("%s: %s" % (path, why))
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def payers_of(rs):
    """({payer: (block, log_index) of its first x402 payment in the file}, {the file's seller wallets})."""
    first = {}
    for r in rs:
        if r["direction"] == "in" and r["x402"] == "True":
            k = (int(r["block"]), int(r["log_index"]))
            if r["counterparty"] not in first or k < first[r["counterparty"]]:
                first[r["counterparty"]] = k
    return first, {r["wallet"] for r in rs}


def memo(fn):
    """fn with its answers kept: the block search and the funding times ask for the same blocks again."""
    seen = {}

    def get(n):
        if n not in seen:
            seen[n] = fn(n)
        return seen[n]
    return get


def first_funders(payers, head, lookback_days, get_logs=None, get_ts=None, chunk=None, group_size=None):
    """({payer: (block, log_index, funder, units, tx_hash)} of its first inbound transfer in its window,
    Counter {funder: units sent to any payer inside those windows}).

    One walk over the blocks from the earliest window start to the last first payment, in chunks, asking
    for the transfers into the payers whose window touches the chunk. chain_flows.transfer_logs answers a
    size refusal by halving the span and then splitting the payers, so the chunk size and the group size
    change how many requests are made, never what is found. get_logs(b, e, group) and get_ts(block) are
    for tests; by default they are the RPC."""
    get_ts = memo(get_ts or cf.block_ts)
    chunk = chunk or cf.CHUNK_BLOCKS
    group_size = group_size or cf.CHUNK_WALLETS
    genesis = get_ts(0)
    start = {p: cf.block_at(max(get_ts(blk) - int(lookback_days * 86400), genesis), head, get_ts)
             for p, (blk, _) in payers.items()}
    first, last = min(start.values()), max(blk for blk, _ in payers.values())
    n_chunks = (last - first) // chunk + 1
    firsts, sent, seen = {}, collections.Counter(), set()
    b = first
    for i in range(n_chunks):
        e = min(b + chunk - 1, last)
        live = sorted(p for p, (blk, _) in payers.items() if start[p] <= e and blk >= b)
        for g in range(0, len(live), group_size):
            logs, _ = cf.transfer_logs(live[g:g + group_size], b, e, get_logs)
            for l in logs:
                key = (l["transactionHash"], l["logIndex"])
                if key in seen:
                    continue
                seen.add(key)
                src, dst = rows.addr(l["topics"][1]), rows.addr(l["topics"][2])
                blk, idx = int(l["blockNumber"], 16), int(l["logIndex"], 16)
                if dst not in payers or src == dst or blk < start[dst] or (blk, idx) >= payers[dst]:
                    continue
                n = int(l["data"], 16)
                sent[src] += n
                if dst not in firsts or (blk, idx) < firsts[dst][:2]:
                    firsts[dst] = (blk, idx, src, n, l["transactionHash"])
        if (i + 1) % PROGRESS_EVERY == 0:
            print("  %d of %d chunks, blocks up to %d" % (i + 1, n_chunks, e), file=sys.stderr, flush=True)
        b = e + 1
    return firsts, sent


def funder_rows(payers, firsts, sent, sellers, get_ts):
    """One row per payer, in the order of their first payments. A payer without a funder has empty funder
    fields and the kind 'unseen'."""
    count = collections.Counter(f[2] for f in firsts.values())
    out = []
    for p in sorted(payers, key=lambda p: (payers[p], p)):
        r = {"payer": p, "first_payment_block": payers[p][0], "funder_kind": "unseen"}
        if p in firsts:
            blk, idx, src, n, tx = firsts[p]
            r.update(funder=src, funding_block=blk, funding_time_utc=rows.iso(get_ts(blk)), funding_tx_hash=tx,
                     funding_log_index=idx, funding_usdc=rows.usdc(n), funder_sent_total_usdc=rows.usdc(sent[src]),
                     funder_payer_count=count[src], funder_is_seller=src in sellers,
                     funder_kind=kind_of(count[src], src in sellers))
        out.append(r)
    return out


def ranked(funded, total):
    """The funders of a seller's payers, most payers first (then most USDC, then address):
    [{funder, payers, usdc, share}]. `funded` is [(funder, units the payer paid the seller)], one per
    payer with a funder; `total` is all of the seller's x402 units, payers without a funder included,
    so the shares of the list can add up to less than 1."""
    n, u = collections.Counter(), collections.Counter()
    for f, paid in funded:
        n[f] += 1
        u[f] += paid
    return [{"funder": f, "payers": n[f], "usdc": rows.usdc(u[f]), "share": round(u[f] / total, 4) if total else None}
            for f in sorted(n, key=lambda f: (-n[f], -u[f], f))]


MEANS = {
    "window": "the first transfer of USDC into a payer, from the start of the lookback up to its first payment "
              "in the rows file; the funder is the wallet that sent it. This says nothing about who is behind a wallet",
    "payers": "wallets that made an x402 payment to this seller wallet in the rows file",
    "seller_funded": "payers whose first funder is one of the seller wallets in the rows file",
    "funded_by_this_seller": "payers whose first funder is this seller wallet",
    "share_a_funder": "payers whose first funder was the first funder of %d or more of the file's payers" % SHARED_MIN,
    "unseen": "payers with no USDC transfer into them in the lookback before their first payment",
    "x402_usdc": "what the payers paid this seller wallet by x402 in the rows file",
    "top_funders": "the %d first funders with the most of this seller's payers; usdc is what their payers paid the "
                   "seller by x402 and share is that over all of the seller's x402 USDC, unseen payers included" % TOP,
    "without_largest_funder": "the same after the funder at the head of that list is taken out, with the shares "
                              "taken over the USDC that is left",
}


def summarize(rs, out_rows, lookback_days):
    """The summary JSON: per seller wallet of the rows file, how its payers were first funded."""
    by_payer = {r["payer"]: r for r in out_rows}
    sellers = {r["wallet"] for r in rs}
    paid = collections.defaultdict(collections.Counter)              # seller -> payer -> x402 units
    for r in rs:
        if r["direction"] == "in" and r["x402"] == "True":
            paid[r["wallet"]][r["counterparty"]] += units(r["usdc"])
    result = {}
    for s in sorted(sellers):
        mine = paid[s]
        total = sum(mine.values())
        funded = [(by_payer[p]["funder"], mine[p]) for p in sorted(mine) if "funder" in by_payer[p]]
        top = ranked(funded, total)
        entry = {"payers": len(mine),
                 "seller_funded": sum(1 for p in mine if by_payer[p].get("funder_is_seller")),
                 "funded_by_this_seller": sum(1 for p in mine if by_payer[p].get("funder") == s),
                 "share_a_funder": sum(1 for p in mine if by_payer[p].get("funder_payer_count", 0) >= SHARED_MIN),
                 "unseen": sum(1 for p in mine if "funder" not in by_payer[p]),
                 "x402_usdc": rows.usdc(total),
                 "top_funders": top[:TOP],
                 "largest_funder": top[0]["funder"] if top else None}
        if top:
            gone = top[0]["funder"]
            left = [(f, n) for f, n in funded if f != gone]
            left_total = total - units(top[0]["usdc"])
            entry["without_largest_funder"] = {"payers": len(mine) - top[0]["payers"], "x402_usdc": rows.usdc(left_total),
                                               "top_funders": ranked(left, left_total)[:TOP]}
        else:
            entry["without_largest_funder"] = {"payers": len(mine), "x402_usdc": rows.usdc(total), "top_funders": []}
        result[s] = entry
    return {"lookback_days": lookback_days, "payers": len(by_payer), "means": MEANS, "sellers": result}


_A = r"0x[0-9a-f]{40}"
_N = r"\d+"
_T = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
_H = r"0x[0-9a-f]{64}"
_U = r"\d+\.\d{6}"
SEEN = ",".join([_A, _N, _A, _N, _T, _H, _N, _U, _U, _N]) + r",(?:True,seller|False,(?:shared|single))"
UNSEEN = ",".join([_A, _N] + [""] * 9 + ["unseen"])
ROW = re.compile("(?:%s|%s)" % (SEEN, UNSEEN))


def check_file(path):
    """None when every line of `path` is what main() writes (the header, then rows of that exact shape);
    otherwise why not. The deploy build takes only files that pass, since rows/ is exempt from its key scan.
    A line ends in \\n or \\r\\n and nothing else; a seller funder is kind 'seller' and no other is."""
    try:
        with open(path, newline="", encoding="ascii") as f:
            text = f.read()
    except UnicodeDecodeError:
        return "the file is not plain ASCII text"
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()                          # the last line's own newline
    lines = [l[:-1] if l.endswith("\r") else l for l in lines]
    if not lines or lines[0] != ",".join(FIELDS):
        return "the first line is not the header"
    for i, line in enumerate(lines[1:], 2):
        if not ROW.fullmatch(line):
            return "line %d is not a row" % i
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", metavar="CSV", help="only check that a file is this script's output; exit 1 if not")
    ap.add_argument("--rows", help="a rows.py file")
    ap.add_argument("--out", help="the funders CSV to write; the summary goes beside it as <out>-summary.json")
    ap.add_argument("--lookback-days", type=int, default=30)
    a = ap.parse_args(argv)
    if a.check:
        why = check_file(a.check)
        if why:
            sys.exit("funders: %s: %s" % (a.check, why))
        return
    if not (a.rows and a.out):
        ap.error("--rows and --out are needed to write funders")
    if a.lookback_days < 1:
        ap.error("--lookback-days must be 1 or more")
    summary_path = os.path.splitext(a.out)[0] + "-summary.json"
    for what, path in (("--out", a.out), ("its summary file", summary_path)):
        if os.path.realpath(path) == os.path.realpath(a.rows):
            ap.error("%s is the rows file itself; it would be overwritten" % what)
    try:
        rs = read_rows(a.rows)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        sys.exit("funders: %s" % e)
    payers, sellers = payers_of(rs)
    firsts, sent, get_ts = {}, collections.Counter(), memo(cf.block_ts)
    if payers:
        head = int(cf.rpc("eth_blockNumber", []), 16)
        firsts, sent = first_funders(payers, head, a.lookback_days, get_ts=get_ts)
    out_rows = funder_rows(payers, firsts, sent, sellers, get_ts)
    with open(a.out, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS)
        wr.writeheader()
        wr.writerows(out_rows)
    with open(summary_path, "w") as f:
        json.dump(summarize(rs, out_rows, a.lookback_days), f, indent=1)
        f.write("\n")
    print("wrote %s: %d payers, %d with a funder, %d unseen" % (a.out, len(out_rows), len(firsts), len(out_rows) - len(firsts)))
    print("wrote %s: %d sellers" % (summary_path, len(sellers)))


if __name__ == "__main__":
    main()
