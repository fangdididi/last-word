import copy
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import lastword as lw  # noqa: E402

D = dt.date.fromisoformat
PREC = {"law": 9, "contract": 5, "amendment": 5, "email": 2, "chat": 1}


def claim(cid, value, kind="contract", start="2026-01-01", **kw):
    c = {"id": cid, "subject": "fee", "property": "amount", "value": value, "kind": kind,
         "source": "doc-" + cid, "recorded_on": kw.pop("recorded_on", start), "quote": "q " + cid}
    if start is not None:
        c["effective_from"] = start
    c.update(kw)
    return c


def ledger(*claims):
    return {"precedence": dict(PREC), "claims": list(claims)}


def codes(issues, level=None):
    return [i[2] for i in issues if level is None or i[0] == level]


class LintTests(unittest.TestCase):
    def test_clean_ledger(self):
        self.assertEqual(codes(lw.lint(ledger(claim("A", "1"))), "ERROR"), [])

    def test_no_precedence(self):
        self.assertIn("NO_PRECEDENCE", codes(lw.lint({"claims": [claim("A", "1")]})))

    def test_bad_rank(self):
        L = ledger(claim("A", "1")); L["precedence"]["contract"] = "high"
        self.assertIn("BAD_RANK", codes(lw.lint(L)))

    def test_no_claims(self):
        self.assertIn("NO_CLAIMS", codes(lw.lint({"precedence": PREC, "claims": []})))

    def test_missing_fields(self):
        c = claim("A", "1"); del c["source"]
        self.assertIn("MISSING", codes(lw.lint(ledger(c))))

    def test_duplicate_id(self):
        self.assertIn("DUP_ID", codes(lw.lint(ledger(claim("A", "1"), claim("A", "2")))))

    def test_unknown_kind(self):
        self.assertIn("UNKNOWN_KIND", codes(lw.lint(ledger(claim("A", "1", kind="memo")))))

    def test_bad_date(self):
        self.assertIn("BAD_DATE", codes(lw.lint(ledger(claim("A", "1", start="2026/01/01")))))

    def test_empty_window(self):
        self.assertIn("EMPTY_WINDOW", codes(lw.lint(ledger(claim("A", "1", effective_to="2026-01-01")))))

    def test_date_guessed_warning(self):
        self.assertIn("DATE_GUESSED", codes(lw.lint(ledger(claim("A", "1", start=None, recorded_on="2026-01-01"))), "WARN"))

    def test_no_quote_warning(self):
        c = claim("A", "1"); c["quote"] = ""
        self.assertIn("NO_QUOTE", codes(lw.lint(ledger(c)), "WARN"))

    def test_long_quote_warning(self):
        c = claim("A", "1", quote="word " * 41)
        self.assertIn("LONG_QUOTE", codes(lw.lint(ledger(c)), "WARN"))

    def test_supersedes_not_list(self):
        self.assertIn("BAD_SUPERSEDES", codes(lw.lint(ledger(claim("A", "1", supersedes="B")))))

    def test_self_supersede(self):
        self.assertIn("SELF_SUPERSEDE", codes(lw.lint(ledger(claim("A", "1", supersedes=["A"])))))

    def test_unknown_target(self):
        self.assertIn("UNKNOWN_TARGET", codes(lw.lint(ledger(claim("A", "1", supersedes=["Z"])))))

    def test_cross_topic(self):
        b = claim("B", "2", supersedes=["A"]); b["property"] = "other"
        self.assertIn("CROSS_TOPIC", codes(lw.lint(ledger(claim("A", "1"), b)), "WARN"))

    def test_check_power(self):
        L = ledger(claim("A", "1"), claim("B", "2", kind="email", supersedes=["A"]))
        self.assertIn("CHECK_POWER", codes(lw.lint(L), "WARN"))

    def test_cycle(self):
        L = ledger(claim("A", "1", supersedes=["B"]), claim("B", "2", supersedes=["A"]))
        self.assertIn("CYCLE", codes(lw.lint(L), "ERROR"))


