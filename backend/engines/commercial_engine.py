"""Commercial Foundation Engine — Engine 7 (CF-01).

The financial operating system for a construction project: Contract,
Milestone, Payment Request, Payment, Variation, and Budget as
first-class, state-machine-governed business objects — replacing the
lightweight commercial_reference snapshot (memory_engine) that
previously existed only to support Reference Portfolio summaries.

Design, matching every other Atlas engine's established conventions:
- Two collections per audit-relevant object class: the entity's own
  read-model collection, plus commercial_events — a single, unified,
  append-only ledger (the same CQRS shape Operations Engine's own
  operational_events already proved at scale), which the ledger is
  always authoritative over.
- Nothing here depends on UI. Every derived value (current contract
  value, outstanding payments, forecast, cash flow, milestone
  completion) is a deterministic calculation over stored fields —
  never manually entered, never computed twice in two different
  places.
- State transitions live only here. Routes translate HTTP <-> engine;
  they never set a status field directly (Atlas Engineering Standards
  v1, §5's own absolute rule).
- A Variation reaching `approved` is the one place in this engine with
  real, automatic side effects: it updates the Contract's derived
  current value, is recorded as a commercial event, and (via the
  Client Impact Engine below) has its cost/schedule/payment/forecast
  impact calculated once, deterministically, for every consumer to
  reuse — never recalculated ad hoc by a route or a frontend.

Reconciliation with the frozen Commercial Foundation Engine
specification (memory/COMMERCIAL_FOUNDATION_ENGINE.md): that
specification treated Milestone as derived (a reference to a Workflow
stage, never stored) and folded "Payment Request" into a generalized
Invoice entity. This sprint's brief defines Milestone with its own
genuine billing lifecycle (Payment Requested / Paid / Closed states no
Workflow Activity has any business owning) and asks for Payment
Request as the billing document directly. Both are adopted here as
real, superseding refinements — Milestone's richer lifecycle is a
legitimate reason for it to be a first-class entity the original
specification's narrower "billing trigger" framing didn't anticipate,
and Payment Request is functionally the same object the frozen spec
called Invoice, under this sprint's own naming. This is stated
explicitly, once, here — not silently reversed without explanation.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional
from core.db import db
from engines import memory_engine

# ---------------------------------------------------------------------------
# Helpers — matching every other engine's own established convention
# exactly (operations_engine._now/_iso/_new_id/_insert).
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4()}"


async def _insert(collection, doc: dict) -> dict:
    await collection.insert_one({**doc})
    return doc


class CommercialError(ValueError):
    """Base class for every commercial-engine domain error — matching
    workflow_engine's own WorkflowError precedent, so routes can catch
    one exception type and translate it to a 400, consistently."""


class CommercialNotFoundError(CommercialError):
    pass


async def assert_project_visible(project_id: str, user: dict) -> dict:
    """RC-01 fix — every project-scoped read in routes/commercial.py
    must call this before returning data. Out-of-scope projects behave
    as if they do not exist (404, not 403), matching the exact same
    convention workflow_engine._assert_project_visible and
    reasoning_engine._assert_project_visible already establish. Public
    (no leading underscore) specifically so routes/commercial.py can
    call it directly without touching a private function — the same
    architecture boundary the VV-01 sprint's own guard test enforces
    platform-wide: a route may call a public engine function, never an
    engine's private internals."""
    project = await memory_engine.get_project(project_id)
    if not project:
        raise CommercialNotFoundError(f"Project '{project_id}' not found")
    if memory_engine._is_project_scoped(user):
        if project_id not in (user.get("assigned_project_ids") or []):
            raise CommercialNotFoundError(f"Project '{project_id}' not found")
    return project


# ---------------------------------------------------------------------------
# Commercial Event ledger — the single, unified, append-only feed every
# other commercial mutation writes to. Reused directly by
# timeline_engine.for_project_commercial() below; never a second,
# independently-maintained event log.
# ---------------------------------------------------------------------------

async def append_commercial_event(*, project_id: str, kind: str, actor: dict,
                                   entity_type: str, entity_id: str,
                                   payload: Optional[dict] = None) -> dict:
    doc = {
        "id": _new_id("ce_"),
        "project_id": project_id,
        "kind": kind,  # always past tense — Atlas Engineering Standards v1, §6
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor_user_id": actor["id"],
        "actor_user_name": actor["name"],
        "payload": payload or {},
        "created_at": _iso(_now()),
    }
    return await _insert(db.commercial_events, doc)


