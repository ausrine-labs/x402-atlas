# Copied from the Aušrinė lab (commit 5c193d9). Edit it there, not here.
"""evmsig_test.py — the signature check against signatures made by the eth_account library
(evmsig_vectors.json, made once with it; the check itself needs nothing outside Python)."""
import json
import os
import unittest

import evmsig

HERE = os.path.dirname(os.path.abspath(__file__))
VECTORS = json.load(open(os.path.join(HERE, "evmsig_vectors.json"), encoding="utf-8"))["messages"]


class Keccak(unittest.TestCase):
    def test_known_digests(self):
        self.assertEqual(evmsig.keccak256(b"").hex(), "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")
        self.assertEqual(evmsig.keccak256(b"abc").hex(), "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45")


class Signer(unittest.TestCase):
    def test_every_vector_recovers_its_address(self):
        for v in VECTORS:
            self.assertEqual(evmsig.signer(v["message"], v["signature"]), v["address"], v["message"][:30])

    def test_a_changed_message_names_someone_else(self):
        v = VECTORS[0]
        self.assertNotEqual(evmsig.signer(v["message"] + " ", v["signature"]), v["address"])

    def test_malformed_signatures_give_none(self):
        v = VECTORS[0]
        for bad in ("", "0x", "0x12", v["signature"][:-2], v["signature"] + "00", "zz" * 65, None, 7):
            self.assertIsNone(evmsig.signer(v["message"], bad), repr(bad)[:20])

    def test_the_high_s_twin_is_refused(self):
        v = VECTORS[0]
        b = bytes.fromhex(v["signature"][2:])
        s = int.from_bytes(b[32:64], "big")
        twin = b[:32] + (evmsig.N - s).to_bytes(32, "big") + bytes([b[64] ^ 1])
        self.assertIsNone(evmsig.signer(v["message"], "0x" + twin.hex()))


if __name__ == "__main__":
    unittest.main()
