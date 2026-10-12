#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 9c81769). Edit it there, not here.
"""rows.py — every USDC transfer into and out of chosen wallets on Base, one row each.

    BASE_RPC_URL=... rows.py --wallet 0x... [--wallet 0x...] --day 2026-10-03 [--day ...] --out rows.csv

The public day files are totals per buyer-seller pair (from, to, n, usdc). An analyst who wants to
pair a payment with the money that funded it needs the payments themselves: block, time, transaction,
log index, direction, the other side, the amount, and whether a facilitator settled it on a signed
authorization (x402). That is what this writes. It is sold, not published (Moltbook, 2026-10-12:
"the free public atlas files are daily aggregates ... your run depends on row-level data from your side").

Base makes a block every two seconds, so a row's time is the day's first block time plus two seconds a
block, checked against the day's last block. The reads are chain_flows' own: the same RPC, chunking and
refusal handling the daily build uses.
"""
import argparse
import csv
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain_flows as cf  # noqa: E402

FIELDS = ["day", "block", "time_utc", "tx_hash", "log_index", "direction", "wallet", "counterparty", "usdc", "x402"]


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def usdc(units):
    """USDC's six-decimal base units as an exact decimal string: 1500000 -> "1.500000"."""
    return "%d.%06d" % divmod(units, 10 ** 6)


def addr(topic):
    return "0x" + topic[-40:].lower()


def outbound_logs(group, b, e, get_logs=None, min_blocks=125):
    """Every USDC Transfer FROM the wallets in `group` over [b, e]. On a size refusal the block span
    halves, and once it is small the wallet group splits, as chain_flows.transfer_logs does inbound."""
    get_logs = get_logs or (lambda b, e, group: cf.rpc("eth_getLogs", [{"fromBlock": hex(b), "toBlock": hex(e), "address": cf.USDC,
                                                                       "topics": [cf.TRANSFER, [cf.topic_addr(w) for w in group]]}]))
    try:
        return get_logs(b, e, group)
    except cf.TooBig:
        if e - b + 1 > min_blocks:
            mid = (b + e) // 2
            return outbound_logs(group, b, mid, get_logs, min_blocks) + outbound_logs(group, mid + 1, e, get_logs, min_blocks)
        if len(group) > 1:
            half = len(group) // 2
            return outbound_logs(group[:half], b, e, get_logs, min_blocks) + outbound_logs(group[half:], b, e, get_logs, min_blocks)
        raise


def to_rows(day, logs, wallets, authorized, first_block, first_ts):
    """Logs to rows, seen from the watched wallets: 'in' when one of them receives, 'out' when one sends.
    A transfer between two watched wallets gives one row each way. Time: two seconds a block."""
    w = {x.lower() for x in wallets}
    out, seen = [], set()
    for l in logs:
        key = (l["transactionHash"], l["logIndex"])
        src, dst = addr(l["topics"][1]), addr(l["topics"][2])
        block = int(l["blockNumber"], 16)
        base = {"day": day, "block": block, "time_utc": iso(first_ts + 2 * (block - first_block)),
                "tx_hash": l["transactionHash"], "log_index": int(l["logIndex"], 16), "usdc": usdc(int(l["data"], 16)),
                "x402": l["transactionHash"] in authorized}
        for direction, me, other in (("in", dst, src), ("out", src, dst)):
            if me in w and (key, direction) not in seen:
                seen.add((key, direction))
                out.append(dict(base, direction=direction, wallet=me, counterparty=other))
    return sorted(out, key=lambda r: (r["block"], r["log_index"], r["direction"]))


def day_rows(day, wallets, get_ts=None, head=None):
    get_ts = get_ts or cf.block_ts
    head = head if head is not None else int(cf.rpc("eth_blockNumber", []), 16)
    t0, t1 = cf.day_bounds(day)
    first, last = cf.block_at(t0, head, get_ts), cf.block_at(t1, head, get_ts) - 1
    if last >= head:                  # as chain_flows: a file is sold as whole days, so a day not over is refused
        raise RuntimeError("%s is not over yet on Base (head %d is inside it)" % (day, head))
    first_ts = get_ts(first)
    # Base blocks are exactly two seconds apart; a day that says otherwise is not written
    if get_ts(last) != first_ts + 2 * (last - first):
        raise RuntimeError("%s: block times are not two seconds apart between %d and %d" % (day, first, last))
    authorized = cf.authorized_txs(first, last)
    logs, b = [], first
    while b <= last:
        e = min(b + cf.CHUNK_BLOCKS - 1, last)
        logs += cf.transfer_logs(sorted(wallets), b, e)[0]
        logs += outbound_logs(sorted(wallets), b, e)
        b = e + 1
    return to_rows(day, logs, wallets, authorized, first, first_ts), (first, last)


ROW = re.compile(r"^\d{4}-\d{2}-\d{2},\d+,\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z,0x[0-9a-f]{64},\d+,(in|out),"
                 r"0x[0-9a-f]{40},0x[0-9a-f]{40},\d+\.\d{6},(True|False)$")


def check_file(path):
    """None when every line of `path` is what main() writes (the header, then rows of that exact shape);
    otherwise why not. The deploy build takes only files that pass, since they are exempt from its key scan."""
    with open(path, newline="") as f:
        lines = f.read().splitlines()
    if not lines or lines[0] != ",".join(FIELDS):
        return "the first line is not the header"
    for i, line in enumerate(lines[1:], 2):
        if not ROW.match(line):
            return "line %d is not a row" % i
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", metavar="CSV", help="only check that a file is this script's output; exit 1 if not")
    ap.add_argument("--wallet", action="append")
    ap.add_argument("--day", action="append", help="YYYY-MM-DD, UTC")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.check:
        why = check_file(a.check)
        if why:
            sys.exit("rows: %s: %s" % (a.check, why))
        return
    if not (a.wallet and a.day and a.out):
        ap.error("--wallet, --day and --out are needed to write rows")
    wallets = [w.lower() for w in a.wallet]
    if not all(re.fullmatch(r"0x[0-9a-f]{40}", w) for w in wallets):
        sys.exit("rows: a wallet must be a 0x address of 40 hex characters")
    head = int(cf.rpc("eth_blockNumber", []), 16)
    total = []
    for day in sorted(set(a.day)):
        rows, (first, last) = day_rows(day, wallets, head=head)
        print("%s: blocks %d..%d, %d rows" % (day, first, last, len(rows)), flush=True)
        total += rows
    with open(a.out, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS)
        wr.writeheader()
        wr.writerows(total)
    print("wrote %s: %d rows, %d wallets, %d days" % (a.out, len(total), len(wallets), len(set(a.day))))


if __name__ == "__main__":
    main()
