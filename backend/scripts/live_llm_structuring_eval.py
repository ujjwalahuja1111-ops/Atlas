"""Layer B: live LLM structuring evaluation (validation infrastructure only).

Sends the golden corpus's natural-language text through the REAL, unmodified
intelligence_engine._structure() - the actual EVENT_SYSTEM_PROMPT and the
actual model call - and judges the model's own output with the transparent
evaluator in eval/evaluator.py.

Run from the backend/ folder (see eval/README.md for copy-paste commands):

    python -m scripts.live_llm_structuring_eval                 # all cases, 1 run
    python -m scripts.live_llm_structuring_eval --runs 3        # repeat to spot model variance
    python -m scripts.live_llm_structuring_eval --domain restaurant
    python -m scripts.live_llm_structuring_eval --case shop_5_hinglish_supplier_promise

It prints, for every failed case: the input, the expected facts, the exact
field that failed with the actual value AND its type, and the COMPLETE raw
model output. Everything (all runs, all raw outputs) is also saved under
eval/output/, which is git-ignored.

If no real credential is configured it prints "LAYER B NOT EXECUTED", writes
nothing and exits with status 2 - it never reports a result it did not get.
The API key is read from the environment / backend/.env, is never printed,
and is redacted from anything saved.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# core.settings requires these at import time; structuring never touches the
# database. Defaults only fill gaps - real values in your environment win.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "atlas_live_eval")
os.environ.setdefault("JWT_SECRET", "not-used-by-the-evaluation")


def _parse(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Live multi-industry structuring evaluation")
    p.add_argument("--runs", type=int, default=1,
                   help="times to run every case (1-10). Use 3 to separate model variance "
                        "from consistent failures.")
    p.add_argument("--domain", choices=["construction", "restaurant", "warehouse", "shop", "software"])
    p.add_argument("--case", help="run a single case id")
    p.add_argument("--out", default=str(BACKEND_DIR / "eval" / "output"),
                   help="folder for saved raw outputs (git-ignored by default)")
    p.add_argument("--verbose", action="store_true", help="also print raw output for passing cases")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse(argv)
    if not 1 <= args.runs <= 10:
        print("--runs must be between 1 and 10")
        return 1

    # Windows consoles default to a legacy encoding that cannot print Hindi/
    # Unicode model output; make printing safe.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    from core.settings import EMERGENT_LLM_KEY  # loads backend/.env
    from eval.golden_corpus import CORPUS
    from eval.live_runner import execute, LIVE_SOURCE_LABEL

    cases = CORPUS
    if args.domain:
        cases = [c for c in cases if c["domain"] == args.domain]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    if not cases:
        print("No matching cases.")
        return 1

    # Import only after the credential check would matter: importing the engine
    # is harmless, but the real call happens inside execute() and only with a key.
    from engines.intelligence_engine import _structure

    result = asyncio.run(execute(cases=cases, runs=args.runs, structure_fn=_structure,
                                 api_key=EMERGENT_LLM_KEY, out_dir=Path(args.out),
                                 verbose=args.verbose, source_label=LIVE_SOURCE_LABEL))
    return 0 if result["executed"] else 2


if __name__ == "__main__":
    sys.exit(main())
