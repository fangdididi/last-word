#!/usr/bin/env python3
"""lastword.py - decide which statement has the last word on a question, as of a date.

Standard library only. Works on one JSON ledger file:

{
  "precedence": {"contract": 5, "amendment": 5, "policy": 4, "email": 2, "chat": 1},
  "claims": [
    {"id": "C1", "subject": "invoice", "property": "payment_days", "value": "30",
     "kind": "contract", "source": "contract.pdf p.4 s.7.2", "recorded_on": "2026-01-10",
     "effective_from": "2026-01-15", "quote": "Invoices are payable within 30 days."}
  ]
}

Commands:
  lint     LEDGER                         check the ledger for mistakes
  resolve  LEDGER -s SUBJ -p PROP [--as-of DATE] [--scope S] [--json]
  timeline LEDGER -s SUBJ -p PROP [--scope S]
  sweep    LEDGER [--as-of DATE]          resolve every subject/property pair
  card     LEDGER -s SUBJ -p PROP [--as-of DATE] [--scope S] [--question TEXT]
"""
import argparse
import datetime as _dt
import json
import sys

REQUIRED = ("id", "subject", "property", "value", "kind", "source", "recorded_on")
DATE_FIELDS = ("recorded_on", "effective_from", "effective_to")
QUOTE_WORD_LIMIT = 40


def parse_date(text):
    return _dt.date.fromisoformat(str(text))


def norm(text):
    return " ".join(str(text).strip().lower().split())


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def start_of(claim):
    return parse_date(claim.get("effective_from") or claim["recorded_on"])


def scope_of(claim):
    return norm(claim.get("scope") or "*")


# ---------------------------------------------------------------- lint

def lint(ledger):
    """Return a list of (level, claim_id, code, message)."""
    out = []
    prec = ledger.get("precedence")
    claims = ledger.get("claims")
    if not isinstance(prec, dict) or not prec:
        out.append(("ERROR", "-", "NO_PRECEDENCE", "ledger needs a non-empty precedence map"))
        prec = {}
    else:
        for kind, rank in prec.items():
            if not isinstance(rank, (int, float)) or isinstance(rank, bool):
                out.append(("ERROR", "-", "BAD_RANK", "rank for %r must be a number" % kind))
    if not isinstance(claims, list) or not claims:
        out.append(("ERROR", "-", "NO_CLAIMS", "ledger needs a non-empty claims list"))
        return out

    by_id = {}
    for c in claims:
        cid = str(c.get("id", "?"))
        missing = [f for f in REQUIRED if c.get(f) in (None, "")]
        if missing:
            out.append(("ERROR", cid, "MISSING", "missing " + ", ".join(missing)))
        if cid in by_id:
            out.append(("ERROR", cid, "DUP_ID", "id used more than once"))
        by_id[cid] = c
        if c.get("kind") and prec and c["kind"] not in prec:
            out.append(("ERROR", cid, "UNKNOWN_KIND", "kind %r is not in precedence" % c["kind"]))
        good_dates = True
        for f in DATE_FIELDS:
            if c.get(f):
                try:
                    parse_date(c[f])
                except ValueError:
                    good_dates = False
                    out.append(("ERROR", cid, "BAD_DATE", "%s=%r is not YYYY-MM-DD" % (f, c[f])))
        if good_dates and c.get("effective_to") and c.get("recorded_on"):
            if parse_date(c["effective_to"]) <= start_of(c):
                out.append(("ERROR", cid, "EMPTY_WINDOW", "effective_to is not after the start"))
        if not c.get("effective_from"):
            out.append(("WARN", cid, "DATE_GUESSED", "no effective_from; recorded_on is used as the start"))
        quote = c.get("quote")
        if not quote:
            out.append(("WARN", cid, "NO_QUOTE", "no quote; the answer cannot show the exact words"))
        elif len(str(quote).split()) > QUOTE_WORD_LIMIT:
            out.append(("WARN", cid, "LONG_QUOTE", "quote over %d words; keep only the deciding sentence" % QUOTE_WORD_LIMIT))
        sup = c.get("supersedes") or []
        if not isinstance(sup, list):
            out.append(("ERROR", cid, "BAD_SUPERSEDES", "supersedes must be a list of ids"))

    for c in claims:
        cid = str(c.get("id", "?"))
        sup = c.get("supersedes") or []
        if not isinstance(sup, list):
            continue
        for target in sup:
            t = by_id.get(str(target))
            if str(target) == cid:
                out.append(("ERROR", cid, "SELF_SUPERSEDE", "a claim cannot supersede itself"))
                continue
            if t is None:
                out.append(("ERROR", cid, "UNKNOWN_TARGET", "supersedes unknown id %r" % target))
                continue
            if (norm(t.get("subject", "")), norm(t.get("property", ""))) != (
                    norm(c.get("subject", "")), norm(c.get("property", ""))):
                out.append(("WARN", cid, "CROSS_TOPIC", "supersedes %s, which is about a different subject/property" % target))
            if prec and c.get("kind") in prec and t.get("kind") in prec and prec[c["kind"]] < prec[t["kind"]]:
                out.append(("WARN", cid, "CHECK_POWER", "a %s claims to replace a higher-ranked %s; confirm it had the power" % (c["kind"], t["kind"])))

    # cycles
    graph = {str(c.get("id")): [str(x) for x in (c.get("supersedes") or []) if isinstance(c.get("supersedes"), list)] for c in claims}
    state = {}

    def visit(node, path):
        state[node] = 1
        for nxt in graph.get(node, []):
            if nxt not in graph:
                continue
            if state.get(nxt) == 1:
                out.append(("ERROR", node, "CYCLE", "supersede loop: " + " -> ".join(path + [nxt])))
            elif state.get(nxt) is None:
                visit(nxt, path + [nxt])
        state[node] = 2

    for node in graph:
        if state.get(node) is None:
            visit(node, [node])
    return out