async def list_commercial_events(project_id: str, limit: int = 200) -> list[dict]:
    return (await db.commercial_events.find({"project_id": project_id}, {"_id": 0})
            .sort("created_at", -1).to_list(limit))


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

CONTRACT_STATUSES = ("draft", "review", "approved", "active", "completed", "closed")
CONTRACT_TRANSITIONS = {
    "draft": {"review"},
    "review": {"draft", "approved"},
    "approved": {"active"},
    "active": {"completed"},
    "completed": {"closed"},
    "closed": set(),
}


async def create_contract(*, actor: dict, project_id: str, client_id: Optional[str],
                          original_contract_value: float, contract_date: str,
                          duration_days: int, retention_percent: float = 5.0,
                          advance_percent: float = 10.0, gst_percent: float = 18.0) -> dict:
    existing = await db.contracts.find_one({"project_id": project_id}, {"_id": 0})
    if existing:
        raise CommercialError(f"Project '{project_id}' already has a Contract.")
    now = _iso(_now())
    doc = {
        "id": _new_id("ctr_"),
        "project_id": project_id,
        "client_id": client_id,
        "original_contract_value": original_contract_value,
        "contract_date": contract_date,
        "duration_days": duration_days,
        "retention_percent": retention_percent,
        "advance_percent": advance_percent,
        "gst_percent": gst_percent,
        "status": "draft",
        "created_at": now,
        "updated_at": now,
    }
    await _insert(db.contracts, doc)
    await append_commercial_event(project_id=project_id, kind="contract_created", actor=actor,
                                  entity_type="contract", entity_id=doc["id"])
    return await get_contract(project_id)


async def update_contract(project_id: str, *, actor: dict,
                          duration_days: Optional[int] = None,
                          retention_percent: Optional[float] = None,
                          advance_percent: Optional[float] = None,
                          gst_percent: Optional[float] = None) -> dict:
    """CP-01 — the smallest possible extension of the Contract lifecycle:
    correcting a term before the contract is active. Deliberately does
    NOT touch original_contract_value (that only ever changes through
    approved Variations, per Contract's own existing, correct design —
    preserved exactly, not reopened here) and is only permitted while
    status is still "draft", so nothing already reviewed or approved
    can silently change underneath anyone. Full contract-revision
    versioning (CO-01 §2, Phase 2) remains a later package's scope —
    this reuses the existing commercial_events ledger for its own
    audit trail rather than introducing a new one."""
    contract = await db.contracts.find_one({"project_id": project_id}, {"_id": 0})
    if not contract:
        raise CommercialNotFoundError(f"No Contract for project '{project_id}'.")
    if contract["status"] != "draft":
        raise CommercialError(
            f"Contract terms can only be edited while status is 'draft' (currently '{contract['status']}').")

    updates: dict = {}
    changes: dict = {}
    for field, value in (
        ("duration_days", duration_days), ("retention_percent", retention_percent),
        ("advance_percent", advance_percent), ("gst_percent", gst_percent),
    ):
        if value is not None and value != contract.get(field):
            updates[field] = value
            changes[field] = {"from": contract.get(field), "to": value}
    if not updates:
        return await get_contract(project_id)

    updates["updated_at"] = _iso(_now())
    await db.contracts.update_one({"id": contract["id"]}, {"$set": updates})
    await append_commercial_event(project_id=project_id, kind="contract_updated", actor=actor,
                                  entity_type="contract", entity_id=contract["id"],
                                  payload={"changes": changes})
    return await get_contract(project_id)


async def get_contract(project_id: str) -> Optional[dict]:
    """Returns the Contract enriched with its derived
    current_contract_value — original + every APPROVED variation's
    difference, computed fresh on every read, never manually edited
    and never stored as a second, potentially-stale field."""
    contract = await db.contracts.find_one({"project_id": project_id}, {"_id": 0})
    if not contract:
        return None
    variations = await list_variations(project_id)
    approved_delta = sum(
        (v.get("approved_cost") or 0) - (v.get("original_cost") or 0)
        for v in variations if v["status"] == "approved"
    )
    contract["current_contract_value"] = contract["original_contract_value"] + approved_delta
    contract["approved_variations_total"] = approved_delta
    return contract


async def transition_contract_status(project_id: str, to_status: str, *, actor: dict) -> dict:
    contract = await db.contracts.find_one({"project_id": project_id}, {"_id": 0})
    if not contract:
        raise CommercialNotFoundError(f"No Contract for project '{project_id}'.")
    cur = contract["status"]
    if to_status not in CONTRACT_TRANSITIONS.get(cur, set()):
        raise CommercialError(f"Illegal Contract transition: '{cur}' -> '{to_status}'.")
    now = _iso(_now())
    await db.contracts.update_one({"id": contract["id"]}, {"$set": {"status": to_status, "updated_at": now}})
    await append_commercial_event(project_id=project_id, kind="contract_status_changed", actor=actor,
                                  entity_type="contract", entity_id=contract["id"],
                                  payload={"from": cur, "to": to_status})
    return await get_contract(project_id)


