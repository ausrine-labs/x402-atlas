#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit a0d9190). Edit it there, not here.
"""where_hosted.py — /where/: the countries x402 sellers' servers answer from.

At build time each seller host is resolved to its addresses (A and AAAA, through the
standard resolver, a few at a time, each with a short timeout) and each address is
looked up in DB-IP's free "IP to Country Lite" file (CC BY 4.0), downloaded in the
build step into a cache outside the repository and never committed. A host whose
addresses belong to Cloudflare or a similar edge network is counted as "behind a CDN"
and not placed: the address says where the edge is, not where the seller runs.

The map is an equirectangular SVG of country centroids from a small table bundled
here — no tiles, no external requests from the page. One dot per country, sized by
sellers; a second map sizes the same dots by USDC received on the rollup's days.

This is where servers answer from, often a cloud region. It is not where anyone lives.

    where_hosted.py fetch-dbip --cache ~/.cache/dbip
    where_hosted.py --snapshot market-2026-09-24.json --whales whales-2026-09-24.json \
                    --dbip ~/.cache/dbip/dbip-country-lite-2026-09.csv.gz --out _site

where_body(data) is the fragment; write(out, data) wraps it. Standard library only.
"""

import argparse
import bisect
import collections
import csv
import gzip
import io
import ipaddress
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import date, timedelta

import coverage_page as cp

DBIP_URL = "https://download.db-ip.com/free/dbip-country-lite-%s.csv.gz"
DBIP_MAX = 64 * 1024 * 1024
TIMEOUT_S = 3.0
WORKERS = 16
TOTAL_S = 240.0          # the whole resolve step, however many hosts; the rest are marked, not waited for

# Edge networks: an address inside one of these says where the edge is, not the seller.
# Prefixes are the providers' own published ranges (Cloudflare publishes its list at
# cloudflare.com/ips; Fastly at api.fastly.com/public-ip-list), trimmed to the well-known
# blocks. A canonical name ending in one of the suffixes counts too.
CDN_NETS = {
    "Cloudflare": ["173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18",
                   "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17",
                   "162.158.0.0/15", "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
                   "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32",
                   "2a06:98c0::/29", "2c0f:f248::/32"],
    "Fastly": ["151.101.0.0/16", "199.232.0.0/16", "23.235.32.0/20", "43.249.72.0/22", "103.244.50.0/24",
               "103.245.222.0/23", "103.245.224.0/24", "104.156.80.0/20", "140.248.64.0/18", "140.248.128.0/17",
               "146.75.0.0/17", "157.52.64.0/18", "167.82.0.0/17", "172.111.64.0/18", "185.31.16.0/22",
               "199.27.72.0/21", "2a04:4e40::/32", "2a04:4e42::/32"],
    "Vercel": ["76.76.21.0/24", "66.33.60.0/24"],
}
CDN_NAMES = {"cloudfront.net": "Amazon CloudFront", "cdn.cloudflare.net": "Cloudflare", "fastly.net": "Fastly",
             "fastlylb.net": "Fastly", "akamaiedge.net": "Akamai", "akamai.net": "Akamai", "edgekey.net": "Akamai",
             "edgesuite.net": "Akamai", "vercel-dns.com": "Vercel", "netlify.app": "Netlify", "azurefd.net": "Azure Front Door",
             "azureedge.net": "Azure CDN", "b-cdn.net": "Bunny CDN", "cdn77.org": "CDN77"}
_NETS = [(name, ipaddress.ip_network(n)) for name, ns in CDN_NETS.items() for n in ns]

