#!/usr/bin/env bash
# smoke.sh — the "does the loop close?" gate (plan 09 §3.2).
# If the coordinator is up (:8900), drive ONE engagement end-to-end and assert the closed loop.
# Otherwise fall back to the coordinator's own test suite as the logic smoke (on-box, no stack).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CO="${REDBLUE_COORDINATOR_URL:-http://localhost:8900}"

pass() { printf '\033[1;32m  PASS\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m  FAIL\033[0m %s\n' "$*" >&2; exit 1; }

if curl -sf "$CO/api/health" >/dev/null 2>&1; then
  echo "[smoke] coordinator up → driving a live engagement"
  eng="eng-smoke-$(date +%Y%m%d)-$(openssl rand -hex 2 2>/dev/null || echo ab12)"
  curl -sf -X POST "$CO/api/engagements" -H 'content-type: application/json' \
    -d "{\"tenant_id\":\"smoke\",\"engagement_id\":\"$eng\",\"scope\":{\"sandbox_url\":\"http://sandbox:9999\"}}" \
    | grep -q '"status"' && pass "engagement created" || fail "engagement create"

  sc=$(curl -sf "$CO/api/engagements/$eng/scorecard")
  echo "$sc" | grep -q 'detection_rate' && pass "scorecard produced" || fail "no scorecard"

  ev=$(curl -sf "$CO/api/engagements/$eng/evidence?verify=true")
  echo "$ev" | grep -q '"verified": *true' && pass "evidence chain verifies" || fail "evidence chain broken"

  egress=$(curl -sf "$CO/metrics" | grep '^redblue_external_egress_bytes_total' | awk '{print $2}')
  [ "${egress:-0}" = "0" ] || [ "${egress:-0}" = "0.0" ] && pass "egress == 0 (sovereign)" || fail "egress non-zero: $egress"

  echo "[smoke] closed loop OK for $eng"
else
  echo "[smoke] coordinator not reachable at $CO → running coordinator logic smoke (pytest)"
  ( cd "$ROOT/redblue-coordinator" && uv run pytest -q ) && pass "coordinator suite green" || fail "coordinator suite red"
fi