class ResolveTests(unittest.TestCase):
    def r(self, L, as_of="2026-06-01", **kw):
        return lw.resolve(L, "fee", "amount", D(as_of), **kw)

    def test_no_source(self):
        self.assertEqual(lw.resolve(ledger(claim("A", "1")), "fee", "nope", D("2026-06-01"))["verdict"], "NO_SOURCE")

    def test_single_claim_settled(self):
        r = self.r(ledger(claim("A", "1")))
        self.assertEqual((r["verdict"], r["winner"]["value"]), ("SETTLED", "1"))

    def test_case_and_space_insensitive_topic(self):
        r = lw.resolve(ledger(claim("A", "1")), "  FEE ", "Amount", D("2026-06-01"))
        self.assertEqual(r["verdict"], "SETTLED")

    def test_not_yet(self):
        r = self.r(ledger(claim("A", "1", start="2026-09-01")))
        self.assertEqual(r["verdict"], "NOT_YET")
        self.assertEqual(r["pending"][0]["id"], "A")

    def test_expired(self):
        r = self.r(ledger(claim("A", "1", effective_to="2026-03-01")))
        self.assertEqual(r["verdict"], "NOTHING_IN_FORCE")
        self.assertEqual(r["beaten"][0]["reason"], "EXPIRED")

    def test_expiry_day_is_exclusive(self):
        L = ledger(claim("A", "1", effective_to="2026-06-01"))
        self.assertEqual(self.r(L, "2026-05-31")["verdict"], "SETTLED")
        self.assertEqual(self.r(L, "2026-06-01")["verdict"], "NOTHING_IN_FORCE")

    def test_supersede_wins(self):
        L = ledger(claim("A", "30"), claim("B", "45", kind="amendment", start="2026-03-01", supersedes=["A"]))
        r = self.r(L)
        self.assertEqual(r["winner"]["id"], "B")
        self.assertEqual(r["beaten"], [{"id": "A", "reason": "SUPERSEDED", "by": "B"}])

    def test_supersede_not_before_its_start(self):
        L = ledger(claim("A", "30"), claim("B", "45", start="2026-08-01", supersedes=["A"]))
        r = self.r(L)
        self.assertEqual(r["winner"]["id"], "A")
        self.assertIn("CHANGE_COMING", r["flags"])

    def test_supersede_beats_rank(self):
        # an explicit replacement removes the target even if it outranks the replacer
        L = ledger(claim("A", "30", kind="law"), claim("B", "45", start="2026-02-01", supersedes=["A"]))
        self.assertEqual(self.r(L)["winner"]["id"], "B")

    def test_higher_rank_beats_later(self):
        L = ledger(claim("A", "30", kind="contract"), claim("B", "60", kind="email", start="2026-01-01", recorded_on="2025-12-01"))
        r = self.r(L)
        self.assertEqual(r["winner"]["id"], "A")

    def test_later_lower_rank_is_drift(self):
        L = ledger(claim("A", "30"), claim("B", "60", kind="email", start="2026-04-01"))
        r = self.r(L)
        self.assertEqual(r["winner"]["id"], "A")
        self.assertEqual(r["drift"][0]["id"], "B")
        self.assertIn("DRIFT", r["flags"])

    def test_earlier_lower_rank_is_outranked(self):
        L = ledger(claim("A", "30", start="2026-03-01"), claim("B", "60", kind="email", start="2026-01-01"))
        r = self.r(L)
        self.assertEqual(r["beaten"], [{"id": "B", "reason": "OUTRANKED"}])
        self.assertEqual(r["drift"], [])

    def test_lower_rank_agreeing(self):
        L = ledger(claim("A", "30"), claim("B", " 30 ", kind="chat", start="2026-04-01"))
        r = self.r(L)
        self.assertEqual(r["beaten"], [{"id": "B", "reason": "AGREES"}])
        self.assertNotIn("DRIFT", r["flags"])

    def test_same_rank_later_wins(self):
        L = ledger(claim("A", "30"), claim("B", "45", start="2026-02-01"))
        r = self.r(L)
        self.assertEqual(r["winner"]["id"], "B")
        self.assertEqual(r["beaten"], [{"id": "A", "reason": "OLDER"}])

    def test_same_rank_same_day_conflict(self):
        L = ledger(claim("A", "30"), claim("B", "45"))
        r = self.r(L)
        self.assertEqual(r["verdict"], "CONFLICT")
        self.assertEqual([c["id"] for c in r["conflict"]], ["A", "B"])
        self.assertIsNone(r["winner"])

    def test_same_day_same_value_not_conflict(self):
        L = ledger(claim("A", "30"), claim("B", "30", recorded_on="2026-01-02"))
        r = self.r(L)
        self.assertEqual((r["verdict"], r["winner"]["id"]), ("SETTLED", "B"))

    def test_conflict_lower_rank_outranked_not_drift(self):
        L = ledger(claim("A", "30"), claim("B", "45"), claim("C", "60", kind="chat", start="2026-05-01"))
        r = self.r(L)
        self.assertEqual(r["drift"], [])
        self.assertIn({"id": "C", "reason": "OUTRANKED"}, r["beaten"])

    def test_date_guessed_flag(self):
        r = self.r(ledger(claim("A", "1", start=None, recorded_on="2026-01-05")))
        self.assertIn("DATE_GUESSED", r["flags"])

    def test_pending_lower_rank_ignored(self):
        L = ledger(claim("A", "30"), claim("B", "60", kind="chat", start="2026-09-01"))
        self.assertEqual(self.r(L)["pending"], [])

    def test_pending_same_value_ignored(self):
        L = ledger(claim("A", "30"), claim("B", "30", start="2026-09-01"))
        self.assertEqual(self.r(L)["pending"], [])

    def test_needs_scope(self):
        L = ledger(claim("A", "500", scope="city"), claim("B", "350", scope="town"))
        r = self.r(L)
        self.assertEqual(r["verdict"], "NEEDS_SCOPE")
        self.assertEqual(r["scopes"], ["city", "town"])

    def test_scope_filters(self):
        L = ledger(claim("A", "500", scope="city"), claim("B", "350", scope="town"))
        self.assertEqual(self.r(L, scope="Town")["winner"]["id"], "B")

    def test_star_scope_applies_everywhere(self):
        L = ledger(claim("A", "500", scope="city"), claim("B", "999", start="2026-02-01"))
        self.assertEqual(self.r(L, scope="city")["winner"]["id"], "B")

    def test_unknown_scope_no_source(self):
        L = ledger(claim("A", "500", scope="city"))
        self.assertEqual(self.r(L, scope="moon")["verdict"], "NO_SOURCE")