# Approximate country centroids (latitude, longitude), for placing one dot per country.
CENTROIDS = {
    "AD": (42.5, 1.5), "AE": (24.0, 54.0), "AF": (33.9, 67.7), "AG": (17.1, -61.8), "AL": (41.2, 20.2),
    "AM": (40.1, 45.0), "AO": (-11.2, 17.9), "AR": (-38.4, -63.6), "AT": (47.5, 14.6), "AU": (-25.3, 133.8),
    "AZ": (40.1, 47.6), "BA": (43.9, 17.7), "BB": (13.2, -59.5), "BD": (23.7, 90.4), "BE": (50.5, 4.5),
    "BF": (12.2, -1.6), "BG": (42.7, 25.5), "BH": (26.0, 50.6), "BJ": (9.3, 2.3), "BN": (4.5, 114.7),
    "BO": (-16.3, -63.6), "BR": (-14.2, -51.9), "BS": (25.0, -77.4), "BT": (27.5, 90.4), "BW": (-22.3, 24.7),
    "BY": (53.7, 28.0), "BZ": (17.2, -88.5), "CA": (56.1, -106.3), "CD": (-4.0, 21.8), "CF": (6.6, 20.9),
    "CG": (-0.2, 15.8), "CH": (46.8, 8.2), "CI": (7.5, -5.5), "CL": (-35.7, -71.5), "CM": (7.4, 12.4),
    "CN": (35.9, 104.2), "CO": (4.6, -74.3), "CR": (9.7, -83.8), "CU": (21.5, -77.8), "CY": (35.1, 33.4),
    "CZ": (49.8, 15.5), "DE": (51.2, 10.5), "DK": (56.3, 9.5), "DO": (18.7, -70.2), "DZ": (28.0, 1.7),
    "EC": (-1.8, -78.2), "EE": (58.6, 25.0), "EG": (26.8, 30.8), "ES": (40.5, -3.7), "ET": (9.1, 40.5),
    "FI": (61.9, 25.7), "FJ": (-17.7, 178.1), "FR": (46.2, 2.2), "GA": (-0.8, 11.6), "GB": (55.4, -3.4),
    "GE": (42.3, 43.4), "GH": (7.9, -1.0), "GI": (36.1, -5.4), "GR": (39.1, 21.8), "GT": (15.8, -90.2),
    "GU": (13.4, 144.8), "HK": (22.3, 114.2), "HN": (15.2, -86.2), "HR": (45.1, 15.2), "HT": (19.0, -72.3),
    "HU": (47.2, 19.5), "ID": (-0.8, 113.9), "IE": (53.4, -8.2), "IL": (31.0, 34.9), "IM": (54.2, -4.5),
    "IN": (20.6, 79.0), "IQ": (33.2, 43.7), "IR": (32.4, 53.7), "IS": (65.0, -19.0), "IT": (41.9, 12.6),
    "JE": (49.2, -2.1), "JM": (18.1, -77.3), "JO": (30.6, 36.2), "JP": (36.2, 138.3), "KE": (-0.0, 37.9),
    "KG": (41.2, 74.8), "KH": (12.6, 105.0), "KR": (35.9, 127.8), "KW": (29.3, 47.5), "KY": (19.3, -81.3),
    "KZ": (48.0, 66.9), "LA": (19.9, 102.5), "LB": (33.9, 35.9), "LI": (47.2, 9.6), "LK": (7.9, 80.8),
    "LT": (55.2, 23.9), "LU": (49.8, 6.1), "LV": (56.9, 24.6), "LY": (26.3, 17.2), "MA": (31.8, -7.1),
    "MC": (43.7, 7.4), "MD": (47.4, 28.4), "ME": (42.7, 19.4), "MG": (-18.8, 46.9), "MK": (41.6, 21.7),
    "ML": (17.6, -4.0), "MM": (21.9, 95.9), "MN": (46.9, 103.8), "MO": (22.2, 113.5), "MT": (35.9, 14.4),
    "MU": (-20.3, 57.6), "MV": (3.2, 73.2), "MX": (23.6, -102.6), "MY": (4.2, 102.0), "MZ": (-18.7, 35.5),
    "NA": (-22.96, 18.5), "NE": (17.6, 8.1), "NG": (9.1, 8.7), "NI": (12.9, -85.2), "NL": (52.1, 5.3),
    "NO": (60.5, 8.5), "NP": (28.4, 84.1), "NZ": (-40.9, 174.9), "OM": (21.5, 55.9), "PA": (8.5, -80.8),
    "PE": (-9.2, -75.0), "PG": (-6.3, 143.9), "PH": (12.9, 121.8), "PK": (30.4, 69.3), "PL": (51.9, 19.1),
    "PR": (18.2, -66.6), "PS": (31.9, 35.2), "PT": (39.4, -8.2), "PY": (-23.4, -58.4), "QA": (25.4, 51.2),
    "RO": (45.9, 25.0), "RS": (44.0, 21.0), "RU": (61.5, 105.3), "RW": (-1.9, 29.9), "SA": (23.9, 45.1),
    "SC": (-4.7, 55.5), "SD": (12.9, 30.2), "SE": (60.1, 18.6), "SG": (1.35, 103.8), "SI": (46.2, 15.0),
    "SK": (48.7, 19.7), "SN": (14.5, -14.5), "SO": (5.2, 46.2), "SV": (13.8, -88.9), "SY": (34.8, 39.0),
    "TH": (15.9, 101.0), "TJ": (38.9, 71.3), "TN": (33.9, 9.5), "TR": (39.0, 35.2), "TT": (10.7, -61.2),
    "TW": (23.7, 121.0), "TZ": (-6.4, 34.9), "UA": (48.4, 31.2), "UG": (1.4, 32.3), "US": (37.1, -95.7),
    "UY": (-32.5, -55.8), "UZ": (41.4, 64.6), "VE": (6.4, -66.6), "VG": (18.4, -64.6), "VN": (14.1, 108.3),
    "YE": (15.6, 48.5), "ZA": (-30.6, 22.9), "ZM": (-13.1, 27.8), "ZW": (-19.0, 29.2),
}


