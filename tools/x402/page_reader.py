#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 0a16b98). Edit it there, not here.
"""page_reader.py — one web page or PDF, read as clean text, for agents that pay per page.

An agent gives a URL; back comes the page's title, description and language, and its
readable text as markdown-ish plain text: headings as #, list items as -, table rows as
cells joined by " | ", links as their text alone. An HTML page, a plain-text or markdown
file, or a PDF with a text layer. sell-who.py puts the price on it (GET /read?url=…,
$0.001 a page); this file only reads, and decides what cannot be read.

THE WALL. This reader must never be a way to reach anything private from the host it runs
on: not the host itself, not its network, not a cloud's metadata service. Every rule is
tested in test_page_reader.py, and this list is the contract:

    schemes     http and https only
    ports       80 and 443 only
    addresses   the host is resolved ONCE, and refused if ANY answer is not public: loopback,
                private (10/8, 172.16/12, 192.168/16), link-local (169.254/16, which holds the
                cloud metadata address), shared/CGNAT (100.64/10), multicast, reserved,
                unspecified, 0/8, IPv6 unique-local (fc00::/7), link-local (fe80::/10), ::1,
                ::, and any IPv6 address that carries an IPv4 one (::ffff:a.b.c.d,
                64:ff9b::/96, 2002::/16), refused whole and judged inside as well
    literal IPs decimal, octal and hex spellings (http://2130706433/, http://0x7f.1/,
                http://0177.0.0.1/) are read as the address they name, then judged the same
    rebinding   the connection goes to the address that was judged, never to the name
                again; for https that socket is wrapped with server_hostname=the name, so
                the certificate is still checked against what the agent asked for
    redirects   at most 5, and each new address is judged from the start
    limits      15 seconds for the whole read, 5 MB of body (reading stops there),
                200,000 characters of text, 100 PDF pages
    types       text/html, application/xhtml+xml, text/plain, text/markdown and
                application/pdf; anything else is refused
    one page    one request reads one page; links are never followed
    identity    User-Agent InfoharmoniReader/1.0 (+https://atlas.infoharmoni.com/docs/#read)

Two things are injectable so the tests run against a local server with no network at all:
the resolver (name → addresses) and the connection opener (judged address → socket).

    pip install pypdf        # for PDFs only; everything else is the standard library

    python3 -c "import page_reader, json; print(json.dumps(page_reader.read('https://example.com/'), indent=1))"
"""

import http.client
import io
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import zlib
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit

PRICE = "$0.001"   # Vilija, 2026-10-09: the cheapest in the category (the busiest reader, stableenrich.dev, asks $0.002)
PATH = "/read"
USER_AGENT = "InfoharmoniReader/1.0 (+https://atlas.infoharmoni.com/docs/#read)"
TIMEOUT = 15.0                   # seconds, for the whole read: every hop, the connect, the headers and the body
MAX_BYTES = 5 * 1024 * 1024      # of body; reading stops past it and the page is refused
MAX_REDIRECTS = 5
MAX_TEXT = 200_000               # characters of text; past it the text is cut and truncated says so
MAX_PAGES = 100                  # PDF pages read; the page count is still the whole document's
MAX_URL = 2048
SCHEMES = ("http", "https")
PORTS = (80, 443)
TYPES = {"text/html": "html", "application/xhtml+xml": "html", "text/plain": "text",
         "text/markdown": "text", "application/pdf": "pdf"}
ACCEPT = "text/html, application/xhtml+xml, application/pdf, text/plain, text/markdown;q=0.9, */*;q=0.1"
CHUNK = 64 * 1024
NO_TEXT_LAYER = "no text layer: this looks like a scanned document; reading scans is not offered yet"


class Refused(Exception):
    """A read that cannot be sold. `error` is one short word for a program, `say` is plain
    words for the agent. Nothing from the page or the host's own words is put in `say`."""

    def __init__(self, error, say):
        super().__init__(say)
        self.error, self.say = error, say

    def body(self):
        return {"ok": False, "charged": False, "error": self.error, "say": self.say}


# ---------------------------------------------------------------- the wall: which addresses

