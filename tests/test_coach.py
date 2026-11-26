import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

from coach import server
from coach.scorer import LLMScorer, RuleScorer, build_prompt, call_metrics, load_rubric

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sample(name):
    with open(os.path.join(ROOT, "samples", name), encoding="utf-8") as f:
        return f.read()


class RuleScorerTests(unittest.TestCase):
    def setUp(self):
        self.rubric = load_rubric()
        self.scorer = RuleScorer()

    def test_strong_call_outscores_weak_call(self):
        strong = self.scorer.score(sample("transcript_strong.txt"), self.rubric)
        weak = self.scorer.score(sample("transcript_weak.txt"), self.rubric)
        self.assertGreater(strong["overall"], weak["overall"] + 40)

    def test_weak_call_has_zero_next_step_and_is_flagged(self):
        weak = self.scorer.score(sample("transcript_weak.txt"), self.rubric)
        scores = {d["id"]: d["score"] for d in weak["dimensions"]}
        self.assertEqual(scores["next_step"], 0)
        self.assertIn(weak["top_gap"]["id"], scores)
        self.assertEqual(weak["top_gap"]["id"], min(scores, key=scores.get))

    def test_perfect_call_has_no_top_gap(self):
        strong = self.scorer.score(sample("transcript_strong.txt"), self.rubric)
        self.assertEqual(strong["overall"], 100)
        self.assertIsNone(strong["top_gap"])

    def test_mixed_call_lands_between_and_flags_a_real_gap(self):
        mixed = self.scorer.score(sample("transcript_mixed.txt"), self.rubric)
        self.assertTrue(30 <= mixed["overall"] <= 70)
        scores = {d["id"]: d["score"] for d in mixed["dimensions"]}
        self.assertEqual(scores["economic_buyer"], 0)
        self.assertEqual(scores["next_step"], 0)
        # Tie at 0 with equal weights: rubric order decides, deterministically.
        self.assertEqual(mixed["top_gap"]["id"], "economic_buyer")

    def test_metrics(self):
        m = call_metrics(sample("transcript_weak.txt"))
        self.assertGreater(m["seller_talk_ratio"], 0.8)
        self.assertEqual(m["seller_questions"], 0)
        strong = call_metrics(sample("transcript_strong.txt"))
        self.assertGreaterEqual(strong["seller_questions"], 5)

    def test_rubric_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(d["weight"] for d in self.rubric["dimensions"]), 1.0)


class LLMScorerTests(unittest.TestCase):
    def test_prompt_contains_every_dimension(self):
        rubric = load_rubric()
        prompt = build_prompt("Seller: hi", rubric)
        for d in rubric["dimensions"]:
            self.assertIn(d["id"], prompt)

    def test_parses_and_clamps_model_output(self):
        rubric = load_rubric()
        items = [{"id": d["id"], "score": 150, "evidence": ["x"]} for d in rubric["dimensions"]]
        fake = lambda payload: {"content": [{"text": "Here: " + json.dumps({"dimensions": items})}]}
        result = LLMScorer(api_key="k", post=fake).score("Seller: hi", rubric)
        self.assertTrue(all(d["score"] == 100 for d in result["dimensions"]))

    def test_rejects_missing_dimensions(self):
        rubric = load_rubric()
        fake = lambda payload: {"content": [{"text": json.dumps({"dimensions": []})}]}
        with self.assertRaises(ValueError):
            LLMScorer(api_key="k", post=fake).score("Seller: hi", rubric)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.Handler.scorer = RuleScorer()
        server.Handler.rubric = load_rubric()
        server.Handler.secret = "s3cret"
        cls.httpd = HTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def post(self, body, signature):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/webhook", data=body,
            headers={"X-Signature": signature} if signature else {})
        return urllib.request.urlopen(req)

    def test_rejects_missing_or_bad_signature(self):
        body = json.dumps({"transcript": "Seller: hi"}).encode()
        for sig in (None, "sha256=deadbeef"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(body, sig)
            self.assertEqual(ctx.exception.code, 401)

    def test_accepts_valid_signature(self):
        body = json.dumps({"call_id": "c1", "transcript": sample("transcript_strong.txt")}).encode()
        with self.post(body, server.sign("s3cret", body)) as resp:
            data = json.load(resp)
        self.assertEqual(data["call_id"], "c1")
        self.assertGreater(data["overall"], 70)

    def test_bad_payload_is_400(self):
        body = b'{"nope": 1}'
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post(body, server.sign("s3cret", body))
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
