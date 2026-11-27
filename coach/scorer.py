"""Scorers for the call-coaching demo.

Two interchangeable scorers return the same result shape:

- RuleScorer: offline and deterministic. Keyword evidence per rubric dimension.
  Good for tests, demos with no network, and as a sanity baseline.
- LLMScorer: asks a model to score against the same rubric and returns the
  same shape. Optional; needs ANTHROPIC_API_KEY.

Transcript format: one utterance per line, prefixed "Seller:" or "Buyer:".
"""
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RUBRIC = os.path.join(HERE, "rubric.json")


def load_rubric(path=DEFAULT_RUBRIC):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def split_speakers(transcript):
    """Return (seller_lines, buyer_lines) as lists of strings."""
    seller, buyer = [], []
    for line in transcript.splitlines():
        line = line.strip()
        if line.lower().startswith("seller:"):
            seller.append(line.split(":", 1)[1].strip())
        elif line.lower().startswith("buyer:"):
            buyer.append(line.split(":", 1)[1].strip())
    return seller, buyer


def call_metrics(transcript):
    seller, buyer = split_speakers(transcript)
    seller_words = sum(len(s.split()) for s in seller)
    buyer_words = sum(len(b.split()) for b in buyer)
    total = seller_words + buyer_words
    return {
        "seller_talk_ratio": round(seller_words / total, 2) if total else 0.0,
        "seller_questions": sum(s.count("?") for s in seller),
        "utterances": len(seller) + len(buyer),
    }


def _shape(rubric, dimension_results, metrics):
    weights = {d["id"]: d["weight"] for d in rubric["dimensions"]}
    overall = sum(r["score"] * weights[r["id"]] for r in dimension_results)
    # Top gap: lowest score; ties go to the heavier dimension, then rubric order.
    gap = min(dimension_results, key=lambda r: (r["score"], -weights[r["id"]]))
    top_gap = None
    if gap["score"] < 100:  # nothing to coach on a perfect call
        top_gap = {"id": gap["id"], "name": gap["name"], "coaching": gap["coaching"]}
    return {
        "rubric": rubric["name"],
        "overall": round(overall),
        "metrics": metrics,
        "dimensions": dimension_results,
        "top_gap": top_gap,
    }


class RuleScorer:
    name = "rules"

    def score(self, transcript, rubric):
        text = transcript.lower()
        results = []
        for d in rubric["dimensions"]:
            hits = [s for s in d["signals"] if s in text]
            ratio = min(1.0, len(hits) / d["target_hits"])
            results.append({
                "id": d["id"],
                "name": d["name"],
                "score": round(ratio * 100),
                "evidence": hits[:5],
                "coaching": d["coaching"],
            })
        return _shape(rubric, results, call_metrics(transcript))


def build_prompt(transcript, rubric):
    """Prompt for the LLM scorer. Kept separate so it can be tested and reviewed."""
    dims = "\n".join(
        f'- {d["id"]} ({d["name"]}): score 0-100. Coaching if weak: {d["coaching"]}'
        for d in rubric["dimensions"]
    )
    return (
        "You are a sales coach scoring a discovery call against a rubric.\n"
        "Score only what is supported by the transcript. If there is no evidence, score 0.\n\n"
        f"Rubric dimensions:\n{dims}\n\n"
        "Return ONLY JSON: a list named \"dimensions\", each item "
        '{"id": str, "score": int, "evidence": [short quotes under 12 words]}.\n\n'
        f"Transcript:\n{transcript}"
    )


class LLMScorer:
    name = "llm"

    def __init__(self, api_key=None, model=None, post=None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self._post = post or self._http_post
        self.last_usage = {}

    def _http_post(self, payload):
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode(),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)

    def score(self, transcript, rubric):
        if not self.api_key and self._post == self._http_post:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        payload = {
            "model": self.model,
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": build_prompt(transcript, rubric)}],
        }
        body = self._post(payload)
        self.last_usage = body.get("usage", {})  # tokens in/out, read by the eval runner
        text = "".join(b.get("text", "") for b in body.get("content", []))
        parsed = json.loads(text[text.index("{"): text.rindex("}") + 1])
        by_id = {d["id"]: d for d in rubric["dimensions"]}
        results = []
        for item in parsed["dimensions"]:
            d = by_id[item["id"]]
            results.append({
                "id": d["id"],
                "name": d["name"],
                "score": max(0, min(100, int(item["score"]))),
                "evidence": item.get("evidence", [])[:5],
                "coaching": d["coaching"],
            })
        missing = set(by_id) - {r["id"] for r in results}
        if missing:
            raise ValueError(f"model omitted dimensions: {sorted(missing)}")
        return _shape(rubric, results, call_metrics(transcript))


def get_scorer(kind=None):
    kind = kind or os.environ.get("COACH_SCORER", "rules")
    return LLMScorer() if kind == "llm" else RuleScorer()
