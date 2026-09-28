# Live multi-industry structuring evaluation

This checks whether the real AI model turns messy operational sentences from
five industries (construction, restaurant, warehouse, small shop, software)
into the right structured facts. It uses the same code path Atlas uses in
production. It does **not** change Atlas.

## Run it (from the `backend` folder)

You need `EMERGENT_LLM_KEY` set, either in `backend/.env` or in your terminal.

Windows PowerShell:
```
cd backend
$env:EMERGENT_LLM_KEY = "your-key"        # skip if it is already in backend/.env
python -m scripts.live_llm_structuring_eval
python -m scripts.live_llm_structuring_eval --runs 3
```

Mac/Linux:
```
cd backend
export EMERGENT_LLM_KEY="your-key"
python -m scripts.live_llm_structuring_eval --runs 3
```

Useful options: `--runs 3` (repeat every case; separates one-off model
variance from consistent failures), `--domain restaurant`,
`--case shop_5_hinglish_supplier_promise`, `--verbose`.

## What you get
* On screen: a summary, and for every failed case the input, the expected
  facts, exactly which field failed (with the value the model actually gave
  and its type), and the complete raw model output.
* Saved in `backend/eval/output/` (ignored by git, stays on your machine):
  `live_eval_<time>.jsonl` (every raw output, every run),
  `..._summary.json`, `..._report.txt`.
  **Send me the `_report.txt` and the `.jsonl` files.**

If no real key is configured it says `LAYER B NOT EXECUTED`, writes nothing,
and does not invent a result. The key is never printed or saved.

## Reading the summary
* **genuine model failures** - the expectation was reviewed as correct and the
  model did not produce it.
* **corpus-sensitive failures** - the sentence is ambiguous, or the prompt's
  own list definitions overlap; look at the raw output before drawing a
  conclusion.
* **evaluator/format failures** - the value was right and only its type
  differed (for example `"80"` instead of `80`).
* **intermittent** (with `--runs 3`) - passed some runs and failed others:
  model variance, not a consistent problem.
