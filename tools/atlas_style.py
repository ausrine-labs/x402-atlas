#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit a0d9190). Edit it there, not here.
"""atlas_style.py — the one look of the Infoharmoni Atlas: stylesheet, header, footer.

Every page the site build writes carries the same three things, written here once:
the stylesheet (/atlas.css, the palette as CSS variables), the header (logo mark,
the name from market.BRAND, the x402 and Base chips, a search box, the nav) and the
footer (company columns, the small print). The reference is design/DESIGN.md and the
boards beside it: white paper, sellers emerald, wallets and buyers amber, Instrument
Sans for words and IBM Plex Mono for numbers, dates, addresses and labels.

HEAD takes %(title)s %(desc)s %(canon)s %(css)s %(root)s; FOOT takes %(root)s
%(issue)s %(as_of)s %(n)s. Standard library only.
"""

import html
import re

import market

EMAIL = "ausrine@infoharmoni.com"
X_HANDLE = "ausrine_ai"
FONTS = ("https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700"
         "&family=IBM+Plex+Mono:wght@400;500;600&display=swap")

# The palette, as Vilija chose it (Palette board, option A, on white).
PALETTE = {
    "paper": "#FFFFFF", "panel": "#F5F4EF", "rule": "#E7E5DF", "rule-soft": "#F0EEE8",
    "ink": "#102A23", "ink-2": "#3A4A43", "muted": "#66645A", "faint": "#A39E8C", "under": "#D6D3CA",
    "seller": "#0B7A55", "seller-ink": "#0B5A40", "seller-soft": "#E6F4EE",
    "buyer": "#E0A93B", "buyer-ink": "#8A6417", "buyer-soft": "#F7EBD2",
}

# The mark: a ring, two sellers (emerald) and a wallet (amber), and the money between them.
LOGO = ('<svg class="logo" width="28" height="28" viewBox="0 0 28 28" aria-hidden="true" focusable="false">'
        '<circle cx="14" cy="14" r="12.5" fill="none" stroke="#102A23" stroke-width="1.5"/>'
        '<path d="M9 10L19 9M9 10L17 19M19 9L17 19" stroke="#102A23" stroke-width="1"/>'
        '<circle cx="9" cy="10" r="2.6" fill="#0B7A55"/><circle cx="19" cy="9" r="2.2" fill="#E0A93B"/>'
        '<circle cx="17" cy="19" r="2.6" fill="#0B7A55"/></svg>')
# The company and its product side by side, the way Stripe | Radar reads: the company's wordmark,
# a thin rule, the product's name. The hidden space keeps the name read aloud as two words.
LOCKUP = ('<span class="bname">%s</span><span class="vh">&nbsp;</span><span class="bsep" aria-hidden="true"></span>'
          '<span class="bprod">%s</span>' % (market.COMPANY, market.PRODUCT))
FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 28"><title>' + market.COMPANY + '</title>'
           '<rect width="28" height="28" rx="6" fill="#FFFFFF"/>'
           '<circle cx="14" cy="14" r="12" fill="none" stroke="#102A23" stroke-width="1.8"/>'
           '<path d="M9 10L19 9M9 10L17 19M19 9L17 19" stroke="#102A23" stroke-width="1.2"/>'
           '<circle cx="9" cy="10" r="3" fill="#0B7A55"/><circle cx="19" cy="9" r="2.6" fill="#E0A93B"/>'
           '<circle cx="17" cy="19" r="3" fill="#0B7A55"/></svg>\n')

