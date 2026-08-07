# ADR-0003 — Telemetry sensor plane (blue detects red for real)

- **Status:** Accepted (P2, 2026-08-05)
- **Plan ref:** `plans/04_TELEMETRY_SENSOR_PLANE.md`, `plans/05` (finding schema), `plans/00 §5`

## Context
RedBlue is *purple* only if blue detects red from **independent telemetry**, not red's self-report
(`00 §10`). Decepticon's `events.jsonl`/KG is ground truth (the answer key); the detection signal must
come from sensors watching the **target**.

## Decision
- **Sensors:** **Wazuh** (host HIDS/FIM) + **Suricata** (network IDS, funneled through Wazuh's native
  decoders) + **Falco** (container/K8s runtime). `telemetry/docker-compose.telemetry.yml`, own project.
- **Alert → Vigil (P2 path, zero Vigil patch):** a Wazuh **Integrator** (`custom-vigil`) transforms each
  `level>=5` alert into a Vigil **canonical finding** and POSTs to the *existing* `/api/ingest/ingest-string`.
  The transform is our code (`telemetry/`), so no engine edit — respects `01 §3`.
- **Not the Elastic connector:** Vigil's Elastic ingestion needs Kibana's Detection API; Wazuh's OpenSearch
  indexer has neither, so the Integrator/webhook is the lane (confirmed in `04 §4.1`).
- **Networks:** `telemetry-net` (sensors) + **`range-net`** (target + Suricata sniff; Kali's only extra
  attachment) + `redblue-shared` (outbound push to Vigil). `00 §5`.
- **Target range:** v1 = **DVWA** (+ a vuln container); sovereign-representative = kubernetes-goat + Linux-AD.

## Status / verification
- ✅ **Transform tested standalone** (`custom-vigil --selftest`): Wazuh host alert (SUID→`T1548.001`,
  sev high) and Suricata-via-Wazuh (nmap→`T1046`, `data_source=suricata`) → correct canonical findings
  (`sha256_16` id, singular `src_ip`, technique-ID mitre, 768-dim embedding, `external_id` dedup key).
- ✅ Compose + sensor configs written; `docker compose -p telemetry config` validates.

## Deviations (recorded)
1. **Falco lane shaping deferred** — Falco is in the compose as the runtime sensor, but its
   Falco→canonical mapping is not yet wired. Options: Falcosidekick→Kafka `security.findings` (Vigil's
   existing consumer; needs kafka on the bus + a shaping template) or the hardened `/api/webhooks/falco`
   receiver (P5). **Wazuh+Suricata (tested) already cover host + network** — the majority of the kill chain.
2. **Full stack not run live** — the Wazuh indexer alone (OpenSearch/JVM ~2-4 GB) plus both engine stacks
   exceeds this box's **14 GB / no-GPU**. The transform is proven; the live "nmap at the range → Vigil
   finding" run (P2 exit test, `04 §6`) awaits a provisioned host (needs `sysctl vm.max_map_count=262144`).

## Consequences
- One tested transform funnels host + network alerts; the hardened HMAC receiver (P5) generalizes it and
  folds in Falco. Sensor→finding is proven correct at the unit level now; end-to-end awaits hardware.
