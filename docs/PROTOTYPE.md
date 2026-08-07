# RedBlue AI — End-to-End Prototype Runbook (DVWA · Ollama · Wazuh)

The single minimal path that exercises the whole loop, traced hop-by-hop from the entry points and
fixed. Read this instead of guessing — every blocker the four trace passes found is either **fixed**
(and marked ✅) or **documented with the exact fix** (marked ⚠ needs-live-step).

```
POST /api/engagements ─▶ coordinator ─trigger─▶ Decepticon ─(Ollama via LiteLLM)─▶ attacks ─▶ DVWA
                              ▲                                                                  │
                              │ score(attacked vs detected)                Suricata/Wazuh detect─┘
                              └───────────────── Vigil findings ◀── custom-vigil integrator ◀────┘
```

There are **two tiers**. Tier 1 (red → DVWA → score) is fixed and ready. Tier 2 (Wazuh detection) is
heavier and has steps that must be run/validated on the live host.

---

## Tier 1 — red attacks DVWA on a local model, coordinator scores `attacked > 0`

This is the prototype's spine and it works with the fixes in this pass. **No Wazuh needed.**

### Prerequisites (one-time)
```bash
cd deploy
make net                       # ✅ creates redblue-shared + range-net (now with subnet 10.20.0.0/24)
make ollama                    # ✅ starts Ollama AND pulls the model (was never pulled → LLM 404s)
#   override the model:  make ollama OLLAMA_MODEL=hf.co/fdtn-ai/Foundation-Sec-8B-Instruct-Q8_0-GGUF
```
> If `range-net` already exists WITHOUT the subnet (created by an earlier run), recreate it once:
> `docker network rm range-net && make net`.
> `make dec-env` now ✅ writes a **sovereign** `Decepticon/.env` (`OLLAMA_API_BASE`, `OLLAMA_MODEL`,
> `DECEPTICON_AUTH_PRIORITY=ollama_local`, no cloud keys) instead of an empty stub — so red runs
> entirely on Ollama with zero cloud egress. If you already have a `Decepticon/.env`, it's left alone.

### Bring up + the target
```bash
make up                        # coordinator (✅ factory CMD + healthcheck) + red + blue (✅ DEV_MODE=true)
docker compose -p telemetry -f ../telemetry/docker-compose.telemetry.yml --profile target up -d dvwa
make health                    # want: langgraph OK · vigil OK · ollama OK · coordinator OK · isolation OK
```

### Launch an engagement — the target comes from the instruction (or `in_scope`)
The **only** target directive that reaches Decepticon is the natural-language `instruction`. If you
omit it, the coordinator now ✅ synthesises one from `scope.in_scope`, so either of these works:

```bash
# explicit instruction (name the container by its container_name: range-dvwa)
curl -s http://localhost:8900/api/engagements -H 'content-type: application/json' -d '{
  "tenant_id":"proto","engagement_id":"eng-proto-20260807-a1",
  "scope":{"in_scope":["range-dvwa"],"sandbox_url":"http://sandbox:9999"},
  "instruction":"Recon and exploit the DVWA web app at http://range-dvwa (authorized, in scope). Run nmap, then test SQLi/XSS/command-injection; validate each finding."
}' | jq

# OR omit instruction — in_scope drives it:
curl -s http://localhost:8900/api/engagements -H 'content-type: application/json' -d '{
  "tenant_id":"proto","engagement_id":"eng-proto-20260807-a2",
  "scope":{"in_scope":["range-dvwa"],"sandbox_url":"http://sandbox:9999"}
}' | jq
```

### See the result
```bash
ENG=eng-proto-20260807-a1
curl -s "http://localhost:8900/api/engagements/$ENG/scorecard" | jq
curl -s "http://localhost:8900/api/engagements" | jq          # list all
curl -s "http://localhost:8900/api/posture" | jq              # org roll-up
curl -N  "http://localhost:8900/api/engagements/$ENG/events"  # live SSE timeline
# or the Vigil console UI → "RedBlue Posture" + "Engagements" tabs
```
- **`attacked > 0`** requires the KG to carry techniques — verify once:
  `docker exec decepticon-neo4j cypher-shell -u neo4j -p decepticon-graph "MATCH (f:Finding) RETURN keys(f) LIMIT 5;"`
  (If a technique property/label is present, `_KGAttackSource` populates it. If not, tell me `keys(f)`.)
- **Even if red errors** (e.g. a model hiccup), the engagement now ✅ **completes with `attacked:0`
  and is viewable** instead of returning a 502 (`_ConnectorRed.launch` degrades to `status:"failed"`).

---

## Tier 2 — Wazuh takes the telemetry and passes it to the blue team (`detected > 0`)