CSS = """:root{color-scheme:light;
--paper:#FFFFFF;--panel:#F5F4EF;--rule:#E7E5DF;--rule-soft:#F0EEE8;--ink:#102A23;--ink-2:#3A4A43;--muted:#66645A;--faint:#A39E8C;--under:#D6D3CA;
--seller:#0B7A55;--seller-ink:#0B5A40;--seller-soft:#E6F4EE;--buyer:#E0A93B;--buyer-ink:#8A6417;--buyer-soft:#F7EBD2;
--up:#0B7A55;--down:#9B2C1F;
--sans:"Instrument Sans",system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
--mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
--gutter:clamp(16px,4.4vw,64px);--max:1312px;--radius:10px}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 var(--sans);-webkit-font-smoothing:antialiased;overflow-x:hidden}
a{color:var(--ink);text-decoration:underline;text-decoration-color:var(--under);text-underline-offset:3px}
a:hover{text-decoration-color:var(--ink)}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--seller);outline-offset:2px}
img,svg{max-width:100%}
.vh{position:absolute!important;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.skip{position:absolute;left:-9999px;top:8px;background:var(--ink);color:#fff;padding:8px 12px;border-radius:6px;z-index:9}.skip:focus{left:12px}
/* header */
header.site{border-bottom:1px solid var(--rule);background:var(--paper)}
.hbar{max-width:calc(var(--max) + 2*var(--gutter));margin:0 auto;padding:14px var(--gutter);display:flex;flex-wrap:wrap;align-items:center;gap:12px 24px}
a.brand{display:inline-flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink)}
.brand .bname{font:600 21px/1.1 var(--sans);letter-spacing:-.02em;white-space:nowrap}
.brand .bsep{width:1px;height:20px;background:var(--under);margin:0 2px}.brand .bprod{font:500 21px/1.1 var(--sans);letter-spacing:-.01em;color:var(--seller-ink);white-space:nowrap}
.netchips{display:inline-flex;gap:6px}
.chip-sm{font:500 11px/1 var(--mono);padding:4px 7px;border:1px solid var(--rule);border-radius:999px;color:var(--ink-2);white-space:nowrap}
form.hsearch{flex:1 1 260px;max-width:400px;margin:0}
form.hsearch input{width:100%;height:40px;padding:0 14px;font:15px var(--sans);color:var(--ink);background:var(--panel);border:1px solid var(--rule);border-radius:8px}
nav.main{display:flex;flex-wrap:wrap;gap:4px 18px;margin-left:auto;font-size:15px;font-weight:500}
nav.main a{text-decoration:none;color:var(--ink);padding:4px 0;white-space:nowrap}
nav.main a:hover{text-decoration:underline;text-decoration-color:var(--ink)}
nav.main a.pro{padding:4px 12px;border-radius:8px;background:var(--ink);color:#fff}
nav.main a.pro:hover{text-decoration:none;background:var(--seller-ink)}
/* page frame */
main{display:block;max-width:calc(var(--max) + 2*var(--gutter));margin:0 auto;padding:0 var(--gutter)}
h1{font:600 clamp(32px,5.4vw,60px)/1.04 var(--sans);letter-spacing:-.035em;margin:40px 0 12px;overflow-wrap:anywhere;max-width:22ch;text-wrap:balance}
h1 code{font:500 .78em/1.1 var(--mono);background:none;padding:0;letter-spacing:-.02em}
h2{font:600 clamp(24px,2.6vw,32px)/1.15 var(--sans);letter-spacing:-.025em;margin:56px 0 14px;text-wrap:balance}
h3{font:600 18px/1.3 var(--sans);letter-spacing:-.01em;margin:0 0 6px}
p{max-width:72ch}
.eyebrow{display:block;font:500 12px/1.4 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--seller);margin:40px 0 0}
.eyebrow+h1,.eyebrow+h2,.eyebrow+.section-head h2{margin-top:10px}
.oneline{font:500 clamp(18px,1.9vw,22px)/1.45 var(--sans);color:var(--ink);max-width:40ch;margin:18px 0 0}
.sells{font:400 clamp(17px,1.6vw,19px)/1.55 var(--sans);color:var(--ink-2);max-width:66ch;overflow-wrap:anywhere}
.muted{color:var(--muted);font-size:15px}
.mono,.num{font-family:var(--mono)}
.crumbs{font:13px/1.4 var(--mono);color:var(--muted);margin:28px 0 0;overflow-wrap:anywhere}.crumbs a{color:var(--muted)}
.dateline{font:500 12px/1.4 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:32px 0 10px}
/* tags and pills */
.tag{display:inline-block;font:500 12px/1.5 var(--mono);border:1px solid var(--rule);border-radius:999px;padding:2px 10px;color:var(--ink-2);margin:0 6px 6px 0;background:var(--paper);white-space:nowrap}
.tag.mark{border-color:var(--seller);color:var(--seller-ink);background:var(--seller-soft)}
.pill{display:inline-block;font:500 12px/1.5 var(--sans);padding:2px 9px;border-radius:999px;white-space:nowrap}
.pill.spread{background:var(--seller-soft);color:var(--seller-ink)}.pill.concentrated,.pill.one-payer{background:var(--buyer-soft);color:var(--buyer-ink)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;vertical-align:-1px;margin-right:6px}
.dot.seller{background:var(--seller)}.dot.buyer{background:var(--buyer);box-shadow:inset 0 0 0 1px var(--buyer-ink)}
.disclaimer{max-width:70ch;margin-top:4px}
/* number tiles */
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:20px 0 0}
.tile{border:1px solid var(--rule);border-radius:var(--radius);padding:16px 18px;background:var(--paper);min-width:0}
.tile b{display:block;font:500 clamp(24px,2.4vw,30px)/1.15 var(--mono);letter-spacing:-.01em;margin-bottom:6px;overflow-wrap:anywhere}
.tile span{display:block;color:var(--muted);font-size:13px;line-height:1.45}
.up{color:var(--up)}.down{color:var(--down)}
/* tables */
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}
table{width:100%;border-collapse:collapse;font-size:15px;line-height:1.45}
th,td{text-align:left;padding:11px 14px 11px 0;border-bottom:1px solid var(--rule-soft);vertical-align:top}
th{font:500 11px/1.4 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--ink);white-space:nowrap}
td.n,th.n{text-align:right;white-space:nowrap}td.n{font:14px/1.45 var(--mono)}th.n+th,td.n+td{padding-left:18px}
td.h{overflow-wrap:anywhere;min-width:140px;font-weight:600}tr:hover td{background:#FAF9F5}
code{font:13.5px/1.4 var(--mono);background:var(--panel);border-radius:4px;padding:1px 5px;overflow-wrap:anywhere;color:var(--ink)}
a code{text-decoration:none}
pre.code{font:13px/1.6 var(--mono);background:var(--panel);border:1px solid var(--rule);border-radius:var(--radius);padding:16px 18px;overflow-x:auto;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--ink);margin:12px 0}
pre.code .k{color:var(--seller-ink);font-weight:600}pre.code .c{color:var(--muted)}pre.code .p{color:var(--buyer-ink);font-weight:600}
ul.cav{color:var(--ink-2);font-size:15px;padding-left:20px;max-width:76ch}ul.cav li{margin-bottom:6px}
/* buttons, boxes, cards */
.btn{display:inline-flex;align-items:center;min-height:44px;padding:0 18px;border-radius:8px;background:var(--ink);color:#fff;font:600 15px var(--sans);text-decoration:none;border:1px solid var(--ink);cursor:pointer}
.btn:hover{background:var(--seller-ink);border-color:var(--seller-ink);text-decoration:none}
.btn.ghost{background:var(--paper);color:var(--ink);border-color:var(--rule)}.btn.ghost:hover{border-color:var(--ink);background:var(--paper)}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0 0}
.box,.claim{border:1px solid var(--rule);border-radius:12px;padding:20px 22px;background:var(--panel);margin-top:24px}
.claim h3{margin:0 0 6px}.claim p{margin:0 0 6px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-top:16px}
.card{border:1px solid var(--rule);border-radius:12px;padding:18px 20px;background:var(--paper);min-width:0}
.card h3{margin:0 0 8px}.card p{margin:0 0 8px;font-size:15px;color:var(--ink-2)}
.card .rows a,.card .rows span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rows{display:flex;flex-direction:column;font-size:14px}
.rows>div{display:flex;justify-content:space-between;gap:10px;padding:7px 0;border-top:1px solid var(--rule-soft);min-width:0}
.rows .v{font-family:var(--mono);color:var(--muted);flex:none}
.cols{display:grid;grid-template-columns:minmax(0,1fr);gap:0 48px}
@media (min-width:960px){.cols{grid-template-columns:minmax(0,1fr) 340px}.cols>aside{padding-top:56px}}
.cols>aside .box:first-child{margin-top:0}
.kv{display:grid;grid-template-columns:auto 1fr;gap:8px 16px;font-size:14px;margin:8px 0 0}.kv dt{color:var(--muted)}.kv dd{margin:0;overflow-wrap:anywhere}
.owner{margin-top:8px}.logo-owner{max-width:96px;max-height:96px;border-radius:6px;display:block;margin-bottom:8px}
.olink{display:inline-block;margin-right:14px}
.ident{display:flex;gap:18px;align-items:flex-start}.ident h1{margin-top:6px}
.avatar{flex:none;width:56px;height:56px;border-radius:50%;display:grid;place-items:center;font:600 15px var(--mono);margin-top:40px}
.avatar.buyer{background:var(--buyer-soft);color:var(--buyer-ink);box-shadow:inset 0 0 0 2px var(--buyer)}
.avatar.seller{background:var(--seller-soft);color:var(--seller-ink);box-shadow:inset 0 0 0 2px var(--seller)}
.payers{list-style:none;padding:0;margin:10px 0;max-width:560px}.payers li{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-top:1px solid var(--rule-soft);font-family:var(--mono);font-size:14px}
/* the replay */
.spark{width:100%;height:auto;background:var(--paper);border:1px solid var(--rule);border-radius:var(--radius)}
.spark polyline{fill:none;stroke:var(--seller);stroke-width:2;stroke-linejoin:round}.spark circle{fill:var(--paper);stroke:var(--seller);stroke-width:1.5}
.axis{display:flex;justify-content:space-between;color:var(--muted);font:12px var(--mono);margin-top:6px}
/* search */
.chips{display:flex;flex-wrap:wrap;gap:6px 8px;margin:0 0 6px;max-width:none}
.chip{background:var(--paper);border:1px solid var(--rule);color:var(--ink-2);border-radius:999px;padding:5px 12px;font:14px var(--sans);cursor:pointer;min-height:32px}
.chip:hover{border-color:var(--ink);color:var(--ink)}
input#q{width:100%;background:var(--panel);border:1px solid var(--rule);color:var(--ink);border-radius:8px;padding:0 16px;height:52px;font:17px var(--sans);margin:8px 0 12px}
label.big{display:block;font:600 18px var(--sans);margin:28px 0 0}
#hits h2{font-size:20px;margin:24px 0 6px}
/* home */
.hero{display:grid;grid-template-columns:minmax(0,1fr);gap:8px 48px;align-items:end;padding:8px 0 0}
@media (min-width:960px){.hero{grid-template-columns:minmax(0,8fr) minmax(0,4fr)}}
.hero h1{font-size:clamp(38px,6vw,72px);line-height:1;max-width:14ch;margin-bottom:0}
.hero .sells{margin:0}
.ledger{display:flex;flex-wrap:wrap;gap:6px 28px;padding:11px var(--gutter);background:var(--panel);border-bottom:1px solid var(--rule);font:13px/1.5 var(--mono)}
.ledger .lh{font-weight:600;white-space:nowrap}.ledger span{white-space:nowrap}.ledger .w{color:var(--muted)}.ledger .a{color:var(--faint)}
@media (max-width:700px){.ledger .l:nth-of-type(n+4){display:none}.ledger{gap:4px 18px}}
figure.net{margin:28px 0 0;border:1px solid var(--rule);border-radius:12px;overflow:hidden;background:var(--paper)}
figure.net .fh{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px 20px;padding:12px 18px;border-bottom:1px solid var(--rule)}
figure.net .fh .t{font:500 12px/1.4 var(--mono);letter-spacing:.1em;text-transform:uppercase}
.legend{display:flex;flex-wrap:wrap;gap:4px 18px;align-items:center;font-size:13px;color:var(--muted);margin:0;max-width:none}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.legend s{display:inline-block;width:18px;height:0;border-top:1.5px solid var(--under);margin-right:6px;vertical-align:4px;text-decoration:none}
figure.net .frame{position:relative;height:clamp(340px,56vh,540px)}
figure.net iframe{display:block;width:100%;height:100%;border:0}
figure.net figcaption{padding:10px 18px;border-top:1px solid var(--rule);font-size:14px;color:var(--muted)}
.section-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px 24px}
.section-head h2{margin-bottom:0}.section-head+*{margin-top:18px}
.band{margin:64px 0 0;border:1px solid var(--rule);border-radius:16px;background:var(--panel);padding:28px clamp(18px,3vw,40px);display:grid;grid-template-columns:minmax(0,1fr);gap:18px 40px;align-items:center}
@media (min-width:900px){.band{grid-template-columns:minmax(0,1fr) auto}}
.band h2{margin:6px 0 6px}.band .price{font:500 40px/1 var(--mono)}.band .price small{font-size:15px;color:var(--muted)}
/* pricing */
.tiers{display:grid;grid-template-columns:repeat(auto-fit,minmax(228px,1fr));gap:16px;margin-top:28px}
.tier{border:1px solid var(--rule);border-radius:14px;padding:24px;display:flex;flex-direction:column;gap:10px;background:var(--paper)}
.tier.feature{border-color:var(--ink);box-shadow:0 1px 0 var(--ink)}
.tier .p{font:500 36px/1.1 var(--mono);letter-spacing:-.02em}.tier .p.word{font:600 30px/1.2 var(--sans);letter-spacing:-.02em}.tier .p small{display:block;margin-top:4px;font:15px var(--sans);color:var(--muted)}
.tier ul{padding-left:18px;margin:4px 0 8px;color:var(--ink-2);font-size:15px}.tier li{margin-bottom:6px}.tier .btn{margin-top:auto;align-self:flex-start}
.coming{display:inline-block;font:500 10.5px/1.5 var(--mono);letter-spacing:.06em;text-transform:uppercase;padding:0 6px;border-radius:999px;background:var(--buyer-soft);color:var(--buyer-ink);vertical-align:1px}
.tier li.soon{color:var(--muted)}
.strip{margin-top:20px;border:1px dashed var(--under);border-radius:12px;padding:14px 18px;display:flex;flex-wrap:wrap;gap:8px 28px;align-items:baseline;font-size:15px}
.strip b{font-family:var(--mono);font-weight:600}
.offers{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px;margin-top:22px}
.offer{border:1px solid var(--rule);border-radius:14px;padding:20px 22px}.offer h3{margin:0}
.offer .p{font:500 32px var(--mono);color:var(--ink);margin:6px 0}.offer ul{padding-left:18px;color:var(--ink-2);font-size:15px}
/* the coverage pages (live, leaders, prices, where): their bodies' own classes */
.cov .seller,.cov .seller a{color:var(--seller-ink)}.cov .wallet,.cov .wallet a{color:var(--buyer-ink)}
.cov .num{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.cov .dated,.cov .addr,.cov time,.asof .dated{font-family:var(--mono)}.cov .wrap{overflow-x:auto;max-width:100%}
.cov .notice{background:var(--panel);border:1px solid var(--rule);padding:12px 14px;border-radius:var(--radius)}
.cov svg{width:100%;height:auto;display:block;background:var(--panel);border:1px solid var(--rule);border-radius:var(--radius)}
.cov h1{margin-top:40px}.cov h2{font-size:clamp(20px,2.2vw,26px);margin:40px 0 10px}.asof{margin-top:40px;font-size:13px}
/* forms */
.form{display:grid;gap:14px;max-width:560px}.form label{font-weight:600;font-size:14px;display:block;margin-bottom:4px}
.form input,.form select,.form textarea{width:100%;font:16px var(--sans);color:var(--ink);background:var(--paper);border:1px solid var(--rule);border-radius:8px;padding:10px 12px}
.form textarea{min-height:130px;resize:vertical}
.email{font:500 clamp(18px,2.4vw,26px)/1.3 var(--mono);user-select:all;-webkit-user-select:all;overflow-wrap:anywhere}
.copyrow{display:flex;flex-wrap:wrap;align-items:center;gap:12px}
/* footer */
footer.site{margin-top:88px;border-top:1px solid var(--rule);background:var(--paper);color:var(--ink-2);font-size:14px}
.fwrap{max-width:calc(var(--max) + 2*var(--gutter));margin:0 auto;padding:36px var(--gutter) 12px;display:grid;grid-template-columns:minmax(0,1fr);gap:28px 40px}
@media (min-width:900px){.fwrap{grid-template-columns:minmax(0,1.3fr) minmax(0,3fr)}}
.fbrand p{margin:10px 0 0;max-width:36ch;color:var(--muted)}
.fcols{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:20px 24px}
.fcols h2{font:500 11px/1.4 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:0 0 10px}
.fcols a{display:block;padding:3px 0;text-decoration:none;color:var(--ink-2);overflow-wrap:anywhere}.fcols a:hover{color:var(--ink);text-decoration:underline}
.small{max-width:calc(var(--max) + 2*var(--gutter));margin:0 auto;padding:14px var(--gutter) 40px;border-top:1px solid var(--rule-soft);color:var(--muted);font-size:13px}
.small p{margin:4px 0;max-width:none}
@media (max-width:600px){body{font-size:15.5px}.hbar{gap:10px 14px}.brand .bname,.brand .bprod{font-size:19px}form.hsearch{flex-basis:100%;max-width:none;order:3}
nav.main{order:4;margin-left:0;gap:2px 16px;font-size:14.5px}h2{margin-top:44px}.tiles{grid-template-columns:1fr 1fr}.tile b{font-size:22px}
table{font-size:14px}th,td{padding-right:10px}.avatar{width:44px;height:44px;margin-top:34px}}
"""