# ---------------------------------------------------------------- resolve

def resolve(ledger, subject, prop, as_of, scope=None):
    prec = ledger["precedence"]
    claims = [c for c in ledger["claims"]
              if norm(c["subject"]) == norm(subject) and norm(c["property"]) == norm(prop)]
    result = {"subject": subject, "property": prop, "as_of": as_of.isoformat(),
              "scope": scope or "*", "verdict": None, "winner": None, "flags": [],
              "beaten": [], "drift": [], "pending": [], "conflict": []}
    if not claims:
        result["verdict"] = "NO_SOURCE"
        return result
    if scope:
        claims = [c for c in claims if scope_of(c) in ("*", norm(scope))]
        if not claims:
            result["verdict"] = "NO_SOURCE"
            return result
    else:
        scopes = sorted({scope_of(c) for c in claims} - {"*"})
        if len(scopes) > 1:
            result["verdict"] = "NEEDS_SCOPE"
            result["scopes"] = scopes
            return result

    live, pending = [], []
    for c in claims:
        if start_of(c) > as_of:
            pending.append(c)
        elif c.get("effective_to") and as_of >= parse_date(c["effective_to"]):
            result["beaten"].append({"id": c["id"], "reason": "EXPIRED"})
        else:
            live.append(c)

    superseded_by = {}
    for c in ledger["claims"]:
        if start_of(c) <= as_of:
            for t in c.get("supersedes") or []:
                superseded_by.setdefault(str(t), c["id"])
    remaining = []
    for c in live:
        if str(c["id"]) in superseded_by:
            result["beaten"].append({"id": c["id"], "reason": "SUPERSEDED", "by": superseded_by[str(c["id"])]})
        else:
            remaining.append(c)

    if not remaining:
        result["verdict"] = "NOT_YET" if pending else "NOTHING_IN_FORCE"
        result["pending"] = [_brief(c, prec) for c in sorted(pending, key=start_of)]
        return result

    top = max(prec[c["kind"]] for c in remaining)
    topset = [c for c in remaining if prec[c["kind"]] == top]
    latest_start = max(start_of(c) for c in topset)
    latest = [c for c in topset if start_of(c) == latest_start]
    values = {norm(c["value"]) for c in latest}
    if len(values) > 1:
        result["verdict"] = "CONFLICT"
        result["conflict"] = [_brief(c, prec) for c in sorted(latest, key=lambda x: str(x["id"]))]
        win_value = None
        winner = None
    else:
        winner = sorted(latest, key=lambda x: (x["recorded_on"], str(x["id"])))[-1]
        win_value = norm(winner["value"])
        result["verdict"] = "SETTLED"
        result["winner"] = _brief(winner, prec)
        if not winner.get("effective_from"):
            result["flags"].append("DATE_GUESSED")

    for c in remaining:
        if winner is not None and c is winner:
            continue
        if c in latest and result["verdict"] == "CONFLICT":
            continue
        same = win_value is not None and norm(c["value"]) == win_value
        if prec[c["kind"]] < top and win_value is None:
            result["beaten"].append({"id": c["id"], "reason": "OUTRANKED"})
        elif prec[c["kind"]] < top:
            if same:
                result["beaten"].append({"id": c["id"], "reason": "AGREES"})
            elif start_of(c) >= latest_start:
                result["drift"].append(_brief(c, prec))
            else:
                result["beaten"].append({"id": c["id"], "reason": "OUTRANKED"})
        else:
            result["beaten"].append({"id": c["id"], "reason": "AGREES" if same else "OLDER"})

    for c in sorted(pending, key=start_of):
        if prec[c["kind"]] >= top and (win_value is None or norm(c["value"]) != win_value):
            result["pending"].append(_brief(c, prec))
    if result["drift"]:
        result["flags"].append("DRIFT")
    if result["pending"]:
        result["flags"].append("CHANGE_COMING")
    result["beaten"].sort(key=lambda b: str(b["id"]))
    return result