# ---------------------------------------------------------------------------
# Milestone
# ---------------------------------------------------------------------------

MILESTONE_STATUSES = ("pending", "ready", "achieved", "payment_requested", "paid", "closed")
MILESTONE_TRANSITIONS = {
    "pending": {"ready"},
    "ready": {"achieved", "pending"},
    "achieved": {"payment_requested"},
    "payment_requested": {"paid"},
    "paid": {"closed"},
    "closed": set(),
}


async def create_milestone(*, actor: dict, project_id: str, name: str, sequence: int,
                           planned_percent: float, trigger: str,
                           planned_date: Optional[str] = None,
                           contract_value: Optional[float] = None) -> dict:
    """contract_value, if not given explicitly, is derived once at
    creation from planned_percent x the Contract's current value at
    that moment — a deliberate one-time snapshot (a milestone's
    billing value shouldn't silently drift every time a later,
    unrelated variation changes the contract total), not a live
    computation like Contract's own current_contract_value is."""
    if contract_value is None:
        contract = await get_contract(project_id)
        if not contract:
            raise CommercialNotFoundError(f"No Contract for project '{project_id}' — cannot derive milestone value.")
        contract_value = round(contract["current_contract_value"] * planned_percent / 100, 2)
    now = _iso(_now())
    doc = {
        "id": _new_id("ms_"),
        "project_id": project_id,
        "name": name,
        "sequence": sequence,
        "planned_percent": planned_percent,
        "contract_value": contract_value,
        "trigger": trigger,
        "planned_date": planned_date,
        "forecast_date": planned_date,
        "actual_date": None,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    await _insert(db.milestones, doc)
    await append_commercial_event(project_id=project_id, kind="milestone_created", actor=actor,
                                  entity_type="milestone", entity_id=doc["id"], payload={"name": name})
    return doc


async def list_milestones(project_id: str) -> list[dict]:
    return (await db.milestones.find({"project_id": project_id}, {"_id": 0})
            .sort("sequence", 1).to_list(500))


async def get_milestone(milestone_id: str) -> Optional[dict]:
    return await db.milestones.find_one({"id": milestone_id}, {"_id": 0})


async def update_milestone(milestone_id: str, *, actor: dict,
                           name: Optional[str] = None,
                           sequence: Optional[int] = None,
                           planned_percent: Optional[float] = None,
                           trigger: Optional[str] = None,
                           planned_date: Optional[str] = None) -> dict:
    """CP-01 — per CO-01's own Product Decisions Register: "full edit
    while pending, append-only notes/comments after." A milestone's
    financial percentage is client-visible once work is underway
    against it; editing it silently after that point is exactly what
    CO-01's own First Principle rules out. contract_value is
    deliberately NOT recomputed here even when planned_percent
    changes — it stays the same one-time-derived snapshot create_
    milestone already establishes, for the same reason create_
    milestone itself derives it once rather than live."""
    milestone = await get_milestone(milestone_id)
    if not milestone:
        raise CommercialNotFoundError(f"Milestone '{milestone_id}' not found.")
    if milestone["status"] != "pending":
        raise CommercialError(
            f"Milestone terms can only be edited while status is 'pending' (currently '{milestone['status']}').")

    updates: dict = {}
    changes: dict = {}
    for field, value in (
        ("name", name), ("sequence", sequence), ("planned_percent", planned_percent),
        ("trigger", trigger), ("planned_date", planned_date),
    ):
        if value is not None and value != milestone.get(field):
            updates[field] = value
            changes[field] = {"from": milestone.get(field), "to": value}
    if not updates:
        return milestone

    # planned_date also drives forecast_date at creation; keep them in
    # sync on edit too, unless forecast_date has already been
    # independently set by a later re-forecast (a real, different
    # workflow this edit must not clobber).
    if planned_date is not None and milestone.get("forecast_date") == milestone.get("planned_date"):
        updates["forecast_date"] = planned_date

    updates["updated_at"] = _iso(_now())
    await db.milestones.update_one({"id": milestone["id"]}, {"$set": updates})
    await append_commercial_event(project_id=milestone["project_id"], kind="milestone_updated", actor=actor,
                                  entity_type="milestone", entity_id=milestone["id"],
                                  payload={"changes": changes})
    return await get_milestone(milestone_id)


async def transition_milestone_status(milestone_id: str, to_status: str, *, actor: dict,
                                      forecast_date: Optional[str] = None) -> dict:
    ms = await get_milestone(milestone_id)
    if not ms:
        raise CommercialNotFoundError(f"Milestone '{milestone_id}' not found.")
    await assert_project_visible(ms["project_id"], actor)
    cur = ms["status"]
    if to_status not in MILESTONE_TRANSITIONS.get(cur, set()):
        raise CommercialError(f"Illegal Milestone transition: '{cur}' -> '{to_status}'.")
    now = _now()
    upd: dict = {"status": to_status, "updated_at": _iso(now)}
    if to_status == "achieved":
        upd["actual_date"] = _iso(now)
    if forecast_date is not None:
        upd["forecast_date"] = forecast_date
    await db.milestones.update_one({"id": milestone_id}, {"$set": upd})
    await append_commercial_event(project_id=ms["project_id"], kind="milestone_status_changed", actor=actor,
                                  entity_type="milestone", entity_id=milestone_id,
                                  payload={"from": cur, "to": to_status})
    if to_status == "closed":
        await append_commercial_event(project_id=ms["project_id"], kind="milestone_closed", actor=actor,
                                      entity_type="milestone", entity_id=milestone_id)
    return await get_milestone(milestone_id)


def milestone_completion_percent(milestones: list[dict]) -> float:
    """Derived, never manually entered — the sum of planned_percent
    across every milestone that has genuinely been reached (achieved
    or further along its own lifecycle), not just "created"."""
    reached = {"achieved", "payment_requested", "paid", "closed"}
    return round(sum(m["planned_percent"] for m in milestones if m["status"] in reached), 2)


# ---------------------------------------------------------------------------
# Payment Request (this sprint's naming for the billing document — see
# module docstring's reconciliation note)
# ---------------------------------------------------------------------------

PAYMENT_REQUEST_STATUSES = ("draft", "raised", "sent", "partially_paid", "paid", "overdue", "cancelled")
PAYMENT_REQUEST_TRANSITIONS = {
    "draft": {"raised", "cancelled"},
    "raised": {"sent", "cancelled"},
    "sent": {"partially_paid", "paid", "overdue", "cancelled"},
    "partially_paid": {"paid", "overdue"},
    "overdue": {"partially_paid", "paid"},
    "paid": set(),
    "cancelled": set(),
}


async def create_payment_request(*, actor: dict, project_id: str, milestone_id: str,
                                 amount: float, raised_date: str, due_date: str,
                                 notes: str = "") -> dict:
    ms = await get_milestone(milestone_id)
    if not ms:
        raise CommercialNotFoundError(f"Milestone '{milestone_id}' not found.")
    if ms["status"] != "achieved":
        raise CommercialError(
            f"Milestone '{ms['name']}' must be 'achieved' before a Payment Request can be raised against it "
            f"(currently '{ms['status']}').")
    count = await db.payment_requests.count_documents({"project_id": project_id})
    number = f"PR-{count + 1:03d}"
    now = _iso(_now())
    doc = {
        "id": _new_id("pr_"),
        "project_id": project_id,
        "number": number,
        "milestone_id": milestone_id,
        "amount": amount,
        "raised_date": raised_date,
        "due_date": due_date,
        "status": "draft",
        "notes": notes,
        "created_at": now,
        "updated_at": now,
    }
    await _insert(db.payment_requests, doc)
    await transition_milestone_status(milestone_id, "payment_requested", actor=actor)
    await append_commercial_event(project_id=project_id, kind="payment_request_raised", actor=actor,
                                  entity_type="payment_request", entity_id=doc["id"],
                                  payload={"number": number, "amount": amount})
    return doc


async def get_payment_request(payment_request_id: str) -> Optional[dict]:
    return await db.payment_requests.find_one({"id": payment_request_id}, {"_id": 0})


async def list_payment_requests(project_id: str) -> list[dict]:
    return (await db.payment_requests.find({"project_id": project_id}, {"_id": 0})
            .sort("created_at", -1).to_list(500))


async def transition_payment_request_status(payment_request_id: str, to_status: str, *, actor: dict) -> dict:
    pr = await get_payment_request(payment_request_id)
    if not pr:
        raise CommercialNotFoundError(f"Payment Request '{payment_request_id}' not found.")
    await assert_project_visible(pr["project_id"], actor)
    cur = pr["status"]
    if to_status not in PAYMENT_REQUEST_TRANSITIONS.get(cur, set()):
        raise CommercialError(f"Illegal Payment Request transition: '{cur}' -> '{to_status}'.")
    await db.payment_requests.update_one({"id": payment_request_id},
                                         {"$set": {"status": to_status, "updated_at": _iso(_now())}})
    await append_commercial_event(project_id=pr["project_id"], kind="payment_request_status_changed", actor=actor,
                                  entity_type="payment_request", entity_id=payment_request_id,
                                  payload={"from": cur, "to": to_status})
    return await get_payment_request(payment_request_id)


# ---------------------------------------------------------------------------
# Payment — actual money received against a Payment Request. Supports
# partial and multiple payments, plus adjustment entries (a signed
# correction, e.g. a bank-fee deduction reconciled after the fact).
# ---------------------------------------------------------------------------

async def record_payment(*, actor: dict, payment_request_id: str, amount: float,
                         date: str, method: str, reference: str = "",
                         is_adjustment: bool = False) -> dict:
    pr = await get_payment_request(payment_request_id)
    if not pr:
        raise CommercialNotFoundError(f"Payment Request '{payment_request_id}' not found.")
    await assert_project_visible(pr["project_id"], actor)
    if pr["status"] == "cancelled":
        raise CommercialError("Cannot record a payment against a cancelled Payment Request.")
    now = _iso(_now())
    doc = {
        "id": _new_id("pay_"),
        "payment_request_id": payment_request_id,
        "project_id": pr["project_id"],
        "amount": amount,
        "date": date,
        "method": method,
        "reference": reference,
        "status": "adjustment" if is_adjustment else "recorded",
        "created_at": now,
    }
    await _insert(db.payments, doc)
    await append_commercial_event(project_id=pr["project_id"], kind="payment_received", actor=actor,
                                  entity_type="payment", entity_id=doc["id"],
                                  payload={"payment_request_number": pr["number"], "amount": amount})

    all_payments = await list_payments_for_request(payment_request_id)
    total_received = sum(p["amount"] for p in all_payments)
    new_pr_status = "paid" if total_received >= pr["amount"] else "partially_paid" if total_received > 0 else pr["status"]
    if new_pr_status != pr["status"] and new_pr_status in PAYMENT_REQUEST_TRANSITIONS.get(pr["status"], set()):
        await transition_payment_request_status(payment_request_id, new_pr_status, actor=actor)
        if new_pr_status == "paid":
            ms = await get_milestone(pr["milestone_id"])
            if ms and ms["status"] == "payment_requested":
                await transition_milestone_status(pr["milestone_id"], "paid", actor=actor)
    return doc


async def list_payments_for_request(payment_request_id: str) -> list[dict]:
    return (await db.payments.find({"payment_request_id": payment_request_id}, {"_id": 0})
            .sort("date", 1).to_list(200))


async def list_payments(project_id: str) -> list[dict]:
    return (await db.payments.find({"project_id": project_id}, {"_id": 0})
            .sort("date", -1).to_list(500))


def outstanding_payments(payment_requests: list[dict], payments: list[dict]) -> dict:
    """Deterministic — raised vs received, across every non-cancelled
    Payment Request. Never a stored field."""
    raised = sum(pr["amount"] for pr in payment_requests if pr["status"] != "cancelled")
    received = sum(p["amount"] for p in payments)
    return {"raised": raised, "received": received, "outstanding": round(raised - received, 2)}


# ---------------------------------------------------------------------------
# Variation
# ---------------------------------------------------------------------------

VARIATION_STATUSES = ("draft", "submitted", "client_review", "approved", "rejected", "implemented")
VARIATION_TRANSITIONS = {
    "draft": {"submitted"},
    "submitted": {"client_review", "draft"},
    "client_review": {"approved", "rejected"},
    "approved": {"implemented"},
    "rejected": set(),
    "implemented": set(),
}


async def create_variation(*, actor: dict, project_id: str, title: str, description: str,
                           original_cost: float, proposed_cost: float,
                           time_impact_days: int = 0,
                           linked_drawing_ids: Optional[list[str]] = None,
                           linked_photo_ids: Optional[list[str]] = None,
                           linked_quotation_ids: Optional[list[str]] = None) -> dict:
    now = _iso(_now())
    doc = {
        "id": _new_id("var_"),
        "project_id": project_id,
        "title": title,
        "description": description,
        "original_cost": original_cost,
        "proposed_cost": proposed_cost,
        "approved_cost": None,
        "time_impact_days": time_impact_days,
        "linked_drawing_ids": linked_drawing_ids or [],
        "linked_photo_ids": linked_photo_ids or [],
        "linked_quotation_ids": linked_quotation_ids or [],
        "raised_by_user_id": actor["id"],
        "raised_by_user_name": actor["name"],
        "approved_by_user_id": None,
        "approved_by_user_name": None,
        "status": "draft",
        "created_at": now,
        "updated_at": now,
        "decided_at": None,
    }
    await _insert(db.variations, doc)
    await append_commercial_event(project_id=project_id, kind="variation_created", actor=actor,
                                  entity_type="variation", entity_id=doc["id"], payload={"title": title})
    return doc


async def get_variation(variation_id: str) -> Optional[dict]:
    return await db.variations.find_one({"id": variation_id}, {"_id": 0})


async def list_variations(project_id: str) -> list[dict]:
    return (await db.variations.find({"project_id": project_id}, {"_id": 0})
            .sort("created_at", -1).to_list(500))


def calculate_variation_impact(variation: dict) -> dict:
    """The Client Impact Engine (CF-01) — every Variation's
    cost/schedule/payment/forecast impact, calculated once,
    deterministically, here — never recalculated inside a route or a
    frontend. Reused identically by the approval flow below and by any
    future consumer (Client Experience, Executive Dashboard) that
    needs to explain what a variation actually means.
    """
    cost = variation.get("approved_cost")
    if cost is None:
        cost = variation.get("proposed_cost", 0)
    cost_impact = cost - variation.get("original_cost", 0)
    return {
        "cost_impact": round(cost_impact, 2),
        "schedule_impact_days": variation.get("time_impact_days", 0),
        "payment_impact": round(cost_impact, 2) if variation["status"] == "approved" else 0,
        "forecast_impact": round(cost_impact, 2) if variation["status"] == "approved" else 0,
    }


async def decide_variation(variation_id: str, decision: str, *, actor: dict,
                           approved_cost: Optional[float] = None) -> dict:
    """Approval Integration (CF-01) — the one place in this engine with
    real, automatic side effects. Approving a Variation:
      1. transitions it to 'approved' (with the actor recorded),
      2. does NOT itself touch the Contract document — Contract's
         current_contract_value is already a live derived calculation
         (get_contract, above) that includes every approved variation
         automatically, so there is nothing to "update" separately;
         recomputing it as a stored field here would be exactly the
         duplicated-calculation Atlas's own principles forbid,
      3. records a commercial event (which Timeline Engine reads),
      4. returns the Client Impact Engine's calculated impact alongside
         the decided variation, so a single call gives a caller
         everything a "what does this mean" view needs.
    """
    if decision not in ("approved", "rejected"):
        raise CommercialError("decision must be 'approved' or 'rejected'.")
    variation = await get_variation(variation_id)
    if not variation:
        raise CommercialNotFoundError(f"Variation '{variation_id}' not found.")
    await assert_project_visible(variation["project_id"], actor)
    cur = variation["status"]
    if decision not in VARIATION_TRANSITIONS.get(cur, set()):
        raise CommercialError(f"Illegal Variation transition: '{cur}' -> '{decision}'.")

    now = _iso(_now())
    upd: dict = {
        "status": decision, "updated_at": now, "decided_at": now,
        "approved_by_user_id": actor["id"], "approved_by_user_name": actor["name"],
    }
    if decision == "approved":
        upd["approved_cost"] = approved_cost if approved_cost is not None else variation["proposed_cost"]
    await db.variations.update_one({"id": variation_id}, {"$set": upd})
    updated = await get_variation(variation_id)

    kind = "variation_approved" if decision == "approved" else "variation_rejected"
    await append_commercial_event(project_id=variation["project_id"], kind=kind, actor=actor,
                                  entity_type="variation", entity_id=variation_id,
                                  payload={"title": variation["title"], "decision": decision})

    impact = calculate_variation_impact(updated)
    return {**updated, "impact": impact}


async def submit_variation(variation_id: str, *, actor: dict) -> dict:
    variation = await get_variation(variation_id)
    if not variation:
        raise CommercialNotFoundError(f"Variation '{variation_id}' not found.")
    await assert_project_visible(variation["project_id"], actor)
    cur = variation["status"]
    if "submitted" not in VARIATION_TRANSITIONS.get(cur, set()):
        raise CommercialError(f"Illegal Variation transition: '{cur}' -> 'submitted'.")
    await db.variations.update_one({"id": variation_id}, {"$set": {"status": "submitted", "updated_at": _iso(_now())}})
    await append_commercial_event(project_id=variation["project_id"], kind="variation_submitted", actor=actor,
                                  entity_type="variation", entity_id=variation_id)
    return await get_variation(variation_id)


async def send_variation_to_client_review(variation_id: str, *, actor: dict) -> dict:
    variation = await get_variation(variation_id)
    if not variation:
        raise CommercialNotFoundError(f"Variation '{variation_id}' not found.")
    await assert_project_visible(variation["project_id"], actor)
    cur = variation["status"]
    if "client_review" not in VARIATION_TRANSITIONS.get(cur, set()):
        raise CommercialError(f"Illegal Variation transition: '{cur}' -> 'client_review'.")
    await db.variations.update_one({"id": variation_id}, {"$set": {"status": "client_review", "updated_at": _iso(_now())}})
    await append_commercial_event(project_id=variation["project_id"], kind="variation_sent_for_client_review",
                                  actor=actor, entity_type="variation", entity_id=variation_id)
    return await get_variation(variation_id)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

async def create_budget(*, actor: dict, project_id: str, original_budget: float) -> dict:
    existing = await db.budgets.find_one({"project_id": project_id}, {"_id": 0})
    if existing:
        raise CommercialError(f"Project '{project_id}' already has a Budget.")
    now = _iso(_now())
    doc = {
        "id": _new_id("bud_"),
        "project_id": project_id,
        "original_budget": original_budget,
        "current_budget": original_budget,
        "committed_cost": 0.0,
        "actual_cost": 0.0,
        "created_at": now,
        "updated_at": now,
    }
    await _insert(db.budgets, doc)
    await append_commercial_event(project_id=project_id, kind="budget_created", actor=actor,
                                  entity_type="budget", entity_id=doc["id"])
    return await get_budget(project_id)


async def get_budget(project_id: str) -> Optional[dict]:
    budget = await db.budgets.find_one({"project_id": project_id}, {"_id": 0})
    if not budget:
        return None
    forecast_cost = max(budget["actual_cost"], budget["committed_cost"])
    budget["forecast_cost"] = round(forecast_cost, 2)
    budget["variance"] = round(budget["current_budget"] - forecast_cost, 2)
    budget["remaining_budget"] = round(budget["current_budget"] - budget["actual_cost"], 2)
    return budget


async def revise_budget(project_id: str, new_current_budget: float, *, actor: dict, reason: str = "") -> dict:
    budget = await db.budgets.find_one({"project_id": project_id}, {"_id": 0})
    if not budget:
        raise CommercialNotFoundError(f"No Budget for project '{project_id}'.")
    await db.budgets.update_one({"id": budget["id"]},
                                {"$set": {"current_budget": new_current_budget, "updated_at": _iso(_now())}})
    await append_commercial_event(project_id=project_id, kind="budget_revised", actor=actor,
                                  entity_type="budget", entity_id=budget["id"],
                                  payload={"from": budget["current_budget"], "to": new_current_budget, "reason": reason})
    return await get_budget(project_id)


async def commit_cost(project_id: str, amount_delta: float, *, actor: dict, reason: str = "") -> dict:
    budget = await db.budgets.find_one({"project_id": project_id}, {"_id": 0})
    if not budget:
        raise CommercialNotFoundError(f"No Budget for project '{project_id}'.")
    new_committed = budget["committed_cost"] + amount_delta
    await db.budgets.update_one({"id": budget["id"]},
                                {"$set": {"committed_cost": new_committed, "updated_at": _iso(_now())}})
    await append_commercial_event(project_id=project_id, kind="cost_committed", actor=actor,
                                  entity_type="budget", entity_id=budget["id"],
                                  payload={"amount_delta": amount_delta, "reason": reason})
    return await get_budget(project_id)


async def record_actual_cost(project_id: str, amount_delta: float, *, actor: dict, reason: str = "") -> dict:
    budget = await db.budgets.find_one({"project_id": project_id}, {"_id": 0})
    if not budget:
        raise CommercialNotFoundError(f"No Budget for project '{project_id}'.")
    new_actual = budget["actual_cost"] + amount_delta
    await db.budgets.update_one({"id": budget["id"]},
                                {"$set": {"actual_cost": new_actual, "updated_at": _iso(_now())}})
    await append_commercial_event(project_id=project_id, kind="actual_cost_recorded", actor=actor,
                                  entity_type="budget", entity_id=budget["id"],
                                  payload={"amount_delta": amount_delta, "reason": reason})
    return await get_budget(project_id)


# ---------------------------------------------------------------------------
# Cash Flow — deterministic signal, not a CRE-style reasoning finding.
# ---------------------------------------------------------------------------

def cash_flow_signal(payment_requests: list[dict], payments: list[dict]) -> str:
    active_prs = [pr for pr in payment_requests if pr["status"] != "cancelled"]
    if not active_prs:
        return "healthy"
    raised = sum(pr["amount"] for pr in active_prs)
    received = sum(p["amount"] for p in payments)
    overdue_count = sum(1 for pr in active_prs if pr["status"] == "overdue")
    if overdue_count > 0:
        return "critical"
    if raised == 0:
        return "healthy"
    ratio = received / raised
    if ratio >= 0.7:
        return "healthy"
    if ratio >= 0.4:
        return "attention"
    return "critical"


def upcoming_payment(payment_requests: list[dict], payments: list[dict], milestones: list[dict]) -> Optional[dict]:
    """The next payment expected: earliest-due unpaid Payment Request,
    with its remaining balance (amount minus whatever's already been
    paid against it) and which milestone triggered it. Beta-02 —
    extracted here (moved, not duplicated) from what was previously
    only reasoning_engine.client_investment_summary's own inline
    calculation, so every caller of get_project_commercial_summary
    (Client Investment, the Commercial Workspace's Cash Flow section,
    Portfolio) reads the same one computation."""
    unpaid_prs = [pr for pr in payment_requests if pr["status"] not in ("paid", "cancelled")]
    if not unpaid_prs:
        return None
    next_pr = min(unpaid_prs, key=lambda pr: pr["due_date"])
    already_paid = sum(p["amount"] for p in payments if p["payment_request_id"] == next_pr["id"])
    milestone = next((m for m in milestones if m["id"] == next_pr["milestone_id"]), None)
    return {
        "amount": round(next_pr["amount"] - already_paid, 2),
        "due_date": next_pr["due_date"],
        "due_after": milestone["name"] if milestone else None,
        "payment_request_id": next_pr["id"],
    }


# ---------------------------------------------------------------------------
# Commercial Snapshot
# ---------------------------------------------------------------------------

async def take_commercial_snapshot(project_id: str, *, actor: dict, is_baseline: bool = False,
                                   baseline_reason: Optional[str] = None) -> dict:
    contract = await get_contract(project_id)
    budget = await get_budget(project_id)
    milestones = await list_milestones(project_id)
    payment_requests = await list_payment_requests(project_id)
    payments = await list_payments(project_id)
    now = _iso(_now())
    doc = {
        "id": _new_id("cs_"),
        "project_id": project_id,
        "contract": contract,
        "budget": budget,
        "milestone_completion_percent": milestone_completion_percent(milestones),
        "outstanding_payments": outstanding_payments(payment_requests, payments),
        "cash_flow_signal": cash_flow_signal(payment_requests, payments),
        "is_baseline": is_baseline,
        "baseline_reason": baseline_reason,
        "created_at": now,
    }
    await _insert(db.commercial_snapshots, doc)
    await append_commercial_event(project_id=project_id, kind="commercial_snapshot_taken", actor=actor,
                                  entity_type="commercial_snapshot", entity_id=doc["id"],
                                  payload={"is_baseline": is_baseline})
    return doc


async def list_commercial_snapshots(project_id: str, limit: int = 50) -> list[dict]:
    return (await db.commercial_snapshots.find({"project_id": project_id}, {"_id": 0})
            .sort("created_at", -1).to_list(limit))


# ---------------------------------------------------------------------------
# Project Commercial Summary — the single composed read every UI
# surface should call.
# ---------------------------------------------------------------------------

async def get_project_commercial_summary(project_id: str) -> Optional[dict]:
    contract = await get_contract(project_id)
    if not contract:
        return None
    budget = await get_budget(project_id)
    milestones = await list_milestones(project_id)
    payment_requests = await list_payment_requests(project_id)
    payments = await list_payments(project_id)
    variations = await list_variations(project_id)

    return {
        "project_id": project_id,
        "contract": contract,
        "budget": budget,
        "milestones": milestones,
        "milestone_completion_percent": milestone_completion_percent(milestones),
        "payment_requests": payment_requests,
        "payments": payments,
        "outstanding_payments": outstanding_payments(payment_requests, payments),
        "cash_flow_signal": cash_flow_signal(payment_requests, payments),
        "upcoming_payment": upcoming_payment(payment_requests, payments, milestones),
        "variations": variations,
        "approved_variations_total": contract.get("approved_variations_total", 0),
        "pending_variations_total": sum(
            v.get("proposed_cost", 0) - v.get("original_cost", 0)
            for v in variations if v["status"] in ("submitted", "client_review")),
    }