def bare(host):
    """The name to resolve: no port, no brackets, no trailing dot, no www."""
    h = (host or "").strip().lower()
    if h.startswith("["):
        return h[1:h.index("]")] if "]" in h else h[1:]
    if h.count(":") == 1:
        h = h.split(":")[0]
    return h.rstrip(".")


def resolve_one(host):
    """(canonical name, sorted addresses) through the standard resolver, A and AAAA."""
    name = bare(host)
    try:
        ipaddress.ip_address(name)
        return name, [name]
    except ValueError:
        pass
    infos = socket.getaddrinfo(name, 443, 0, socket.SOCK_STREAM, 0, socket.AI_CANONNAME)
    canon = next((i[3] for i in infos if i[3]), name)
    return canon.lower().rstrip("."), sorted({i[4][0] for i in infos})


def resolve_all(hosts, resolve=resolve_one, workers=WORKERS, timeout=TIMEOUT_S, total=TOTAL_S):
    """{host: {"canon", "ips"} or {"error"}}: `workers` at a time, each given `timeout` seconds,
    the whole run at most about `total` seconds. Lookups run on daemon threads: one the
    resolver never answers is recorded as a timeout and abandoned, and cannot keep the build
    from exiting (a pool's threads are joined at exit; these are not). Hosts not reached
    before the total runs out are recorded as "time limit"."""
    out = {}
    hosts = sorted(set(hosts))
    deadline = time.monotonic() + total
    for i in range(0, len(hosts), workers):
        wave = hosts[i:i + workers]
        left = deadline - time.monotonic()
        if left <= 0:
            for h in hosts[i:]:
                out[h] = {"error": "time limit"}
            break
        answers, threads = {}, []
        for h in wave:
            def run(h=h):
                try:
                    canon, ips = resolve(h)
                    answers[h] = {"canon": canon, "ips": list(ips)}
                except Exception as e:
                    answers[h] = {"error": type(e).__name__}
            t = threading.Thread(target=run, name="resolve " + h, daemon=True)
            t.start()
            threads.append(t)
        stop = time.monotonic() + min(timeout, left)
        for t in threads:
            t.join(max(0.0, stop - time.monotonic()))
        for h in wave:
            out[h] = dict(answers[h]) if h in answers else {"error": "timeout"}
    return out