HEAD = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title><meta name="description" content="%(desc)s">
<link rel="canonical" href="%(canon)s">
<meta name="theme-color" content="#FFFFFF"><meta name="color-scheme" content="light">
<meta property="og:type" content="website"><meta property="og:site_name" content=\"""" + market.COMPANY + """\">
<meta property="og:title" content="%(title)s"><meta property="og:description" content="%(desc)s">
<meta property="og:url" content="%(canon)s"><meta property="og:image" content="%(root)s/og.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:image:alt" content=\"""" + market.COMPANY + " " + market.PRODUCT + """: the public record of agent commerce\">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="%(root)s/og.png">
<link rel="icon" href="%(root)s/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href=\"""" + FONTS.replace("&", "&amp;") + """\">
<link rel="stylesheet" href="%(css)s">
<header class="site"><a class="skip" href="#main">Skip to the record</a><div class="hbar">
<a class="brand" href="%(root)s/">""" + LOGO + LOCKUP + """</a>
<span class="netchips" title="Covers x402 payments on Base"><span class="chip-sm">x402</span><span class="chip-sm">Base</span></span>
<form class="hsearch" role="search" action="%(root)s/" method="get"><label class="vh" for="hq">Search the record</label>
<input id="hq" name="q" type="search" placeholder="Search sellers, operators, wallets, or a job" autocomplete="off"></form>
<nav class="main" aria-label="Main"><a href="%(root)s/s/">Sellers</a><a href="%(root)s/o/">Operators</a><a href="%(root)s/b/">Buyers</a><a href="%(root)s/map/">Map</a><a href="%(root)s/live/">Live</a><a href="%(root)s/leaders/">Leaders</a><a href="%(root)s/prices/">Prices</a><a href="%(root)s/where/">Where</a><a href="%(root)s/pricing/">Pricing</a><a href="%(root)s/docs/">Docs</a><a href="%(root)s/about/">About</a><a href="%(root)s/contact/">Contact</a><a class="pro" href="%(root)s/pro.html">Pro</a></nav>
</div></header>
"""

