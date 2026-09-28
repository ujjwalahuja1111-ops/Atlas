"""Self-tests for the live-evaluation HARNESS (validation infrastructure).

IMPORTANT: these tests use a scripted fake in place of the model, purely to
prove the evaluator/runner/reporting behave correctly. They say NOTHING about
what a real model returns; only scripts/live_llm_structuring_eval.py run with
real credentials does. They are deterministic and credential-free.

Run from backend/:  python -m pytest tests/test_eval_harness.py -q
"""
import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "atlas_eval_harness_test")
os.environ.setdefault("JWT_SECRET", "test")

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from eval import evaluator as ev  # noqa: E402
from eval.golden_corpus import CORPUS  # noqa: E402
from eval import live_runner as lr  # noqa: E402

FAKE_KEY = "sk-live-FAKEKEY1234567890abcdef"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _case(case_id):
    return next(c for c in CORPUS if c["id"] == case_id)


# ======================================================================
# Evaluator transparency: type / absent / null / wrong, never a bare MISSING
# ======================================================================

EXPECT_80 = [{"list": "materials", "quantity": {"equals": 80}, "unit": {"contains_any": ["kg"]}}]


def _field(result, name):
    leaf = ev.representative_leaf(result["results"][0])
    return next(f for f in leaf["candidate"]["fields"] if f["field"] == name)


def test_number_passes_including_float():
    for q in (80, 80.0):
        assert ev.evaluate_case({"materials": [{"quantity": q, "unit": "kg"}]}, EXPECT_80)["passed"]


def test_string_quantity_is_reported_as_a_type_problem_not_a_miss():
    r = ev.evaluate_case({"materials": [{"quantity": "80", "unit": "kg"}]}, EXPECT_80)
    assert not r["passed"]
    leaf = r["results"][0]
    assert leaf["failure_kind"] == ev.FORMAT_ONLY
    f = _field(r, "quantity")
    assert f["status"] == "wrong_type" and f["actual"] == "80" and f["actual_type"] == "string"
    text = "\n".join(ev.describe_failure(leaf))
    assert "'80'" in text or '"80"' in text
    assert "string" in text and "WRONG TYPE" in text


def test_string_with_unit_is_also_format_only():
    r = ev.evaluate_case({"materials": [{"quantity": "80 kg", "unit": "kg"}]}, EXPECT_80)
    assert r["results"][0]["failure_kind"] == ev.FORMAT_ONLY


def test_absent_null_and_wrong_value_are_distinguished():
    absent = ev.evaluate_case({"materials": [{"unit": "kg"}]}, EXPECT_80)
    null = ev.evaluate_case({"materials": [{"quantity": None, "unit": "kg"}]}, EXPECT_80)
    wrong = ev.evaluate_case({"materials": [{"quantity": 90, "unit": "kg"}]}, EXPECT_80)
    assert _field(absent, "quantity")["status"] == "field_absent"
    assert _field(null, "quantity")["status"] == "null"
    assert _field(wrong, "quantity")["status"] == "wrong_value"
    assert _field(wrong, "quantity")["actual"] == 90
    for r in (absent, null, wrong):
        assert r["results"][0]["failure_kind"] == ev.WRONG_VALUE


def test_fact_in_another_list_is_misrouted_not_missing():
    r = ev.evaluate_case({"materials": [], "issues": ["only 80 kg chicken came"]}, EXPECT_80)
    leaf = r["results"][0]
    assert leaf["failure_kind"] == ev.MISROUTED
    assert leaf["found_elsewhere"][0]["list"] == "issues"
    assert "another list" in "\n".join(ev.describe_failure(leaf))


def test_fact_nowhere_is_not_captured():
    r = ev.evaluate_case({"materials": [], "issues": ["the weather was nice"]}, EXPECT_80)
    assert r["results"][0]["failure_kind"] == ev.NOT_CAPTURED


def test_digit_tokens_match_whole_numbers_only():
    """'180' must not count as evidence of '80' elsewhere."""
    r = ev.evaluate_case({"materials": [], "issues": ["180 units"]}, EXPECT_80)
    assert r["results"][0]["failure_kind"] == ev.NOT_CAPTURED


# ---- no-fabrication check ---------------------------------------------------

NO_QTY = [{"list": "materials", "all_entries": {"quantity": {"is_null": True}}}]


def test_declining_to_emit_anything_is_correct_behaviour():
    assert ev.evaluate_case({"materials": []}, NO_QTY)["passed"]
    assert ev.evaluate_case({}, NO_QTY)["passed"]


def test_null_quantity_entry_passes_and_invented_quantity_fails():
    assert ev.evaluate_case({"materials": [{"quantity": None}]}, NO_QTY)["passed"]
    bad = ev.evaluate_case({"materials": [{"quantity": 12, "name": "x"}]}, NO_QTY)
    assert not bad["passed"]
    assert bad["results"][0]["violations"][0]["fields"][0]["actual"] == 12


