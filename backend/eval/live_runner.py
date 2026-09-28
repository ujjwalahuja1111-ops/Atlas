"""Runner, diagnostics and reporting for the live structuring evaluation.

Validation infrastructure only. The runner is generic over a
`structure_fn(transcript, text_input, photo_b64s) -> dict`. The real script
(scripts/live_llm_structuring_eval.py) passes intelligence_engine._structure,
i.e. the actual production structuring path with the actual EVENT_SYSTEM_
PROMPT. Unit tests pass a scripted fake purely to test THIS HARNESS; results
from a fake are never live results and are labelled as harness self-tests.

What this module guarantees
  * every run's COMPLETE raw structured output is kept (or, when the model
    returned unparseable text, the complete raw text);
  * failures are explained field by field with the actual value and type;
  * failures are separated into genuine model failures, evaluator/format
    issues, and corpus-sensitive cases (see `summarize`);
  * credentials are never written: the key value is redacted from anything
    persisted or printed, and nothing here ever reads the key into a file.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

from eval.evaluator import (
    describe_expectation, describe_failure, evaluate_case, failure_flags, FORMAT_ONLY,
)

StructureFn = Callable[[str, Optional[str], list], Awaitable[dict]]

# What produced the outputs is stated in every report. Only the real script
# passes LIVE_SOURCE_LABEL; anything else is labelled as not live.
LIVE_SOURCE_LABEL = "real _structure() path, real model"
DEFAULT_SOURCE_LABEL = "HARNESS TEST with a substitute model - NOT a live result"

_KEY_LIKE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{8,})")
_PLACEHOLDER_PREFIXES = ("REPLACE", "YOUR_", "CHANGEME", "sk-test")


def looks_like_real_key(key: Optional[str]) -> bool:
    """True only for something that could be a real credential. Empty values,
    the .env.example placeholder and known test placeholders are not."""
    if not key or len(key) < 8:
        return False
    return not key.upper().startswith(tuple(p.upper() for p in _PLACEHOLDER_PREFIXES)) \
        and key.lower() not in ("test", "sk-test")


def make_redactor(secret: Optional[str]) -> Callable[[str], str]:
    def redact(text: str) -> str:
        if not isinstance(text, str):
            text = str(text)
        if secret and len(secret) >= 8:
            text = text.replace(secret, "***REDACTED***")
        return _KEY_LIKE.sub("***REDACTED***", text)
    return redact


# ------------------------------------------------------------------ running

async def run_cases(cases: list[dict], runs: int, structure_fn: StructureFn,
                    redact: Callable[[str], str] = lambda s: s,
                    on_record: Optional[Callable[[dict], None]] = None) -> list[dict]:
    """One record per (case, run). A failed model call or unparseable reply is
    recorded as an ERROR (an infrastructure/format problem), never as a
    passed or failed extraction."""
    records: list[dict] = []
    for case in cases:
        for run in range(1, runs + 1):
            rec = {"case_id": case["id"], "domain": case["domain"], "run": run,
                   "text": case["text"], "review_verdict": case["review"]["verdict"],
                   "raw": None, "raw_text": None, "error": None, "eval": None, "passed": False}
            try:
                raw = await structure_fn("", case["text"], [])
                if not isinstance(raw, dict):
                    raise TypeError(f"structuring returned {type(raw).__name__}, expected a JSON object")
                rec["raw"] = raw
                rec["eval"] = evaluate_case(raw, case["expect"])
                rec["passed"] = rec["eval"]["passed"]
            except Exception as exc:  # noqa: BLE001 - recorded, never swallowed silently
                rec["error"] = redact(f"{type(exc).__name__}: {exc}")
                doc = getattr(exc, "doc", None)  # json.JSONDecodeError carries the full text
                if doc:
                    rec["raw_text"] = redact(str(doc))
            records.append(rec)
            if on_record:
                on_record(rec)
    return records


# ------------------------------------------------------------------ summary

def matched_lists(eval_result: dict) -> list[str]:
    lists = []
    for r in eval_result["results"]:
        if not r["passed"]:
            continue
        if r["kind"] == "any_of":
            lists.append(r["alternatives"][r["matched_alternative"]]["list"])
        else:
            lists.append(r["list"])
    return lists


def summarize(records: list[dict], cases: list[dict]) -> dict:
    case_by_id = {c["id"]: c for c in cases}
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_case[r["case_id"]].append(r)

    per_case = []
    for cid, recs in by_case.items():
        case = case_by_id[cid]
        passed_runs = sum(r["passed"] for r in recs)
        error_runs = sum(1 for r in recs if r["error"])
        if passed_runs == len(recs):
            status = "pass"
        elif error_runs == len(recs):
            status = "error"
        elif passed_runs == 0:
            status = "fail"            # failed every run that produced output
        else:
            status = "intermittent"    # passed some runs, not others
        first_fail = next((r for r in recs if r["eval"] and not r["passed"]), None)
        flags = failure_flags(first_fail["eval"]) if first_fail else set()
        bucket = None
        if status == "error":
            bucket = "infrastructure_error"
        elif status != "pass":
            if flags and flags <= {"format_only"}:
                bucket = "evaluator_format"
            elif case["review"]["verdict"] in ("B", "D"):
                bucket = "corpus_sensitive"
            else:
                bucket = "genuine_model"
        per_case.append({"case_id": cid, "domain": case["domain"], "status": status,
                         "runs": len(recs), "passed_runs": passed_runs, "error_runs": error_runs,
                         "review_verdict": case["review"]["verdict"], "bucket": bucket,
                         "flags": sorted(flags)})

    def count(pred):
        return sum(1 for p in per_case if pred(p))

    by_domain: dict[str, dict] = {}
    for p in per_case:
        d = by_domain.setdefault(p["domain"], {"cases": 0, "pass": 0, "fail": 0,
                                               "intermittent": 0, "error": 0})
        d["cases"] += 1
        d[p["status"]] += 1

    flag_counts = {k: count(lambda p, k=k: k in p["flags"] and p["status"] != "pass")
                   for k in ("quantity", "attribution", "temporal", "classification",
                             "not_captured", "content", "format_only")}

    fact_pass = fact_fail = 0
    for r in records:
        if r["eval"]:
            for leaf in r["eval"]["results"]:
                if leaf["passed"]:
                    fact_pass += 1
                else:
                    fact_fail += 1

    return {
        "total_cases": len(per_case),
        "runs_per_case": max((p["runs"] for p in per_case), default=0),
        "passed": count(lambda p: p["status"] == "pass"),
        "failed": count(lambda p: p["status"] == "fail"),
        "intermittent": count(lambda p: p["status"] == "intermittent"),
        "errored": count(lambda p: p["status"] == "error"),
        "genuine_model_failures": count(lambda p: p["bucket"] == "genuine_model"),
        "corpus_sensitive_failures": count(lambda p: p["bucket"] == "corpus_sensitive"),
        "evaluator_format_failures": count(lambda p: p["bucket"] == "evaluator_format"),
        "infrastructure_errors": count(lambda p: p["bucket"] == "infrastructure_error"),
        "by_domain": by_domain,
        "failure_flags": flag_counts,
        "fact_level": {"passed": fact_pass, "failed": fact_fail, "total": fact_pass + fact_fail},
        "per_case": per_case,
    }


# ------------------------------------------------------------------- report

def _pretty(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def format_report(records: list[dict], cases: list[dict], summary: dict,
                  *, verbose: bool = False, source_label: str = DEFAULT_SOURCE_LABEL) -> str:
    case_by_id = {c["id"]: c for c in cases}
    per = {p["case_id"]: p for p in summary["per_case"]}
    out: list[str] = []
    out.append("=" * 78)
    out.append(f"STRUCTURING EVALUATION  ({source_label})")
    out.append(f"cases: {summary['total_cases']}   runs per case: {summary['runs_per_case']}")
    out.append("=" * 78)

    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_case[r["case_id"]].append(r)

    for cid, recs in by_case.items():
        case, p = case_by_id[cid], per[cid]
        tag = {"pass": "PASS", "fail": "FAIL", "intermittent": "INTERMITTENT",
               "error": "ERROR"}[p["status"]]
        head = f"[{tag}] {cid} ({case['domain']})  passed {p['passed_runs']}/{p['runs']} runs"
        if p["status"] == "pass":
            out.append(head + "   captured in: " + ", ".join(
                sorted({l for r in recs if r["eval"] for l in matched_lists(r["eval"])})))
            if verbose:
                out.append("    RAW: " + json.dumps(recs[0]["raw"], ensure_ascii=False))
            continue

        out.append("")
        out.append(head + f"   expectation review: {case['review']['verdict']}"
                   + (f"   -> {p['bucket']}" if p["bucket"] else ""))
        out.append(f"  INPUT: {case['text']!r}")
        out.append("  EXPECTED FACTS:")
        for i, exp in enumerate(case["expect"], 1):
            out.append(f"    {i}. {describe_expectation(exp)}")
        out.append(f"  (expectation note: {case['review']['rationale']})")

        shown = False
        for r in recs:
            if r["error"]:
                out.append(f"  RUN {r['run']}: ERROR (no extraction to judge): {r['error']}")
                if r["raw_text"]:
                    out.append("    complete raw text returned by the model:")
                    out.append("      " + r["raw_text"].replace("\n", "\n      "))
                continue
            if r["passed"]:
                out.append(f"  RUN {r['run']}: passed")
                continue
            out.append(f"  RUN {r['run']}: FAILED")
            for i, res in enumerate(r["eval"]["results"], 1):
                if res["passed"]:
                    out.append(f"    expectation {i}: ok")
                else:
                    out.append(f"    expectation {i}: FAILED")
                    out.extend(describe_failure(res))
            if not shown:
                out.append("    COMPLETE RAW MODEL OUTPUT:")
                out.append("      " + _pretty(r["raw"]).replace("\n", "\n      "))
                shown = True
            else:
                out.append("    (raw output for this run is in the saved .jsonl file)")
    out.append("")
    out.extend(format_summary(summary))
    return "\n".join(out)


def format_summary(summary: dict) -> list[str]:
    s = summary
    lines = ["-" * 78, "DIAGNOSTIC SUMMARY", "-" * 78,
             f"total cases:           {s['total_cases']}   (runs per case: {s['runs_per_case']})",
             f"passed (every run):    {s['passed']}",
             f"failed (every run):    {s['failed']}",
             f"intermittent:          {s['intermittent']}   (passed some runs, failed others = model variance)",
             f"errored:               {s['errored']}   (call/parse problems, not judged)",
             "",
             "WHY THE NON-PASSING CASES DID NOT PASS",
             f"  genuine model failures:          {s['genuine_model_failures']}"
             "   (expectation reviewed as correct; model did not produce it)",
             f"  corpus-sensitive failures:       {s['corpus_sensitive_failures']}"
             "   (expectation was ambiguous/overlapping; inspect the raw output before concluding)",
             f"  evaluator/format failures:       {s['evaluator_format_failures']}"
             "   (value was right, only the TYPE differed, e.g. \"80\" vs 80)",
             f"  infrastructure errors:           {s['infrastructure_errors']}",
             "",
             "FAILURE TYPES (cases that did not fully pass; a case can appear in several)",
             ]
    fl = s["failure_flags"]
    lines += [f"  quantity/count wrong or missing:   {fl['quantity']}",
              f"  attribution wrong or missing:      {fl['attribution']}",
              f"  temporal (date phrase) wrong:      {fl['temporal']}",
              f"  classification (right fact, wrong list): {fl['classification']}",
              f"  fact not captured anywhere:        {fl['not_captured']}",
              f"  other content wrong:               {fl['content']}",
              f"  format only (type differs):        {fl['format_only']}",
              "", "RESULTS BY DOMAIN"]
    for dom, d in s["by_domain"].items():
        lines.append(f"  {dom:<13} cases {d['cases']}  pass {d['pass']}  fail {d['fail']}  "
                     f"intermittent {d['intermittent']}  error {d['error']}")
    f = s["fact_level"]
    lines += ["", f"fact-level (all runs): {f['passed']} passed / {f['failed']} failed of {f['total']}"]
    return lines


# ------------------------------------------------------------------ outputs

def write_outputs(records: list[dict], summary: dict, report: str, out_dir: Path) -> dict:
    """Saves complete raw outputs (JSONL), the summary (JSON) and the readable
    report (text). The default directory is git-ignored. Nothing written here
    can contain the API key: model output is not a credential and every error
    string was redacted when recorded."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = out_dir / f"live_eval_{stamp}"
    jsonl = base.with_suffix(".jsonl")
    with jsonl.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    summ = base.with_name(base.name + "_summary.json")
    summ.write_text(_pretty(summary), encoding="utf-8")
    rep = base.with_name(base.name + "_report.txt")
    rep.write_text(report, encoding="utf-8")
    return {"raw_jsonl": str(jsonl), "summary_json": str(summ), "report_txt": str(rep)}