def cdn_of(canon, ips):
    """The edge network a host sits behind, or None."""
    for suffix, name in CDN_NAMES.items():
        if canon == suffix or (canon or "").endswith("." + suffix):
            return name
    for ip in ips:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        for name, net in _NETS:
            if a.version == net.version and a in net:
                return name
    return None


class CountryDB:
    """DB-IP's country CSV (ip_start, ip_end, country), IPv4 and IPv6, looked up by bisection."""

    def __init__(self, rows):
        by = {4: [], 6: []}
        for start, end, cc in rows:
            try:
                a, b = ipaddress.ip_address(start), ipaddress.ip_address(end)
            except ValueError:
                continue
            by[a.version].append((int(a), int(b), cc.upper()))
        self.tables = {}
        for v, t in by.items():
            t.sort()
            self.tables[v] = ([r[0] for r in t], t)

    @classmethod
    def load(cls, path):
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", newline="") as f:
            return cls((r[0], r[1], r[2]) for r in csv.reader(f) if len(r) >= 3)

    def country(self, ip):
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return None
        starts, rows = self.tables.get(a.version, ([], []))
        i = bisect.bisect_right(starts, int(a)) - 1
        if i >= 0 and rows[i][0] <= int(a) <= rows[i][1] and rows[i][2] not in ("ZZ", "--", ""):
            return rows[i][2]
        return None


