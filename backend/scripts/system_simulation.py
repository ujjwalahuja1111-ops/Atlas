"""Atlas System Simulation Harness (RC1-HARDENING H5).

    cd backend
    python -m scripts.system_simulation

Runs the full, real operational chain a construction project actually
goes through — Project -> Contract -> Budget -> Milestone -> Reality
Capture -> Variation -> Approval -> Milestone Achieved -> Payment
Request -> Payment -> Timeline -> Continuous Memory -> Knowledge Graph
-> Workspace Project Pulse -> Relationship Explorer — through the real
HTTP API surface the frontend itself calls, exactly as every prior
package in this engagement has verified its own work. This script
exists so that verification stops being "run a one-off script during
development and discard it" and becomes a permanent, re-runnable
regression fixture any future package can invoke.

Every step asserts a real invariant and raises immediately (not just
logs a warning) if broken — per this task's own "the script must fail
if any invariant in the chain is broken" rule. No new business logic
lives here; every assertion checks a fact the relevant engine already
computes, the same discipline bootstrap.py's own docstring establishes
for orchestration scripts in this codebase.
"""
import asyncio
import sys

import httpx


class InvariantFailure(AssertionError):
    """Raised the moment any step's own invariant doesn't hold —
    deliberately a distinct type from a plain AssertionError so a
    caller can catch simulation failures specifically."""


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise InvariantFailure(message)