# Ranges that are never public. The standard library's own is_global knows most of them; they
# are spelled out so a reader can see the wall in one place, and so a change in the library's
# idea of "global" can never quietly open a hole. Both judgments must pass.
NOT_PUBLIC = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
    "192.0.0.0/24", "192.0.2.0/24", "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
    "::/128", "::1/128", "::ffff:0:0/96", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64",
    "2001::/23", "2001:db8::/32", "2002::/16", "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8")]
NAT64 = ipaddress.ip_network("64:ff9b::/96")


def carried_ipv4(addr):
    """The IPv4 address an IPv6 address carries inside it (mapped, 6to4, NAT64), or None."""
    if addr.version != 6:
        return None
    inner = addr.ipv4_mapped or addr.sixtofour
    if inner is None and addr in NAT64:
        inner = ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return inner


def address_problem(text):
    """Why this address may not be connected to, or None when it is a public one. An IPv6
    address that carries an IPv4 one is judged as both, and its ranges are refused whole."""
    try:
        addr = ipaddress.ip_address(str(text).split("%", 1)[0])     # fe80::1%eth0: the zone is not the address
    except ValueError:
        return "not an address"
    for a in (addr, carried_ipv4(addr)):
        if a is None:
            continue
        if any(a in net for net in NOT_PUBLIC) or not a.is_global:
            return "%s is not a public address" % a
    return None


