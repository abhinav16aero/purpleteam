#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════════════════════
# demo-seed.sh — detailed END-TO-END demo for the RedBlue / Swaraj Chakravyuh console.
#
# Populates EVERY tab of the web UI without the (slow, CPU-bound) red engine:
#   • Graph        — a recon graph in Neo4j: host → ports → services → findings → techniques
#   • Posture      — attacked-vs-detected KPIs, donut, gaps
#   • Engagements  — a completed engagement + scorecard + live timeline
#   • Evidence     — the hash-chained WORM ledger
#
# It VERIFIES each hop and prints clear diagnostics, so if something's off you see exactly where.
# Run from anywhere with the stack up:   bash deploy/demo-seed.sh
# Optional: bash deploy/demo-seed.sh <engagement-id>
# ═══════════════════════════════════════════════════════════════════════════════════════════════
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CO="${REDBLUE_COORDINATOR_URL:-http://localhost:8900}"
VIGIL="${VIGIL_URL:-http://localhost:6987}"
NEO4J_C="${NEO4J_CONTAINER:-decepticon-neo4j}"
NEO4J_PASS="${NEO4J_PASS:-decepticon-graph}"
TARGET="${TARGET:-10.20.0.9}"
ENG="${1:-eng-demo-$(date +%H%M%S)}"

now=$(date +%s); ts_atk=$((now+45)); ts_det=$((now+55))   # generous offsets → always inside the scoring window
iso_det=$(date -u -d "@${ts_det}" +%Y-%m-%dT%H:%M:%S.000Z 2>/dev/null || date -u -r "${ts_det}" +%Y-%m-%dT%H:%M:%S.000Z)

B=$'\033[1m'; DIM=$'\033[2m'; GRN=$'\033[1;32m'; RED=$'\033[1;31m'; YEL=$'\033[1;33m'; CYA=$'\033[1;36m'; Z=$'\033[0m'
step(){ printf '\n%s══ %s ══%s\n' "$CYA" "$*" "$Z"; }
ok(){   printf '  %s✓%s %s\n' "$GRN" "$Z" "$*"; }
warn(){ printf '  %s!%s %s\n' "$YEL" "$Z" "$*"; }
die(){  printf '  %s✗ %s%s\n' "$RED" "$*" "$Z"; FAILED=1; }
pp(){   jq . 2>/dev/null || python3 -m json.tool 2>/dev/null || cat; }
cyq(){  docker exec "$NEO4J_C" cypher-shell -u neo4j -p "$NEO4J_PASS" --format plain "$1" 2>&1; }
FAILED=0
printf '%sRedBlue demo seed%s  engagement=%s  target=%s\n' "$B" "$Z" "$ENG" "$TARGET"

# ───────────────────────────────────────────────────────────────────────────────────────────────
step "0 · Preflight — is the stack reachable?"
curl -sf "$CO/api/health"  >/dev/null 2>&1 && ok "coordinator  $CO" || die "coordinator NOT reachable at $CO — is redblue-coordinator up? (make up)"
curl -sf "$VIGIL/api/findings" >/dev/null 2>&1 && ok "vigil        $VIGIL" || die "vigil NOT reachable at $VIGIL (need DEV_MODE=true) — make blue-only"
if docker ps --format '{{.Names}}' | grep -qx "$NEO4J_C"; then
  [ "$(cyq 'RETURN 1 AS ok;' | tail -1)" = "1" ] && ok "neo4j        $NEO4J_C (auth ok)" || die "neo4j auth failed — password mismatch? (NEO4J_PASS=$NEO4J_PASS)"
else die "neo4j container '$NEO4J_C' not running — make red-only"; fi
[ "$FAILED" = 1 ] && { echo; die "preflight failed — fix the above and re-run"; exit 1; }

