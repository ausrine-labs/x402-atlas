#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 21a8a83). Edit it there, not here.
"""Tests for team_pay.py: a team's split is shown only when Base says it pays the card's terms, with no owner."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evmsig  # noqa: E402
import team_pay as tp  # noqa: E402

A, B = "0x" + "a1" * 20, "0x" + "b2" * 20
SPLIT = "0x" + "5c" * 20
TXH = "0x" + "77" * 32
FACTORY = "0x8e8eb0cc6ae34a38b67d5cf91aca38f60bc3ecf4"
REAL_EVENT = ("0x" + "%064x" % 0x80 + "%064x" % 0x5789d634b3bba3f68958f21975c2eec8d91847c4 * 2 + "0" * 64 + "%064x" % 0x80
              + "%064x" % 0xe0 + "%064x" % 1000000 + "0" * 64 + "%064x" % 2 + "%064x" % 0x297de03802b95e84311d509d125d2585a4c88deb
              + "%064x" % 0x39c5b4fc88bcaf3df897e6a82e6aeeda6a0b9921 + "%064x" % 2 + "%064x" % 500000 * 2)
REAL_HASH = "0xad2817cd2188ca92cdc2cfbb537ac48ece3970b115e5912796a24ae6971266b6"
W = lambda x: int(x).to_bytes(32, "big")


def team(split=(("sq:a", 60), ("sq:b", 40)), proven=True, payto=SPLIT, tx=TXH):
    return {"at": "2026-11-01T00:00:00", "payto": payto, "payto_tx": tx, "split": [list(x) for x in split],
            "members": [{"author": "sq:a", "wallet_proven": proven, "payto": A},
                        {"author": "sq:b", "wallet_proven": proven, "payto": B}]}


def made(recipients=(A, B, tp.SQUARE_FEE_WALLET), allocs=(588000, 392000, 20000), incentive=0):
    return {"recipients": list(recipients), "allocations": list(allocs), "total": sum(allocs), "incentive": incentive}


def chain(s=None, owner=0, factory=FACTORY, created=SPLIT, status="0x1", now_hash=None, now_owner=0, fail=False):
    """A fake Base: one SplitCreated log in the receipt, and the split's answers to splitHash() and owner()."""
    s = s or made()
    data = W(128) + W(owner) + W(0xc0ffee) + W(0) + tp.encode_split(s)[32:]
    log = {"address": factory, "topics": [sorted(tp.CREATED)[0], "0x" + "00" * 12 + created[2:]], "data": "0x" + data.hex()}
    h = now_hash or "0x" + evmsig.keccak256(tp.encode_split(s)).hex()

    def call(method, params):
        if fail:
            raise OSError("down")
        if method == "eth_getTransactionReceipt":
            return {"status": status, "logs": [log]}
        if params[0]["data"] == tp.SEL_SPLIT_HASH:
            return h
        return "0x" + W(now_owner).hex()
    return call


class TeamPay(unittest.TestCase):
    def test_a_split_with_the_cards_terms_and_no_owner_is_payable(self):
        r = tp.check(team(), call=chain())
        self.assertEqual(r["status"], "payable", r)
        self.assertEqual(r["address"], SPLIT)

    def test_the_encoding_matches_a_real_split_on_base(self):
        # SplitCreated from PushSplitFactory v2.2 on Base, tx 0x607e3e40…1d5a, split 0x25c9953f…501a; on 16 Oct 2026
        # its splitHash() answered REAL_HASH. Decoding the event and hashing it again must give the same value.
        data = bytes.fromhex(REAL_EVENT[2:])
        s = tp.decode_split(data, tp._word(data, 0))
        self.assertEqual(s["allocations"], [500000, 500000])
        self.assertEqual("0x" + data[44:64].hex(), "0x5789d634b3bba3f68958f21975c2eec8d91847c4")   # it has an owner
        self.assertEqual("0x" + evmsig.keccak256(tp.encode_split(s)).hex(), REAL_HASH)

    def test_an_owner_is_refused(self):
        self.assertEqual(tp.check(team(), call=chain(owner=0xbad))["status"], "refused")
        self.assertIn("owner", tp.check(team(), call=chain(now_owner=0xbad))["why"])

    def test_another_factory_or_another_address_is_refused(self):
        self.assertEqual(tp.check(team(), call=chain(factory="0x" + "11" * 20))["status"], "refused")
        self.assertEqual(tp.check(team(), call=chain(created="0x" + "22" * 20))["status"], "refused")
        self.assertEqual(tp.check(team(), call=chain(status="0x0"))["status"], "refused")

    def test_terms_changed_since_creation_are_refused(self):
        r = tp.check(team(), call=chain(now_hash="0x" + "00" * 32))
        self.assertEqual(r["status"], "refused")
        self.assertIn("no longer", r["why"])

    def test_shares_fee_and_incentive_must_match(self):
        self.assertIn("differ", tp.check(team(), call=chain(made(allocs=(500000, 480000, 20000))))["why"])
        self.assertIn("leaves out", tp.check(team(), call=chain(made(recipients=(A, B), allocs=(600000, 400000))))["why"])
        self.assertIn("also pays", tp.check(team(), call=chain(made(recipients=(A, B, tp.SQUARE_FEE_WALLET, "0x" + "99" * 20),
                                                                    allocs=(588000, 382000, 20000, 10000))))["why"])
        self.assertIn("incentive", tp.check(team(), call=chain(made(incentive=1)))["why"])

    def test_not_yet_when_a_member_is_unproven_or_base_is_down(self):
        self.assertEqual(tp.check(team(proven=False), call=chain())["status"], "not_yet")
        self.assertEqual(tp.check(team(), call=chain(fail=True))["status"], "not_yet")
        self.assertEqual(tp.check(team(payto=None), call=chain())["status"], "not_yet")
        self.assertEqual(tp.check(team(tx=None), call=chain())["status"], "refused")

    def test_a_zero_share_seat_needs_no_wallet_and_is_left_out(self):
        tm = team(split=(("sq:a", 60), ("sq:b", 40), ("sq:c", 0)))
        tm["members"].append({"author": "sq:c", "wallet_proven": False, "payto": None})
        self.assertEqual(tp.check(tm, call=chain())["status"], "payable")

    def test_terms_tell_the_lead_what_to_enter(self):
        got, why = tp.terms(team())
        self.assertIsNone(why)
        self.assertEqual(got, [(A, 58.8), (B, 39.2), (tp.SQUARE_FEE_WALLET, 2.0)])


if __name__ == "__main__":
    unittest.main()