# ---- alternatives and free text ------------------------------------------------

ANY = [{"any_of": [
    {"list": "commitments", "by_when": {"contains_any": ["monday"]}},
    {"list": "labour", "required_date": {"contains_any": ["monday"]}}]}]


def test_any_of_accepts_either_list_and_reports_which():
    a = ev.evaluate_case({"commitments": [{"by_when": "Monday"}]}, ANY)
    b = ev.evaluate_case({"labour": [{"required_date": "on Monday"}]}, ANY)
    assert a["passed"] and b["passed"]
    assert lr.matched_lists(a) == ["commitments"] and lr.matched_lists(b) == ["labour"]


def test_any_of_failure_describes_the_closest_alternative():
    r = ev.evaluate_case({"commitments": [{"by_when": "Friday"}]}, ANY)
    assert not r["passed"]
    text = "\n".join(ev.describe_failure(r["results"][0]))
    assert "none of 2 acceptable alternatives" in text and "Friday" in text


def test_free_text_requires_a_relevant_entry():
    exp = [{"list": "issues", "text_contains_any": ["rain"]}]
    assert ev.evaluate_case({"issues": ["dispatch delayed by rain"]}, exp)["passed"]
    assert not ev.evaluate_case({"issues": ["something else"]}, exp)["passed"]


# ---- failure flags feed the summary ----------------------------------------------

def test_failure_flags_by_field_type():
    q = ev.evaluate_case({"materials": [{"quantity": 1, "unit": "kg"}]}, EXPECT_80)
    attr = ev.evaluate_case({"commitments": [{"by_when": "monday", "attributed_to": None}]},
                            [{"list": "commitments", "attributed_to": {"contains_any": ["rahul"]}}])
    temporal = ev.evaluate_case({"commitments": [{"by_when": "friday"}]},
                                [{"list": "commitments", "by_when": {"contains_any": ["monday"]}}])
    misrouted = ev.evaluate_case({"issues": ["80 kg chicken"]}, EXPECT_80)
    fmt = ev.evaluate_case({"materials": [{"quantity": "80", "unit": "kg"}]}, EXPECT_80)
    assert ev.failure_flags(q) == {"quantity"}
    assert ev.failure_flags(attr) == {"attribution"}
    assert ev.failure_flags(temporal) == {"temporal"}
    assert ev.failure_flags(misrouted) == {"classification"}
    assert ev.failure_flags(fmt) == {"format_only"}


# ======================================================================
# Corpus review integrity
# ======================================================================

def test_every_case_has_a_documented_review():
    for c in CORPUS:
        r = c["review"]
        assert r["verdict"] in ("A", "B", "C", "D"), c["id"]
        assert r["rationale"].strip(), c["id"]
        if r["changed"]:
            assert r["original_expectation"].strip(), f"{c['id']}: changed but original not recorded"


def test_corpus_still_covers_five_domains_with_the_same_inputs():
    from collections import Counter
    counts = Counter(c["domain"] for c in CORPUS)
    assert set(counts) == {"construction", "restaurant", "warehouse", "shop", "software"}
    assert len(CORPUS) == 31 and all(5 <= n <= 8 for n in counts.values())


def test_every_expectation_can_be_described_without_error():
    for c in CORPUS:
        for exp in c["expect"]:
            assert ev.describe_expectation(exp)


def test_review_premises_exist_in_the_actual_prompt():
    """The B/D rationales rely on specific wording in EVENT_SYSTEM_PROMPT.
    If that wording is ever changed, these reviews must be revisited, so this
    fails loudly instead of leaving stale documentation."""
    from engines.intelligence_engine import EVENT_SYSTEM_PROMPT as P
    assert "a person committing to a task" in P
    assert "not already covered above" in P
    assert "tool, machine, or device requirement" in P
    assert "any scheduled check or verification" in P
    assert "ONLY when the speaker is explicitly quoting or relaying" in P


def test_no_expectation_was_relaxed_for_attribution_of_relayed_claims():
    """Guard against silently loosening the attribution-vs-observation test:
    the relayed-claim cases must still REQUIRE attribution, and the own-plan /
    own-observation cases must still REQUIRE null attribution."""
    def flat(exp):
        return exp["any_of"] if "any_of" in exp else [exp]
    def specs(case_id, field):
        return [leaf.get(field) for e in _case(case_id)["expect"] for leaf in flat(e)]
    assert all(s and "contains_any" in s for s in specs("software_2_relayed_claim_attributed", "attributed_to"))
    assert all(s == {"is_null": True} for s in specs("software_1_own_plan_not_attributed", "attributed_to"))
    second = _case("restaurant_1_confirmed_and_shortfall")["expect"][1]
    assert second["attributed_to"] == {"is_null": True}


