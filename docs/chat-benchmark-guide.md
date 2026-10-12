# Chat benchmark — how to run it (owner, on the laptop)

Owner order 2026-09-26, chat redesign PR 7: 30 questions, answered by this
system, ChatGPT and Claude.ai, scored side by side.

**Everything with client content stays in `.cowork/`, which git ignores.**
The questions (they name your documents) and the answers (they quote them)
never enter the repository, an issue, a PR or CI. This guide holds only the
KINDS of question to ask, never a question.

## 1. Write the 30 questions

Create `.cowork/chat-benchmark-questions.txt`, one question per line,
optionally `category | question`. Lines starting with `#` are skipped.
Suggested mix (six kinds, five each):

| Kind | What it tests | Example of the SHAPE (write your own) |
|---|---|---|
| Datasheet value | a figure is found and cited on its page | "What is the design pressure of <equipment>?" |
| Submittal vs standard | a comparison, with the engineer notice | "Does <datasheet> meet <standard>'s hydrotest requirement?" |
| Not in the documents | honesty: says so, does not invent | a question the documents do not answer |
| Standard explained | plain-language summary of a clause | "Summarise <standard> clause <n> in plain English" |
| General engineering | general knowledge, labelled as such | "What is the difference between barg and bara?" |
| Follow-up / rewrite | memory and "in points" / "shorter" | a first question, then "give me that in points" |

Put at least three questions whose honest answer is "the documents don't
say" — the benchmark must reward saying so.

## 2. Run this system's side

With the backend running (`python run.py`) and Claude set up as you want it:

```
python scripts/chat_benchmark.py --email <your login>        # password is asked for
python scripts/chat_benchmark.py --no-auth                   # if AUTH_MODE=disabled
```

It writes `.cowork/CHAT-BENCHMARK-2026-09.md`: a summary table (answer kind,
points found on the page, sources, seconds, Claude cost) and, per question,
this system's answer. It refuses to write anywhere but `.cowork/`, refuses if
git would track the report, and prints only the question number and
category while it runs. Claude spend is capped by `claude_spend` as always.

## 3. Add ChatGPT and Claude.ai

For each question, paste the same question into ChatGPT and Claude.ai (with
the same document attached where the question needs it, if you choose to —
that is your decision, outside this system), and paste their answers under
"ChatGPT (paste here)" and "Claude.ai (paste here)".

## 4. Score

Score all three with the rubric at the top of the report (Correct 0-2,
Grounded 0-2, Cites the page 0-1, Honest about limits 0-1, Clear 0-1; out
of 7). The script never fills a score in: correctness is an engineer's
judgement against the documents.