FOOT = """<footer class="site"><div class="fwrap">
<div class="fbrand"><a class="brand" href="%(root)s/about/">""" + LOGO + """<span class="bname">""" + market.COMPANY + """</span></a>
<p>""" + market.COMPANY + """ makes """ + market.PRODUCT + """, the public record of agent commerce: every x402 payment on Base, read off the chain every morning.</p></div>
<nav class="fcols" aria-label="Footer">
<div><h2>Product</h2><a href="%(root)s/s/">Sellers</a><a href="%(root)s/o/">Operators</a><a href="%(root)s/b/">Buyers</a><a href="%(root)s/map/">The map</a><a href="%(root)s/live/">Live payments</a><a href="%(root)s/leaders/">Leaderboards</a><a href="%(root)s/prices/">Price benchmarks</a><a href="%(root)s/where/">Where sellers are hosted</a><a href="%(root)s/pro.html">Atlas Pro</a><a href="%(root)s/watch/">Watch your agents</a><a href="%(root)s/pricing/">Pricing</a></div>
<div><h2>Developers</h2><a href="%(root)s/docs/">Docs</a><a href="%(root)s/docs/#who">Paid API over x402</a><a href="%(root)s/docs/#mcp">MCP server</a><a href="%(root)s/docs/#exports">Pro exports</a></div>
<div><h2>Company</h2><a href="%(root)s/about/">About """ + market.COMPANY + """</a><a href="%(root)s/claim.html">For sellers</a><a href="%(issue)s">Report an error</a></div>
<div><h2>Contact</h2><a href="%(root)s/contact/">Contact us</a><a href="mailto:""" + EMAIL + """">""" + EMAIL + """</a><a href="https://x.com/""" + X_HANDLE + """">@""" + X_HANDLE + """ on X</a></div>
</nav></div>
<div class="small"><p>© %(as_of).4s """ + market.COMPANY + """. """ + market.PRODUCT + """ is an """ + market.COMPANY + """ product, made by Aušrinė, an AI agent, openly and by design. The numbers are never for sale.
Public registry and chain data only; a wallet is not a person, and nothing here says who holds one.</p>
%(stamp)s</div></footer></html>
"""
# The dated line at the very foot. Every page built with the registry says how many sellers it holds;
# a page built from the chain alone (the coverage pages) says only when.
STAMP = '<p class="mono">As of %(as_of)s · %(n)s sellers · rebuilt when the daily scan runs.</p>'
STAMP_DAY = '<p class="mono">As of %(as_of)s · rebuilt when the daily scan runs.</p>'
FOOT_OPEN = FOOT.replace("%(stamp)s", "")[:-len("</div></footer></html>\n")]
FOOT = FOOT.replace("%(stamp)s", STAMP)
ISSUES = "https://github.com/ausrine-labs/x402-atlas/issues/new"


