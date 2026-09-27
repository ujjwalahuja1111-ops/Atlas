"""Multi-Industry Validation Follow-up — Natural-Language Structuring Proof.

LAYER B: live LLM evaluation. Sends the golden corpus's own natural-
language text through the REAL, unmodified intelligence_engine._structure()
function — the actual EVENT_SYSTEM_PROMPT, the actual model call — and
evaluates the REAL model's own output against the same fact-level
`expect` checks Layer A uses (eval/golden_corpus.py's own
evaluate_case(), unchanged).

This is NOT part of normal CI (see tests/test_golden_corpus_pipeline.py
for the deterministic, credential-free layer). It requires a real
EMERGENT_LLM_KEY/OPENAI_API_KEY to be configured in the environment.

Run manually from backend/, with real credentials configured:
    python -m scripts.live_llm_structuring_eval
    python -m scripts.live_llm_structuring_eval --domain restaurant
    python -m scripts.live_llm_structuring_eval --case restaurant_1_confirmed_and_shortfall

If no key is configured, this script exits immediately with a clear
message rather than silently skip cases or fabricate a result -
Layer B's own evaluation is either genuinely executed against the real
model, or it does not run at all, and the difference must never be
ambiguous to whoever reads its output.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.settings import EMERGENT_LLM_KEY  # noqa: E402
from engines.intelligence_engine import _structure  # noqa: E402
from eval.golden_corpus import CORPUS, evaluate_case  # noqa: E402


def _has_real_credentials() -> bool:
    return bool(EMERGENT_LLM_KEY) and EMERGENT_LLM_KEY not in ("", "sk-test", "test")


async def _run_case(case: dict) -> dict:
    """Calls the REAL _structure() - the exact function reality_engine.
    capture()'s own background worker calls - with this case's own
    natural-language text. No mocking, no simulation."""
    structured = await _structure(transcript="", text_input=case["text"], photo_b64s=[])
    result = evaluate_case(structured, case["expect"])
    return {"id": case["id"], "domain": case["domain"], "text": case["text"],
            "structured": structured, "eval": result}


async def main(domain_filter: str = None, case_filter: str = None):
    if not _has_real_credentials():
        print("LAYER B NOT EXECUTED — no real LLM credentials configured "
              "(EMERGENT_LLM_KEY is unset or a placeholder).")
        print("This is not a passed or failed evaluation — it did not run. "
              "Configure real credentials and re-run this script directly "
              "to genuinely evaluate the live model.")
        return

    cases = CORPUS
    if domain_filter:
        cases = [c for c in cases if c["domain"] == domain_filter]
    if case_filter:
        cases = [c for c in cases if c["id"] == case_filter]
    if not cases:
        print("No matching cases.")
        return

    print(f"LAYER B — LIVE LLM EVALUATION — {len(cases)} case(s), real model calls, real credentials.")
    print()

    results = []
    for case in cases:
        try:
            r = await _run_case(case)
        except Exception as e:
            r = {"id": case["id"], "domain": case["domain"], "text": case["text"],
                 "structured": None, "eval": {"passed": False, "results": [],
                                               "error": f"{type(e).__name__}: {e}"}}
        results.append(r)
        status = "PASS" if r["eval"].get("passed") else "FAIL"
        print(f"[{status}] {r['id']} ({r['domain']})")
        print(f"  text: {r['text']!r}")
        if r["eval"].get("error"):
            print(f"  ERROR: {r['eval']['error']}")
        else:
            for item in r["eval"]["results"]:
                mark = "ok" if item["matched"] else "MISSING"
                print(f"  [{mark}] list={item['list']} constraints={item['constraints']}")
        print()

    passed = sum(1 for r in results if r["eval"].get("passed"))
    print(f"TOTAL: {passed}/{len(results)} cases passed against the real, live model.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default=None,
                         choices=["construction", "restaurant", "warehouse", "shop", "software"])
    parser.add_argument("--case", default=None)
    args = parser.parse_args()
    asyncio.run(main(domain_filter=args.domain, case_filter=args.case))