# ------------------------------------------------------------------ driver

NOT_EXECUTED_MESSAGE = (
    "LAYER B NOT EXECUTED - no real LLM credentials are configured "
    "(EMERGENT_LLM_KEY is unset or a placeholder).\n"
    "This is not a passed or failed evaluation - it did not run, and nothing was written.\n"
    "Set EMERGENT_LLM_KEY (see eval/README.md) and run it again."
)


async def execute(*, cases: list[dict], runs: int, structure_fn: StructureFn,
                  api_key: Optional[str], out_dir: Path, verbose: bool = False,
                  echo: Callable[[str], None] = print,
                  source_label: str = DEFAULT_SOURCE_LABEL) -> dict:
    """Runs the evaluation and returns a result dict. Never runs, and never
    writes files, when there is no real credential."""
    if not looks_like_real_key(api_key):
        echo(NOT_EXECUTED_MESSAGE)
        return {"executed": False}

    redact = make_redactor(api_key)
    total = len(cases) * runs
    counter = {"n": 0}

    def progress(rec: dict) -> None:
        counter["n"] += 1
        state = "error" if rec["error"] else ("pass" if rec["passed"] else "FAIL")
        echo(f"  [{counter['n']}/{total}] {rec['case_id']} run {rec['run']}: {state}")

    echo(f"Running {len(cases)} case(s) x {runs} run(s): {source_label} ...")
    records = await run_cases(cases, runs, structure_fn, redact=redact, on_record=progress)
    summary = summarize(records, cases)
    report = redact(format_report(records, cases, summary, verbose=verbose,
                                  source_label=source_label))
    paths = write_outputs(records, summary, report, out_dir)
    echo("")
    echo(report)
    echo("")
    echo("Saved (git-ignored, local only):")
    for k, v in paths.items():
        echo(f"  {k}: {v}")
    return {"executed": True, "summary": summary, "paths": paths, "records": records}
