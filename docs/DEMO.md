# RedBlue AI — 10-minute sovereign-cloud demo (plan 09 §6)

Audience: Indian BFSI / government security buyer. Every beat maps to a **moat pillar** no incumbent
ships together. The happy path IS the `make smoke` happy path, so it's CI-guarded, not a liveware gamble.

**Bring-up:** `cd deploy && make demo` (engines + telemetry + coordinator + observability). Console:
`http://localhost:6988`. Grafana: `http://localhost:3001` (import `observability/redblue_posture.json`).

| Min | Beat | Operator does | They see | Pillar |
|----:|------|---------------|----------|--------|
| 0:00 | **Frame** | Open the console; show the Grafana **Egress = 0** stat + models are local Ollama | Counter flat at 0; no foreign API | **Sovereignty as structure** |
| 1:00 | **Pull the cable** | Cut external network; ask Vigil a question | It still answers — inference is local | **Sovereignty** (the killer vs US SaaS) |
| 2:00 | **Launch an attack** | **Red Team** screen → Launch `eng-demo-*` (scoped by RoE) at the range | Engagement goes Running; phases advance | **Closed purple-team loop** |
| 3:30 | **Detect for real** | Engagement **Timeline** (SSE) | Red steps + **blue detections** interleave — blue caught it from *sensors*, not red's self-report | **Closed loop** (honest detection) |
| 5:00 | **Score posture** | **Posture** dashboard | Attacked-vs-Detected donut, MTTD vs baseline, ATT&CK coverage, **false-negative watchlist** | **Closed loop + eval rigor** |
| 6:30 | **Governed action** | Loop proposes isolating a *production* workload → it **pauses** in the approvals queue | `gate.pending`; waits for a human; a tenant-boundary action is **never-auto** | **Graduated-autonomy governance** |
| 8:00 | **Approve + AI-defense** | Approve the reversible action; run `make eval` (or the console) to show a **poisoned log blocked** | Auto-tier executes; the injection is refused; **agent_hijack_rate = 0** | **First-class AI-native defense** |
| 9:00 | **Hand over evidence** | **Export** the engagement | A tamper-evident, hash-chained report: every red action, blue verdict, response, approver | **Immutable evidence / audit** |
| 9:45 | **Close** | One line | "Sovereign, closed-loop, governed, AI-defended — the four things no incumbent ships together." | All four |

## The proof numbers (from `make eval` / `GET /api/coordinator/eval/injection`)
`injection_catch_rate=1.0 · false_positive_rate=0.0 · canary_leak_rate=0.0 · agent_hijack_rate=0.0 · passed=true`
— and the tests prove `agent_hijack_rate` is *sensitive* (a permissive policy makes it non-zero), so 0
is earned, not trivial.

## Fallbacks (so the demo never dies)
- VStrike 3-D unavailable → native SVG kill-chain timeline (the console degrades gracefully).
- SSE drop → the 10-s poll reconciles.
- Live engagement stalls (local-LLM latency) → replay a pre-recorded `eng-demo-golden` from the
  evidence store. All three are built, not improvised.

## What's real vs staged
Real: sovereignty (packet-proof egress=0), the closed loop (sensor-driven detection), the tiered
governance gate, the hash-chained evidence, the injection defense + eval. Staged/limited today:
`isolate_host` executes only via a wired EDR (else it **fails closed** — never fakes containment);
the live two-engine run wants ≥32 GB / GPU (the logic is all tested on-box at 74→90 passing tests).