def fetch_dbip(cache, today=None, get=None):
    """Download this month's (or last month's) DB-IP Country Lite file into `cache` and
    return its path. Kept out of the repository by .gitignore; never committed."""
    today = today or date.today()
    months = [today.strftime("%Y-%m"), (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")]
    os.makedirs(cache, exist_ok=True)

    def http(url):
        req = urllib.request.Request(url, headers={"User-Agent": "infoharmoni-atlas-build/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read(DBIP_MAX + 1)
        if len(data) > DBIP_MAX:
            raise ValueError("larger than %d bytes" % DBIP_MAX)
        return data

    get = get or http
    errors = []
    for m in months:
        path = os.path.join(cache, "dbip-country-lite-%s.csv.gz" % m)
        if os.path.exists(path):
            return path
        try:
            data = get(DBIP_URL % m)
            gzip.GzipFile(fileobj=io.BytesIO(data)).read(1024)       # it is a gzip file, or it is not kept
        except Exception as e:
            errors.append("%s: %s" % (m, str(e)[:80] or type(e).__name__))
            continue
        fd, tmp = tempfile.mkstemp(dir=cache, prefix=".tmp-")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return path
    raise RuntimeError("DB-IP Country Lite could not be downloaded: " + "; ".join(errors))


def where_data(sellers, rollup=None, resolved=None, db=None, as_of="", dbip_name="", site=""):
    """Place each seller host. sellers: the snapshot's {host: row}. resolved: resolve_all's
    answer. db: a CountryDB, or None when the file could not be had."""
    resolved = resolved or {}
    classified = cp.classified_chains(rollup)
    usdc = collections.Counter()
    for s in (rollup or {}).get("sellers") or []:
        usdc[s["host"]] += cp.paid(s, classified)[0]
    countries = collections.defaultdict(lambda: {"sellers": 0, "usdc": 0.0, "hosts": []})
    cdn, unresolved, unplaced = collections.Counter(), [], []
    for host in sorted(sellers):
        r = resolved.get(host)
        if not r or "error" in r or not r.get("ips"):
            unresolved.append(host)
            continue
        c = cdn_of(r.get("canon", ""), r["ips"])
        if c:
            cdn[c] += 1
            continue
        ccs = collections.Counter(cc for cc in (db.country(ip) if db else None for ip in r["ips"]) if cc)
        if not ccs:
            unplaced.append(host)
            continue
        cc = sorted(ccs.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        row = countries[cc]
        row["sellers"] += 1
        row["usdc"] += usdc.get(host, 0.0)
        row["hosts"].append(host)
    rows = [{"cc": cc, "sellers": v["sellers"], "usdc": round(v["usdc"], 2),
             "hosts": sorted(v["hosts"], key=lambda h: (-usdc.get(h, 0.0), h))[:8],
             "placed": cc in CENTROIDS} for cc, v in countries.items()]
    rows.sort(key=lambda r: (-r["sellers"], -r["usdc"], r["cc"]))
    return {"as_of": as_of or (rollup or {}).get("as_of", ""), "days": ", ".join((rollup or {}).get("dates") or []),
            "site": cp.site_path(site), "classified": sorted(classified), "chains_covered": cp.chains_of(rollup),
            "timed_out": sum(1 for h in sellers if (resolved.get(h) or {}).get("error") in ("timeout", "time limit")),
            "have_db": db is not None, "dbip": dbip_name,
            "hosts": len(sellers), "countries": rows,
            "cdn": dict(sorted(cdn.items(), key=lambda kv: -kv[1])), "behind_cdn": sum(cdn.values()),
            "unresolved": len(unresolved), "unplaced": len(unplaced),
            "placed": sum(r["sellers"] for r in rows)}


def project(lat, lon, w=1000, h=500):
    return (lon + 180.0) / 360.0 * w, (90.0 - lat) / 180.0 * h


def map_svg(rows, key, label, fmt, w=1000, h=500):
    """One equirectangular field: a graticule, and a dot per country sized by rows[key]."""
    o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (w, h, cp.esc(label))]
    for lon in range(-150, 181, 30):
        x = project(0, lon, w, h)[0]
        o.append('<line x1="%.1f" y1="0" x2="%.1f" y2="%d" stroke="#e7e5df"/>' % (x, x, h))
    for lat in range(-60, 61, 30):
        y = project(lat, 0, w, h)[1]
        o.append('<line x1="0" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>' % (y, w, y, "#d6d3ca" if lat == 0 else "#e7e5df"))
    top = max([r[key] for r in rows if r["placed"]] or [0])
    for r in sorted((r for r in rows if r["placed"] and r[key] > 0), key=lambda r: -r[key]):
        lat, lon = CENTROIDS[r["cc"]]
        x, y = project(lat, lon, w, h)
        rad = 3 + 27 * (r[key] / top) ** 0.5 if top else 3
        o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#e0a93b" fill-opacity="0.55" stroke="#0b7a55" stroke-width="1">'
                 '<title>%s: %s</title></circle>' % (x, y, rad, cp.esc(r["cc"]), cp.esc(fmt(r[key]))))
        if rad >= 8:
            o.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="11" font-family="monospace" fill="#102a23">%s</text>'
                     % (x, y + 4, cp.esc(r["cc"])))
    o.append("</svg>")
    return "".join(o)


def where_body(data):
    rows = data["countries"]
    x402 = cp.basis(set(data["classified"]), data["chains_covered"])
    site = data.get("site", "")
    parts = ['<section class="where">', "<h1>Where sellers are hosted</h1>",
             '<p class="muted">The countries x402 sellers\' servers answer from, resolved <span class="dated">%s</span>. '
             "This is where a server answers from, often a cloud region. It is not where anyone lives, and it says "
             "nothing about who runs a seller.</p>" % cp.esc(data["as_of"])]
    if data["have_db"]:
        unplaced = (", %s resolved to addresses the country file does not place" % "{:,}".format(data["unplaced"])
                    if data["unplaced"] else "")
    else:
        unplaced = ", %s resolved but cannot be placed without the country file" % "{:,}".format(data["unplaced"])
    parts.append("<p>%s looked up. %s placed in %s. %s behind a CDN, not placed. %s did not resolve%s.</p>" % (
        cp.num(data["hosts"], "seller host"), cp.num(data["placed"], "seller"), cp.num(len(rows), "country", "countries"),
        cp.num(data["behind_cdn"], "seller"),
        "{:,}".format(data["unresolved"]) + (" (%s of them ran out of time)" % "{:,}".format(data["timed_out"])
                                             if data.get("timed_out") else ""), unplaced))
    if not data["have_db"]:
        parts.append('<p class="notice">The country file could not be had for this build, so no seller is placed and no '
                     "map is drawn. The CDN and resolution counts above still hold.</p>")
    elif any(r["placed"] for r in rows):
        parts.append("<h2>By sellers</h2>")
        parts.append(map_svg(rows, "sellers", "Seller hosts by country", lambda v: cp.num(v, "seller")))
        parts.append('<h2>By USDC received</h2><p class="muted">%s on <span class="dated">%s</span>, by the country of the '
                     "seller's server.</p>" % (cp.esc(x402), cp.esc(data["days"] or data["as_of"])))
        parts.append(map_svg(rows, "usdc", "USDC received by country", cp.money))
    if rows:
        parts.append('<div class="wrap"><table><thead><tr><th>country</th><th class="num">sellers</th><th class="num">USDC</th>'
                     "<th>busiest hosts</th></tr></thead><tbody>")
        for r in rows:
            parts.append('<tr><td class="addr">%s%s</td><td class="num">%s</td><td class="num">%s</td><td>%s</td></tr>' % (
                cp.esc(r["cc"]), "" if r["placed"] else " (not on the map)", "{:,}".format(r["sellers"]),
                cp.esc(cp.money(r["usdc"])), ", ".join(cp.seller_html(h, site) for h in r["hosts"][:5])))
        parts.append("</tbody></table></div>")
    if data["cdn"]:
        parts.append("<h2>Behind a CDN</h2><p>%s</p>" % " · ".join(
            "%s: %s" % (cp.esc(k), "{:,}".format(v)) for k, v in data["cdn"].items()))
    parts.append('<p class="muted">How: each host resolved through the standard resolver (A and AAAA), each address looked '
                 "up in a country table; a host is counted once, in the country most of its addresses fall in. A host whose "
                 "addresses or canonical name belong to an edge network is counted as behind a CDN, because the address "
                 "shows the edge, not the server. Dots sit on country centroids.</p>")
    parts.append('<p class="muted">IP to country data: <a href="https://db-ip.com">IP Geolocation by DB-IP</a>, '
                 '"IP to Country Lite"%s, licensed under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.</p>'
                 % (" (%s)" % cp.esc(data["dbip"]) if data["dbip"] else ""))
    parts.append("</section>")
    return "".join(parts)


def write(out, data):
    return cp.write(out, "where", cp.page("Where sellers are hosted", where_body(data), data["as_of"],
                                          "The countries x402 sellers' servers answer from.",
                                          room="where", root=data.get("site", "")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd")
    f = sub.add_parser("fetch-dbip", help="download the DB-IP Country Lite file into a cache")
    f.add_argument("--cache", required=True)
    ap.add_argument("--snapshot")
    ap.add_argument("--whales")
    ap.add_argument("--site", default="")
    ap.add_argument("--dbip", help="the DB-IP country CSV (.csv or .csv.gz); without it no seller is placed")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "fetch-dbip":
        print(fetch_dbip(a.cache))
        return
    if not (a.snapshot and a.out):
        ap.error("--snapshot and --out are needed to build the page")
    snap = json.load(open(a.snapshot))
    rollup = json.load(open(a.whales)) if a.whales else None
    db = CountryDB.load(a.dbip) if a.dbip else None
    resolved = resolve_all(snap["sellers"])
    d = where_data(snap["sellers"], rollup, resolved, db, date.today().isoformat(), os.path.basename(a.dbip or ""), a.site)
    print("where: %d hosts, %d placed in %d countries, %d behind a CDN, %d unresolved -> %s" % (
        d["hosts"], d["placed"], len(d["countries"]), d["behind_cdn"], d["unresolved"], write(a.out, d)))


if __name__ == "__main__":
    sys.exit(main())
