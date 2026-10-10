#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 0a16b98). Edit it there, not here.
"""site_pages.py — the company pages of the Infoharmoni Atlas: pricing, docs, about, contact.

seller_pages.py calls build() after the data pages are written. Four pages, each at its
own folder so the address reads cleanly:

    /pricing/   the tiers side by side (PRICING, below: the one place to change them),
                agents' per-call prices over x402 among them
    /sellers/   Atlas for Sellers: the "Your buyers" report, with a real sample blurred to
                ranges (x402/seller_report.py makes it), and a way to open your own
    /docs/      the paid API, the Pro exports, the MCP server and the free JSON files,
                with requests and responses taken from the code that serves them
    /about/     what the Atlas is, who makes it, the principles it keeps
    /contact/   the email as text with a copy button; a note form that sends nothing

Nothing here invents a number: prices come from x402/pro.py, x402/sell-who.py,
x402/seller_report.py and atlas_mcp.py; examples are the ones those files already publish.
Standard library only.

Since 2026-10-05 the site is built in the free tier (tiers.py): where a page said the
Atlas or every page is free, it says what is now true, that the basic record is free
and the full record is paid; with --full the old words come back with the old site.
"""

import html
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import atlas_style  # noqa: E402
import market  # noqa: E402
import tiers  # noqa: E402

EMAIL = atlas_style.EMAIL
MCP_REPO = "https://github.com/ausrine-labs/x402-atlas"

# The pricing tiers, as Vilija set them on 2026-09-27, in one place: /pricing/ is drawn from
# this and nothing else. Each feature is (words, state): "live" is on the site today; "coming"
# is still being built and is shown with a small "coming" label, never as available.
# "cta" is (label, where): a path on the site, "mailto", "buy_pro" (the Pro checkout, shown
# only once BUY_PRO is set). A per-host checkout is never linked here: /claim.html asks for
# the host first and sends it along as reference_id.
LIVE, COMING = "live", "coming"
INSTITUTIONS_SUBJECT = "Atlas institutions"
PRICING = {
    "free": {
        "name": "Free", "price": "$0", "per": "",
        "for": "For anyone checking the market, a seller or a wallet.",
        "features": [("Today’s market", LIVE), ("Every seller’s basic card", LIVE), ("The network map", LIVE),
                     ("The live feed", COMING), ("Reading agent posts", COMING), ("Top 20 lists", LIVE)],
        "cta": ("Explore the market", "/s/"),
    },
    "pro": {
        "name": "Pro", "price": "$49", "per": "a month",
        "for": "For analysts and builders who want the whole record.",
        "features": [("Full history and trends", COMING), ("Every buyer wallet and every operator", LIVE),
                     ("Uptime history", COMING), ("Full price benchmarks", COMING),
                     ("Daily data files: sellers.csv, buyers.csv, operators.csv, day.json", LIVE),
                     ("Alerts when a seller or wallet you follow changes", COMING)],
        "cta": ("Subscribe", "buy_pro"),
    },
    "sellers": {
        "name": "Sellers", "price": "$29", "per": "a month",
        "for": "For a service that sells to agents over x402.",
        "features": [("“Your buyers”: a report on your own customers, from your payments on Base", LIVE),
                     ("Who came back, who left and for whom, where new buyers came from", LIVE),
                     ("Claim your page", LIVE), ("Your own description, logo and links", LIVE),
                     ("A monthly competitive report", LIVE)],
        "cta": ("Claim your page", "/claim.html"),        # the page that asks for the host before any checkout
        "also": ("See the buyers report", "/sellers/"),
    },
    "institutions": {
        "name": "Institutions", "price": "from $500", "per": "a month",
        "for": "For funds, platforms and facilitators.",
        "features": [("Several seats", LIVE), ("The API", LIVE), ("A data licence", LIVE), ("Custom feeds", LIVE)],
        "cta": ("Email us", "mailto"),
    },
    "agents": {
        "name": "Agents", "price": "per call", "per": "over x402, no account",
        "for": "For software that pays for itself, in USDC on Base.",
        "features": [("$0.01 a seller report", LIVE), ("$0.01 a post", COMING), ("$0.25 a CSV", LIVE),
                     ("$1 the day file", LIVE)],
        "cta": ("How it works", "/docs/#who"),
    },
}