def literal_ipv4(host):
    """An IPv4 address spelled the way inet_aton reads it (decimal, octal with a leading 0,
    hex with 0x; one to four parts, the last filling the rest), or None when the host is not
    such a spelling. http://2130706433/, http://0x7f.1/ and http://0177.0.0.1/ all name
    127.0.0.1, and a browser or curl would go there; so this reads them the same way."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4 or not all(parts):
        return None
    nums = []
    for p in parts:
        if re.fullmatch(r"0[xX][0-9a-fA-F]+", p):
            nums.append(int(p[2:], 16))
        elif re.fullmatch(r"0[0-7]*", p):
            nums.append(int(p, 8))
        elif re.fullmatch(r"[1-9][0-9]*", p):
            nums.append(int(p))
        else:
            return None
    *head, last = nums
    width = 4 - len(head)
    if any(n > 255 for n in head) or last >= 256 ** width:
        return None
    value = last
    for n in reversed(head):
        value |= n << (8 * width)
        width += 1
    return ipaddress.IPv4Address(value)


HOSTNAME = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)*$")


# A name lookup can hang far past any timeout the reader keeps (getaddrinfo has none), and it
# runs before payment (Codex, 2026-10-09). So it runs in a small pool of its own and is waited
# for DNS_SECONDS at most; a lookup still hanging after that keeps its thread, but at most
# DNS_AT_ONCE of them can be outstanding, and past that a new one is refused as busy.
DNS_SECONDS = 5.0
DNS_AT_ONCE = threading.BoundedSemaphore(8)
_DNS_POOL = None


def _lookup(host, port):
    try:
        return socket.getaddrinfo(host, port or 80, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    finally:
        DNS_AT_ONCE.release()


def resolve(host, port=None, seconds=DNS_SECONDS):
    """Every address the system's resolver gives for the name, in its order, without repeats.
    An empty list when the name has none. Refused (busy, or timeout) when the lookup cannot be
    had within `seconds`."""
    global _DNS_POOL
    import concurrent.futures
    if not DNS_AT_ONCE.acquire(blocking=False):
        raise Refused("busy", "too many name lookups are waiting right now; ask again in a moment")
    if _DNS_POOL is None:
        _DNS_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="dns")
    try:
        infos = _DNS_POOL.submit(_lookup, host, port).result(timeout=seconds)
    except concurrent.futures.TimeoutError:
        raise Refused("timeout", "the site's name did not resolve within %d seconds" % seconds)
    out = []
    for _family, _type, _proto, _name, sockaddr in infos:
        if sockaddr[0] not in out:
            out.append(sockaddr[0])
    return out


class Target:
    """A URL judged safe to connect to: where the connection goes (one judged address and the
    port), and how to ask (the name for the Host header and the certificate, the path)."""

    def __init__(self, url, scheme, host, port, address, request_path):
        self.url, self.scheme, self.host, self.port = url, scheme, host, port
        self.address, self.request_path = address, request_path

    def __repr__(self):
        return "Target(%s → %s)" % (self.url, self.address)


def shape(url):
    """Judge a URL's shape, with no lookup at all: scheme, port, host, no login in it, and a
    literal address judged on the spot. Returns a Target whose address is still None for a
    name that has to be resolved (judge() does that), or raises Refused with the reason."""
    if not isinstance(url, str) or not url.strip():
        raise Refused("missing_url", "give a URL in ?url=, like ?url=https://example.com/page")
    url = url.strip()
    if len(url) > MAX_URL or re.search(r"[\s\x00-\x1f\x7f]", url):
        raise Refused("malformed_url", "the URL is too long or carries whitespace or control characters")
    try:
        u = urlsplit(url)
        port = u.port                                         # raises on a port that is not a number
    except ValueError:
        raise Refused("malformed_url", "the URL could not be parsed")
    scheme = (u.scheme or "").lower()
    if scheme not in SCHEMES:
        raise Refused("unsupported_scheme", "only http and https URLs are read")
    if not u.hostname or u.username is not None or u.password is not None:
        raise Refused("malformed_url", "the URL needs a host, and may not carry a login")
    if port is not None and port not in PORTS:
        raise Refused("bad_port", "only ports 80 and 443 are read")
    port = port or (443 if scheme == "https" else 80)
    host = u.hostname.lower().rstrip(".")
    if ":" in host:                                           # an IPv6 literal, its brackets already gone
        why = address_problem(host)
        if why:
            raise Refused("private_address", why)
        address, host_header = str(ipaddress.ip_address(host.split("%", 1)[0])), "[%s]" % host
    elif literal_ipv4(host) is not None:
        address = str(literal_ipv4(host))
        why = address_problem(address)
        if why:
            raise Refused("private_address", why)
        host_header = address
    else:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise Refused("bad_host", "the host name could not be read")
        if host == "localhost" or host.endswith(".localhost"):
            raise Refused("private_address", "localhost is never read")
        if not HOSTNAME.match(host):
            raise Refused("bad_host", "not a host name that can be read")
        address, host_header = None, host
    path = quote(u.path or "/", safe="/%:@!$&'()*+,;=-._~")
    if u.query:
        path += "?" + quote(u.query, safe="/%:@!$&'()*+,;=-._~?")
    return Target(url, scheme, host_header, port, address, path)


def judge(url, resolver=None, seconds=None):
    """Judge one URL before anything is sent: its shape, then the addresses its host names.
    Returns a Target with its judged address, or raises Refused with the reason. The name is
    resolved ONCE, here; the connection goes to the address returned, never to the name
    again. Every address the name resolves to must be public, not just the first: a name
    that answers with one public and one private address is refused."""
    t = shape(url)
    if t.address is not None:                                 # a literal address, judged in shape()
        return t
    if resolver is not None:
        addresses = resolver(t.host, t.port)
    else:
        # within what is left of the read when given (a redirect's lookup), else DNS_SECONDS (Codex)
        wait = DNS_SECONDS if seconds is None else min(DNS_SECONDS, seconds)
        if wait <= 0:
            raise Refused("timeout", "the page took longer than %d seconds to read" % TIMEOUT)
        addresses = resolve(t.host, t.port, seconds=wait)
    if not addresses:
        raise Refused("no_such_host", "the host name has no address")
    for a in addresses:
        if address_problem(a):
            raise Refused("private_address", "the host resolves to a private address; those are never read")
    # one judged address; IPv4 first, since the host this runs on may have no IPv6 route
    t.address = sorted(addresses, key=lambda a: ":" in a)[0]
    return t


# ---------------------------------------------------------------- the fetch

def open_connection(target, timeout):
    """A socket to the judged address, never to the name. For https the socket is wrapped
    with TLS for the NAME, so the certificate is checked against what the agent asked for."""
    sock = socket.create_connection((target.address, target.port), timeout=timeout)
    if target.scheme == "https":
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(sock, server_hostname=target.host.strip("[]"))
    return sock


def content_type(header):
    """(media type, charset) from a Content-Type header; ('', None) when there is none."""
    if not header:
        return "", None
    media, _, params = header.partition(";")
    m = re.search(r"charset\s*=\s*\"?([A-Za-z0-9_.:-]+)", params)
    return media.strip().lower(), (m.group(1).lower() if m else None)


def read_body(resp, sock, max_bytes, deadline):
    """The body, in chunks, within the deadline and the byte cap: reading STOPS past the cap,
    so a page that never ends costs this host at most max_bytes and timeout seconds."""
    chunks, size, raw = [], 0, 0          # size: bytes of page; raw: bytes off the wire (they differ when compressed)
    encoding = (resp.getheader("Content-Encoding") or "").strip().lower()
    inflate = None
    if encoding in ("gzip", "deflate", "x-gzip"):
        inflate = zlib.decompressobj(47 if encoding != "deflate" else 15)
    elif encoding and encoding != "identity":
        raise Refused("unsupported_type", "the page came compressed in a way this reader does not read")
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Refused("timeout", "the page took longer than %d seconds to read" % TIMEOUT)
        sock.settimeout(remaining)
        chunk = resp.read(CHUNK)
        if not chunk:
            break
        raw += len(chunk)
        if raw > max_bytes:                # the cap holds on the wire too, not only on what it unpacks to (Codex)
            raise Refused("too_large", "the page is larger than %d MB; reading stopped" % (MAX_BYTES // (1024 * 1024)))
        if inflate is not None:
            chunk = inflate.decompress(chunk, max_bytes + 1 - size)
        size += len(chunk)
        if size > max_bytes:
            raise Refused("too_large", "the page is larger than %d MB; reading stopped" % (MAX_BYTES // (1024 * 1024)))
        chunks.append(chunk)
        if inflate is not None and inflate.eof:
            break                          # the compressed page has ended; anything after it is not read
    return b"".join(chunks)


def fetch(url, resolver=None, opener=None, timeout=TIMEOUT, max_bytes=MAX_BYTES, target=None):
    """Fetch one page: its bytes, final URL and content type. Up to MAX_REDIRECTS hops, each
    judged from the start (a redirect to 127.0.0.1 is refused like a URL to it); the whole
    read within `timeout` seconds; the body capped at `max_bytes`. `target` is a URL already
    judged by judge(): the first hop then goes to the address judged there, so nothing can
    change between the judgment and the connection. Returns
    {"body", "final_url", "status", "content_type", "charset", "hops"}; raises Refused."""
    deadline = time.monotonic() + timeout
    target = target or judge(url, resolver)
    opener = opener or open_connection
    for hop in range(MAX_REDIRECTS + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Refused("timeout", "the page took longer than %d seconds to read" % TIMEOUT)
        try:
            sock = opener(target, remaining)
        except (socket.timeout, TimeoutError):
            raise Refused("timeout", "the site did not answer within %d seconds" % TIMEOUT)
        except (OSError, ssl.SSLError) as e:
            raise Refused("unreachable", "could not connect to the site: %s" % type(e).__name__)
        # the connection class only names the Host header's default port; connect() is never
        # called, because the socket is already there, to the judged address
        cls = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
        # http.client puts an IPv6 host in brackets itself when it writes the Host header; given
        # "[addr]" with a port, Python 3.11 (Render runs 3.11.9) wrote "[[addr]]". It gets the bare address.
        conn = cls(target.host[1:-1] if target.host.startswith("[") else target.host, target.port, timeout=remaining)
        conn.sock = sock
        try:
            sock.settimeout(remaining)
            conn.request("GET", target.request_path, headers={
                "User-Agent": USER_AGENT, "Accept": ACCEPT, "Accept-Encoding": "identity", "Connection": "close"})
            # the response is read off the socket directly, so the socket stays ours: the deadline
            # is re-applied to it before every chunk of the body (read_body)
            resp = http.client.HTTPResponse(sock, method="GET")
            resp.begin()
            status = resp.status
            if status in (301, 302, 303, 307, 308):
                location = resp.getheader("Location")
                if not location:
                    raise Refused("unreachable", "the site redirected without saying where")
                if hop == MAX_REDIRECTS:
                    raise Refused("too_many_redirects", "more than %d redirects" % MAX_REDIRECTS)
                target = judge(urljoin(target.url, location.strip()), resolver, seconds=deadline - time.monotonic())
                continue
            if not 200 <= status < 300:
                raise Refused("unreachable", "the site answered HTTP %d" % status)
            ctype, charset = content_type(resp.getheader("Content-Type"))
            if ctype not in TYPES:
                raise Refused("unsupported_type", "the page is %s; this reader takes HTML, plain text, markdown "
                                                  "and PDF" % (ctype or "of no stated type"))
            length = resp.getheader("Content-Length")
            if length and length.strip().isdigit() and int(length) > max_bytes:
                raise Refused("too_large", "the page is larger than %d MB" % (MAX_BYTES // (1024 * 1024)))
            body = read_body(resp, sock, max_bytes, deadline)
        except (socket.timeout, TimeoutError):
            raise Refused("timeout", "the page took longer than %d seconds to read" % TIMEOUT)
        except (http.client.HTTPException, OSError, ssl.SSLError) as e:
            raise Refused("unreachable", "the site's answer could not be read: %s" % type(e).__name__)
        finally:
            conn.close()
            try:
                sock.close()
            except OSError:
                pass
        return {"body": body, "final_url": target.url, "status": status, "content_type": ctype,
                "charset": charset, "hops": hop}
    raise Refused("too_many_redirects", "more than %d redirects" % MAX_REDIRECTS)


# ---------------------------------------------------------------- HTML to text

DROP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "iframe", "template",
        "canvas", "video", "audio", "object", "map", "select", "button", "dialog"}
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
BLOCKS = {"p", "div", "section", "article", "main", "ul", "ol", "li", "blockquote", "pre", "table", "thead",
          "tbody", "tfoot", "tr", "td", "th", "caption", "dl", "dt", "dd", "figure", "figcaption", "details",
          "summary", "address", "hr", "body", "html", "center", "fieldset", "legend", "menu", "dir",
          "option", "textarea", "label", "h1", "h2", "h3", "h4", "h5", "h6"}
VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "param", "source", "track",
        "wbr"}
# a tag that opens while one of these is on top closes it first, as a browser would (<li>a<li>b)
IMPLIED_END = {"li": {"li"}, "p": BLOCKS, "dt": {"dt", "dd"}, "dd": {"dt", "dd"},
               "tr": {"tr"}, "td": {"td", "th", "tr"}, "th": {"td", "th", "tr"}, "option": {"option"}}


def collapse(pieces, pre=False):
    """One block's text from its pieces: whitespace collapsed to single spaces, a <br> kept as
    a line break, empty lines gone. Inside <pre> everything is kept as it is."""
    s = "".join(pieces)
    if pre:
        return s.strip("\n")
    lines = [re.sub(r"[ \t\r\f\v\xa0]+", " ", line).strip() for line in s.split("\n")]
    return "\n".join(line for line in lines if line)


class Extractor(HTMLParser):
    """Reads one HTML document into blocks of text with a kind each: heading (with its level),
    paragraph, list item (with its depth), table row, quote, or preformatted. Everything in
    DROP is skipped with all it holds; the title, the meta description and the html lang are
    kept aside. Blocks inside <main> or <article> are marked, and read() prefers them."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.stack, self.buf, self.cells = [], [], [], None
        self.title, self.description, self.language = None, None, None
        self.in_title, self.in_cell = False, False

    # --- context from the open tags
    def depth(self, *names):
        return sum(1 for t in self.stack if t in names)

    def flush(self):
        """End the block being collected. Inside a table cell the text stays in the cell."""
        if self.in_cell:
            self.buf.append(" ")
            return
        pre = self.depth("pre") > 0
        text = collapse(self.buf, pre)
        self.buf = []
        if not text:
            return
        kind, level = "p", 0
        heading = next((HEADINGS[t] for t in reversed(self.stack) if t in HEADINGS), None)
        if pre:
            kind = "pre"
        elif heading:
            kind, level = "h", heading
        elif "li" in self.stack:
            kind, level = "li", self.depth("ul", "ol", "menu", "dir") or 1
        elif "blockquote" in self.stack:
            kind = "quote"
        self.blocks.append({"kind": kind, "level": level, "text": text, "main": self.depth("main", "article") > 0})

    def close(self, tag):
        """Pop the stack down to and including `tag`, ending what each popped tag held."""
        if tag not in self.stack:
            return
        while self.stack:
            top = self.stack[-1]
            self.ended(top)                    # with the tag still on the stack: the kind is read from it
            self.stack.pop()
            if top == tag:
                break

    def ended(self, tag):
        if tag in ("td", "th"):
            if self.cells is not None:
                self.cells.append(collapse(self.buf).replace("\n", " "))
            self.buf, self.in_cell = [], False
        elif tag == "tr":
            self.flush()
            if self.cells is not None and any(self.cells):
                self.blocks.append({"kind": "row", "level": 0, "text": " | ".join(self.cells),
                                    "main": self.depth("main", "article") > 0})
            self.cells = None
        elif tag in BLOCKS:
            self.flush()
        elif tag == "title":
            self.in_title = False

    # --- the parser's calls
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.language = (a.get("lang") or a.get("xml:lang") or "").strip() or self.language
        if tag == "meta":
            name = (a.get("name") or a.get("property") or "").strip().lower()
            if name in ("description", "og:description") and a.get("content") and (
                    self.description is None or name == "description"):
                self.description = re.sub(r"\s+", " ", a["content"]).strip() or None
            return
        if self.depth(*DROP) > 0:
            if tag not in VOID:
                self.stack.append(tag)
            return
        if tag == "title":
            self.in_title = True
            self.stack.append(tag)
            return
        if tag == "br":
            self.buf.append("\n")
            return
        if tag in VOID:
            if tag == "hr":
                self.flush()
            return
        while self.stack and self.stack[-1] in IMPLIED_END and tag in IMPLIED_END[self.stack[-1]]:
            self.close(self.stack[-1])
        if tag in DROP:
            self.flush()
        elif tag == "tr":
            self.flush()
            self.cells = []
        elif tag in ("td", "th"):
            self.flush()
            if self.cells is None:
                self.cells = []
            self.in_cell = True
        elif tag in BLOCKS:
            self.flush()
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        self.close(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self.in_title:
            self.title = ((self.title or "") + data)
            return
        if self.depth(*DROP) > 0:
            return
        if self.depth("pre") == 0:
            data = re.sub(r"[\r\n\t\f\v]+", " ", data)
        self.buf.append(data)

    def finish(self):
        """What is left when the document ends, and the blocks to keep."""
        while self.stack:
            self.ended(self.stack[-1])
            self.stack.pop()
        self.flush()
        if any(b["main"] for b in self.blocks):
            self.blocks = [b for b in self.blocks if b["main"]]
        self.title = re.sub(r"\s+", " ", self.title).strip() if self.title else None
        return self.blocks


def render(blocks):
    """The blocks as markdown-ish text: one blank line between blocks, list items and table
    rows on consecutive lines."""
    out, last = [], None
    for b in blocks:
        kind, text = b["kind"], b["text"]
        if kind == "h":
            line = "#" * b["level"] + " " + text.replace("\n", " ")
        elif kind == "li":
            line = "  " * (b["level"] - 1) + "- " + text.replace("\n", "\n" + "  " * b["level"])
        elif kind == "quote":
            line = "\n".join("> " + ln for ln in text.split("\n"))
        elif kind == "pre":
            line = "```\n" + text + "\n```"
        else:
            line = text
        if out:
            out.append("\n" if kind == last and kind in ("li", "row") else "\n\n")
        out.append(line)
        last = kind
    return "".join(out)


def decode(body, charset=None, html=False):
    """Bytes to text: the header's charset, else for HTML the <meta charset> in the first
    bytes, else UTF-8; never raises (bad bytes become U+FFFD)."""
    if html and not charset:
        head = body[:4096].decode("ascii", "replace")
        m = re.search(r"<meta[^>]+charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:-]+)", head, re.IGNORECASE)
        charset = m.group(1).lower() if m else None
    if body.startswith(b"\xef\xbb\xbf"):
        body, charset = body[3:], "utf-8"
    for enc in (charset, "utf-8"):
        if not enc:
            continue
        try:
            return body.decode(enc, "replace")
        except LookupError:
            continue
    return body.decode("utf-8", "replace")


def html_text(text):
    """An HTML document as {title, description, language, text}."""
    x = Extractor()
    try:
        x.feed(text)
        x.close()
    except Exception:          # a document html.parser cannot finish: keep what was read
        pass
    blocks = x.finish()
    return {"title": x.title, "description": x.description, "language": x.language or None,
            "text": render(blocks), "pages": None, "truncated": False}


def plain_text(text, markdown=False):
    """A plain-text or markdown file: line ends normalised, trailing spaces gone, runs of blank
    lines reduced to one. A markdown file's first # heading is its title."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")
    title = None
    if markdown:
        m = re.search(r"^#\s+(.+?)\s*#*\s*$", text, re.MULTILINE)
        title = m.group(1).strip() if m else None
    return {"title": title, "description": None, "language": None, "text": text, "pages": None, "truncated": False}


def pdf_text(body):
    """A PDF's text layer, page by page, with pypdf: at most MAX_PAGES pages read, the whole
    document's page count recorded. A PDF with pages and no text at all is a scan, and is
    refused with NO_TEXT_LAYER: reading scans is not offered."""
    try:
        import logging
        from pypdf import PdfReader
        logging.getLogger("pypdf").setLevel(logging.ERROR)
    except ImportError:
        raise Refused("pdf_not_installed", "PDF reading is not installed on this host")
    try:
        reader = PdfReader(io.BytesIO(body))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise Refused("encrypted_pdf", "the PDF is encrypted; it cannot be read")
        count = len(reader.pages)
        pages = []
        for i in range(min(count, MAX_PAGES)):
            pages.append((reader.pages[i].extract_text() or "").strip())
        meta = reader.metadata
        title = (str(meta.title).strip() if meta is not None and meta.title else None) or None
    except Refused:
        raise
    except Exception as e:
        raise Refused("unreadable_pdf", "this PDF could not be read: %s" % type(e).__name__)
    if count == 0:
        raise Refused("empty_text", "the PDF has no pages")
    text = "\n\n".join(p for p in pages if p)
    if not text.strip():
        raise Refused("scanned_pdf", NO_TEXT_LAYER)
    return {"title": title, "description": None, "language": None, "text": text, "pages": count,
            "truncated": count > MAX_PAGES}


# A PDF is read in a process of its own, under hard limits (Codex, 2026-10-09). The 5 MB cap
# bounds the download, not what it unpacks into: a small PDF built to expand, or to cost CPU,
# could take this server down, and a failed read is never charged, so for free. The child:
#   - lowers pypdf's per-stream decompression caps from 75 MB to PDF_STREAM_CAP;
#   - limits its own CPU time (and its address space where the OS enforces it, as Linux does);
#   - is killed past PDF_SECONDS of wall clock.
# At most PDF_AT_ONCE such children run at a time; past that, a request waits a little, then
# is refused as busy (503, not charged).
HERE = os.path.dirname(os.path.abspath(__file__))
PDF_SECONDS = 15
PDF_CPU_SECONDS = 12
PDF_MEMORY = 768 * 1024 * 1024
PDF_STREAM_CAP = 16 * 1024 * 1024
PDF_AT_ONCE = threading.BoundedSemaphore(2)
_PDF_CHILD = r"""
import json, sys
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (int(sys.argv[3]), int(sys.argv[3]) + 1))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (int(sys.argv[4]), int(sys.argv[4])))
    except (ValueError, OSError):
        pass                                    # macOS does not enforce an address-space limit
