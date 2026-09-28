"""Transparent fact-level evaluator for the golden multi-industry corpus.

Validation infrastructure only — this module judges what a structuring
pass returned; it never changes Atlas's own behaviour.

Why this exists (what was wrong with the first evaluator)
---------------------------------------------------------
The first evaluator answered every failed expectation with a single
"[MISSING]" line. That hid four different situations:
  * the field was absent            (model never returned it)
  * the field was null              (model returned it as null)
  * the value was wrong             (model returned a different value)
  * the value was right but the TYPE differed, e.g. quantity "80" (a
    string) instead of 80 (a number)
and it could not say whether the fact had been captured in a DIFFERENT
list (for example a goods delivery filed under `issues`), which is a
classification problem, not a missing fact.

This evaluator reports, for every failed expectation: the exact field,
what was expected, the actual value AND its type, whether the fact turned
up in another list, and a `failure_kind` that separates those cases.

Expectation grammar (all leaves are plain dicts)
------------------------------------------------
  {"list": "materials", "quantity": {"equals": 80}, "unit": {"contains_any": ["kg"]}}
      -> at least one entry in `materials` satisfies EVERY field spec.
  {"list": "issues", "text_contains_any": ["rain", "delay"]}
      -> a free-text list (issues/work_done) has an entry containing a term.
  {"list": "materials", "all_entries": {"quantity": {"is_null": True}}}
      -> EVERY entry in the list satisfies the spec; an empty list passes.
         Used for "must not fabricate a quantity": declining to emit an
         entry at all is correct behaviour and must not be scored as a miss.
  {"any_of": [<leaf>, <leaf>, ...]}
      -> passes if any alternative passes. Used ONLY where the current
         prompt's own list definitions overlap (documented per case in the
         corpus `review`), so an expectation does not demand one list when
         the prompt legitimately permits several.

Field specs: {"equals": v} | {"contains_any": [terms]} | {"is_null": bool}.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

DICT_LIST_KEYS = (
    "materials", "labour", "equipment", "client_approvals", "drawing_requests",
    "inspections", "safety_observations", "quality_observations",
    "commitments", "follow_ups",
)
FREE_TEXT_KEYS = ("issues", "work_done")
ALL_LIST_KEYS = DICT_LIST_KEYS + FREE_TEXT_KEYS

QUANTITY_FIELDS = {"quantity", "count"}
ATTRIBUTION_FIELDS = {"attributed_to"}
TEMPORAL_FIELDS = {"required_date", "by_when", "when"}

_RESERVED = {"list", "note", "any_of", "all_entries", "text_contains_any"}
_NUMERIC_STRING = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[A-Za-z%.]*\s*$")

# Failure kinds for a failed leaf.
FORMAT_ONLY = "format_only"        # value correct, type differs ("80" vs 80)
MISROUTED = "misrouted"            # fact captured, but in a different list
NOT_CAPTURED = "not_captured"      # fact not found anywhere
WRONG_VALUE = "wrong_value"        # right list/entry, a field is absent/null/wrong


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number(int)"
    if isinstance(value, float):
        return "number(float)"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


# ------------------------------------------------------------------ fields

def check_field(entry: dict, field: str, spec: dict) -> dict:
    """Checks one field of one entry. Never collapses the outcome to a
    boolean: `status` is one of ok | field_absent | null | wrong_value |
    wrong_type, and the actual value and its type are always returned."""
    present = field in entry
    actual = entry.get(field)
    res = {
        "field": field, "expected": spec, "present": present, "actual": actual,
        "actual_type": type_name(actual) if present else "absent",
        "status": "ok", "note": None,
    }

    def missing_status() -> str:
        return "null" if present else "field_absent"

    if "is_null" in spec:
        if spec["is_null"] and actual is not None:
            res.update(status="wrong_value", note="expected null/absent")
            return res
        if not spec["is_null"] and actual is None:
            res["status"] = missing_status()
            return res

    if "equals" in spec:
        expected = spec["equals"]
        if actual is None:
            res["status"] = missing_status()
            return res
        if isinstance(actual, bool) or actual != expected:
            if isinstance(actual, str) and isinstance(expected, (int, float)):
                m = _NUMERIC_STRING.match(actual)
                if m and float(m.group(1)) == float(expected):
                    res.update(status="wrong_type",
                               note=f"value {expected} is right but was returned as a string {actual!r}")
                    return res
            res["status"] = "wrong_value"
            return res

    if "contains_any" in spec:
        if actual is None:
            res["status"] = missing_status()
            return res
        lowered = str(actual).lower()
        if not any(str(t).lower() in lowered for t in spec["contains_any"]):
            res["status"] = "wrong_value"
            return res

    return res


def score_entry(entry: dict, constraints: dict) -> dict:
    fields = [check_field(entry, f, spec) for f, spec in constraints.items()]
    ok = sum(1 for f in fields if f["status"] == "ok")
    return {"fields": fields, "ok_count": ok, "all_ok": ok == len(fields)}


# --------------------------------------------------------- "found elsewhere"

def _value_token_groups(constraints: dict) -> list[list[str]]:
    """Positive value-bearing constraints as groups of alternatives; an
    entry 'contains the fact' if it holds one token from EVERY group."""
    groups: list[list[str]] = []
    for spec in constraints.values():
        if "equals" in spec:
            groups.append([str(spec["equals"])])
        if "contains_any" in spec:
            groups.append([str(t) for t in spec["contains_any"]])
    return groups


def _has_token(text: str, token: str) -> bool:
    token = token.lower()
    if token.isdigit():
        return re.search(rf"(?<!\d){re.escape(token)}(?!\d)", text) is not None
    return token in text


def _find_elsewhere(structured: dict, exclude: set, groups: list[list[str]]) -> list[dict]:
    if not groups:
        return []
    hits = []
    for key in ALL_LIST_KEYS:
        if key in exclude:
            continue
        for i, entry in enumerate(structured.get(key) or []):
            text = (json.dumps(entry, ensure_ascii=False) if isinstance(entry, (dict, list))
                    else str(entry)).lower()
            if all(any(_has_token(text, t) for t in grp) for grp in groups):
                hits.append({"list": key, "index": i, "entry": entry})
    return hits


# ------------------------------------------------------------------- leaves

def _constraints_of(exp: dict) -> dict:
    return {k: v for k, v in exp.items() if k not in _RESERVED}


def _eval_entry_leaf(structured: dict, exp: dict, exclude: frozenset = frozenset()) -> dict:
    list_key = exp["list"]
    constraints = _constraints_of(exp)
    entries = structured.get(list_key) or []
    scored = [(i, e, score_entry(e, constraints))
              for i, e in enumerate(entries) if isinstance(e, dict)]
    res: dict = {"kind": "entry", "list": list_key, "expected": constraints,
                 "list_size": len(entries), "passed": False, "candidate": None,
                 "found_elsewhere": [], "failure_kind": None, "failed_fields": [],
                 "closeness": 0}
    for i, e, s in scored:
        if s["all_ok"]:
            res.update(passed=True, candidate={"index": i, "entry": e, **s}, closeness=s["ok_count"])
            return res

    best = max(scored, key=lambda t: t[2]["ok_count"], default=None)
    if best is not None:
        i, e, s = best
        res["candidate"] = {"index": i, "entry": e, **s}
        res["closeness"] = s["ok_count"]
        res["failed_fields"] = [f for f in s["fields"] if f["status"] != "ok"]

    res["found_elsewhere"] = _find_elsewhere(structured, {list_key} | set(exclude),
                                               _value_token_groups(constraints))
    failed = res["failed_fields"]
    if best is not None and failed and all(f["status"] == "wrong_type" for f in failed):
        res["failure_kind"] = FORMAT_ONLY
    elif res["found_elsewhere"] and (best is None or best[2]["ok_count"] == 0):
        res["failure_kind"] = MISROUTED
    elif best is not None:
        res["failure_kind"] = WRONG_VALUE
    elif res["found_elsewhere"]:
        res["failure_kind"] = MISROUTED
    else:
        res["failure_kind"] = NOT_CAPTURED
    return res


def _eval_free_text_leaf(structured: dict, exp: dict, exclude: frozenset = frozenset()) -> dict:
    list_key = exp["list"]
    terms = [str(t) for t in exp.get("text_contains_any", [])]
    entries = [str(e) for e in (structured.get(list_key) or [])]
    res: dict = {"kind": "free_text", "list": list_key, "expected": {"text_contains_any": terms},
                 "list_size": len(entries), "passed": False, "candidate": None,
                 "found_elsewhere": [], "failure_kind": None, "failed_fields": [], "closeness": 0}
    for i, text in enumerate(entries):
        if not terms or any(t.lower() in text.lower() for t in terms):
            res.update(passed=True, candidate={"index": i, "entry": text}, closeness=1)
            return res
    res["found_elsewhere"] = _find_elsewhere(structured, {list_key} | set(exclude),
                                               [terms] if terms else [])
    if entries:
        res["failure_kind"] = WRONG_VALUE
        res["candidate"] = {"index": 0, "entry": entries[0]}
    elif res["found_elsewhere"]:
        res["failure_kind"] = MISROUTED
    else:
        res["failure_kind"] = NOT_CAPTURED
    return res


def _eval_all_entries_leaf(structured: dict, exp: dict) -> dict:
    list_key = exp["list"]
    spec = exp["all_entries"]
    entries = structured.get(list_key) or []
    res: dict = {"kind": "all_entries", "list": list_key, "expected": spec,
                 "list_size": len(entries), "passed": True, "candidate": None,
                 "found_elsewhere": [], "failure_kind": None, "failed_fields": [], "closeness": 1,
                 "violations": []}
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        s = score_entry(e, spec)
        if not s["all_ok"]:
            res["violations"].append({"index": i, "entry": e,
                                      "fields": [f for f in s["fields"] if f["status"] != "ok"]})
    if res["violations"]:
        res.update(passed=False, failure_kind=WRONG_VALUE, closeness=0,
                   failed_fields=[f for v in res["violations"] for f in v["fields"]])
    return res


def evaluate_expectation(structured: dict, exp: dict, exclude: frozenset = frozenset()) -> dict:
    """`exclude` lists are other ACCEPTABLE alternatives: a fact sitting in one
    of them is not a 'misroute' (it just failed a different constraint)."""
    if "any_of" in exp:
        sibling_lists = frozenset(a["list"] for a in exp["any_of"] if "list" in a)
        alts = [evaluate_expectation(structured, a, frozenset(exclude) | sibling_lists)
                for a in exp["any_of"]]
        matched = next((i for i, a in enumerate(alts) if a["passed"]), None)
        rep = matched if matched is not None else max(
            range(len(alts)), key=lambda i: alts[i].get("closeness", 0))
        rep_alt = alts[rep]
        return {"kind": "any_of", "expectation": exp, "passed": matched is not None,
                "alternatives": alts, "matched_alternative": matched, "representative": rep,
                "failure_kind": None if matched is not None else _any_of_kind(alts, rep),
                "failed_fields": [] if matched is not None else rep_alt.get("failed_fields", []),
                "closeness": rep_alt.get("closeness", 0)}
    if "all_entries" in exp:
        res = _eval_all_entries_leaf(structured, exp)
    elif "text_contains_any" in exp:
        res = _eval_free_text_leaf(structured, exp, frozenset(exclude))
    else:
        res = _eval_entry_leaf(structured, exp, frozenset(exclude))
    res["expectation"] = exp
    return res


def _any_of_kind(alts: list[dict], representative: int) -> str:
    """A format-only near miss in any alternative is reported as such;
    otherwise the closest alternative decides the kind."""
    if any(a.get("failure_kind") == FORMAT_ONLY for a in alts):
        return FORMAT_ONLY
    return alts[representative]["failure_kind"] or NOT_CAPTURED


def evaluate_case(structured: dict, expect: list[dict]) -> dict:
    results = [evaluate_expectation(structured, e) for e in expect]
    return {"passed": all(r["passed"] for r in results), "results": results}


# ---------------------------------------------------------------- reporting

def representative_leaf(result: dict) -> dict:
    """The leaf to describe for a failed result (for any_of: the closest alternative)."""
    if result["kind"] == "any_of":
        return result["alternatives"][result["representative"]]
    return result


def failure_flags(eval_result: dict) -> set[str]:
    """Which kinds of problem a failed case shows. Used only for the
    summary counts; never affects pass/fail."""
    flags: set[str] = set()
    for r in eval_result["results"]:
        if r["passed"]:
            continue
        kind = r["failure_kind"]
        if kind == FORMAT_ONLY:
            flags.add("format_only")
        elif kind == MISROUTED:
            flags.add("classification")
        elif kind == NOT_CAPTURED:
            flags.add("not_captured")
        else:
            for f in r["failed_fields"]:
                name = f["field"]
                if name in QUANTITY_FIELDS:
                    flags.add("quantity")
                elif name in ATTRIBUTION_FIELDS:
                    flags.add("attribution")
                elif name in TEMPORAL_FIELDS:
                    flags.add("temporal")
                else:
                    flags.add("content")
            if not r["failed_fields"]:
                flags.add("content")
    return flags


def describe_expectation(exp: dict) -> str:
    if "any_of" in exp:
        return "ANY OF: " + "  |  ".join(describe_expectation(a) for a in exp["any_of"])
    if "all_entries" in exp:
        specs = "; ".join(_describe_spec(f, s) for f, s in exp["all_entries"].items())
        return f"{exp['list']}: EVERY entry must have {specs} (no entry at all is fine)"
    if "text_contains_any" in exp:
        return f"{exp['list']}: some entry mentions any of {exp['text_contains_any']}"
    specs = "; ".join(_describe_spec(f, s) for f, s in _constraints_of(exp).items())
    return f"{exp['list']}: {specs}"


def _describe_spec(field: str, spec: dict) -> str:
    parts = []
    if "equals" in spec:
        parts.append(f"equals {spec['equals']!r}")
    if "contains_any" in spec:
        parts.append(f"contains any of {spec['contains_any']}")
    if "is_null" in spec:
        parts.append("is null/absent" if spec["is_null"] else "is present")
    return f"{field} " + " and ".join(parts)


_STATUS_LABEL = {"ok": "OK", "field_absent": "ABSENT", "null": "NULL",
                 "wrong_value": "WRONG VALUE", "wrong_type": "WRONG TYPE"}


def describe_failure(result: dict) -> list[str]:
    """Human-readable lines explaining one failed expectation."""
    lines: list[str] = []
    leaf = representative_leaf(result)
    if result["kind"] == "any_of":
        lines.append(f"    none of {len(result['alternatives'])} acceptable alternatives matched; "
                     f"closest was alternative #{result['representative'] + 1}: "
                     f"{describe_expectation(result['alternatives'][result['representative']]['expectation'])}")
    lines.append(f"    failure kind: {leaf['failure_kind']}")
    if leaf["kind"] == "entry":
        lines.append(f"    entries in `{leaf['list']}`: {leaf['list_size']}")
        cand = leaf["candidate"]
        if cand is None:
            lines.append(f"    (no entry to compare in `{leaf['list']}`)")
        else:
            lines.append(f"    closest entry: {leaf['list']}[{cand['index']}]")
            for f in cand["fields"]:
                actual = json.dumps(f["actual"], ensure_ascii=False) if f["present"] else "<field absent>"
                lines.append(f"      {f['field']:<14} expected {_describe_spec('', f['expected']).strip():<40} "
                             f"actual {actual} ({f['actual_type']}) -> {_STATUS_LABEL[f['status']]}"
                             + (f"  [{f['note']}]" if f["note"] else ""))
    elif leaf["kind"] == "all_entries":
        for v in leaf["violations"]:
            lines.append(f"    {leaf['list']}[{v['index']}] violates: "
                         + "; ".join(f"{f['field']} actual {json.dumps(f['actual'], ensure_ascii=False)} "
                                     f"({f['actual_type']})" for f in v["fields"]))
    elif leaf["kind"] == "free_text":
        lines.append(f"    entries in `{leaf['list']}`: {leaf['list_size']}")
    for hit in leaf.get("found_elsewhere", []):
        lines.append(f"    fact appears in another list: {hit['list']}[{hit['index']}] = "
                     f"{json.dumps(hit['entry'], ensure_ascii=False)}")
    return lines
