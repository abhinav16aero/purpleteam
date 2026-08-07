# patches/ — tracked git patches for edits to EXISTING engine files (plan 01 §3.2, Tier B)

In-place edits to upstream-owned files are kept as `git`-format patches under
`patches/<engine>/NNNN-<slug>.patch`, generated from the pinned base and re-applied by `setup.sh` with
`git apply --3way`. A failed apply is a *precise* signal ("upstream moved this exact file").

Generated patch set (all target existing Vigil files; each verified to reverse-apply cleanly against
the pinned base + parse in Vigil's venv):

| Patch | Target(s) | What / why | Plan |
|---|---|---|---|
| `0001-isolate_host-real-action.patch` | `services/autonomous_response_service.py` (`_execute_isolation` **and** `create_isolation_action`) | Kill the `"(MOCK)"` success; **fail closed** (no EDR ⇒ `success:false`). **The auto-approve caller now HONORS `result["success"]`** — marks the action FAILED (not falsely EXECUTED) so containment is never reported when it didn't happen | 06 §5a / 08 risk #2 |
| `0002-tool-tier-verb-gate.patch` | `services/tool_manager.py` | `launch/exploit/attack` verbs + `red_*` tools + the 4 blue ActionTypes (`block_domain/waf_block/gateway_block/access_revoke`) → `requires_approval` | 06 §4.3 / 08 §2.3 |
| `0003-approval-tenant-id.patch` | `database/init/13_approval_actions.sql` **+ `helm/vigil/files/database-init/13_approval_actions.sql`** | Add `tenant_id` column + idempotent `ALTER`+index. **Helm bundle synced** so the chart CI `diff -r` passes. (The ORM model doesn't yet write the column — coordinator owns per-tenant policy at L1; wiring `create_action(tenant_id=…)` is a future Vigil-multitenancy step) | 08 §3 / risk #1 |
| `0004-approval-085-to-090.patch` | `services/approval_service.py` **+ `tests/unit/test_approval_workflow.py`** | Reconcile stale **0.85 → 0.90**; **the stale test (asserted 0.87→auto-approve) updated** to expect the flagged-not-auto behavior | 08 §0 / risk #4 |
| `0005-daemon-workflow-step-map.patch` | `daemon/plan_generator.py` | Register the `purple-team-response` workflow (7 steps, gated containment) in `WORKFLOW_STEP_MAP` + route `data_source=='decepticon'` findings to it in `select_workflow` | 06 §4.4 |

All 5 verified: reverse-apply cleanly vs the pinned base, parse in Vigil's venv, and (0002/0004/0005) behavior-checked. The 6 unrelated `test_approval_workflow.py` failures are pre-existing `psycopg2 Connection refused` (no Postgres running), not patch-induced.

`setup.sh` applies these idempotently (reverse-check skips already-applied). A failed apply is a
precise signal that the upstream file moved — regenerate that one patch.