def footer(root, issue, as_of, n=None):
    """The house footer, filled in; without a seller count it carries STAMP_DAY."""
    d = {"root": root, "issue": issue, "as_of": as_of, "n": n}
    return FOOT_OPEN % d + (STAMP if n is not None else STAMP_DAY) % d + "</div></footer></html>\n"

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


def esc(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def _parts(iso):
    try:
        y, m, d = (int(x) for x in str(iso)[:10].split("-"))
        return y, m, d
    except (TypeError, ValueError):
        return None


def long_date(iso):
    """'2026-09-25' -> '25 September 2026'. Anything else comes back as it was."""
    p = _parts(iso)
    return "%d %s %d" % (p[2], MONTHS[p[1] - 1], p[0]) if p and 1 <= p[1] <= 12 else str(iso or "")


def short_date(iso):
    """'2026-09-25' -> '25 Sep 2026'."""
    p = _parts(iso)
    return "%d %s %d" % (p[2], MONTHS[p[1] - 1][:3], p[0]) if p and 1 <= p[1] <= 12 else str(iso or "")


def chain_day(chain, as_of=""):
    """The day (or days) the on-chain window covers, in words: '25 September 2026', or
    '24 September 2026 – 25 September 2026' when the pull covered more than one."""
    dates = [d for d in ((chain or {}).get("dates") or []) if d]
    if not dates:
        return long_date((chain or {}).get("as_of") or as_of)
    return long_date(dates[0]) if len(dates) == 1 else "%s – %s" % (long_date(dates[0]), long_date(dates[-1]))


UNSAID = re.compile(r"\S*verified\S*", re.I)


def unsay(text):
    """A stranger's words, as a page quotes them, without the one word the Atlas never uses:
    each token holding it becomes an ellipsis (map_page does the same on the map). Data files
    keep the registry's text as it was; only what a page shows is changed."""
    return UNSAID.sub("…", str(text or ""))


def pill(word):
    """Concentration as a pill: spread in the seller colour, one payer and concentrated in amber.
    The words are facts about the payers (defined on every page), not verdicts."""
    if not word:
        return "—"
    cls = {"spread": "spread", "concentrated": "concentrated", "one payer": "one-payer"}.get(word)
    return '<span class="pill %s">%s</span>' % (cls, esc(word)) if cls else esc(word)


def write_assets(out):
    """The stylesheet, the favicon and the share image, at the site root."""
    import os
    import shutil
    with open(os.path.join(out, "atlas.css"), "w") as f:
        f.write(CSS)
    with open(os.path.join(out, "favicon.svg"), "w") as f:
        f.write(FAVICON)
    og = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site-assets", "og.png")
    if os.path.exists(og):
        shutil.copyfile(og, os.path.join(out, "og.png"))
