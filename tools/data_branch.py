#!/usr/bin/env python3
"""data_branch.py — today's published window, added to the `data` branch as one commit.

The site's radar/ and flows/ directories are also kept on this repository's `data`
branch, so a program (the paid seller, tomorrow's build) can read them from
raw.githubusercontent.com: https, no redirect, whatever happens to the site's address.

    python3 tools/data_branch.py merge --new <site dir> --branch <data branch checkout>

Rules (Map Room ruling AUSRINE-ATLAS-DATA-BRANCH-2026-09-27):
  - a date-named file, once published on the branch, is never rewritten. When today's
    build made the same name again with the same content, the published bytes stay;
    with different content (a same-day rerun), the published file stays and a warning
    says so. The branch's manifest always describes the bytes on the branch.
  - every file today's manifest names must be present and match its sha256 before
    anything is written; a partial window fails here, before any commit.
  - files that fell out of the window leave the tree; the branch history keeps them.
Standard library only. Exit 1 on any refusal.
"""

import argparse
import gzip
import hashlib
import json
import os
import sys

DIRS = ("radar", "flows")          # radar is required; flows may be absent on a bad day
MAX_JSON = 64 * 1024 * 1024


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def unzipped(b):
    return gzip.GzipFile(fileobj=__import__("io").BytesIO(b)).read(MAX_JSON + 1)


def load_window(d):
    """Today's manifest and its files, all checked. Raises ValueError on anything partial."""
    manifest = json.loads(read(os.path.join(d, "manifest.json")))
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("%s: the manifest names no files" % d)
    data = {}
    for f in files:
        name = f.get("name", "")
        if not name or "/" in name or name.startswith("."):
            raise ValueError("%s: a bad file name in the manifest: %r" % (d, name))
        p = os.path.join(d, name)
        if not os.path.isfile(p):
            raise ValueError("%s: %s is in the manifest but not published" % (d, name))
        b = read(p)
        if sha(b) != f.get("sha256") or len(b) != f.get("bytes"):
            raise ValueError("%s: %s does not match its manifest entry" % (d, name))
        data[name] = b
    return manifest, data


def merge_dir(new_dir, branch_dir, warn):
    manifest, data = load_window(new_dir)
    os.makedirs(branch_dir, exist_ok=True)
    out = []
    for f in manifest["files"]:
        name, b = f["name"], data[f["name"]]
        dst = os.path.join(branch_dir, name)
        entry = dict(f)
        if os.path.isfile(dst):
            old = read(dst)
            if sha(old) != sha(b):
                if unzipped(old) != unzipped(b):
                    warn("%s: already published with different content; the published file stays"
                         % os.path.join(os.path.basename(branch_dir), name))
                entry.update(sha256=sha(old), bytes=len(old))
        else:
            with open(dst, "wb") as fh:
                fh.write(b)
        out.append(entry)
    keep = {e["name"] for e in out}
    for f in os.listdir(branch_dir):
        if f.endswith(".json.gz") and f not in keep:
            os.remove(os.path.join(branch_dir, f))
    manifest = dict(manifest, files=out)
    with open(os.path.join(branch_dir, "manifest.json"), "wb") as fh:
        fh.write(json.dumps(manifest, indent=1, sort_keys=True).encode())
    load_window(branch_dir)                        # the branch must now be a complete window
    return len(out)


def merge(new, branch, warn=lambda m: print("::warning::" + m)):
    if not os.path.isfile(os.path.join(new, "radar", "manifest.json")):
        raise ValueError("no radar window in today's build: nothing is published")
    report = {}
    for d in DIRS:
        src = os.path.join(new, d)
        if not os.path.isfile(os.path.join(src, "manifest.json")):
            warn("no %s window in today's build; the branch keeps what it has" % d)
            continue
        report[d] = merge_dir(src, os.path.join(branch, d), warn)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("--new", required=True, help="the built site directory (holds radar/ and flows/)")
    m.add_argument("--branch", required=True, help="a checkout of the data branch")
    a = ap.parse_args()
    try:
        print("data-branch:", merge(a.new, a.branch))
    except (ValueError, OSError) as e:
        sys.exit("data-branch: refusing: %s" % e)


if __name__ == "__main__":
    main()
