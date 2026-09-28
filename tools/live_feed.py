# Copied from the Aušrinė lab (commit 935dfef). Edit it there, not here.
#!/usr/bin/env python3
"""live_feed.py — /live/: x402 payments as they settle, read in the viewer's own browser.

Every other Atlas page is a photograph of yesterday. This one is a window. The page
is static; a small inline script asks the public Base RPC (mainnet.base.org) for the
last ~200 blocks of USDC logs, keeps the transfers whose transaction also used an
EIP-3009 authorization (a facilitator settled a payment the buyer signed — the same
rule chain_flows.py uses), and keeps only the ones paid to a seller wallet the Atlas
knows. It asks again every 15 seconds, and waits longer after each error.

The page carries, inline, the table it needs: seller wallet → host, written at build
time from the newest rollup (and the registry snapshot, for wallets the rollup did
not see paid), and the wallets that have a buyer page. No other script is loaded
and no other host is asked anything. If the RPC refuses the browser (CORS) or fails,
the page says so plainly and shows the newest day's totals instead.

    live_feed.py --whales whales-2026-09-24.json [--snapshot market-2026-09-24.json] --out _site

live_body(data) is the fragment; write(out, data) wraps it in the minimal page.
Standard library only.
"""

import argparse
import json
import sys

import chain_flows
import coverage_page as cp

RPC = chain_flows.RPC
POLL_MS = 15000
BLOCKS = 200
ROWS = 200


site_path = cp.site_path       # links keep only the path of the site, so the page names no host but the RPC's


def base_day(flows):
    """One day of Base, from its chain_flows.py file: the fallback the page shows when the RPC
    will not answer. x402-settled figures when the pull told them apart, else every transfer
    to a seller wallet, and it says which."""
    if not flows or {"solana": "Solana"}.get(flows.get("chain", ""), "Base") != "Base":
        return None
    edges = flows.get("edges") or []
    x402 = any("n_x402" in e for e in edges)
    host = {w.lower(): (hs[0] if hs else w) for w, hs in (flows.get("sellers") or {}).items()}
    n = (lambda e: e.get("n_x402") or 0) if x402 else (lambda e: e.get("n") or 0)
    u = (lambda e: e.get("usdc_x402") or 0.0) if x402 else (lambda e: e.get("usdc") or 0.0)
    paid = [e for e in edges if n(e)]
    return {"date": flows.get("date") or "", "x402": x402, "payments": sum(n(e) for e in paid),
            "usdc": round(sum(u(e) for e in paid), 2), "buyers": len({e["from"].lower() for e in paid}),
            "sellers": len({host.get(e["to"].lower(), e["to"].lower()) for e in paid})}


def live_data(rollup, snapshot=None, site="", base_flows=None):
    """What the page needs: {wallet: {"h": shown name, "s": page slug or ""}}, the wallets
    with a buyer page, and what to show when the RPC will not answer: the newest Base day
    (base_flows, a chain_flows.py file) when given, else the rollup's totals, labelled as
    the rollup's days and chains."""
    # Only EVM addresses go in: the script pads each into a log topic, and one Solana address
    # (a host paid on both chains keeps both wallets in one row) would make the RPC refuse
    # the whole batch.
    wallets = {}
    for s in (rollup or {}).get("sellers") or []:
        for w in s.get("wallets") or []:
            if cp.evm(w):
                wallets.setdefault(cp.evm(w), s["host"])
    for host, s in sorted((snapshot or {}).items(), key=lambda kv: -(kv[1].get("calls") or 0)):
        for w in s.get("wallets") or []:
            if cp.evm(w):
                wallets.setdefault(cp.evm(w), host)
    table = {}
    for w, host in sorted(wallets.items()):
        if cp.BANNED.search(host):
            table[w] = {"h": cp.short(w), "s": ""}
        else:
            table[w] = {"h": host, "s": cp.slug(host)}
    buyers = sorted({cp.evm(b["wallet"]) for b in (rollup or {}).get("buyers") or []
                     if b.get("payments_x402") and cp.evm(b.get("wallet"))})
    t = (rollup or {}).get("totals") or {}
    dates = (rollup or {}).get("dates") or []
    return {"as_of": (rollup or {}).get("as_of") or (dates[-1] if dates else ""),
            "day": ", ".join(dates), "classified": bool((rollup or {}).get("classified")),
            "classified_chains": sorted(cp.classified_chains(rollup)), "chains": cp.chains_of(rollup),
            "base_day": base_day(base_flows),
            "site": site_path(site), "wallets": table, "buyers": buyers,
            "totals": {"payments_x402": t.get("payments_x402", 0), "usdc_x402": t.get("usdc_x402", 0.0),
                       "buyer_wallets_x402": t.get("buyer_wallets_x402", 0), "sellers_paid": t.get("sellers_paid", 0),
                       # sellers with at least one x402-settled payment, not every seller a transfer reached
                       "sellers_paid_x402": sum(1 for s in (rollup or {}).get("sellers") or []
                                                if s.get("on_chain_payments_x402")),
                       "payments": t.get("payments", 0), "usdc": t.get("usdc", 0.0)}}