class TimelineSweepCardTests(unittest.TestCase):
    def setUp(self):
        self.L = ledger(claim("A", "30"),
                        claim("B", "45", kind="amendment", start="2026-03-01", supersedes=["A"]),
                        claim("C", "15", kind="amendment", start="2026-07-01", supersedes=["B"]))

    def test_timeline_steps(self):
        rows = lw.timeline(self.L, "fee", "amount")
        self.assertEqual([(r["as_of"], r["winner"]["value"]) for r in rows],
                         [("2026-01-01", "30"), ("2026-03-01", "45"), ("2026-07-01", "15")])

    def test_timeline_merges_unchanged(self):
        L = ledger(claim("A", "30"), claim("B", "30", kind="email", start="2026-02-01"))
        self.assertEqual(len(lw.timeline(L, "fee", "amount")), 1)

    def test_timeline_shows_expiry(self):
        L = ledger(claim("A", "30", effective_to="2026-05-01"))
        self.assertEqual([r["verdict"] for r in lw.timeline(L, "fee", "amount")], ["SETTLED", "NOTHING_IN_FORCE"])

    def test_sweep_expands_scopes(self):
        L = ledger(claim("A", "500", scope="city"), claim("B", "350", scope="town"))
        rows = lw.sweep(L, D("2026-06-01"))
        self.assertEqual(sorted(r["scope"] for r in rows), ["city", "town"])

    def test_sweep_pairs(self):
        other = claim("X", "2"); other["subject"] = "rent"
        rows = lw.sweep(ledger(claim("A", "1"), other), D("2026-06-01"))
        self.assertEqual(len(rows), 2)

    def test_card_settled(self):
        txt = lw.card(lw.resolve(self.L, "fee", "amount", D("2026-05-01")), "Q?")
        self.assertIn("## Q?", txt)
        self.assertIn("Answer: **45**", txt)
        self.assertIn("Change coming: C sets **15**", txt)
        self.assertIn("A SUPERSEDED by B", txt)

    def test_card_conflict(self):
        txt = lw.card(lw.resolve(ledger(claim("A", "1"), claim("B", "2")), "fee", "amount", D("2026-05-01")))
        self.assertIn("ask the owner", txt)

    def test_card_no_source(self):
        txt = lw.card(lw.resolve(self.L, "fee", "nothing", D("2026-05-01")))
        self.assertIn("Do not answer from memory", txt)

    def test_card_needs_scope(self):
        L = ledger(claim("A", "500", scope="city"), claim("B", "350", scope="town"))
        self.assertIn("Ask which one", lw.card(lw.resolve(L, "fee", "amount", D("2026-05-01"))))


class CliTests(unittest.TestCase):
    def run_cli(self, L, *args):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(L, fh)
            path = fh.name
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = lw.main([args[0], path] + list(args[1:]))
        finally:
            os.unlink(path)
        return code, out.getvalue(), err.getvalue()

    def test_lint_exit_codes(self):
        self.assertEqual(self.run_cli(ledger(claim("A", "1")), "lint")[0], 0)
        self.assertEqual(self.run_cli(ledger(claim("A", "1", kind="memo")), "lint")[0], 1)

    def test_resolve_refuses_broken_ledger(self):
        code, _, err = self.run_cli(ledger(claim("A", "1", kind="memo")), "resolve", "-s", "fee", "-p", "amount")
        self.assertEqual(code, 2)
        self.assertIn("run lint first", err)

    def test_resolve_json(self):
        code, out, _ = self.run_cli(ledger(claim("A", "1")), "resolve", "-s", "fee", "-p", "amount", "--as-of", "2026-02-01", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["winner"]["value"], "1")

    def test_sweep_tally(self):
        code, out, _ = self.run_cli(ledger(claim("A", "1")), "sweep", "--as-of", "2026-02-01")
        self.assertIn("SETTLED 1", out)

    def test_timeline_cli(self):
        code, out, _ = self.run_cli(ledger(claim("A", "1")), "timeline", "-s", "fee", "-p", "amount")
        self.assertIn("2026-01-01", out)

    def test_examples_are_clean(self):
        for name in ("freelance-contract", "travel-policy-zh"):
            L = lw.load(os.path.join(ROOT, "examples", name, "ledger.json"))
            self.assertEqual(codes(lw.lint(L), "ERROR"), [], name)

    def test_example_contract_answer(self):
        L = lw.load(os.path.join(ROOT, "examples", "freelance-contract", "ledger.json"))
        r = lw.resolve(L, "invoice", "payment_days", D("2026-05-15"))
        self.assertEqual((r["winner"]["value"], r["drift"][0]["value"], r["pending"][0]["value"]), ("45", "60", "15"))


if __name__ == "__main__":
    unittest.main()
