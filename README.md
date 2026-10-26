# Last Word

English | [中文](README.zh-CN.md)

**When your documents disagree, find the one that actually governs on the date that matters.**

Last Word is an agent skill for answering questions from a pile of documents that revise each other: a contract and its amendments, several versions of a policy, a spec plus decision notes, and the emails and chat messages around them. Instead of quoting whatever search returned first, the agent builds a small claim ledger, ranks document kinds on a precedence ladder you agree to, and resolves each question as of a specific date. The answer comes with the exact deciding sentence, what it overrode, what people said that is not binding, and what changes soon. When two equal sources disagree, it says so and asks you, rather than guessing.

It works with Claude Code, Codex, Cursor and any agent that can read a `SKILL.md` file. A standard-library Python helper does the deterministic part.

## Why

Search finds every version of the truth. The usual failures come after that:

- quoting the newest message even though a chat has no power to change a signed agreement;
- quoting the most official-looking file even though a later amendment replaced the clause;
- blending two sources into a confident answer no document actually says.

Last Word makes the rule visible and repeatable, so you can check the reasoning in ten seconds.

## Features

- **Precedence ladder**: you decide how much each kind of document counts (law, agreement, amendment, policy, guideline, email, chat). The ladder is part of the ledger, so the ruling is reproducible.
- **Dated answers**: every question is resolved as of a date, with `effective_from`, `effective_to`, and pending changes handled.
- **Explicit replacement**: a statement that says it replaces another removes it, and the linter warns when a lower document claims to replace a higher one.
- **Drift detection**: later, lower-ranked statements that disagree with the winner are shown as "said but not binding", because people act on them.
- **Honest conflicts**: same rank, same day, different values gives CONFLICT with both sources, never a coin flip.
- **Scopes**: answers that differ by region, product or grade are kept apart; an unscoped question that needs one returns NEEDS_SCOPE.
- **No answer from memory**: if nothing in the ledger covers the question, the verdict is NO_SOURCE.
- **Timeline and sweep**: see what applied when, or review every topic in a folder at once.
- **Helper script** `scripts/lastword.py` with `lint`, `resolve`, `card`, `timeline` and `sweep`, covered by 58 tests.

## Verdicts

| Verdict | Meaning |
|---|---|
| SETTLED | One value governs on that date (flags: DRIFT, CHANGE_COMING, DATE_GUESSED) |
| CONFLICT | Equal-rank sources disagree on the same start date; the owner decides |
| NEEDS_SCOPE | The answer differs by scope and none was given |
| NO_SOURCE | Nothing in the ledger speaks to the question |
| NOT_YET | Only statements that start after the date |
| NOTHING_IN_FORCE | Everything relevant has expired or been replaced |

## Installation

Copy the folder into your agent's skills directory.

```bash
git clone https://github.com/fangdididi/last-word
# Claude Code
cp -R last-word ~/.claude/skills/last-word
# Codex
cp -R last-word ~/.codex/skills/last-word
# Cursor (project skill)
mkdir -p .cursor/skills && cp -R last-word .cursor/skills/last-word
```

Other agents: point them at `SKILL.md` (or `SKILL.zh-CN.md`) and keep the `scripts/` folder next to it. Python 3.9 or newer is enough; there are no dependencies.

## Usage

Ask your agent something like:

> "Here is the client folder. What are our payment terms as of today? Use last word."

> "Sweep this policy folder as of 1 October and tell me what is settled, what conflicts, and what changes soon."

The agent pins the question, proposes a precedence ladder for you to confirm, harvests every relevant statement into `ledger.json`, lints it, and resolves.

You can also run the helper yourself:

```bash
python3 scripts/lastword.py lint examples/freelance-contract/ledger.json
python3 scripts/lastword.py card examples/freelance-contract/ledger.json \
  -s invoice -p payment_days --as-of 2026-05-15 --question "What are our payment terms?"
python3 scripts/lastword.py timeline examples/freelance-contract/ledger.json -s invoice -p payment_days
python3 scripts/lastword.py sweep examples/travel-policy-zh/ledger.json --as-of 2025-10-01
```

## Example

```text
## What are our payment terms on 15 May 2026?

- As of: 2026-05-15
- Verdict: **SETTLED**
- Answer: **45**
- Last word: amendment-1.pdf s.2 (amendment, rank 5, in force from 2026-03-01)
  > "Section 6.1 is replaced: invoices are due forty-five (45) days after receipt."
- Said but not binding: C3 says **60** (mail 2026-04-02 from accounts@client, subject 'payment run', rank 2)
- Change coming: C4 sets **15** from 2026-07-01 (amendment-2.pdf s.1)
- Set aside: C1 SUPERSEDED by C2
```

The agent's reply: "45 days, under amendment 1 from 1 March. The accounts email about 60 days does not change the contract. From 1 July it becomes 15 days."

More in [`examples/freelance-contract/answers.md`](examples/freelance-contract/answers.md) and [`examples/travel-policy-zh/answers.md`](examples/travel-policy-zh/answers.md).

## File structure

```text
last-word/
├── SKILL.md                      # skill instructions (English)
├── SKILL.zh-CN.md                # skill instructions (Chinese)
├── README.md
├── README.zh-CN.md
├── LICENSE
├── scripts/
│   └── lastword.py               # lint / resolve / card / timeline / sweep
├── templates/
│   └── ledger.template.json      # empty ledger with a suggested ladder
├── examples/
│   ├── freelance-contract/       # contract, amendments, email drift, SOW conflict
│   └── travel-policy-zh/         # 差旅制度：版本、通知、群消息、适用范围
└── tests/
    └── test_lastword.py          # 58 tests
```

Run the tests with `python3 -m unittest discover -s tests`.

## Limits

Last Word is a reading aid, not legal advice. It compares values as trimmed, lowercased text, so the agent still has to read meaning (for example "thirty days" versus "30"). The ruling is only as good as the ladder and the rows: confirm both with the person responsible for anything with real legal or financial weight.

## License

MIT, see [LICENSE](LICENSE).