def table_json(data):
    """The inline table: safe inside a <script type="application/json"> block."""
    obj = {"site": data["site"], "wallets": data["wallets"], "buyers": data["buyers"]}
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).replace("<", "\\u003c").replace(">", "\\u003e")


SCRIPT = r"""(function(){
"use strict";
var RPC="%(rpc)s", USDC="%(usdc)s", TRANSFER="%(transfer)s", AUTH="%(auth)s";
var POLL=%(poll)d, BLOCKS=%(blocks)d, ROWS=%(rows)d, CHUNK=100, MAXB=10;
var T=JSON.parse(document.getElementById("atlas-live-wallets").textContent);
var SELL=T.wallets, BUY=new Set(T.buyers), SITE=T.site, KEYS=Object.keys(SELL);
var list=document.getElementById("live-rows"), state=document.getElementById("live-state"),
    fall=document.getElementById("live-fallback"), wrap=document.getElementById("live-table");
var last=0, fails=0, ok=false, seen=new Set(), rows=[], timer=null;
function hex(n){return "0x"+n.toString(16);}
function pad(a){return "0x"+"000000000000000000000000"+a.slice(2).toLowerCase();}
function short(w){return w.slice(0,6)+"…"+w.slice(-4);}
function post(body){
  return fetch(RPC,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body),credentials:"omit"})
    .then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);return r.json();});
}
function res(r){if(!r||r.error)throw new Error((r&&r.error&&r.error.message)||"no answer");return r.result;}
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;}
function link(href,text){var a=document.createElement("a");a.href=href;a.textContent=text;return a;}
function ago(ts){var s=Math.max(0,Math.round(Date.now()/1000-ts));
  return s<60?s+" seconds ago":s<3600?Math.floor(s/60)+" min ago":Math.floor(s/3600)+" h ago";}
function utc(ts){return new Date(ts*1000).toISOString().slice(11,19)+" UTC";}
function draw(){
  list.textContent="";
  rows.forEach(function(p){
    var tr=document.createElement("tr"), s=SELL[p.to];
    var t=el("td"); var tm=el("time",null,utc(p.ts)); tm.dateTime=new Date(p.ts*1000).toISOString();
    t.appendChild(tm); t.appendChild(el("div","muted ago",ago(p.ts))); t.lastChild.dataset.ts=p.ts; tr.appendChild(t);
    var sc=el("td","seller"); if(s.s){sc.appendChild(link(SITE+"/s/"+s.s+"/",s.h));}else{sc.textContent=s.h;} tr.appendChild(sc);
    tr.appendChild(el("td","num",(p.usdc>=0.01?p.usdc.toFixed(2):p.usdc.toFixed(6).replace(/0+$/,""))+" USDC"));
    var wc=el("td","wallet addr"); if(BUY.has(p.from)){wc.appendChild(link(SITE+"/b/"+p.from+"/",short(p.from)));}
    else{wc.textContent=short(p.from);} wc.title=p.from; tr.appendChild(wc);
    list.appendChild(tr);
  });
  wrap.hidden=false;
}
function tick(){document.querySelectorAll(".ago").forEach(function(e){e.textContent=ago(+e.dataset.ts);});}
function fail(err){
  fails+=1;
  var wait=Math.min(POLL*Math.pow(2,fails),300000);
  if(!ok||rows.length===0){state.textContent="The public Base RPC did not answer this browser ("+err.message+"), so there is no live feed right now. The newest day's totals are below. Trying again in "+Math.round(wait/1000)+" s.";
    fall.hidden=false;}
  else{state.textContent="The RPC stopped answering ("+err.message+"). The list below is what came before; trying again in "+Math.round(wait/1000)+" s.";}
  timer=setTimeout(poll,wait);
}
function poll(){
  post({jsonrpc:"2.0",id:1,method:"eth_getBlockByNumber",params:["latest",false]}).then(function(r){
    var b=res(r), head=parseInt(b.number,16), headTs=parseInt(b.timestamp,16);
    var from=Math.max(last+1,head-BLOCKS);
    if(from>head){return null;}
    var batch=[{jsonrpc:"2.0",id:0,method:"eth_getLogs",params:[{fromBlock:hex(from),toBlock:hex(head),address:USDC,topics:[AUTH]}]}];
    for(var i=0;i<KEYS.length;i+=CHUNK){
      batch.push({jsonrpc:"2.0",id:1+i/CHUNK,method:"eth_getLogs",
        params:[{fromBlock:hex(from),toBlock:hex(head),address:USDC,topics:[TRANSFER,null,KEYS.slice(i,i+CHUNK).map(pad)]}]});
    }
    // The public Base RPC takes at most 10 calls in one batch: send groups of MAXB, then join.
    var groups=[]; for(var g=0;g<batch.length;g+=MAXB){groups.push(post(batch.slice(g,g+MAXB)));}
    return Promise.all(groups).then(function(parts){
      parts.forEach(function(p){if(!Array.isArray(p))throw new Error("the RPC refused a batch");});
      var ans=[].concat.apply([],parts);
      var by={}; ans.forEach(function(a){by[a.id]=a;});
      var auth=new Set(res(by[0]).map(function(l){return l.transactionHash;}));
      for(var j=1;j<batch.length;j++){
        res(by[j]).forEach(function(l){
          var key=l.transactionHash+":"+l.logIndex;
          if(!auth.has(l.transactionHash)||seen.has(key))return;
          var to="0x"+l.topics[2].slice(26).toLowerCase(), frm="0x"+l.topics[1].slice(26).toLowerCase();
          if(!SELL[to])return;
          seen.add(key);
          var bn=parseInt(l.blockNumber,16);
          var ts=l.blockTimestamp?parseInt(l.blockTimestamp,16):headTs-(head-bn)*2;
          rows.push({to:to,from:frm,usdc:parseInt(l.data,16)/1e6,ts:ts,bn:bn,li:parseInt(l.logIndex,16)});
        });
      }
      rows.sort(function(a,b){return b.bn-a.bn||b.li-a.li;}); rows=rows.slice(0,ROWS);
      last=head; return rows.length;
    });
  }).then(function(n){
    ok=true; fails=0; fall.hidden=true;
    state.textContent=rows.length?("Watching Base. "+rows.length+" x402 payment"+(rows.length===1?"":"s")+" to sellers the Atlas knows since this page opened, newest first. Next look in 15 s."):
      "Watching Base: no x402 payment to a seller the Atlas knows in the last "+BLOCKS+" blocks yet. Next look in 15 s.";
    if(rows.length)draw();
    timer=setTimeout(poll,POLL);
  }).catch(fail);
}
setInterval(tick,1000);
poll();
})();"""