# ======================================================================
# Runner: repeat runs, raw capture, buckets, redaction, no-credential behaviour
# ======================================================================

def _scripted(outputs: dict):
    """Fake structure_fn keyed by the case text; each value is a dict, an
    Exception to raise, or a callable(run_index)->dict for per-run variation."""
    calls = {}

    async def fn(transcript, text_input, photos):
        n = calls.get(text_input, 0)
        calls[text_input] = n + 1
        out = outputs[text_input]
        if callable(out):
            out = out(n)
        if isinstance(out, Exception):
            raise out
        return out
    fn.calls = calls
    return fn


CORRECT_C1 = {"materials": [{"name": "tiles", "quantity": 200, "unit": "tiles",
                             "required_date": "Thursday", "attributed_to": "supplier"}]}
WRONG_C1 = {"materials": [{"name": "tiles", "quantity": 20, "unit": "tiles",
                           "required_date": "Thursday", "attributed_to": "supplier"}]}


def _subset(*ids):
    return [_case(i) for i in ids]


def test_runs_repeat_and_separate_variance_from_consistent_failure():
    cases = _subset("construction_1_supplier_delivery", "construction_6_urgent_material_today")
    fn = _scripted({
        cases[0]["text"]: lambda n: CORRECT_C1 if n == 1 else WRONG_C1,       # 1 of 3 passes
        cases[1]["text"]: {"materials": [{"quantity": 15, "unit": "bags", "required_date": "today"}]},  # never
    })
    records = _run(lr.run_cases(cases, 3, fn))
    assert len(records) == 6
    s = lr.summarize(records, cases)
    by = {p["case_id"]: p for p in s["per_case"]}
    assert by["construction_1_supplier_delivery"]["status"] == "intermittent"
    assert by["construction_6_urgent_material_today"]["status"] == "fail"
    assert s["intermittent"] == 1 and s["failed"] == 1 and s["passed"] == 0
    assert fn.calls[cases[0]["text"]] == 3            # really ran 3 times


def test_failure_buckets_separate_model_from_evaluator_from_corpus():
    genuine = _case("construction_6_urgent_material_today")     # review A
    fmt = _case("restaurant_1_confirmed_and_shortfall")          # review A, but value right / type wrong
    sensitive = _case("software_2_relayed_claim_attributed")     # review B
    cases = [genuine, fmt, sensitive]
    fn = _scripted({
        genuine["text"]: {"materials": [{"quantity": 15, "unit": "bags", "required_date": "today"}]},
        fmt["text"]: {"materials": [
            {"quantity": "80", "unit": "kg", "required_date": "Friday", "attributed_to": "food supplier"},
            {"quantity": 20, "unit": "kg", "required_date": "tomorrow", "attributed_to": None}]},
        sensitive["text"]: {"commitments": [{"what": "Rahul joins", "by_when": "Monday", "attributed_to": None}]},
    })
    s = lr.summarize(_run(lr.run_cases(cases, 1, fn)), cases)
    b = {p["case_id"]: p["bucket"] for p in s["per_case"]}
    assert b[genuine["id"]] == "genuine_model"
    assert b[fmt["id"]] == "evaluator_format"
    assert b[sensitive["id"]] == "corpus_sensitive"
    assert s["genuine_model_failures"] == 1 and s["evaluator_format_failures"] == 1
    assert s["corpus_sensitive_failures"] == 1
    assert s["failure_flags"]["quantity"] == 1        # genuine one
    assert s["failure_flags"]["attribution"] == 1     # software_2
    assert s["failure_flags"]["format_only"] == 1
    assert s["by_domain"]["construction"]["fail"] == 1 and s["by_domain"]["software"]["fail"] == 1


def test_errors_are_not_counted_as_failed_extractions_and_keep_raw_text():
    import json as _json
    case = _case("warehouse_4_dispatch_delay_issue")
    other = _case("construction_1_supplier_delivery")
    bad_json = _json.JSONDecodeError("Expecting value", "Sure! here is JSON: {oops", 0)
    fn = _scripted({case["text"]: bad_json,
                    other["text"]: RuntimeError(f"401 from server using key {FAKE_KEY}")})
    redact = lr.make_redactor(FAKE_KEY)
    records = _run(lr.run_cases([case, other], 1, fn, redact=redact))
    s = lr.summarize(records, [case, other])
    assert s["errored"] == 2 and s["failed"] == 0 and s["infrastructure_errors"] == 2
    assert records[0]["raw_text"] == "Sure! here is JSON: {oops"   # complete text kept
    assert FAKE_KEY not in json.dumps(records)                       # secret never recorded


