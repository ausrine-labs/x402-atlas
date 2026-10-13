#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 5c193d9). Edit it there, not here.
"""evmsig.py — who signed this message? Ethereum's personal_sign, checked with the standard library.

    signer(message, signature) -> "0x..." (lowercase) or None

An EVM wallet proves it is its own by signing a text message (EIP-191 personal_sign, what
every wallet's "sign message" does). This recovers the signing address from the message and
the 65-byte signature: Keccak-256 and secp256k1 public-key recovery, written out here so
the Atlas build needs nothing outside Python. It only checks signatures; it never makes or
holds a key. A signature that is malformed, has a high S value (EIP-2), or does not recover
gives None, never an exception.

Tested against the eth_account library's own signatures (evmsig_test.py).
"""

import re

# ── Keccak-256 (the pre-NIST padding Ethereum uses) ──────────────────────

_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B,
       0x0000000080000001, 0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088,
       0x0000000080008009, 0x000000008000000A, 0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
       0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x, n):
    return ((x << n) | (x >> (64 - n))) & _M if n else x


def _keccak_f(a):
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        a = [[a[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        a = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        a[0][0] ^= rc
    return a


def keccak256(data):
    rate = 136
    msg = bytearray(data) + b"\x01"
    while len(msg) % rate:
        msg += b"\x00"
    msg[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        block = msg[off:off + rate]
        for i in range(rate // 8):
            x, y = i % 5, i // 5
            a[x][y] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        a = _keccak_f(a)
    out = b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))
    return out


# ── secp256k1 ────────────────────────────────────────────────────────────

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % P == 0:
        return None
    if p == q:
        lam = 3 * p[0] * p[0] * pow(2 * p[1], -1, P) % P
    else:
        lam = (q[1] - p[1]) * pow(q[0] - p[0], -1, P) % P
    x = (lam * lam - p[0] - q[0]) % P
    return x, (lam * (p[0] - x) - p[1]) % P


def _mul(k, p):
    r = None
    while k:
        if k & 1:
            r = _add(r, p)
        p = _add(p, p)
        k >>= 1
    return r


def _recover(h, r, s, v):
    """The public key (x, y) that signed hash h with (r, s) and recovery id v (0 or 1), or None."""
    if not (1 <= r < N and 1 <= s <= N // 2) or v not in (0, 1):   # low S only (EIP-2): no second form of a signature
        return None
    x = r
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if y * y % P != y2:
        return None
    if y % 2 != v:
        y = P - y
    R = (x, y)
    e = int.from_bytes(h, "big") % N
    rinv = pow(r, -1, N)
    Q = _add(_mul(s * rinv % N, R), _mul((-e * rinv) % N, G))
    return Q


SIG = re.compile(r"^(0x)?[0-9a-fA-F]{130}$")


def personal_hash(message):
    m = message.encode("utf-8") if isinstance(message, str) else bytes(message)
    return keccak256(b"\x19Ethereum Signed Message:\n" + str(len(m)).encode() + m)


def signer(message, signature):
    """The 0x address (lowercase) whose key made `signature` over `message` with personal_sign,
    or None when the signature is malformed or recovers nothing."""
    try:
        if not isinstance(signature, str) or not SIG.match(signature):
            return None
        b = bytes.fromhex(signature[2:] if signature.startswith("0x") else signature)
        r, s, v = int.from_bytes(b[:32], "big"), int.from_bytes(b[32:64], "big"), b[64]
        v = v - 27 if v >= 27 else v
        Q = _recover(personal_hash(message), r, s, v)
        if Q is None:
            return None
        pub = Q[0].to_bytes(32, "big") + Q[1].to_bytes(32, "big")
        return "0x" + keccak256(pub)[-20:].hex()
    except Exception:  # noqa: BLE001 - untrusted input: no answer, never a crash
        return None