def _brief(c, prec):
    return {"id": c["id"], "value": c["value"], "kind": c["kind"], "rank": prec[c["kind"]],
            "start": start_of(c).isoformat(), "source": c["source"], "quote": c.get("quote", "")}


def change_points(ledger, subject, prop, scope=None):
    dates = set()
    for c in ledger["claims"]:
        if norm(c["subject"]) == norm(subject) and norm(c["property"]) == norm(prop):
            if scope and scope_of(c) not in ("*", norm(scope)):
                continue
            dates.add(start_of(c))
            if c.get("effective_to"):
                dates.add(parse_date(c["effective_to"]))
    return sorted(dates)


def timeline(ledger, subject, prop, scope=None):
    rows, last = [], None
    for d in change_points(ledger, subject, prop, scope):
        r = resolve(ledger, subject, prop, d, scope)
        key = (r["verdict"], r["winner"]["value"] if r["winner"] else None)
        if key != last:
            rows.append(r)
            last = key
    return rows


def sweep(ledger, as_of):
    pairs = sorted({(norm(c["subject"]), norm(c["property"])) for c in ledger["claims"]})
    out = []
    for s, p in pairs:
        r = resolve(ledger, s, p, as_of)
        if r["verdict"] == "NEEDS_SCOPE":
            for sc in r["scopes"]:
                out.append(resolve(ledger, s, p, as_of, sc))
        else:
            out.append(r)
    return out


# ---------------------------------------------------------------- output

def text_line(r):
    who = r["winner"]["value"] if r["winner"] else "-"
    flags = ",".join(r["flags"]) or "-"
    return "%-18s %-24s %-10s %-16s %-24s %s" % (r["subject"], r["property"], r["scope"], r["verdict"], who, flags)