except ImportError:
    pass
sys.path.insert(0, sys.argv[1])
try:
    import pypdf.filters as f
    for name in ("ZLIB_MAX_OUTPUT_LENGTH", "MAX_DECLARED_STREAM_LENGTH", "LZW_MAX_OUTPUT_LENGTH",
                 "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH", "RUN_LENGTH_MAX_OUTPUT_LENGTH", "FLATE_MAX_BUFFER_SIZE"):
        if hasattr(f, name):
            setattr(f, name, int(sys.argv[2]))
except ImportError:
    pass
import page_reader as p
try:
    out = {"ok": True, "doc": p.pdf_text(sys.stdin.buffer.read())}
except p.Refused as e:
    out = {"ok": False, "error": e.error, "say": e.say}
sys.stdout.write(json.dumps(out))
"""


def pdf_text_bounded(body, seconds=PDF_SECONDS):
    """pdf_text() in a child process under the limits above, all within `seconds` (the waiting
    for a free place included). Raises Refused: busy, timeout, unreadable_pdf (the child died or
    ran out of what it was allowed), or what pdf_text() says."""
    deadline = time.monotonic() + seconds
    if seconds <= 0:
        raise Refused("timeout", "the page took longer than %d seconds to read" % TIMEOUT)
    if not PDF_AT_ONCE.acquire(timeout=seconds):
        raise Refused("busy", "too many PDFs are being read right now; ask again in a moment")
    try:
        left = deadline - time.monotonic()
        if left <= 0:
            raise subprocess.TimeoutExpired("pdf", seconds)
        r = subprocess.run([sys.executable, "-I", "-c", _PDF_CHILD, HERE, str(PDF_STREAM_CAP), str(PDF_CPU_SECONDS),
                            str(PDF_MEMORY)], input=body, capture_output=True, timeout=left)
    except subprocess.TimeoutExpired:
        raise Refused("timeout", "the PDF took longer than %d seconds to read" % seconds)
    finally:
        PDF_AT_ONCE.release()
    try:
        out = json.loads(r.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Refused("unreadable_pdf", "this PDF could not be read within this reader's limits")
    if not out.get("ok"):
        raise Refused(out.get("error") or "unreadable_pdf", out.get("say") or "this PDF could not be read")
    return out["doc"]


# ---------------------------------------------------------------- the answer

def read(url, resolver=None, opener=None, timeout=TIMEOUT, max_bytes=MAX_BYTES, target=None, now=None):
    """One page as clean text: {ok, url, final_url, status, content_type, title, description,
    language, text, words, chars, pages, truncated, fetched_at}. pages is the PDF's page count
    and None otherwise. Raises Refused for anything that cannot be sold."""
    started = time.monotonic()
    got = fetch(url, resolver, opener, timeout, max_bytes, target)
    kind = TYPES[got["content_type"]]
    if kind == "pdf":
        # one deadline for the whole read: the PDF gets what the download left of it (Codex)
        left = min(PDF_SECONDS, timeout - (time.monotonic() - started))
        if left <= 0:
            raise Refused("timeout", "the page took longer than %d seconds to read" % timeout)
        doc = pdf_text_bounded(got["body"], seconds=left)
    elif kind == "html":
        doc = html_text(decode(got["body"], got["charset"], html=True))
    else:
        doc = plain_text(decode(got["body"], got["charset"]), markdown=got["content_type"] == "text/markdown")
    text, truncated = doc["text"], doc["truncated"]
    if len(text) > MAX_TEXT:
        text, truncated = text[:MAX_TEXT], True
    if not text.strip():
        raise Refused("empty_text", "the page has no readable text")
    fetched = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"ok": True, "url": target.url if target is not None else url.strip(), "final_url": got["final_url"],
            "status": got["status"], "content_type": got["content_type"], "title": doc["title"],
            "description": doc["description"], "language": doc["language"], "text": text,
            "words": len(text.split()), "chars": len(text), "pages": doc["pages"], "truncated": truncated,
            "fetched_at": fetched}


class Reader:
    """The reader with its outside world named: `resolver(host, port)` answers addresses and
    `opener(target, timeout)` connects. Both default to the real network; tests hand in a
    local pair. sell-who.py judges with one call before payment and reads with the other
    after it, so the address judged is the address connected to."""

    def __init__(self, resolver=None, opener=None, timeout=TIMEOUT, max_bytes=MAX_BYTES):
        self.resolver, self.opener, self.timeout, self.max_bytes = resolver, opener, timeout, max_bytes

    def judge(self, url):
        return judge(url, self.resolver)

    def read(self, target, now=None):
        return read(target.url, self.resolver, self.opener, self.timeout, self.max_bytes, target=target, now=now)


if __name__ == "__main__":
    import json
    import sys
    try:
        print(json.dumps(read(sys.argv[1]), indent=1, ensure_ascii=False))
    except Refused as r:
        sys.exit("refused: %s: %s" % (r.error, r.say))
