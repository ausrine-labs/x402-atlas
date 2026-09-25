#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 507dd4a). Edit it there, not here.
"""snapshot_handoff.py — how a seller with no disk gets its market snapshots.

Two halves of one hand-off. Standard library only.

    publish(store, out)      the Mac, after the morning scan: write the most
                             recent 8 snapshots, gzipped, plus a manifest of
                             their checksums, into a folder that is served
                             publicly. Older days are removed from the folder.
    archive(base_url, store) the machine that keeps the long history: add the days
                             it lacks, never delete, never overwrite.
    fetch(base_url, store)   the seller, at startup and hourly: read the
                             manifest, download what it lacks, and CHECK each
                             file before trusting it. A file that fails is
                             dropped and the rest still serve.

Decision (Vilija, 2026-09-18): a rolling 8 days may be public; the long
history never leaves the Mac. That is why `keep` is small and why publish
deletes what falls out of the window.

What a file must pass, on both sides:
    - its checksum matches the manifest (fetch side)
    - it parses, and the date inside it matches the date in its name
    - it holds at least `floor` sellers. This registry was once silently
      truncated at a third of its size; a short file is a broken scan, and a
      broken scan must not be sold.

    ./snapshot_handoff.py publish --out /path/to/public/folder
    ./snapshot_handoff.py fetch https://example.org/radar/ --store /tmp/store
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone

KEEP = 8
FLOOR = 1000
MAX_GZ = 5 * 1024 * 1024        # a day is ~240 KB gzipped; 5 MB means something is wrong
MAX_JSON = 40 * 1024 * 1024
NAME = re.compile(r"^market-(\d{4}-\d{2}-\d{2})\.json(\.gz)?$")


class HandoffError(Exception):
    pass


ROW_NUMBERS = ("endpoints", "calls", "payers", "take", "price_min", "price_med", "price_max")
ROW_FIELDS = ROW_NUMBERS + ("chains", "wallets", "sells", "url")


def row_problem(host, row):
    """Why a seller row cannot be sold as an answer, or None. A number that is missing,
    negative, infinite, or a boolean is not a fact about a seller."""
    import math
    if not isinstance(row, dict):
        return "row for %s is not an object" % host
    for k in ROW_FIELDS:
        if k not in row:
            return "row for %s lacks %r" % (host, k)
    for k in ROW_NUMBERS:
        v = row[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
            return "row for %s has %s=%r" % (host, k, v)
    if row["endpoints"] < 1:
        return "row for %s has no endpoints" % host
    if not (row["price_min"] <= row["price_med"] <= row["price_max"]):
        return "row for %s has prices out of order" % host
    if not isinstance(row["sells"], str) or not isinstance(row["chains"], list) \
            or not isinstance(row["wallets"], list) or not isinstance(row["url"], str):
        return "row for %s has the wrong shape" % host
    if not all(isinstance(x, str) for x in row["chains"]) or not all(isinstance(x, str) for x in row["wallets"]):
        return "row for %s has a chain or wallet that is not text" % host
    return None


def parse_day(s):
    """A real calendar date in ISO form, or None."""
    from datetime import date
    try:
        return date.fromisoformat(s) if isinstance(s, str) and len(s) == 10 else None
    except ValueError:
        return None


def check_snapshot(raw_json, want_date, floor, today=None):
    """Why this snapshot must not be used, or None when it may. Checked: it parses, its
    date is a real day that is not in the future and matches its name, it holds at least
    `floor` sellers, and every seller row is complete and sane."""
    from datetime import date
    want = parse_day(want_date)
    if want is None:
        return "its name is not a real date"
    if want > (today or datetime.now(timezone.utc).date()):   # names are UTC days; a local clock can lag a day
        return "is dated %s, in the future" % want_date
    try:
        snap = json.loads(raw_json)
    except ValueError:
        return "does not parse"
    if not isinstance(snap, dict) or not isinstance(snap.get("sellers"), dict):
        return "has no sellers table"
    if snap.get("date") != want_date:
        return "says it is %r, its name says %s" % (snap.get("date"), want_date)
    if len(snap["sellers"]) < floor:
        return "holds %d sellers, fewer than the floor of %d" % (len(snap["sellers"]), floor)
    for host, row in snap["sellers"].items():
        why = row_problem(host, row)
        if why:
            return why
    return None


def _write_atomic(path, data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


# ── the Mac side ─────────────────────────────────────────────────────────

def publish(store, out, keep=KEEP, floor=FLOOR, now=None):
    """Write the newest `keep` good snapshots and a manifest into `out`.
    Returns the manifest. The manifest is written LAST, so a reader never
    sees it name a file that is not there yet."""
    os.makedirs(out, exist_ok=True)
    days = sorted(f for f in os.listdir(store) if NAME.match(f) and f.endswith(".json"))
    files, skipped = [], []
    for f in reversed(days):
        if len(files) == keep:
            break
        day = NAME.match(f).group(1)
        with open(os.path.join(store, f), "rb") as fh:
            raw = fh.read()
        why = check_snapshot(raw, day, floor)
        if why:
            skipped.append({"name": f, "why": why})
            continue
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:   # mtime=0: same bytes every run
            gz.write(raw)
        data = buf.getvalue()
        name = f + ".gz"
        _write_atomic(os.path.join(out, name), data)
        files.append({"date": day, "name": name, "bytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest(),
                      "sellers": len(json.loads(raw)["sellers"])})
    files.sort(key=lambda x: x["date"])
    if not files:
        raise HandoffError("nothing fit to publish: %s" % (skipped or "the store is empty"))
    manifest = {"published_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
                "keep": keep, "floor": floor, "files": files, "skipped": skipped}
    _write_atomic(os.path.join(out, "manifest.json"),
                  json.dumps(manifest, indent=1, sort_keys=True).encode())
    wanted = {x["name"] for x in files}
    for f in os.listdir(out):                      # the window rolls: old days leave the public folder
        if NAME.match(f) and f not in wanted:
            os.remove(os.path.join(out, f))
    return manifest


# ── the seller side ──────────────────────────────────────────────────────

def _allowed(url):
    u = urllib.parse.urlparse(url)
    return u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HandoffError("refusing a redirect from %s to %s" % (req.full_url, newurl))


_OPENER = urllib.request.build_opener(_NoRedirect)


def http_get(url, limit):
    """Fetch from the trusted publisher only: https, no redirects, a size cap. The
    publisher (our own Pages site) is trusted explicitly; this does not make the data
    independently authentic, it makes sure it came from there."""
    if not _allowed(url):
        raise HandoffError("refusing %s: https only (plain http is for localhost tests)" % url)
    req = urllib.request.Request(url, headers={"User-Agent": "infoharmoni-radar-seller/1.0"})
    with _OPENER.open(req, timeout=30) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise HandoffError("%s is larger than %d bytes" % (url, limit))
    return data


def fetch(base_url, store, floor=FLOOR, get=http_get):
    """Bring `store` in line with the published manifest. Returns a report:
    {"as_of", "kept": [...], "fetched": [...], "rejected": [{"name","why"}]}.
    Never raises for one bad file; raises HandoffError when there is no usable
    manifest, because then there is nothing to trust at all."""
    base = base_url if base_url.endswith("/") else base_url + "/"
    try:
        manifest = json.loads(get(base + "manifest.json", 256 * 1024))
        listed = manifest["files"]
        assert isinstance(listed, list)
    except HandoffError:
        raise
    except Exception as e:
        raise HandoffError("no usable manifest at %s: %s" % (base, type(e).__name__))
    os.makedirs(store, exist_ok=True)
    report = {"as_of": None, "kept": [], "fetched": [], "rejected": []}
    good = set()
    for item in listed:
        name = str(item.get("name", ""))
        m = NAME.match(name)
        if not m or not name.endswith(".gz"):
            report["rejected"].append({"name": name, "why": "not a snapshot name"})
            continue
        day, local = m.group(1), os.path.join(store, "market-%s.json" % m.group(1))
        marker = local + ".sha256"
        if os.path.exists(local) and os.path.exists(marker) \
                and open(marker).read().strip() == item.get("sha256"):
            good.add(os.path.basename(local))
            report["kept"].append(day)
            continue
        try:
            data = get(base + name, MAX_GZ)
            if hashlib.sha256(data).hexdigest() != item.get("sha256"):
                raise HandoffError("checksum does not match the manifest")
            raw = gzip.GzipFile(fileobj=io.BytesIO(data)).read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise HandoffError("unpacks to more than %d bytes" % MAX_JSON)
            why = check_snapshot(raw, day, floor)
            if why:
                raise HandoffError(why)
        except Exception as e:
            report["rejected"].append({"name": name, "why": str(e) if isinstance(e, HandoffError)
                                       else type(e).__name__})
            continue
        _write_atomic(local, raw)
        _write_atomic(marker, item["sha256"].encode())
        good.add(os.path.basename(local))
        report["fetched"].append(day)
    for f in os.listdir(store):                    # nothing the manifest does not vouch for stays
        if NAME.match(f) and f.endswith(".json") and f not in good:
            os.remove(os.path.join(store, f))
            if os.path.exists(os.path.join(store, f + ".sha256")):
                os.remove(os.path.join(store, f + ".sha256"))
    days = sorted(report["kept"] + report["fetched"])
    report["as_of"] = days[-1] if days else None
    return report


def coverage(store):
    """What the long archive holds: first and last day, how many, and every missing day between."""
    from datetime import date, timedelta
    days = sorted(NAME.match(f).group(1) for f in os.listdir(store)
                  if NAME.match(f) and f.endswith(".json")) if os.path.isdir(store) else []
    if not days:
        return {"days": 0, "first": None, "last": None, "missing": []}
    d, end, have, missing = date.fromisoformat(days[0]), date.fromisoformat(days[-1]), set(days), []
    while d <= end:
        if d.isoformat() not in have:
            missing.append(d.isoformat())
        d += timedelta(days=1)
    return {"days": len(days), "first": days[0], "last": days[-1], "missing": missing}


def archive(base_url, store, floor=FLOOR, get=http_get):
    """For the machine that keeps the LONG history. Adds the published days it lacks and
    does nothing else: never deletes, never overwrites. `fetch` prunes a store to match the
    manifest, which is right for a throwaway seller and would destroy an archive."""
    base = base_url if base_url.endswith("/") else base_url + "/"
    try:
        listed = json.loads(get(base + "manifest.json", 256 * 1024))["files"]
    except HandoffError:
        raise
    except Exception as e:
        raise HandoffError("no usable manifest at %s: %s" % (base, type(e).__name__))
    os.makedirs(store, exist_ok=True)
    report = {"added": [], "already_had": [], "rejected": []}
    for item in listed:
        name = str(item.get("name", ""))
        m = NAME.match(name)
        if not m or not name.endswith(".gz"):
            continue
        day, local = m.group(1), os.path.join(store, "market-%s.json" % m.group(1))
        if os.path.exists(local):
            report["already_had"].append(day)          # ours wins, always
            continue
        try:
            data = get(base + name, MAX_GZ)
            if hashlib.sha256(data).hexdigest() != item.get("sha256"):
                raise HandoffError("checksum does not match the manifest")
            raw = gzip.GzipFile(fileobj=io.BytesIO(data)).read(MAX_JSON + 1)
            why = "unpacks too large" if len(raw) > MAX_JSON else check_snapshot(raw, day, floor)
            if why:
                raise HandoffError(why)
        except Exception as e:
            report["rejected"].append({"name": name, "why": str(e) if isinstance(e, HandoffError)
                                       else type(e).__name__})
            continue
        _write_atomic(local, raw)
        report["added"].append(day)
    report["holds"] = coverage(store)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("publish", help="the Mac side")
    p.add_argument("--store", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "radar-store"))
    p.add_argument("--out", required=True)
    p.add_argument("--keep", type=int, default=KEEP)
    p.add_argument("--floor", type=int, default=FLOOR)
    f = sub.add_parser("fetch", help="the seller side")
    f.add_argument("url")
    f.add_argument("--store", required=True)
    f.add_argument("--floor", type=int, default=FLOOR)
    ar = sub.add_parser("archive", help="the long-history side: add missing days, never delete")
    ar.add_argument("url")
    ar.add_argument("--store", required=True)
    ar.add_argument("--floor", type=int, default=FLOOR)
    a = ap.parse_args()
    try:
        if a.cmd == "archive":
            r = archive(a.url, a.store, a.floor)
            h = r["holds"]
            print("archive: +%d day(s)%s; holds %d days, %s to %s; missing forever: %s%s"
                  % (len(r["added"]), (" " + ",".join(r["added"])) if r["added"] else "", h["days"], h["first"],
                     h["last"], ", ".join(h["missing"]) or "none",
                     ("; REJECTED: %s" % r["rejected"]) if r["rejected"] else ""))
            return
        if a.cmd == "publish":
            m = publish(a.store, a.out, a.keep, a.floor)
            print("published %d days (%s … %s), %d KB; skipped %d"
                  % (len(m["files"]), m["files"][0]["date"], m["files"][-1]["date"],
                     sum(x["bytes"] for x in m["files"]) // 1024, len(m["skipped"])))
            for s in m["skipped"]:
                print("  skipped %s: %s" % (s["name"], s["why"]))
        else:
            print(json.dumps(fetch(a.url, a.store, a.floor), indent=1))
    except HandoffError as e:
        sys.exit("snapshot-handoff: %s" % e)


if __name__ == "__main__":
    main()
