#!/usr/bin/env bash
# demo-seed.sh — end-to-end route test WITHOUT the (slow, CPU-bound) red engine.
#
# Seeds a realistic Kali-tool red engagement into Decepticon's Neo4j KG (nmap / sqlmap / hydra),
# seeds the matching Wazuh/Suricata blue detections into Vigil (via the real custom-vigil transform),
# then drives a `simulate:true` engagement so the coordinator scores the SEEDED data live — proving
# the whole route (attack ground-truth → detections → correlate → scorecard → evidence) end to end.
#
# Run from anywhere on the host with the stack up:  bash deploy/demo-seed.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CO="${REDBLUE_COORDINATOR_URL:-http://localhost:8900}"
VIGIL="${VIGIL_URL:-http://localhost:6987}"
NEO4J_PASS="${NEO4J_PASS:-decepticon-graph}"
TARGET="${TARGET:-10.20.0.9}"          # DVWA's range IP (or use range-dvwa)
ENG="${1:-eng-demo-$(date +%H%M%S)}"

now=$(date +%s)
ts_atk=$((now + 20)); ts_det=$((now + 25))     # attack then detection (+5s MTTD), inside the window
iso_det=$(date -u -d "@${ts_det}" +%Y-%m-%dT%H:%M:%S.000Z 2>/dev/null || date -u -r "${ts_det}" +%Y-%m-%dT%H:%M:%S.000Z)

say() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

say "1/4  Seed the RED attack graph (Kali tools → Neo4j Finding nodes) for $ENG"
# 3 attacks on the target: nmap recon (T1046), sqlmap SQLi (T1190), hydra brute (T1110).
docker exec decepticon-neo4j cypher-shell -u neo4j -p "$NEO4J_PASS" \
  "MATCH (f:Finding {engagement:'$ENG'}) DETACH DELETE f;" >/dev/null
docker exec decepticon-neo4j cypher-shell -u neo4j -p "$NEO4J_PASS" "
MERGE (h:Host {key:'$TARGET'})
CREATE (f1:Finding {key:'FIND-$ENG-nmap', engagement:'$ENG', tool:'nmap',   severity:'medium',
        label:'nmap: 22/80/3306 open on $TARGET',                 mitre_techniques:['T1046'], target:'$TARGET', ts:$ts_atk}),
       (f2:Finding {key:'FIND-$ENG-sqli', engagement:'$ENG', tool:'sqlmap', severity:'high',
        label:'sqlmap: SQL injection in /vulnerabilities/sqli id', mitre_techniques:['T1190'], target:'$TARGET', ts:$ts_atk}),
       (f3:Finding {key:'FIND-$ENG-brute',engagement:'$ENG', tool:'hydra',  severity:'high',
        label:'hydra: weak creds admin:password on /login.php',   mitre_techniques:['T1110'], target:'$TARGET', ts:$ts_atk}),
       (h)-[:REACHES]->(f1), (h)-[:REACHES]->(f2), (h)-[:REACHES]->(f3);" >/dev/null
echo "   seeded 3 Finding nodes (T1046 nmap, T1190 sqlmap, T1110 hydra) on $TARGET"

say "2/4  Seed the BLUE detections (Wazuh/Suricata alerts → custom-vigil → Vigil ingest)"
# Suricata DETECTS the nmap scan (T1046); Wazuh DETECTS the SQLi (T1190). The hydra brute (T1110) is
# NOT detected → it becomes the scorecard's false-negative gap.
CV="$ROOT/telemetry/wazuh/integrations/custom-vigil"
seed_det() {  # <alert-json> — transform + POST to Vigil via the real integrator
  local f; f=$(mktemp); printf '%s' "$1" > "$f"
  python3 "$CV" "$f" unused "$VIGIL" 2>&1 | sed 's/^/   /' || echo "   (post failed — is Vigil up + DEV_MODE=true?)"
  rm -f "$f"
}
seed_det "{\"id\":\"suri-$ENG-1\",\"timestamp\":\"$iso_det\",\"rule\":{\"level\":6,\"id\":\"86601\",
  \"description\":\"Suricata: ET SCAN Nmap scan of $TARGET\",\"groups\":[\"ids\",\"suricata\"],\"mitre\":{\"id\":[\"T1046\"]}},
  \"agent\":{\"name\":\"suricata\"},\"data\":{\"srcip\":\"10.20.0.5\",\"dstip\":\"$TARGET\",\"dstport\":\"80\",\"protocol\":\"TCP\"}}"
seed_det "{\"id\":\"wazuh-$ENG-2\",\"timestamp\":\"$iso_det\",\"rule\":{\"level\":9,\"id\":\"31103\",
  \"description\":\"Web attack: SQL injection on $TARGET\",\"groups\":[\"web\",\"attack\"],\"mitre_techniques\":[\"T1190\"]},
  \"agent\":{\"name\":\"wazuh-manager\"},\"data\":{\"srcip\":\"10.20.0.5\",\"dstip\":\"$TARGET\",\"url\":\"/vulnerabilities/sqli/?id=1'\"}}"

say "3/4  Drive the coordinator (simulate:true → score the seeded data, no live red)"
curl -s "$CO/api/engagements" -H 'content-type: application/json' -d "{
  \"tenant_id\":\"demo\",\"engagement_id\":\"$ENG\",\"simulate\":true,
  \"scope\":{\"in_scope\":[\"$TARGET\"]}}" | (jq . 2>/dev/null || cat)

say "4/4  The scorecard (attacked vs detected, MTTD, the false-negative gap)"
curl -s "$CO/api/engagements/$ENG/scorecard" | (jq . 2>/dev/null || cat)
echo
echo "posture:  $CO/api/posture   |   evidence:  $CO/api/engagements/$ENG/evidence?verify=true"
echo "expected: attacked 3 (T1046,T1190,T1110) · detected 2 (T1046,T1190) · rate 0.67 · gap T1110 · MTTD 5s"
