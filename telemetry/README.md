# telemetry/ — the sensor plane (P2)

Wazuh (host HIDS) + Suricata (network IDS) + Falco (container/K8s runtime) watching the **target
range**, so blue detects red from independent telemetry. Design: `plans/04_TELEMETRY_SENSOR_PLANE.md`.

- `docker-compose.telemetry.yml` — sensors + range (built in P2)
- `wazuh/` `suricata/` `falco/` `target-range/` — configs + rule packs
- Alert → Vigil: Wazuh **Integrator webhook** (`POST /api/webhooks/wazuh`) + Falco → Kafka `security.findings`
- Networks: `telemetry-net` + `range-net` (Kali's only extra attachment) · `redblue-shared` for the outbound push
- Wazuh/Suricata are GPLv2 — deployed as pinned images only, never forked (plan 00 §6).
