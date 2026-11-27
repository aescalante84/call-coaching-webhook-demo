import json
import os
import unittest

from coach.scorer import LLMScorer, RuleScorer, load_rubric
from evals import run_eval

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def labeled_reply(cases_by_prompt):
    """A fake model that answers with the human labels. Tests the harness, not a real model."""
    def post(payload):
        prompt = payload["messages"][0]["content"]
        labels = next(c["labels"] for t, c in cases_by_prompt.items() if t in prompt)
        items = [{"id": k, "score": v, "evidence": []} for k, v in labels.items()]
        return {"content": [{"type": "text", "text": json.dumps({"dimensions": items})}],
                "usage": {"input_tokens": 100, "output_tokens": 20}}
    return post


class EvalHarnessTests(unittest.TestCase):
    def setUp(self):
        self.rubric = load_rubric()
        self.cases = run_eval.load_cases()
        self.dims = [d["id"] for d in self.rubric["dimensions"]]

    def test_every_transcript_has_valid_labels(self):
        files = {f[:-4] for f in os.listdir(os.path.join(ROOT, "evals", "dataset")) if f.endswith(".txt")}
        self.assertEqual(files, {c["name"] for c in self.cases})
        for c in self.cases:
            self.assertEqual(set(c["labels"]), set(self.dims))
            self.assertTrue(all(v in (0, 50, 100) for v in c["labels"].values()))

    def test_perfect_scorer_has_zero_error(self):
        by_prompt = {c["transcript"]: c for c in self.cases}
        scorer = LLMScorer(api_key="x", post=labeled_reply(by_prompt))
        summary = run_eval.summarize(run_eval.run(scorer, self.rubric, self.cases), self.dims)
        self.assertEqual(summary["mae"], 0)
        self.assertEqual(summary["agree_pct"], 100)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["input_tokens"], 100 * len(self.cases))

    def test_scorer_errors_are_counted_not_dropped(self):
        def broken(payload):
            return {"content": [{"type": "text", "text": "not json"}]}
        scorer = LLMScorer(api_key="x", post=broken)
        results = run_eval.run(scorer, self.rubric, self.cases)
        summary = run_eval.summarize(results, self.dims)
        self.assertEqual(summary["failed"], len(self.cases))
        self.assertTrue(all("error" in r for r in results))

    def test_rules_baseline_has_known_failure_modes(self):
        results = run_eval.run(RuleScorer(), self.rubric, self.cases)
        by = {r["name"]: r["predicted"] for r in results}
        self.assertEqual(by["04_negated_pain_and_budget"]["pain_and_impact"], 100)  # keyword fooled by negation
        self.assertEqual(by["05_next_step_without_keywords"]["next_step"], 0)        # misses paraphrase

    def test_metrics_math(self):
        results = [{"name": "a", "labels": {"x": 0}, "predicted": {"x": 100}, "seconds": 0, "input_tokens": 0, "output_tokens": 0},
                   {"name": "b", "labels": {"x": 100}, "predicted": {"x": 0}, "seconds": 0, "input_tokens": 0, "output_tokens": 0}]
        s = run_eval.summarize(results, ["x"])
        self.assertEqual((s["mae"], s["agree_pct"], s["false_positives"], s["misses"]), (100, 0, 1, 1))


if __name__ == "__main__":
    unittest.main()
