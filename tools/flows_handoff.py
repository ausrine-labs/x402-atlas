#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 507dd4a). Edit it there, not here.
"""flows_handoff.py — the rolling public window of on-chain pulls, and how a
machine with no disk gets it back.

The site keeps no data in its repository. Each morning's build reads the
window it published yesterday, adds today's pull, drops what is older than
KEEP days, and publishes again — the same hand-off snapshot_handoff.py does
for market snapshots, here for the files chain_flows.py and whales.py write:

    flows-<date>.json    who paid whom, one day of Base (or another chain)
    whales-<date>.json   the rollup over the window, as of that day

    flows_handoff.py publish --store flows --out _site/flows
    flows_handoff.py fetch https://example.org/flows/ --store flows

publish writes the newest KEEP days of each kind, gzipped, and the manifest of
their checksums LAST, so a reader never sees it name a file that is not there.
fetch reads the manifest, downloads only what the store lacks, and checks each
file's checksum, its unpacked size, that it parses, and that its date matches
its name, before keeping it. A file that fails is dropped and the rest still
land. Beside each kept file a .sha256 sidecar records the manifest's checksum
and the plain file's own; a local file is trusted only while both still match,
and a flows or whales file the manifest no longer lists leaves the store.
Standard library only.
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
from datetime import date, datetime, timezone

KEEP = 8
NAME = re.compile(r"^(flows|whales)-(\d{4}-\d{2}-\d{2})\.json(\.gz)?$")
MAX_GZ = 8 * 1024 * 1024        # a day of flows is ~300 KB raw; 8 MB gzipped means something is wrong
MAX_JSON = 64 * 1024 * 1024     # unpacked: a rollup is a few MB; past this it is a bomb, not a day


class HandoffError(Exception):
    pass


def _write_atomic(path, data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".tmp-")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def file_problem(raw, kind, day, today=None):
    """Why this file must not be kept, or None."""
    try:
        want = date.fromisoformat(day)
    except ValueError:
        return "its name is not a real date"
    if want > (today or datetime.now(timezone.utc).date()):   # names are UTC days; a local clock can lag a day
        return "is dated %s, in the future" % day
    try:
        obj = json.loads(raw)
    except ValueError:
        return "does not parse"
    if not isinstance(obj, dict):
        return "is not an object"
    if kind == "flows":
        if obj.get("date") != day:
            return "says it is %r, its name says %s" % (obj.get("date"), day)
        if not isinstance(obj.get("edges"), list) or not isinstance(obj.get("sellers"), dict):
            return "has no edges or sellers"
    else:
        if not isinstance(obj.get("totals"), dict) or not isinstance(obj.get("buyers"), list):
            return "has no totals or buyers"
        if day not in (obj.get("dates") or []) and obj.get("as_of") != day:
            return "does not cover %s" % day
    return None


def publish(store, out, keep=KEEP, now=None):
    """Write the newest `keep` good days of each kind and a manifest into `out`."""
    os.makedirs(out, exist_ok=True)
    files, skipped, taken = [], [], {"flows": 0, "whales": 0}
    names = sorted((f for f in os.listdir(store) if NAME.match(f) and f.endswith(".json")),
                   key=lambda f: NAME.match(f).group(2), reverse=True)
    for f in names:
        kind, day, _ = NAME.match(f).groups()
        if taken[kind] >= keep:
            continue
        with open(os.path.join(store, f), "rb") as fh:
            raw = fh.read()
        why = file_problem(raw, kind, day)
        if why:
            skipped.append({"name": f, "why": why})
            continue
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:   # mtime=0: same bytes every run
            gz.write(raw)
        data = buf.getvalue()
        _write_atomic(os.path.join(out, f + ".gz"), data)
        files.append({"kind": kind, "date": day, "name": f + ".gz", "bytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
        taken[kind] += 1
    files.sort(key=lambda x: (x["kind"], x["date"]))
    if not files:
        raise HandoffError("nothing fit to publish: %s" % (skipped or "the store is empty"))
    manifest = {"published_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
                "keep": keep, "files": files, "skipped": skipped}
    _write_atomic(os.path.join(out, "manifest.json"), json.dumps(manifest, indent=1, sort_keys=True).encode())
    wanted = {x["name"] for x in files}
    for f in os.listdir(out):                      # the window rolls: old days leave the public folder
        if NAME.match(f) and f not in wanted:
            os.remove(os.path.join(out, f))
    return manifest


def _allowed(url):
    u = urllib.parse.urlparse(url)
    return u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HandoffError("refusing a redirect from %s to %s" % (req.full_url, newurl))


_OPENER = urllib.request.build_opener(_NoRedirect)


def http_get(url, limit):
    """Fetch from the trusted publisher only: https, no redirects, a size cap — the
    same rule snapshot_handoff keeps. A redirect could land on plain http or on a
    host we never chose, and the checksum in a manifest fetched that way vouches
    for nothing."""
    if not _allowed(url):
        raise HandoffError("refusing %s: https only (plain http is for localhost tests)" % url)
    req = urllib.request.Request(url, headers={"User-Agent": "ausrine-flows-handoff/1.0"})
    with _OPENER.open(req, timeout=60) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise HandoffError("%s is larger than %d bytes" % (url, limit))
    return data


def fetch(base_url, store, get=http_get):
    """Bring `store` in line with the published manifest. Returns a report:
    what was fetched, what was already there, what was rejected and why."""
    os.makedirs(store, exist_ok=True)
    base = base_url if base_url.endswith("/") else base_url + "/"
    try:
        manifest = json.loads(get(base + "manifest.json", 256 * 1024))
        listed = manifest["files"]
    except Exception as e:
        raise HandoffError("no usable manifest at %s: %s" % (base, type(e).__name__))
    report = {"fetched": [], "had": [], "rejected": []}
    good = set()
    for x in listed:
        m = NAME.match(x.get("name", ""))
        if not m or not m.group(3):
            report["rejected"].append({"name": x.get("name"), "why": "not a name this hand-off publishes"})
            continue
        kind, day, _ = m.groups()
        plain = "%s-%s.json" % (kind, day)
        local = os.path.join(store, plain)
        if _still_good(local, x.get("sha256")):
            good.add(plain)
            report["had"].append(plain)
            continue
        try:
            data = get(base + x["name"], MAX_GZ)
            if hashlib.sha256(data).hexdigest() != x.get("sha256"):
                raise HandoffError("checksum does not match the manifest")
            raw = gzip.GzipFile(fileobj=io.BytesIO(data)).read(MAX_JSON + 1)   # streamed: stops at the cap
            if len(raw) > MAX_JSON:
                raise HandoffError("unpacks to more than %d bytes" % MAX_JSON)
            why = file_problem(raw, kind, day)
            if why:
                raise HandoffError(why)
        except Exception as e:
            report["rejected"].append({"name": x["name"], "why": str(e) or type(e).__name__})
            continue
        _write_atomic(local, raw)
        _write_atomic(local + ".sha256", ("%s %s" % (x["sha256"], hashlib.sha256(raw).hexdigest())).encode())
        good.add(plain)
        report["fetched"].append(plain)
    for f in os.listdir(store):                    # nothing the manifest does not vouch for stays
        if NAME.match(f) and f.endswith(".json") and f not in good:
            os.remove(os.path.join(store, f))
    for f in os.listdir(store):                    # nor a sidecar without its file
        if f.endswith(".json.sha256") and NAME.match(f[:-7]) and f[:-7] not in good:
            os.remove(os.path.join(store, f))
    return report


def _still_good(local, sha):
    """A local file is kept only when its sidecar names the manifest's checksum and
    the file still hashes to what was written."""
    try:
        with open(local + ".sha256") as f:
            listed, own = f.read().split()
        if not sha or listed != sha:
            return False
        h = hashlib.sha256()
        with open(local, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest() == own
    except (OSError, ValueError):
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("publish")
    p.add_argument("--store", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--keep", type=int, default=KEEP)
    f = sub.add_parser("fetch")
    f.add_argument("base_url")
    f.add_argument("--store", required=True)
    a = ap.parse_args()
    try:
        if a.cmd == "publish":
            m = publish(a.store, a.out, a.keep)
            print("published %d files, %d skipped" % (len(m["files"]), len(m["skipped"])))
        else:
            r = fetch(a.base_url, a.store)
            print("fetched %d, had %d, rejected %d" % (len(r["fetched"]), len(r["had"]), len(r["rejected"])))
            for x in r["rejected"]:
                print("  rejected %s: %s" % (x["name"], x["why"]), file=sys.stderr)
    except HandoffError as e:
        sys.exit("flows-handoff: %s" % e)


if __name__ == "__main__":
    main()