async def run_simulation() -> None:
    import server
    from engines import memory_engine

    print("Atlas System Simulation Harness — RC1-HARDENING H5")
    print("=" * 60)

    async with server.lifespan(server.app):
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            pm = await memory_engine.upsert_user(phone="9990000900", name="Sim PM", role="project_manager")
            sup = await memory_engine.upsert_user(phone="9990000901", name="Sim Supervisor", role="site_supervisor")
            r = await c.post("/api/auth/login", json={"phone": "9990000900", "role": "project_manager"})
            h = {"Authorization": f"Bearer {r.json()['token']}"}

            # Step 1 — Create Project
            print("1. Create Project ...", end=" ")
            proj = (await c.post("/api/projects", json={"name": "Simulation Project", "code": "SIM001"}, headers=h)).json()
            _check(proj.get("lifecycle_stage") == "planning", "New project must default to 'planning' stage (PL-01)")
            from engines.memory_engine import set_user_projects
            await set_user_projects(sup["id"], [proj["id"]])
            rsup = await c.post("/api/auth/login", json={"phone": "9990000901", "role": "site_supervisor"})
            sh = {"Authorization": f"Bearer {rsup.json()['token']}"}
            # Establish the Since Last Visit baseline HERE, before any
            # commercial activity — calling this for the first time
            # after all ten prior steps would silently mark every real
            # event as already-seen, making step 12's own assertion
            # untestable rather than genuinely verified.
            svl_baseline = (await c.get(f"/api/projects/{proj['id']}/since-last-visit", headers=h)).json()
            _check(svl_baseline["is_first_visit"] is True, "The first-ever visit to a project must be reported as such")
            _check(svl_baseline["changes"] == [], "A first visit must show no changes, never a fabricated summary")
            print("OK")

            # Step 2 — Create Contract
            print("2. Create Contract ...", end=" ")
            contract = (await c.post("/api/commercial/contracts", json={
                "project_id": proj["id"], "original_contract_value": 5000000,
                "contract_date": "2026-01-01", "duration_days": 180,
            }, headers=h)).json()
            _check(contract["status"] == "draft", "New contract must start in 'draft' status")
            print("OK")

            # Step 3 — Create Budget
            print("3. Create Budget ...", end=" ")
            budget = (await c.post("/api/commercial/budgets", json={
                "project_id": proj["id"], "original_budget": 4000000,
            }, headers=h)).json()
            _check(budget["current_budget"] == 4000000, "Budget's current_budget must equal original_budget on creation")
            print("OK")

            # Step 4 — Create Milestone
            print("4. Create Milestone ...", end=" ")
            site = (await c.post("/api/sites", json={"project_id": proj["id"], "name": "Main Site"}, headers=h)).json()
            ms = (await c.post("/api/commercial/milestones", json={
                "project_id": proj["id"], "name": "Foundation", "sequence": 1,
                "planned_percent": 30, "trigger": "foundation complete",
            }, headers=h)).json()
            _check(ms["contract_value"] == round(5000000 * 0.30, 2), "Milestone contract_value must derive from planned_percent * contract value")
            print("OK")

            # Step 5 — Capture Observation
            print("5. Capture Observation ...", end=" ")
            files = {"photos": ("crack.jpg", b"fakejpegdata", "image/jpeg")}
            data = {"site_id": site["id"], "text": "Structural crack found requiring repair"}
            event = (await c.post("/api/events", data=data, files=files, headers=sh)).json()
            assets = await memory_engine.get_assets_for_event(event["id"])
            _check(len(assets) == 1, "Captured event with one photo must produce exactly one raw asset")
            asset_id = assets[0]["id"]
            print("OK")

            # Step 6 — Create Variation (linked to the observation)
            print("6. Create Variation (linked to Observation) ...", end=" ")
            var = (await c.post("/api/commercial/variations", json={
                "project_id": proj["id"], "title": "Structural repair", "description": "Repair crack",
                "original_cost": 0, "proposed_cost": 200000, "linked_photo_ids": [asset_id],
            }, headers=h)).json()
            _check(asset_id in var["linked_photo_ids"], "Variation must retain the linked_photo_ids it was created with")
            await c.post(f"/api/commercial/variations/{var['id']}/submit", headers=h)
            await c.post(f"/api/commercial/variations/{var['id']}/send-for-client-review", headers=h)
            print("OK")

            # Step 7 — Approve Variation
            print("7. Approve Variation ...", end=" ")
            before_contract = (await c.get(f"/api/projects/{proj['id']}/commercial/summary", headers=h)).json()
            before_value = before_contract["contract"]["current_contract_value"]
            await c.post(f"/api/commercial/variations/{var['id']}/decide", json={"decision": "approved"}, headers=h)
            after_contract = (await c.get(f"/api/projects/{proj['id']}/commercial/summary", headers=h)).json()
            after_value = after_contract["contract"]["current_contract_value"]
            _check(after_value == before_value + 200000, "Approving a variation must automatically increase the contract's current_contract_value by the proposed cost")
            print("OK")

            # Step 8 — Achieve Milestone
            print("8. Achieve Milestone ...", end=" ")
            await c.post(f"/api/commercial/milestones/{ms['id']}/status", json={"status": "ready"}, headers=h)
            r8 = await c.post(f"/api/commercial/milestones/{ms['id']}/status", json={"status": "achieved"}, headers=h)
            _check(r8.json()["status"] == "achieved", "Milestone must transition to 'achieved'")
            print("OK")

            # Step 9 — Create Payment Request
            print("9. Create Payment Request ...", end=" ")
            pr = (await c.post("/api/commercial/payment-requests", json={
                "project_id": proj["id"], "milestone_id": ms["id"], "amount": ms["contract_value"],
                "raised_date": "2026-02-01", "due_date": "2026-02-15",
            }, headers=h)).json()
            _check(pr["milestone_id"] == ms["id"], "Payment request must reference the milestone it was raised against")
            print("OK")

            # Step 10 — Record Payment
            print("10. Record Payment ...", end=" ")
            pay = (await c.post("/api/commercial/payments", json={
                "payment_request_id": pr["id"], "amount": ms["contract_value"],
                "date": "2026-02-10", "method": "bank_transfer",
            }, headers=h)).json()
            _check(pay["payment_request_id"] == pr["id"], "Payment must reference the payment request it settles")
            print("OK")

            # Step 11 — Verify Timeline
            print("11. Verify Timeline (commercial_events) ...", end=" ")
            events = (await c.get(f"/api/projects/{proj['id']}/commercial/events", headers=h)).json()
            kinds = {e["kind"] for e in events}
            required_kinds = {"contract_created", "milestone_created", "variation_created",
                             "variation_approved", "milestone_status_changed", "payment_request_raised", "payment_received"}
            _check(required_kinds.issubset(kinds), f"Timeline must include every real event that occurred; missing {required_kinds - kinds}")
            print("OK")

            # Step 12 — Verify Continuous Memory (CM-01)
            print("12. Verify Continuous Memory (Since Last Visit) ...", end=" ")
            svl_second = (await c.get(f"/api/projects/{proj['id']}/since-last-visit", headers=h)).json()
            _check(svl_second["is_first_visit"] is False, "A second visit must not be reported as first")
            change_kinds = {c["kind"] for c in svl_second["changes"]}
            _check("payment_received" in change_kinds, "Since Last Visit must surface the payment that happened since the first visit")
            print("OK")

            # Step 13 — Verify Knowledge Graph relationships (KM-01)
            print("13. Verify Knowledge Graph relationships ...", end=" ")
            var_rel = (await c.get(f"/api/knowledge-graph/variation/{var['id']}/relationships", headers=h)).json()
            incoming_kinds = {(e["entity_type"], e["relationship"]) for e in var_rel["incoming"]}
            _check(("event", "CAUSED") in incoming_kinds, "The Variation's relationships must show the Observation that caused it")
            outgoing_kinds = {(e["entity_type"], e["relationship"]) for e in var_rel["outgoing"]}
            _check(("contract", "MODIFIED") in outgoing_kinds, "The Variation's relationships must show the Contract it modified")
            impact = (await c.get(f"/api/knowledge-graph/events/{event['id']}/impact-trace", headers=h)).json()
            impact_types = [step["entity_type"] for step in impact["chain"]]
            _check("variation" in impact_types and "contract" in impact_types, "Impact Trace from the observation must reach both the Variation and the Contract")
            print("OK")

            # Step 14 — Verify Workspace Project Pulse
            print("14. Verify Workspace Project Pulse ...", end=" ")
            health = (await c.get(f"/api/projects/{proj['id']}/explain-health", headers=h)).json()
            summary = (await c.get(f"/api/projects/{proj['id']}/commercial/summary", headers=h)).json()
            _check(summary["cash_flow_signal"] in ("healthy", "attention", "critical"), "Cash flow signal must be one of the three known states")
            _check(summary["outstanding_payments"]["outstanding"] == 0, "Outstanding must be zero after the full payment was recorded")
            _check(isinstance(health.get("score"), (int, float)), "Explain Health must return a numeric score for the Workspace's own Project Pulse")
            print("OK")

            # Step 15 — Verify Relationship Explorer (decision trace)
            print("15. Verify Relationship Explorer (Decision Trace) ...", end=" ")
            dtrace = (await c.get(f"/api/knowledge-graph/payment/{pay['id']}/decision-trace", headers=h)).json()
            evidence_rel = {(e["entity_type"], e["relationship"]) for e in dtrace["evidence"]}
            _check(("payment_request", "SETTLES") in evidence_rel, "Decision Trace for a Payment must show it settles the Payment Request that generated it")
            print("OK")

    print("=" * 60)
    print("ALL 15 STEPS PASSED — every named invariant holds.")


def main() -> None:
    try:
        asyncio.run(run_simulation())
    except InvariantFailure as e:
        print(f"\nINVARIANT FAILURE: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