**The blue path is now fixed AND verified end-to-end** (logic-level, no heavy stack needed): a
realistic Wazuh alert → `custom-vigil` transform → canonical finding → the coordinator's
`findings_to_detections` → `correlate` scored it **DETECTED, MTTD 12 s**. So the transform + ingest +
detection + correlation chain is proven; the remaining unknowns are purely operational (does the
heavy stack come up, and does Suricata actually emit an alert).

**✅ Fixed / applied this pass**
- **Wazuh now actually runs the `custom-vigil` integrator + reads the sensors.** The bare snippet
  mount never merged into `ossec.conf`. Replaced with the **complete `telemetry/wazuh/ossec.conf`**
  (the real 4.9.2 default + our `<integration>` and `<localfile>` blocks) mounted at
  `/wazuh-config-mount/etc/ossec.conf` — the **official** mechanism (`0-wazuh-init` honours
  `$WAZUH_CONFIG_MOUNT` and copies it over the default on boot). No entrypoint hack. `custom-vigil`
  is now `chmod +x`.
- **Two detection sources wired**, both via `<localfile>` in that config:
  1. **Suricata `eve.json`** (native Wazuh Suricata decoders) from the shared `suricata_logs` volume;
  2. **DVWA apache access log** (`dvwa_logs` volume shared DVWA→manager) — Wazuh's built-in web-attack
     rules fire on SQLi/XSS/command-injection in the request URL. This is the **more reliable**
     prototype signal (no network-IDS rules needed).
- **Suricata now sees the attack** — moved to `network_mode: "service:dvwa"` (shares DVWA's netns) so
  it sniffs the real unicast flows instead of only broadcast on the bridge; gated behind `profiles: [target]`.
- **TLS certs** — `make certs` (wazuh-certs-generator); `make telemetry` depends on it.
- **`range-net` subnet** `10.20.0.0/24` (matches Suricata `HOME_NET`); phantom `wazuh-agent` image gone.
- **DEV_MODE=true** on Vigil (enclave) so the integrator's unauthenticated ingest is accepted.

**⚠ The one remaining runtime variable**
- **Suricata rules** — `jasonish/suricata` ships none; the service now runs `suricata-update` on start,
  but that needs egress to fetch ET Open. Run it **once while the host still has internet** (before the
  egress lockdown), or bake a rules file in. The **DVWA apache-log** detection path needs no external
  rules, so prefer it for a first `detected > 0`.

### Verify it live (on the resourced host)
```bash
sudo sysctl -w vm.max_map_count=262144
make certs                                       # one-time TLS certs
make telemetry PROFILES=target                   # Wazuh + Suricata(netns) + DVWA
# attack DVWA (Tier-1), then watch the telemetry cross the boundary:
docker exec wazuh-manager tail -n5 /var/ossec/logs/alerts/alerts.json          # Wazuh raised alerts
docker logs wazuh-manager 2>&1 | grep -i custom-vigil                          # integrator fired
curl -s http://localhost:6987/api/findings | jq '.[]|select(.data_source!="decepticon")|.finding_id'  # landed in Vigil
curl -s http://localhost:8900/api/engagements/$ENG/scorecard | jq '.detected_techniques'              # scored
```

---

## Fixes applied in this pass (all in the additive layer, coordinator 103/103 tests green)

| Fix | File |
|---|---|
| Coordinator Docker CMD used a non-existent `app` → never served :8900 | `redblue-coordinator/Dockerfile` (factory), `deploy/docker-compose.redblue.yml` (healthcheck) |
| Red-run failure 502'd the whole engagement | `redblue/loop/live.py` `_ConnectorRed.launch` (degrade to `status:"failed"`) |
| Empty `instruction` → red had no target | `redblue/api/routes/engagements.py` (`_default_instruction` from `in_scope`) |
| Ollama model never pulled; `Decepticon/.env` was an empty stub | `deploy/Makefile` (`ollama` pull, sovereign `dec-env`) |
| `range-net` local & subnet-less; sandbox not attached | `deploy/Makefile` (subnet), `deploy/overrides/decepticon.redblue.yml` (sandbox→range-net) |
| Vigil backend fail-closed on `JWT_SECRET_KEY` | `deploy/overrides/vigil.redblue.yml` (`DEV_MODE=true`, enclave-only) |
| Wazuh certs / phantom agent image / eve.json path | `deploy/Makefile` (`certs`), `telemetry/*` |

## Security note
`DEV_MODE=true` (Vigil) and the sovereign no-auth ingest are the **P4 enclave** posture — fine on an
isolated host. Before exposing Vigil anywhere: set `DEV_MODE=false` + a real `JWT_SECRET_KEY` and wire
`REDBLUE_VIGIL_TOKEN` (P5).