def card(r, question=None):
    lines = ["## " + (question or "%s / %s" % (r["subject"], r["property"])), ""]
    lines.append("- As of: %s%s" % (r["as_of"], "" if r["scope"] == "*" else "  (scope: %s)" % r["scope"]))
    lines.append("- Verdict: **%s**" % r["verdict"])
    w = r["winner"]
    if w:
        lines.append("- Answer: **%s**" % w["value"])
        lines.append("- Last word: %s (%s, rank %s, in force from %s)" % (w["source"], w["kind"], w["rank"], w["start"]))
        if w["quote"]:
            lines.append('  > "%s"' % w["quote"])
    if r["verdict"] == "CONFLICT":
        lines.append("- Equal-rank sources disagree; ask the owner which one holds:")
        for c in r["conflict"]:
            lines.append("  - %s says **%s** (%s)" % (c["id"], c["value"], c["source"]))
    if r["verdict"] == "NO_SOURCE":
        lines.append("- No document in the ledger speaks to this. Do not answer from memory.")
    if r["verdict"] == "NEEDS_SCOPE":
        lines.append("- Different answers exist per scope: %s. Ask which one." % ", ".join(r["scopes"]))
    if r["verdict"] in ("NOT_YET", "NOTHING_IN_FORCE"):
        lines.append("- Nothing is in force on that date.")
    for d in r["drift"]:
        lines.append("- Said but not binding: %s says **%s** (%s, rank %s)" % (d["id"], d["value"], d["source"], d["rank"]))
    for p in r["pending"]:
        lines.append("- Change coming: %s sets **%s** from %s (%s)" % (p["id"], p["value"], p["start"], p["source"]))
    if r["beaten"]:
        lines.append("- Set aside: " + "; ".join(
            "%s %s%s" % (b["id"], b["reason"], (" by " + str(b["by"])) if b.get("by") else "") for b in r["beaten"]))
    if "DATE_GUESSED" in r["flags"]:
        lines.append("- Note: the winning source has no stated start date; its document date was used.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find the statement that has the last word, as of a date.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_l = sub.add_parser("lint")
    p_l.add_argument("ledger")
    for name in ("resolve", "timeline", "card"):
        p = sub.add_parser(name)
        p.add_argument("ledger")
        p.add_argument("-s", "--subject", required=True)
        p.add_argument("-p", "--property", required=True)
        p.add_argument("--scope")
        if name != "timeline":
            p.add_argument("--as-of")
        if name == "resolve":
            p.add_argument("--json", action="store_true")
        if name == "card":
            p.add_argument("--question")
    p_s = sub.add_parser("sweep")
    p_s.add_argument("ledger")
    p_s.add_argument("--as-of")
    a = ap.parse_args(argv)

    ledger = load(a.ledger)
    if a.cmd == "lint":
        issues = lint(ledger)
        for lvl, cid, code, msg in issues:
            print("%-5s %-8s %-15s %s" % (lvl, cid, code, msg))
        errors = sum(1 for i in issues if i[0] == "ERROR")
        print("%d error(s), %d warning(s)" % (errors, len(issues) - errors))
        return 1 if errors else 0
    errors = [i for i in lint(ledger) if i[0] == "ERROR"]
    if errors:
        print("ledger has %d error(s); run lint first" % len(errors), file=sys.stderr)
        return 2
    as_of = parse_date(a.as_of) if getattr(a, "as_of", None) else _dt.date.today()
    if a.cmd == "resolve":
        r = resolve(ledger, a.subject, a.property, as_of, a.scope)
        print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else text_line(r))
        return 0
    if a.cmd == "card":
        print(card(resolve(ledger, a.subject, a.property, as_of, a.scope), a.question), end="")
        return 0
    if a.cmd == "timeline":
        for r in timeline(ledger, a.subject, a.property, a.scope):
            who = r["winner"]["value"] if r["winner"] else "-"
            src = r["winner"]["id"] if r["winner"] else ",".join(c["id"] for c in r["conflict"]) or "-"
            print("%s  %-16s %-24s %s" % (r["as_of"], r["verdict"], who, src))
        return 0
    if a.cmd == "sweep":
        rows = sweep(ledger, as_of)
        for r in rows:
            print(text_line(r))
        tally = {}
        for r in rows:
            tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
        print("as of %s: " % as_of.isoformat() + ", ".join("%s %d" % kv for kv in sorted(tally.items())))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