# ───────────────────────────────────────────────────────────────────────────────────────────────
step "1 · Seed the RED recon graph → Neo4j"
cyq "MATCH (n {engagement:'$ENG'}) DETACH DELETE n;" >/dev/null
CREATE_OUT=$(cyq "
MERGE (h:Host {key:'$TARGET'}) SET h.engagement='$ENG', h.label='$TARGET'
CREATE (p22:Port{key:'$ENG:22', engagement:'$ENG', label:'22/tcp'}),
       (p80:Port{key:'$ENG:80', engagement:'$ENG', label:'80/tcp'}),
       (p3306:Port{key:'$ENG:3306', engagement:'$ENG', label:'3306/tcp'}),
       (ssh:Service{key:'$ENG:ssh', engagement:'$ENG', label:'OpenSSH'}),
       (http:Service{key:'$ENG:http', engagement:'$ENG', label:'http DVWA'}),
       (mysql:Service{key:'$ENG:mysql', engagement:'$ENG', label:'MySQL'}),
       (t46:Technique{key:'$ENG:T1046', engagement:'$ENG', label:'T1046'}),
       (t90:Technique{key:'$ENG:T1190', engagement:'$ENG', label:'T1190'}),
       (t10:Technique{key:'$ENG:T1110', engagement:'$ENG', label:'T1110'}),
       (f1:Finding{key:'FIND-$ENG-nmap', engagement:'$ENG', tool:'nmap', severity:'medium', label:'nmap: 22/80/3306 open', mitre_techniques:['T1046'], target:'$TARGET', ts:$ts_atk}),
       (f2:Finding{key:'FIND-$ENG-sqli', engagement:'$ENG', tool:'sqlmap', severity:'high', label:'sqlmap: SQLi in /sqli id', mitre_techniques:['T1190'], target:'$TARGET', ts:$ts_atk}),
       (f3:Finding{key:'FIND-$ENG-brute', engagement:'$ENG', tool:'hydra', severity:'high', label:'hydra: weak ssh creds', mitre_techniques:['T1110'], target:'$TARGET', ts:$ts_atk}),
       (h)-[:HAS_PORT]->(p22),(h)-[:HAS_PORT]->(p80),(h)-[:HAS_PORT]->(p3306),
       (p22)-[:RUNS_SERVICE]->(ssh),(p80)-[:RUNS_SERVICE]->(http),(p3306)-[:RUNS_SERVICE]->(mysql),
       (h)-[:REACHES]->(f1),(h)-[:REACHES]->(f2),(h)-[:REACHES]->(f3),
       (f1)-[:AGAINST]->(h),(f2)-[:AGAINST]->(http),(f3)-[:AGAINST]->(ssh),
       (f1)-[:USES]->(t46),(f2)-[:USES]->(t90),(f3)-[:USES]->(t10);")
NCOUNT=$(cyq "MATCH (n {engagement:'$ENG'}) RETURN count(n) AS n;" | tail -1)
if [ "${NCOUNT:-0}" -ge 13 ] 2>/dev/null; then ok "$NCOUNT nodes seeded (host·ports·services·findings·techniques)"
else die "seed failed — only ${NCOUNT:-0} nodes. cypher said: $(echo "$CREATE_OUT" | tail -2)"; fi

# ───────────────────────────────────────────────────────────────────────────────────────────────
step "2 · Seed the BLUE detections → Vigil (via the real custom-vigil transform)"
CV="$ROOT/telemetry/wazuh/integrations/custom-vigil"
[ -f "$CV" ] || die "custom-vigil not found at $CV"
seed_det(){  # $1 = alert JSON — transform + POST to Vigil, capture result
  local af; af=$(mktemp); printf '%s' "$1" > "$af"
  local out; out=$(python3 "$CV" "$af" unused "$VIGIL" 2>&1); rm -f "$af"
  echo "$out" | grep -q 'HTTP 200' && ok "posted: $(echo "$out" | sed 's/.*ingested //')" || die "post failed: $out"
}
# Suricata detects the nmap scan (T1046); Wazuh detects the SQLi (T1190). Hydra brute (T1110) → undetected gap.
seed_det "{\"id\":\"suri-$ENG-1\",\"timestamp\":\"$iso_det\",\"rule\":{\"level\":6,\"id\":\"86601\",\"description\":\"Suricata: ET SCAN Nmap of $TARGET\",\"groups\":[\"ids\",\"suricata\"],\"mitre\":{\"id\":[\"T1046\"]}},\"agent\":{\"name\":\"suricata\"},\"data\":{\"srcip\":\"10.20.0.5\",\"dstip\":\"$TARGET\",\"dstport\":\"80\",\"protocol\":\"TCP\"}}"
seed_det "{\"id\":\"wazuh-$ENG-2\",\"timestamp\":\"$iso_det\",\"rule\":{\"level\":9,\"id\":\"31103\",\"description\":\"Web attack: SQL injection on $TARGET\",\"groups\":[\"web\",\"attack\"],\"mitre_techniques\":[\"T1190\"]},\"agent\":{\"name\":\"wazuh-manager\"},\"data\":{\"srcip\":\"10.20.0.5\",\"dstip\":\"$TARGET\",\"url\":\"/vulnerabilities/sqli/?id=1'\"}}"
FCOUNT=$(curl -s "$VIGIL/api/findings?limit=500" | grep -oc "$ENG" || true)
[ "${FCOUNT:-0}" -ge 2 ] && ok "verified: both detections present in Vigil /api/findings" || warn "only ${FCOUNT:-0} seeded detections found in Vigil (may still work if ingest is async)"

# ───────────────────────────────────────────────────────────────────────────────────────────────
step "3 · Drive the coordinator (simulate:true → score the seeded data, no live red)"
t0=$(date +%s)
CREATE=$(curl -s --max-time 90 "$CO/api/engagements" -H 'content-type: application/json' \
  -d "{\"tenant_id\":\"demo\",\"engagement_id\":\"$ENG\",\"simulate\":true,\"scope\":{\"in_scope\":[\"$TARGET\"]}}")
t1=$(date +%s); took=$((t1-t0))
echo "$CREATE" | pp | sed 's/^/  /'
if echo "$CREATE" | grep -q '"status"'; then
  [ "$took" -gt 15 ] && warn "took ${took}s — the coordinator may be running REAL red (rebuild it: docker compose -p coordinator ... up -d --build) — 'simulate' needs the latest image" \
                     || ok "engagement completed in ${took}s (simulate)"
else die "engagement create failed: $CREATE"; fi

# ───────────────────────────────────────────────────────────────────────────────────────────────
step "4 · Verify every UI tab has data"
GRAPH=$(curl -s "$CO/api/engagements/$ENG/graph")
GN=$(echo "$GRAPH" | grep -o '"id"' | wc -l | tr -d ' ')
if [ "${GN:-0}" -ge 13 ]; then ok "GRAPH tab: coordinator reads ${GN} KG nodes for $ENG"
else die "GRAPH tab EMPTY (${GN} nodes) — the coordinator can't read the seeded KG. Check REDBLUE_DECEPTICON_NEO4J_PASSWORD=$NEO4J_PASS in deploy/env/shared.env and that it matches the neo4j container."; fi
echo
printf '  %sSCORECARD%s (Engagements + Posture tabs):\n' "$B" "$Z"
curl -s "$CO/api/engagements/$ENG/scorecard" | pp | sed 's/^/  /'
echo
printf '  %sPOSTURE%s roll-up:\n' "$B" "$Z"
curl -s "$CO/api/posture" | pp | sed 's/^/  /'

# ───────────────────────────────────────────────────────────────────────────────────────────────
step "Done — open the console (tunnel :8900) and use engagement  $ENG"
cat <<EOF
  Web UI:     $CO/                    (Posture · Engagements · Graph · Evidence)
  Graph tab:  load engagement id →    $ENG
  Expected:   attacked 3 (T1046,T1190,T1110) · detected 2 (T1046,T1190) · rate 0.67 · gap T1110 · graph ~13 nodes
EOF
[ "$FAILED" = 1 ] && printf '\n%s⚠ some steps failed above — see the ✗ lines.%s\n' "$YEL" "$Z"
exit "${FAILED:-0}"
