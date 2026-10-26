---
name: last-word
description: Answer a question from a pile of documents that revise each other (contract plus amendments, policy versions, spec plus decision notes, emails and chat) by finding which statement has the last word on the date asked. Builds a small claim ledger with a precedence ladder, resolves each question as of a date, and returns the answer with its deciding quote, the statements it overrode, non-binding drift, coming changes, or a plain CONFLICT for the owner to settle. Use when the user asks "what applies now / on date X", "which version is right", "did that email change the deal", or when sources in a folder disagree.
---

# Last Word

## What this is

Most document piles are not a set of facts. They are a conversation that went on for months: a contract, then an amendment, then an email that says something else, then a chat message, then a new version of the policy that only starts next quarter. Search finds all of them. The hard part is deciding which one actually governs on the date that matters.

Agents usually get this wrong in one of three ways. They quote the newest thing they found, even if it is a chat message with no power to change a signed agreement. They quote the most "official" looking file, even though a later amendment replaced the clause. Or they quietly average the two and give a confident answer that no document says.

This skill makes the decision explicit. Every relevant statement becomes one row in a ledger, each document kind gets a rank on a precedence ladder the user agrees to, and a fixed rule picks the winner for a given date. The answer always shows the exact deciding sentence and everything it beat. When two equal-ranked sources disagree on the same day, the skill does not pick one. It says CONFLICT and asks the owner.

## When to use it

- "What are our payment terms right now?" when there is a contract, two amendments and an email from accounts.
- "How much can I claim for a hotel in Shanghai in October?" when the policy has versions, notices and a team chat that says otherwise.
- "Did that call change what we agreed?" or "Which spec version is the real one?"
- Any time a search returns two or more sources with different values for the same thing.
- Reviewing a folder before a deadline: sweep every topic and list what is settled, what is in conflict, and what changes soon.

Do not use it for questions whose answer is a judgment rather than a stated value, or when there is only one source.

## The ledger in one minute

One JSON file holds two things:

- `precedence`: a map from document kind to a number. Higher numbers win. Example: law 9, signed agreement 5, amendment 5, official policy 4, team guideline 3, email 2, chat or call notes 1. Agree this ladder with the user before resolving anything; it is the most important decision in the whole process.
- `claims`: one row per statement. Fields:
  - `id`, `subject`, `property`, `value`: what is said about what. Keep `subject` and `property` short and reuse them exactly so rows line up.
  - `kind`: must exist in `precedence`.
  - `source`: file plus page, section or line, so a person can open it.
  - `recorded_on`: the document date.
  - `effective_from` / `effective_to` (optional): when it applies. `effective_to` is the first day it no longer applies.
  - `scope` (optional, default `*`): a region, product, team or grade when the answer differs by it.
  - `supersedes` (optional): ids this statement explicitly replaces ("Section 6.1 is replaced by...").
  - `quote`: the one deciding sentence, verbatim, under 40 words.

## How the winner is chosen

For a subject, property, date and optional scope:

1. Keep only rows for that subject and property (and scope, where `*` applies everywhere). If different scopes give different answers and none was asked, stop with NEEDS_SCOPE.
2. A row whose start (`effective_from`, else `recorded_on`) is after the date is pending. A row past its `effective_to` is expired.
3. A row named in `supersedes` by any row that has started is out, whatever its rank. Explicit replacement beats rank because the replacing text says so; the linter warns if a lower kind claims to replace a higher one so you can check it had the power.
4. Among what is left, the highest rank wins. Inside that rank, the latest start wins.
5. If the latest top-rank rows have different values, the verdict is CONFLICT. Show both, ask the owner, and do not guess.
6. Lower-rank rows that started on or after the winner and say something different are **drift**: said, but not binding. Show them, because people act on them.
7. Pending rows at the winner's rank or higher with a different value are a **change coming**.

Verdicts: SETTLED, CONFLICT, NEEDS_SCOPE, NO_SOURCE (nothing in the ledger speaks to it; never fill the gap from memory), NOT_YET (only future rows), NOTHING_IN_FORCE (everything expired or replaced). Flags on a settled answer: DRIFT, CHANGE_COMING, DATE_GUESSED.