def live_body(data):
    """The /live/ fragment: the running list, its notice, the fallback totals, the inline
    wallet table and the inline script."""
    fallback = fallback_html(data)
    script = SCRIPT % {"rpc": RPC, "usdc": chain_flows.USDC.lower(), "transfer": chain_flows.TRANSFER,
                       "auth": chain_flows.AUTHORIZATION_USED, "poll": POLL_MS, "blocks": BLOCKS, "rows": ROWS}
    return _assemble(data, fallback, script)


def fallback_html(data):
    """The words shown when the RPC will not answer: one Base day when the build had it,
    otherwise the rollup's totals, named as exactly that."""
    b = data.get("base_day")
    if b:
        what = "x402-settled payments" if b["x402"] else "transfers to seller wallets (that pull did not split out x402)"
        return ("<p>Newest Base day on record, <span class=\"dated\">%s</span> (UTC): %s %s, %s USDC, from %s, to %s.</p>"
                % (cp.esc(b["date"]), "{:,}".format(b["payments"]), what, cp.esc(cp.money(b["usdc"])),
                   cp.num(b["buyers"], "wallet"), cp.num(b["sellers"], "seller")))
    t, chains = data["totals"], data.get("chains") or ["Base"]
    every = set(chains) <= set(data.get("classified_chains") or [])
    where = "%s over <span class=\"dated\">%s</span>" % (" and ".join(chains), cp.esc(data["day"] or data["as_of"]))
    if every:
        return ("<p>Not one day and not Base alone: the rollup of %s, together: %s x402-settled payments, %s USDC, "
                "from %s, to %s.</p>" % (where, "{:,}".format(t["payments_x402"]), cp.esc(cp.money(t["usdc_x402"])),
                                         cp.num(t["buyer_wallets_x402"], "wallet"), cp.num(t["sellers_paid_x402"], "seller")))
    return ("<p>Not one day and not Base alone: the rollup of %s, together: %s transfers to seller wallets, %s USDC, "
            "to %s. Not every pull in it split out x402, so this counts every transfer.</p>"
            % (where, "{:,}".format(t["payments"]), cp.esc(cp.money(t["usdc"])), cp.num(t["sellers_paid"], "seller")))


