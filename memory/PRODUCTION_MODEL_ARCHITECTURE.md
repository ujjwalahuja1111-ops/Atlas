# Construction Knowledge Base v2 — Production Model Architecture

**Status:** Implemented (Sprint 01 — first parametric activity: Wall Masonry)
**Audience:** this is the reference document for future Planning, CRE, Commercial Intelligence, and Scheduling work that consumes production models.

---

## Purpose

Today, an Activity template in the Knowledge Base stores a single static number — default_duration_days. That number is wrong for almost every real project: a "Wall Masonry" activity takes a genuinely different number of days on a 1000 sqft house than on a 3500 sqft villa, because the actual wall area differs, even though it's the same activity template, the same trade, the same checklist.

A Production Model replaces "duration is a fixed number" with "duration is derived from this project's actual parameters, run through a named, deterministic calculation." The same activity template now produces different, correct durations for different projects — without duplicating the template.

## Inputs

A production model declares its own inputs — a list of {key, label, category, unit, default_value?} objects. Three categories exist today (project, execution, material), matching the brief's Project/Execution/Material parameter groups, but category is purely descriptive — it groups parameters for display, and is never read by the calculation logic itself. This is deliberate: adding a fourth category, or a new parameter within an existing one, never requires touching the calculation code.

Two kinds of input values exist:
- **Template defaults** (default_value on the input declaration) — e.g. the Knowledge Base's default productivity (70 sqm/day). Editable by management via the same PATCH /knowledge-items/{id} endpoint every other activity field already uses.
- **Instance overrides** (stored per workflow activity, e.g. this project's actual wall area) — set via POST /workflow-activities/{id}/production-inputs.

An instance override always wins over a template default; a template default is used only when no override exists for that key.

## Outputs

A production model's calculation function returns a dict of named outputs. This sprint implements exactly two: duration_days and crew_recommendation, matching the brief's scope for the first parametric activity. The architecture supports (but does not yet implement) three more: labour_days, material_quantities, equipment_needs — a future calculation function can return any of these without any change to the storage shape, the route, or the fallback logic; they're just more keys in the same outputs dict.

## Architecture

```
Activity (Knowledge Item)
  |-- production_model: {
        calculation_method: "wall_area_productivity_v1",   # registry key
        inputs: [ {key, label, category, unit, default_value?}, ... ],
        outputs: ["duration_days", "crew_recommendation"],
      }

Workflow Activity (project-scoped instance)
  |-- production_model_inputs: {wall_area: 420, ...}        # this instance's overrides
  |-- production_model_result: {outputs, explanation,
  |                              resolved_inputs, calculated_at}
  `-- expected_duration_days (computed on every read)         # the field Planning/CRE actually consume
```

**calculation_method is a registry key, not a stored formula string.** A formula string would need a runtime expression evaluator — a real correctness and security surface, and much harder to unit-test than a named function. Instead, engines/knowledge_engine.py holds CALCULATION_REGISTRY: dict[str, Callable[[dict], dict]], a plain Python dict mapping a string key to a pure function. This is what "keep deterministic calculations separate from AI," "AI may recommend values but never calculate production logic," and "avoid black-box calculations" mean concretely in code: every registered function is source-controlled, independently unit-testable, versioned by its own name (_v1 suffix — a _v2 can be added later without touching _v1 or anything that still references it), and returns its own worked calculation for display.

**The calculation entrypoint is pure.** knowledge_engine.calculate_production_model(production_model, input_values) -> {resolved_inputs, outputs, explanation} has no I/O and no side effects — safe to call from a route, a test, or a future engine (Planning, CRE, Commercial Intelligence) without any of them needing to know about HTTP, the database, or workflow activities at all. It resolves each input, runs the registered function, and returns everything needed to both use the result and explain it.

**Instance data lives on the workflow activity, not a new collection.** production_model_inputs and production_model_result are two more fields on the existing workflow_activities document — additive, no new collection, no schema migration. workflow_engine.set_production_inputs() merges new override values into whatever was already stored, re-fetches the activity's current template (so a management edit to the default productivity is picked up immediately — see below), and re-runs the calculation.

## Extension Strategy

Three axes can grow without a redesign:

1. **New parameter types.** A production model's inputs list is just data — adding a new parameter (e.g. "Ceiling Area") to an existing or new activity means adding one object to that list, nothing else.
2. **New calculation methods.** A new activity gets its own function in CALCULATION_REGISTRY, addressed by its own key. Nothing about an existing activity's calculation is touched by adding a new one.
3. **New output types.** labour_days, material_quantities, equipment_needs all fit the existing outputs dict shape today; a calculation function simply returns more keys when someone implements the logic for them. resolve_expected_duration() only ever reads outputs["duration_days"], so adding more outputs never risks the duration calculation that's already working.

## Migration Strategy

**There is no migration.** Every existing Activity's production_model field is None by default — on every activity created before this feature existed, and on every new activity that doesn't opt in. workflow_engine.resolve_expected_duration() is the single place this is decided:

```python
def resolve_expected_duration(activity):
    result = activity.get("production_model_result")
    if result and result.get("outputs", {}).get("duration_days") is not None:
        return result["outputs"]["duration_days"]
    return activity.get("default_duration_days")   # unmodified, exactly as before
```

No existing template needs editing, no existing project needs recalculating, no existing workflow activity needs a data backfill. A template opts into parametric behavior only when someone deliberately adds a production_model to it.

## Example Calculation

Wall Masonry, a 3500 sqft villa, wall area 420 sqm:

```
production_model.inputs (template):
  wall_area     - no default (must be provided per project)
  crew_size     - default_value: 4
  productivity  - default_value: 17.5 sqm/day/worker

instance override: {"wall_area": 420}

resolved_inputs = {wall_area: 420, crew_size: 4, productivity: 17.5}
daily_output    = crew_size x productivity = 4 x 17.5 = 70 sqm/day
duration_days   = ceil(wall_area / daily_output) = ceil(420 / 70) = 6

result:
  outputs: {duration_days: 6, crew_recommendation: 4}
  explanation.duration_days: {
    formula: "wall_area / (crew_size x productivity)",
    values: {wall_area: 420, crew_size: 4, productivity: 17.5, daily_output: 70},
    result: 6
  }
```

The same template, on a 1000 sqft house with wall area 150 sqm and the same defaults, produces ceil(150 / 70) = 3 days — a different, correct duration from the identical activity template, which is the sprint's core demonstration.

Changing the template's default productivity to 30 sqm/day/worker (management edits it via PATCH /knowledge-items/{id}) and recalculating the villa activity (even with no change to its own wall_area override) immediately produces ceil(420 / 120) = 4 days — confirming "changing productivity should immediately affect derived duration."

## What Was Not Built This Sprint

- Only duration_days and crew_recommendation are implemented outputs; labour_days, material_quantities, equipment_needs are supported by the architecture (same dict shape) but have no calculation logic yet.
- crew_recommendation in this sprint is the crew size used in the calculation, not a crew size derived from a target duration — a genuine "recommend the crew size to hit this deadline" calculation is a natural, separate future addition.
- No frontend UI for entering production model inputs or viewing the explanation was built this sprint — the API is complete and tested; the UI touchpoint is a follow-up.
- No second calculation method exists yet to prove the registry pattern generalizes beyond Wall Masonry — that's the natural next validation once a second parametric activity is needed.