## Steps

1. **Pin the question.** Write it as subject, property, date and scope. "Payment terms" becomes `invoice / payment_days / 2026-05-15`. If the user gave no date, use today and say so.
2. **Agree the ladder.** Propose a precedence map for the kinds of documents present. Ask about anything unusual (a board resolution, a regulator letter, a signed side letter). Record any written precedence clause the documents contain ("in case of conflict, the agreement prevails over the SOW") and follow it.
3. **Harvest claims.** Search the whole pile, not just the first hit. For each statement about the pinned topic, add a row with source and verbatim quote. Include the informal ones (emails, chats, call notes); they become drift, which is often the most useful finding. Write down `supersedes` only when the text actually says it replaces something.
4. **Lint.** Run `python3 scripts/lastword.py lint ledger.json`. Fix every ERROR. Read every WARN: DATE_GUESSED means you used the document date as the start, CHECK_POWER means a lower document claims to replace a higher one.
5. **Resolve.** Run `card` for the question, or `sweep` for every topic at once, and `timeline` when the user wants to know what applied when.
6. **Answer.** Lead with the value and the date. Quote the deciding sentence and name its source. Then, in this order: drift ("an email on 2 April said 60 days; it does not change the agreement"), change coming, and what was set aside. For CONFLICT, show both sides and ask one direct question.
7. **Keep the ledger.** Save it next to the documents. When a new document arrives, add rows and resolve again rather than starting over.

## Helper script

`scripts/lastword.py` uses only the Python standard library.

```bash
python3 scripts/lastword.py lint ledger.json
python3 scripts/lastword.py card ledger.json -s invoice -p payment_days --as-of 2026-05-15 --question "What are our payment terms?"
python3 scripts/lastword.py resolve ledger.json -s invoice -p payment_days --as-of 2026-05-15 --json
python3 scripts/lastword.py timeline ledger.json -s invoice -p payment_days
python3 scripts/lastword.py sweep ledger.json --as-of 2026-05-15
```

`resolve`, `card`, `timeline` and `sweep` refuse to run on a ledger with lint errors. Tests: `python3 -m unittest discover -s tests`.

## Example

A freelancer asks: "What are our payment terms on 15 May 2026?" The folder has the master agreement (30 days from 12 January), amendment 1 (45 days from 1 March, replacing section 6.1), an email from the client's accounts team on 2 April ("our system pays all vendors at 60 days now") and amendment 2 (15 days from 1 July).

The card says:

- Verdict SETTLED, answer **45**, last word amendment-1.pdf s.2, with its sentence quoted.
- Said but not binding: the 2 April email says 60.
- Change coming: amendment 2 sets 15 from 1 July.
- Set aside: the original 30 days, replaced by amendment 1.

So the reply is: "45 days, under amendment 1 from 1 March. The accounts email about 60 days does not change the contract, so you can push back on late payment. From 1 July it becomes 15 days."

The same folder has two versions of the statement of work, dated the same day, one saying two revision rounds and one saying three. That is a CONFLICT: the skill shows both files and asks which one was signed, instead of picking the newer-looking file name.

Full ledgers and outputs: `examples/freelance-contract/` (English) and `examples/travel-policy-zh/` (Chinese travel policy with scopes).

## Tips

- One property per row. "Payment within 45 days, 2% late fee" is two rows.
- Store values exactly as written ("45", "600元"). Compare meaning yourself before deciding two values truly differ; the script compares text after trimming and lowercasing.
- File names lie. "final-v2" is not a rank and not a date; read the document date and signature block.
- A signed document that nobody announced still governs; a loud announcement with no authority is still drift. Say both plainly.
- When the user owns the decision (CONFLICT), offer to add their answer as a new row with a higher rank or a `supersedes`, so the ledger remembers the ruling.
- This is a reading aid, not legal advice. For anything with real legal or financial weight, suggest the user confirms with the person responsible.
