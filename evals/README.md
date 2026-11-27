# Scorer evaluation

Does a scorer agree with a human coach? This folder answers that with a small labeled set.

## How it works
- `dataset/` has 16 fictional discovery-call transcripts.
- `labels.json` has a human label per transcript per rubric dimension: `0` the behavior is absent, `50` partial, `100` clear and stated by the buyer.
- `run_eval.py` runs a scorer over every transcript and compares its scores to the labels.

```bash
python3 -m evals.run_eval --scorer rules
ANTHROPIC_API_KEY=... python3 -m evals.run_eval --scorer both
```
Results are written to `evals/results/<scorer>.json` with every prediction, so you can read the disagreements. A call where the scorer errors is counted as a failure and shown. It is not dropped.

## What the set is built to test
| Case type | Examples | Why |
|---|---|---|
| Clean strong and clean weak | `01`, `02`, `16` | Both scorers should get these. If not, something is broken. |
| Keywords present, meaning absent | `04` (negated), `06` (vague next step), `07` (numbers that aren't metrics), `13` (seller says the pain, buyer never does) | Where counting words fails. |
| Meaning present, keywords absent | `05`, `08`, `09`, `11`, `15` | Where paraphrase defeats a word list. |
| Partial credit | `10`, `12`, `14` | Tests whether a scorer can say "half". |

## Reading the results
- **Agreement:** the share of dimension scores within 25 points of the label.
- **False positive:** scored 75 or higher where the label is 0. In a coaching tool this is the costly one: a rep is told they did something they didn't.
- **Miss:** scored 25 or lower where the label is 75 or higher.
- **Tokens and time** are recorded for the LLM scorer, so you can price a call and judge latency. Multiply tokens by your model's current rate.

## Limits
- One labeler, who is also the author. A real calibration set has at least two human raters and reports their agreement with each other first. A scorer cannot meaningfully beat that ceiling.
- 16 calls is enough to find failure modes and not enough to estimate accuracy.
- About half the set is adversarial on purpose. Do not read the baseline numbers as typical performance.
- The prompt is not tuned. A better prompt, or few-shot examples, should move the LLM numbers, and the harness lets you measure that.
