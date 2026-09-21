#!/bin/sh
# build_site.sh — the whole public site, from one morning's photograph of the market.
#
# Run by .github/workflows/daily.yml. It keeps NO market data in this repository's
# history: the rolling window lives only on the published site. Each run reads that
# window back (checking every file), adds today, drops what is older than 8 days,
# rebuilds every seller page, and hands the result to GitHub Pages.
set -eu
SITE=https://ausrine-labs.github.io/x402-atlas
rm -rf store _site && mkdir -p store _site

# 1. yesterday's window, from the live site; from this repo's radar/ only if the site has none
python3 tools/snapshot_handoff.py fetch "$SITE/radar/" --store store || {
  echo "::warning::no published window on the site; seeding from radar/ in the repository"
  for f in radar/market-*.json.gz; do [ -f "$f" ] && gunzip -c "$f" > "store/$(basename "${f%.gz}")"; done
}

# 2. today's photograph. A failed scan is not fatal: the site is rebuilt from the last good day.
RADAR_STORE=store python3 tools/radar.py snapshot || echo "::warning::today's scan failed; rebuilding from the last good day"

# 3. never build from a broken photograph (this registry was once silently truncated)
python3 - <<'PY'
import glob, os, re, sys
sys.path.insert(0, "tools")
import snapshot_handoff as sh
for f in sorted(glob.glob("store/market-*.json")):
    day = re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
    why = sh.check_snapshot(open(f, "rb").read(), day, sh.FLOOR)
    if why:
        print("::warning::dropping %s: %s" % (f, why)); os.remove(f)
if not glob.glob("store/market-*.json"):
    sys.exit("no usable snapshot at all: refusing to deploy an empty site")
PY

# 4. the site
for p in index.html market.html data LICENSE README.md robots.txt; do [ -e "$p" ] && cp -R "$p" _site/; done
python3 tools/snapshot_handoff.py publish --store store --out _site/radar
python3 tools/seller_pages.py --out _site --store store
touch _site/.nojekyll
du -sh _site | cut -f1