def _assemble(data, fallback, script):
    return "".join([
        '<section class="live">',
        '<h1>Live payments</h1>',
        '<p class="muted">x402 payments on Base as they settle, read by your browser straight from the public Base RPC '
        '(%s). Only payments to the %s seller wallets the Atlas knows are shown. Page built <span class="dated">%s</span> '
        'from the rollup of <span class="dated">%s</span>.</p>' % (cp.esc(RPC), "{:,}".format(len(data["wallets"])),
                                                                   cp.esc(data["as_of"]), cp.esc(data["day"] or data["as_of"])),
        '<p id="live-state" class="notice" role="status">Asking Base for the last %d blocks…</p>' % BLOCKS,
        '<noscript><p class="notice">The live list needs JavaScript.</p>%s</noscript>' % fallback,
        '<div id="live-fallback" class="notice" hidden>%s</div>' % fallback,
        '<div class="wrap"><table id="live-table" hidden><thead><tr><th>time</th><th>seller</th><th class="num">amount</th>'
        '<th>paid by</th></tr></thead><tbody id="live-rows"></tbody></table></div>',
        '<p class="muted">An x402 payment here is a USDC transfer whose transaction used an EIP-3009 authorization: a '
        'facilitator settled a payment the buyer signed. Times come from the block; where the RPC does not give one, it is '
        'counted back from the newest block at two seconds a block. A wallet is shown by its address. The Atlas does not '
        'say who holds it.</p>',
        '</section>',
        '<script type="application/json" id="atlas-live-wallets">%s</script>' % table_json(data),
        '<script>%s</script>' % script,
    ])


def write(out, data):
    """out/live/index.html, and the wallet table beside it as wallets.json."""
    html_text = cp.page("Live payments", live_body(data), data["as_of"],
                        "x402 payments on Base as they settle, to sellers the Atlas knows.",
                        room="live", root=data.get("site", ""))
    return cp.write(out, "live", html_text, {"wallets.json": table_json(data)})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--whales", required=True, help="the newest whales-<date>.json rollup")
    ap.add_argument("--snapshot", help="the newest registry snapshot, market-<date>.json")
    ap.add_argument("--flows", help="the newest Base flows-<date>.json, for the fallback when the RPC will not answer")
    ap.add_argument("--site", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rollup = json.load(open(a.whales))
    snap = json.load(open(a.snapshot))["sellers"] if a.snapshot else None
    d = live_data(rollup, snap, a.site, json.load(open(a.flows)) if a.flows else None)
    print("live: %d seller wallets, %d buyer pages -> %s" % (len(d["wallets"]), len(d["buyers"]), write(a.out, d)))


if __name__ == "__main__":
    sys.exit(main())