def test_report_shows_input_expected_fact_field_value_type_and_complete_raw_output():
    case = _case("restaurant_1_confirmed_and_shortfall")
    raw = {"materials": [{"quantity": "80", "unit": "kg", "required_date": "Friday",
                          "attributed_to": "food supplier", "note": "UNIQUE-RAW-MARKER"},
                         {"quantity": 20, "unit": "kg", "required_date": "tomorrow", "attributed_to": None}]}
    fn = _scripted({case["text"]: raw})
    records = _run(lr.run_cases([case], 1, fn))
    s = lr.summarize(records, [case])
    report = lr.format_report(records, [case], s)
    assert case["text"] in report                              # original input
    assert "quantity equals 80" in report                      # expected fact
    assert "actual \"80\" (string)" in report                  # actual value AND type
    assert "WRONG TYPE" in report                              # exact field verdict
    assert "COMPLETE RAW MODEL OUTPUT" in report and "UNIQUE-RAW-MARKER" in report
    assert "DIAGNOSTIC SUMMARY" in report and "evaluator/format failures" in report


def test_outputs_are_saved_complete_and_never_contain_the_key(tmp_path):
    case = _case("construction_1_supplier_delivery")
    fn = _scripted({case["text"]: lambda n: {**CORRECT_C1, "run_marker": f"RUN-{n}"}})
    out_dir = tmp_path / "output"
    result = _run(lr.execute(cases=[case], runs=2, structure_fn=fn, api_key=FAKE_KEY,
                             out_dir=out_dir, echo=lambda *_: None))
    assert result["executed"] is True
    paths = result["paths"]
    lines = [json.loads(l) for l in Path(paths["raw_jsonl"]).read_text(encoding="utf-8").splitlines()]
    assert [l["raw"]["run_marker"] for l in lines] == ["RUN-0", "RUN-1"]      # every run, complete raw
    assert json.loads(Path(paths["summary_json"]).read_text(encoding="utf-8"))["runs_per_case"] == 2
    for p in paths.values():
        assert FAKE_KEY not in Path(p).read_text(encoding="utf-8")


def test_nothing_runs_or_is_written_without_a_real_credential(tmp_path):
    out_dir = tmp_path / "output"
    messages = []

    async def must_not_be_called(*a, **k):
        raise AssertionError("the model must not be called without a real key")

    for key in (None, "", "REPLACE_WITH_EMERGENT_LLM_KEY", "sk-test", "test"):
        r = _run(lr.execute(cases=CORPUS[:2], runs=1, structure_fn=must_not_be_called,
                            api_key=key, out_dir=out_dir, echo=messages.append))
        assert r == {"executed": False}
    assert not out_dir.exists()
    assert all("NOT EXECUTED" in m for m in messages)


def test_key_recognition_and_redaction():
    assert lr.looks_like_real_key(FAKE_KEY)
    for bad in (None, "", "short", "REPLACE_WITH_EMERGENT_LLM_KEY", "sk-test", "test"):
        assert not lr.looks_like_real_key(bad)
    red = lr.make_redactor(FAKE_KEY)
    assert FAKE_KEY not in red(f"failed with {FAKE_KEY} and Bearer abcdefgh12345678 and sk-abcdefgh1234")
    assert "sk-abcdefgh1234" not in red("sk-abcdefgh1234")


def test_default_output_folder_is_git_ignored():
    root = BACKEND.parent / ".gitignore"
    assert "backend/eval/output/" in root.read_text(encoding="utf-8").splitlines()


def test_cli_without_credentials_exits_2_and_says_not_executed(monkeypatch, capsys):
    import core.settings as settings
    monkeypatch.setattr(settings, "EMERGENT_LLM_KEY", "")
    spec = importlib.util.spec_from_file_location(
        "live_llm_structuring_eval_under_test", BACKEND / "scripts" / "live_llm_structuring_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--runs", "1"]) == 2
    assert "NOT EXECUTED" in capsys.readouterr().out
    assert mod.main(["--runs", "99"]) == 1          # argument validation


def test_only_the_real_script_may_label_output_as_live(tmp_path):
    case = _case("construction_1_supplier_delivery")
    fn = _scripted({case["text"]: CORRECT_C1})
    lines = []
    _run(lr.execute(cases=[case], runs=1, structure_fn=fn, api_key=FAKE_KEY,
                    out_dir=tmp_path / "o", echo=lines.append))
    joined = "\n".join(lines)
    assert "NOT a live result" in joined and "real model" not in joined
    script = (BACKEND / "scripts" / "live_llm_structuring_eval.py").read_text(encoding="utf-8")
    assert "LIVE_SOURCE_LABEL" in script and lr.LIVE_SOURCE_LABEL == "real _structure() path, real model"