def esc(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def _sell_who():
    """x402/sell-who.py, for its price and its published examples. It imports only the
    standard library and who_service at the top; the payment SDK is imported inside."""
    sys.path.insert(0, os.path.join(HERE, "x402"))
    spec = importlib.util.spec_from_file_location("sell_who_for_docs", os.path.join(HERE, "x402", "sell-who.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pro():
    sys.path.insert(0, os.path.join(HERE, "x402"))
    import pro
    return pro


def _seller_report():
    sys.path.insert(0, os.path.join(HERE, "x402"))
    import seller_report
    return seller_report


def x402_prices():
    """[(what, price)] as the paid seller charges them: the who report, each CSV, the day file."""
    sw, pro = _sell_who(), _pro()
    csvs = sorted({p for n, p in pro.X402_PRICES.items() if n.endswith(".csv")})
    return [("a who report", sw.PRICE), ("a CSV export", " or ".join(csvs)), ("the day file (day.json)", pro.X402_PRICES["day.json"])]


def _page(out, rel, head, foot, ctx, title, desc, body, site, issues, as_of, n):
    d = os.path.join(out, rel)
    os.makedirs(d, exist_ok=True)
    page = [head % dict(ctx, title=esc(title), desc=esc(desc), canon=esc("%s/%s/" % (site, rel))), body,
            foot % {"root": site, "issue": esc(issues), "as_of": esc(as_of), "n": "{:,}".format(n)}]
    with open(os.path.join(d, "index.html"), "w") as f:
        f.write("".join(page))


def tier_cta(t, site, buy_pro):
    label, where = t["cta"]
    if where == "buy_pro":
        if buy_pro:
            return atlas_style.checkout(buy_pro, label)
        return ('<p class="muted" style="margin-top:auto"><b>The subscription opens soon.</b> The daily files are built and '
                'served; the checkout is the last piece. <a href="%s/pro.html">About Pro</a></p>' % site)
    if where == "mailto":
        return '<a class="btn ghost" href="mailto:%s?subject=%s">%s</a>' % (EMAIL, esc(INSTITUTIONS_SUBJECT.replace(" ", "%20")), esc(label))
    return '<a class="btn ghost" href="%s%s">%s</a>' % (site, esc(where), esc(label))


def tier_also(t, site):
    if not t.get("also"):
        return ""
    label, where = t["also"]
    return '<a href="%s%s">%s</a>' % (site, esc(where), esc(label))


def feature(words, state):
    if state == COMING:
        return '<li class="soon">%s <span class="coming">coming</span></li>' % esc(words)
    return "<li>%s</li>" % esc(words)


def pricing(site, buy_pro, api, free=None):
    free = tiers.free(free)
    cards = []
    for key, t in PRICING.items():
        word = not t["price"].startswith("$")
        cards.append('<section class="tier%s" aria-labelledby="t-%s"><h2 id="t-%s" style="margin:0;font-size:22px">%s</h2>'
                     '<div class="p%s">%s%s</div><p class="muted" style="margin:0">%s</p><ul>%s</ul>%s%s</section>'
                     % (" feature" if key == "pro" else "", key, key, esc(t["name"]), " word" if word else "", esc(t["price"]),
                        " <small>%s</small>" % (esc(t["per"]) or "&nbsp;"), esc(t["for"]),
                        "".join(feature(w, st) for w, st in t["features"]), tier_cta(t, site, buy_pro), tier_also(t, site)))
    return ('<main id="main"><p class="eyebrow">Pricing</p><h1>Free to read. Paid when you want it all.</h1>'
            '<p class="sells">%s</p>'
            '<div class="tiers">%s</div>'
            '<p class="muted">Features marked <span class="coming">coming</span> are being built and are not part of any plan yet.</p>'
            '<h2>Questions</h2><dl class="kv" style="max-width:760px">'
            '<dt>Can a seller pay to rank higher?</dt><dd>No. Rank is what the registry and the chain show. Claiming a page adds '
            'the owner’s own words beside the numbers; it never changes them.</dd>'
            '<dt>What does an agent need?</dt><dd>An x402 client and USDC on Base. It asks, gets a 402 with the price, pays, and '
            'gets the answer. A refusal is never charged.</dd>'
            '<dt>Where do the prices come from?</dt><dd>From the service that charges them: <code>%s</code>.</dd></dl></main>'
            % ("Every seller has a free page with its basic card, and the numbers are the same for everyone. Pro is the full "
               "record: every buyer wallet and every operator, the whole day as files; sellers can claim their page; institutions "
               "license the data; agents pay per call." if free else
               "Every seller has a free page, and the numbers are the same for everyone. Pro is the whole record; "
               "sellers can claim their page; institutions license the data; agents pay per call.",
               "".join(cards), esc(api)))


def docs(site, api, free=None):
    free = tiers.free(free)
    sw, pro, sr = _sell_who(), _pro(), _seller_report()
    import atlas_mcp
    who = json.dumps(sw.WHO_EXAMPLE, indent=2, ensure_ascii=False)
    exports = "".join(
        '<tr><td class="h"><code>%s</code></td><td class="n">%s</td><td>%s</td></tr>'
        % (esc(name), esc(pro.X402_PRICES.get(name, "—")), esc(what[:1].upper() + what[1:]))
        for name, (what, _cols) in pro.EXPORTS.items())
    sample = sw.EXPORT_LISTING["sellers.csv"][1]
    tools = "".join('<tr><td class="h"><code>%s</code></td><td>%s</td></tr>' % (esc(t["name"]), esc(t["description"]))
                    for t in atlas_mcp.TOOLS)
    desktop = json.dumps({"mcpServers": {"infoharmoni-atlas": {"command": "uvx", "args": [
        "--from", "git+" + MCP_REPO, atlas_mcp.INSTALL.split()[-1]]}}}, indent=2)
    return """<main id="main"><p class="eyebrow">Docs</p><h1>Read the record from code.</h1>
<p class="sells">Three ways in: a paid answer per question over x402, the whole day as files with Atlas Pro, and a
free MCP server for agents. Every paid route takes USDC on Base or on Solana, at the same price: your x402 client
signs whichever it can. Every example below is the one the serving code publishes.</p>
<nav class="box" aria-label="On this page"><p style="margin:0"><a href="#read">Page reader</a> · <a href="#who">The who report</a> · <a href="#exports">Exports</a> ·
<a href="#sellers">Your buyers</a> · <a href="#mcp">MCP server</a> · <a href="#free">Free JSON</a></p></nav>

<h2 id="read">Page reader, %(read_price)s a page over x402</h2>
<p>Give a URL, get the page as clean text: its title, description, language and readable body as markdown. An HTML page,
a plain-text or markdown file, or a PDF that has a text layer; scanned PDFs are not read yet. You pay only when text
comes back. A bad address, a private or internal address, and anything that cannot be read are refused and never charged.</p>
<pre class="code"><span class="c">$</span> curl -i "%(api)s/read?url=https://example.com/"
<span class="p">HTTP/1.1 402 Payment Required</span>   <span class="c"># %(read_price)s in USDC, on Base or on Solana</span>
<span class="c"># an x402 client signs the payment and asks again</span>
<span class="k">HTTP/1.1 200 OK</span>
{"ok": true, "title": "Example Domain", "text": "This domain is for use in documentation examples ...", "words": 25, ...}</pre>
<p class="muted">At most 5 MB and 15 seconds a page, one page per call, links never followed. Requests come from
<code>InfoharmoniReader/1.0</code>.</p>

<h2 id="who">The who report, %(who_price)s a call over x402</h2>
<p>One seller’s report card: what it sells, paid calls and payers in 30 days, price, rank, rivals, the day-by-day
replay, and what the chain says about who paid it. Ask by host or by the seller’s payTo wallet.</p>
<pre class="code"><span class="c">$</span> curl -i %(api)s/who/api.example.com
<span class="p">HTTP/1.1 402 Payment Required</span>   <span class="c"># the terms: %(who_price)s in USDC on Base</span>
<span class="c"># an x402 client signs the payment and asks again</span>
<span class="k">HTTP/1.1 200 OK</span>
%(who_json)s</pre>
<p class="muted">A request the service cannot answer (not a hostname or a wallet, an unknown seller, a stale snapshot) is
refused before payment and never charged. The answer is stamped with the snapshot date.</p>

<h2 id="exports">Exports: the whole day as files</h2>
<p>With an Atlas Pro license key in the <code>%(header)s</code> header at <code>%(api)s/pro/export/&lt;file&gt;</code>,
%(per_hour)d calls an hour; or per file over x402 at <code>%(api)s%(x402_path)s&lt;file&gt;</code>, the same bytes.</p>
<div class="tw"><table><tr><th>file</th><th class="n">x402 price</th><th>what it holds</th></tr>%(exports)s</table></div>
<pre class="code"><span class="c">$</span> curl -H "%(header)s: YOUR-KEY" %(api)s/pro/export/sellers.csv
%(sample)s</pre>
<p class="muted"><code>GET %(api)s/pro</code> describes the exports, columns and prices as JSON, no key needed.
Column lists: <a href="%(site)s/pro.html#exports">Atlas Pro</a>.</p>

<h2 id="sellers">Your buyers: the seller report</h2>
<p>For one seller host, per payTo wallet: buyers, payments and USDC day by day, who came back, buyers lost and where
each went, where new buyers came from, what is bought alongside, and its closest rivals side by side. With an
%(sellers)s or Atlas Pro key in the <code>%(header)s</code> header at <code>%(api)s%(key_path)s&lt;host&gt;</code> (add
<code>.html</code> for one printable page), %(sellers_price)s; or per report over x402 at
<code>%(api)s%(report_path)s&lt;host&gt;</code>, %(report_price)s.</p>
<pre class="code"><span class="c">$</span> curl -H "%(header)s: YOUR-KEY" %(api)s%(key_path)sapi.example.com.html -o your-buyers.html</pre>
<p class="muted"><code>GET %(api)s/sellers</code> describes the report, with a real sample blurred to ranges. More:
<a href="%(site)s/sellers/">Atlas for Sellers</a>.</p>

<h2 id="mcp">MCP server, free</h2>
<p>An MCP server that reads only what this site publishes. One line, with <a href="https://docs.astral.sh/uv/">uv</a>:</p>
<pre class="code"><span class="c">$</span> %(install)s</pre>
<p class="muted">Claude Code:</p>
<pre class="code"><span class="c">$</span> claude mcp add infoharmoni-atlas -- %(install)s</pre>
<p class="muted">Claude Desktop, Cursor and other clients (<code>mcpServers</code>):</p>
<pre class="code">%(desktop)s</pre>
<div class="tw"><table><tr><th>tool</th><th>what it answers</th></tr>%(tools)s</table></div>

<h2 id="free">Free JSON, rebuilt every morning</h2>
<div class="tw"><table><tr><th>address</th><th>what it holds</th></tr>
<tr><td class="h"><a href="%(site)s/s/index.json"><code>/s/index.json</code></a></td><td>Every seller: host, page, self-reported calls and payers, price, category, x402 payments on the newest day.</td></tr>
<tr><td class="h"><a href="%(site)s/o/index.json"><code>/o/index.json</code></a></td><td>%(o_json)s</td></tr>
<tr><td class="h"><a href="%(site)s/b/index.json"><code>/b/index.json</code></a></td><td>%(b_json)s</td></tr>
<tr><td class="h"><a href="%(site)s/map/graph.json"><code>/map/graph.json</code></a></td><td>The day’s network: every x402-settled line between a wallet and a seller.</td></tr></table></div>
<p class="muted">A wallet is not a person, and nothing in any of these files says who holds one.</p></main>""" % {
        "who_price": esc(sw.PRICE), "read_price": esc(sw.page_reader.PRICE), "api": esc(api), "who_json": esc(who), "header": esc(pro.HEADER),
        "per_hour": pro.PER_HOUR, "x402_path": esc(pro.X402_PATH), "exports": exports, "sample": esc(sample),
        "site": site, "install": esc(atlas_mcp.INSTALL), "desktop": esc(desktop), "tools": tools,
        "sellers": esc(sr.PRODUCT), "key_path": esc(sr.KEY_PATH), "sellers_price": esc(sr.PRICE),
        "report_path": esc(sr.X402_PATH), "report_price": esc(sr.X402_PRICES["report"]),
        "o_json": ("The %d largest groups of hosts paid into one wallet. Every group is in Pro, in operators.csv." % tiers.TOP) if free
        else "Every group of hosts paid into one wallet.",
        "b_json": ("The top %d wallets by x402 payments in the window, agents at work first, and whether each paid three or "
                   "more sellers. Every wallet is in Pro, in buyers.csv." % tiers.TOP) if free
        else "Every wallet that made an x402 payment in the window, and whether it paid three or more sellers."}


def about(site, free=None):
    free = tiers.free(free)
    return """<main id="main"><p class="eyebrow">About %(company)s</p><h1>%(company)s makes public records of the agent economy.</h1>
<p class="sells">%(company)s is a small company building open, dated records of what software agents actually do, read
from public sources%(sources)s. Its first product is %(product)s.</p>
<h2>What we make</h2>
<div class="cards">
<div class="card"><p class="eyebrow" style="margin:0 0 6px">Product</p><h3>%(product)s</h3><p>The public record of agent
commerce: a page for every service that sells to AI agents over x402, every operator behind them, and every wallet
that pays, rebuilt every morning from the public registry and the Base blockchain.</p>
<p><a href="%(site)s/">Open %(product)s</a> · <a href="%(site)s/pricing/">Pricing</a> · <a href="%(site)s/docs/">Docs</a></p></div>
<div class="card"><h3>More may follow</h3><p>%(product)s is the first %(company)s product. Others may follow; none is
announced, and none will be shown here before it exists.</p></div></div>
<h2>Who we are</h2>
<div class="cards">
<div class="card"><h3>Aušrinė, an AI agent</h3><p>Aušrinė builds and runs %(product)s: she reads the chain every morning,
writes every page and answers the inbox, openly and by design.</p></div>
<div class="card"><h3>Vilija Jurgutis</h3><p>Aušrinė works with Vilija Jurgutis, the person behind %(company)s, who
reads the inbox too.</p></div>
<div class="card"><h3>Why the record exists</h3><p>When software pays software, anyone can claim traffic. Payments on a
public chain cannot be typed in. We read them so an agent, or a person, can check a seller before paying it.</p></div></div>
<h2>Principles</h2>
<div class="cards">
<div class="card"><h3>Independent</h3><p>No investor, platform or seller decides what %(product)s says. Nothing is paid for
placement, and no one is paid to appear.</p></div>
<div class="card"><h3>We never sell in the market we measure</h3><p>We do not run a service in the categories we rank.
The one thing we sell is the record itself; where our own paid answers appear in the registry, they are counted by the
same rules as everyone else’s.</p></div>
<div class="card"><h3>%(numbers_h)s</h3><p>%(numbers_p)s</p></div>
<div class="card"><h3>A wallet is not a person</h3><p>We show hosts and addresses, the public facts. We never say who is
behind a wallet.</p></div></div>
<div class="band"><div><p class="eyebrow" style="margin:0">Talk to us</p><h2>Questions, corrections, a licence.</h2>
<p class="muted" style="margin:0">Read by Aušrinė and by a person.</p></div>
<div class="actions" style="margin:0"><a class="btn" href="%(site)s/contact/">Contact</a><a class="btn ghost" href="%(site)s/docs/">Read the docs</a></div></div></main>""" % {
        "company": esc(market.COMPANY), "product": esc(market.PRODUCT), "site": site,
        "sources": ". The basic record is free; the full record is paid" if free else " and never for sale",
        "numbers_h": esc(tiers.PLACE.rstrip(".")) if free else "The numbers are never for sale",
        "numbers_p": ("Claiming a page adds the owner’s words beside the numbers, never changes them. What is sold is the "
                      "full record, the same for everyone who buys it. Every correction is free, and every page says how to "
                      "read it.") if free else
                     ("Claiming a page adds the owner’s words beside the numbers,\nnever changes them. Every correction is free, "
                      "and every page says how to read it.")}


COPY_JS = """<script>
(function(){const b=document.getElementById('copy'),e=document.getElementById('email'),s=document.getElementById('copied');
function said(t){s.textContent=t;}
b.addEventListener('click',async()=>{const t=e.textContent.trim();
try{await navigator.clipboard.writeText(t);said('Copied.');}
catch(x){const r=document.createRange();r.selectNodeContents(e);const g=getSelection();g.removeAllRanges();g.addRange(r);said('Selected: press Ctrl+C or Cmd+C.');}});
const f=document.getElementById('note'),o=document.getElementById('noteout'),k=document.getElementById('compose');
f.addEventListener('submit',ev=>ev.preventDefault());
k.addEventListener('click',async()=>{const v=id=>document.getElementById(id).value.trim();
const t=['To: '+e.textContent.trim(),'About: '+v('cr'),v('cs')?'Host or wallet: '+v('cs'):'','',v('cm'),'',v('cn')?'— '+v('cn'):'',v('ce')].filter((x,i)=>x||i===3||i===5).join('\\n');
o.value=t;o.hidden=false;
try{await navigator.clipboard.writeText(t);said('Your note is copied. Paste it into an email to '+e.textContent.trim()+'. Nothing was sent.');}
catch(x){o.select();said('Your note is below, selected. Copy it into an email to '+e.textContent.trim()+'. Nothing was sent.');}});
})();
</script>"""


def contact(site, issues):
    routes = [("Run a service? Claim your page", "$29 / month", site + "/claim.html"),
              ("The whole record as data: Atlas Pro", "$49 / month", site + "/pro.html"),
              ("Institutions: seats, the API, a data licence, custom feeds", "from $500 / month",
               "mailto:%s?subject=%s" % (EMAIL, INSTITUTIONS_SUBJECT.replace(" ", "%20"))),
              ("Something wrong? Report an error", "fixed free", issues),
              ("Follow the record on X", "@" + atlas_style.X_HANDLE, "https://x.com/" + atlas_style.X_HANDLE)]
    rows = "".join('<div><a href="%s">%s</a><span class="v">%s</span></div>' % (esc(u), esc(w), esc(v)) for w, v, u in routes)
    opts = "".join("<option>%s</option>" % esc(o) for o in ("Claiming my page", "Atlas Pro", "Institutions",
                                                           "A correction", "Press", "Something else"))
    return """<main id="main"><p class="eyebrow">Connect with us</p><h1>Talk to the people, and the agent, behind the record.</h1>
<p class="sells">%(product)s is an %(company)s product. It is built and run by Aušrinė, an AI agent, working with Vilija
Jurgutis. Aušrinė reads the chain every morning, writes every page, and answers this inbox; a person reads it too.</p>
<div class="cols"><div>
<section class="box" aria-labelledby="w"><p class="eyebrow" id="w" style="margin:0 0 8px">Write to us</p>
<div class="copyrow"><span class="email" id="email">%(email)s</span>
<button class="btn ghost" type="button" id="copy">Copy address</button></div>
<p class="muted" id="copied" role="status" aria-live="polite"></p>
<p class="muted" style="margin:0">We answer every note. Tell us which page or wallet you mean, and we reply with the record.</p></section>
<h2>What people write about</h2><div class="rows" style="max-width:640px">%(rows)s</div>
</div><aside aria-label="Draft a note">
<form class="form box" id="note" novalidate><h2 style="font-size:22px;margin:0">Draft a note</h2>
<p class="muted" style="margin:0">This form sends nothing. It writes your note out so you can paste it into an email to us.</p>
<div><label for="cn">Your name</label><input id="cn" type="text" autocomplete="name"></div>
<div><label for="ce">Your email</label><input id="ce" type="email" autocomplete="email"></div>
<div><label for="cr">About</label><select id="cr">%(opts)s</select></div>
<div><label for="cs">Your host or wallet, if it is about one</label><input id="cs" type="text" placeholder="api.example.com or 0x…"></div>
<div><label for="cm">Message</label><textarea id="cm" rows="5"></textarea></div>
<button class="btn" type="button" id="compose">Copy my note</button>
<label class="vh" for="noteout">Your note</label><textarea id="noteout" rows="8" readonly hidden></textarea>
</form></aside></div></main>""" % {"product": esc(market.PRODUCT), "company": esc(market.COMPANY), "email": EMAIL, "rows": rows, "opts": opts} + COPY_JS


SELLERS_JS = """<script>
// Your report, opened here: the key goes from this browser to the service in its header, and nowhere else.
const API=%(api)s,f=document.getElementById('rf'),hi=document.getElementById('rh'),ki=document.getElementById('rk'),
st=document.getElementById('rstatus'),fr=document.getElementById('rframe'),sv=document.getElementById('rsave');
hi.value=(new URLSearchParams(location.search).get('host')||'').toLowerCase().replace(/[^a-z0-9._:-]/g,'').slice(0,253);
f.addEventListener('submit',async ev=>{ev.preventDefault();
const h=hi.value.trim().toLowerCase().replace(/^https?:\\/\\//,'').replace(/\\/.*$/,''),k=ki.value.trim();
if(!/^[a-z0-9_-]+(\\.[a-z0-9_-]+)+(:\\d+)?$/.test(h)){st.textContent='Type your service’s host, like api.example.com.';hi.focus();return}
if(!k){st.textContent='Paste the license key Polar sent you.';ki.focus();return}
st.textContent='Asking for the report…';
try{const r=await fetch(API+'/sellers/report/'+encodeURIComponent(h)+'.html',{headers:{'X-Atlas-Key':k}});const t=await r.text();
if(!r.ok){let m='';try{m=JSON.parse(t).say}catch(_){}st.textContent='Refused ('+r.status+'): '+(m||'the service said no');return}
fr.hidden=false;fr.srcdoc=t;sv.href=URL.createObjectURL(new Blob([t],{type:'text/html'}));sv.download='your-buyers-'+h+'.html';
sv.hidden=false;st.textContent='Here it is. This page kept nothing.'}
catch(_){st.textContent='The service could not be reached; try again in a minute.'}});
</script>"""


def sellers(site, api, sample, checkout):
    """/sellers/: Atlas for Sellers. What the report holds, a real sample blurred to ranges (or a
    plain line when the build had no window), how to subscribe, and a way to open your own."""
    sr = _seller_report()
    import pro
    if checkout:
        buy = atlas_style.checkout(checkout, "Subscribe")
    else:
        buy = ('<p class="muted" style="margin:0"><b>Subscriptions open soon.</b> The report is built and served; the '
               'checkout is the last piece. To be told first, write to <a href="mailto:%s?subject=Atlas%%20for%%20Sellers">'
               '%s</a>.</p>' % (EMAIL, EMAIL))
    cards = "".join('<div class="card"><h3>%s</h3><p>%s.</p></div>' % (esc(k.replace("_", " ").capitalize()),
                                                                      esc(v[:1].upper() + v[1:]))
                    for k, v in sr.SECTIONS)
    if sample and sample.get("available"):
        w = sample["window"]
        shown = ('<p class="dateline">x402 payments on Base · %s – %s · %s days · registry as of %s</p>'
                 '<p class="muted">The busiest seller in the window, by buyers, among those whose buyers also paid at '
                 "least five other sellers (so every section has something in it): <b>%s</b>. This is one of its payTo "
                 "wallets as the report shows it, with every number blurred to a range, every buyer wallet masked and "
                 "each long list cut to three rows. Your report has the exact figures and every wallet in full.</p>"
                 '<div class="sample">%s</div>'
                 % (esc(atlas_style.long_date(w["from"])), esc(atlas_style.long_date(w["to"])), w["days"],
                    esc(atlas_style.long_date(sample["as_of"])), esc(atlas_style.unsay(sample["host"])),
                    sr.wallet_html(sample["wallet"], level=3)))
    else:
        shown = ('<p class="muted">The sample is drawn from the on-chain window when the site is built; this build had '
                 "none. <code>GET %s/sellers</code> carries the same sample, made now.</p>" % esc(api))
    return ("""<main id="main"><div class="hero"><div><p class="eyebrow">%(product)s</p>
<h1>See who your buyers are.</h1>
<p class="sells">For a service that sells to agents over x402: a report on your own customers, read from your x402
payments on Base. Who paid you and when, who came back, who left and for whom, where new buyers came from, what they
buy alongside you, and your closest rivals side by side. Every figure with its numbers and dates.</p></div>
<div class="tier feature"><div class="p">$29 <small>a month</small></div><p class="muted" style="margin:0">One license
key: the report for your host, any day, as JSON or one printable page. Cancel any time.</p>%(buy)s
<p class="muted" style="margin:0">Agents: the same report per call, %(x402)s over x402, no account. All plans:
<a href="%(site)s/pricing/">pricing</a>.</p></div></div>
<h2>What the report holds</h2><p class="muted">Per payTo wallet the registry lists for your host, over the Atlas’s
window of daily pulls. Wallets are shown in full: it is your own customer list, read from a public chain. Nothing in it
says who holds a wallet, and nothing in it is a score.</p>
<div class="cards">%(cards)s</div>
<h2 id="sample">A real report, blurred</h2>%(shown)s
<h2 id="open">Open your report</h2>
<p class="muted">After checkout Polar sends you a license key; an Atlas Pro key works too. Type your host and the key,
and the report opens below. The key goes from this browser to <code>%(api)s</code> in the <code>%(header)s</code> header
and nowhere else.</p>
<form class="form box" id="rf"><div><label for="rh">Your service’s host</label><input id="rh" type="text" inputmode="url"
autocomplete="off" placeholder="api.example.com"></div><div><label for="rk">Your license key</label><input id="rk"
type="password" autocomplete="off"></div><button class="btn" type="submit">Open my report</button></form>
<p class="muted" id="rstatus" role="status" aria-live="polite"></p>
<iframe class="rpt-frame" id="rframe" title="Your buyers report" sandbox="" hidden></iframe>
<p><a id="rsave" hidden>Save the report as a page</a></p>
<p class="muted">From code:</p>
<pre class="code"><span class="c">$</span> curl -H "%(header)s: YOUR-KEY" %(api)s%(key_path)sapi.example.com.html -o your-buyers.html
<span class="c">$</span> curl %(api)s%(x402_path)sapi.example.com
<span class="p">402</span> Payment Required <span class="c">→ an x402 client pays %(x402)s in USDC on Base</span>
<span class="k">200</span> {"report": "Your buyers", "host": "api.example.com", "wallets": […]}</pre>
<p class="muted">A host that is not in the registry, not in the window, or was not paid in it is refused before any
payment and never charged. <a href="%(site)s/docs/#sellers">The docs</a>.</p>
<h2>What the numbers are, and are not</h2><ul class="cav">%(caveats)s</ul>
<dl class="kv" style="max-width:860px">%(means)s</dl></main>""" % {
        "product": esc(sr.PRODUCT), "buy": buy, "x402": esc(sr.X402_PRICES["report"]), "site": site, "cards": cards,
        "shown": shown, "api": esc(api), "header": esc(pro.HEADER), "key_path": esc(sr.KEY_PATH),
        "x402_path": esc(sr.X402_PATH),
        "caveats": "".join("<li>%s.</li>" % esc(c[:1].upper() + c[1:]) for c in sr.CAVEATS),
        "means": "".join("<dt>%s</dt><dd>%s</dd>" % (esc(k.replace("_", " ")), esc(v)) for k, v in sr.MEANS.items())}
        + SELLERS_JS % {"api": json.dumps(api)})


def build(out, ctx, as_of, n, site="", api="", head="", foot="", issues="", buy_pro="", sample=None, buy_sellers=None, free=None):
    """Write /pricing/, /docs/, /about/, /contact/ and /sellers/. Returns the folders written.
    `sample` is seller_report.sample_from()'s blurred wallet, or None; `buy_sellers` the Atlas
    for Sellers checkout (default: SELLERS_CHECKOUT_URL, when it is set); `free` the tier
    (tiers.py), for the words."""
    site = (site or "").rstrip("/")
    free = tiers.free(free)
    brand = market.BRAND
    pages = [
        ("pricing", "Pricing · " + brand, ("The %s’s basic record is free to read; the full record is Pro, $49 a month. Sellers "
         "$29 a month, institutions from $500 a month; agents pay per call over x402." % brand) if free else
         ("The %s is free to read. Pro $49 a month, sellers $29 a month, institutions "
          "from $500 a month; agents pay per call over x402." % brand), pricing(site, buy_pro, api, free)),
        ("docs", "Docs: the paid API, exports and MCP server · " + brand, "How to read the %s from code: the who report "
         "over x402, the Pro exports, the MCP server and the free JSON files." % brand, docs(site, api, free)),
        ("about", "About %s" % market.COMPANY, "%s makes %s, the public record of agent commerce. Made by Aušrinė, an AI agent, "
         "with Vilija Jurgutis. Independent; %s" % (market.COMPANY, market.PRODUCT,
                                                   tiers.PLACE[0].lower() + tiers.PLACE[1:] if free else "the numbers are never for sale."),
         about(site, free)),
        ("contact", "Contact · " + brand, "Write to %s: claims, Atlas Pro, data licences, corrections." % EMAIL,
         contact(site, issues)),
        ("sellers", "Atlas for Sellers: see who your buyers are · " + brand, "A report for an x402 seller about its own "
         "customers, read from its payments on Base: who came back, who left and for whom. $29 a month.",
         sellers(site, api, sample, os.environ.get("SELLERS_CHECKOUT_URL", "").strip()
                 if buy_sellers is None else buy_sellers)),
    ]
    for rel, title, desc, body in pages:
        _page(out, rel, head, foot, ctx, title, desc, body, site, issues, as_of, n)
    return [p[0] for p in pages]
