"""Score the labeled transcripts and compare scorers against the human labels.

    python3 -m evals.run_eval --scorer rules      # offline, no key
    python3 -m evals.run_eval --scorer llm        # needs ANTHROPIC_API_KEY
    python3 -m evals.run_eval --scorer both

Results are written to evals/results/<scorer>.json and a markdown summary is printed.
A case where the scorer errors is counted as a failure and reported. It is never dropped silently.
"""
import argparse
import json
import os
import sys
import time

from coach.scorer import LLMScorer, RuleScorer, load_rubric

HERE = os.path.dirname(os.path.abspath(__file__))
AGREE_WITHIN = 25  # a score within 25 points of the label counts as agreeing
HIGH, LOW = 75, 25  # false positive: predicted >= HIGH where label is 0. Miss: predicted <= LOW where label >= HIGH.


def load_cases(dataset=None, labels=None):
    dataset = dataset or os.path.join(HERE, "dataset")
    with open(labels or os.path.join(HERE, "labels.json"), encoding="utf-8") as f:
        label_map = json.load(f)["labels"]
    cases = []
    for name in sorted(label_map):
        with open(os.path.join(dataset, name + ".txt"), encoding="utf-8") as f:
            cases.append({"name": name, "transcript": f.read(), "labels": label_map[name]})
    return cases


def run(scorer, rubric, cases):
    results = []
    for c in cases:
        started = time.time()
        entry = {"name": c["name"], "labels": c["labels"]}
        try:
            out = scorer.score(c["transcript"], rubric)
            entry["predicted"] = {d["id"]: d["score"] for d in out["dimensions"]}
        except Exception as exc:  # recorded, not hidden
            entry["error"] = f"{type(exc).__name__}: {exc}"
        entry["seconds"] = round(time.time() - started, 2)
        usage = getattr(scorer, "last_usage", None) or {}
        entry["input_tokens"] = usage.get("input_tokens", 0)
        entry["output_tokens"] = usage.get("output_tokens", 0)
        results.append(entry)
    return results


def summarize(results, dim_ids):
    ok = [r for r in results if "predicted" in r]
    per_dim = {}
    for d in dim_ids:
        errs = [abs(r["predicted"][d] - r["labels"][d]) for r in ok]
        per_dim[d] = {
            "mae": round(sum(errs) / len(errs), 1) if errs else None,
            "agree_pct": round(100 * sum(e <= AGREE_WITHIN for e in errs) / len(errs)) if errs else None,
        }
    pairs = [(r["predicted"][d], r["labels"][d]) for r in ok for d in dim_ids]
    return {
        "cases": len(results),
        "failed": len(results) - len(ok),
        "mae": round(sum(abs(p - l) for p, l in pairs) / len(pairs), 1) if pairs else None,
        "agree_pct": round(100 * sum(abs(p - l) <= AGREE_WITHIN for p, l in pairs) / len(pairs)) if pairs else None,
        "false_positives": sum(p >= HIGH and l == 0 for p, l in pairs),
        "misses": sum(p <= LOW and l >= HIGH for p, l in pairs),
        "total_seconds": round(sum(r["seconds"] for r in results), 1),
        "input_tokens": sum(r["input_tokens"] for r in results),
        "output_tokens": sum(r["output_tokens"] for r in results),
        "per_dimension": per_dim,
    }


def render(name, summary, results, dim_ids):
    lines = [f"### {name}", "",
             f"- Cases: {summary['cases']} ({summary['failed']} failed)",
             f"- Agreement within {AGREE_WITHIN} points of the label: {summary['agree_pct']}%",
             f"- Mean absolute error: {summary['mae']} points",
             f"- False positives (scored >= {HIGH} where the label is 0): {summary['false_positives']}",
             f"- Misses (scored <= {LOW} where the label is >= {HIGH}): {summary['misses']}"]
    if summary["input_tokens"] or summary["output_tokens"]:
        lines.append(f"- Tokens: {summary['input_tokens']} in, {summary['output_tokens']} out; {summary['total_seconds']}s total")
    lines += ["", "| Dimension | Agree | MAE |", "|---|---|---|"]
    for d in dim_ids:
        pd = summary["per_dimension"][d]
        lines.append(f"| {d} | {pd['agree_pct']}% | {pd['mae']} |")
    bad = [r for r in results if "predicted" in r and any(abs(r["predicted"][d] - r["labels"][d]) > AGREE_WITHIN for d in dim_ids)]
    if bad:
        lines += ["", "Cases with a disagreement:", ""]
        for r in bad:
            diffs = ", ".join(f"{d} {r['predicted'][d]} vs {r['labels'][d]}" for d in dim_ids
                              if abs(r["predicted"][d] - r["labels"][d]) > AGREE_WITHIN)
            lines.append(f"- `{r['name']}`: {diffs}")
    for r in results:
        if "error" in r:
            lines.append(f"- FAILED `{r['name']}`: {r['error']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scorer", choices=["rules", "llm", "both"], default="rules")
    args = ap.parse_args(argv)
    rubric, cases = load_rubric(), load_cases()
    dim_ids = [d["id"] for d in rubric["dimensions"]]
    kinds = ["rules", "llm"] if args.scorer == "both" else [args.scorer]
    if "llm" in kinds and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Run with --scorer rules, or set the key.", file=sys.stderr)
        return 2
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    for kind in kinds:
        scorer = LLMScorer() if kind == "llm" else RuleScorer()
        results = run(scorer, rubric, cases)
        summary = summarize(results, dim_ids)
        with open(os.path.join(HERE, "results", kind + ".json"), "w", encoding="utf-8") as f:
            json.dump({"scorer": kind, "model": getattr(scorer, "model", None), "summary": summary, "cases": results}, f, indent=2)
        print(render(kind, summary, results, dim_ids))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
