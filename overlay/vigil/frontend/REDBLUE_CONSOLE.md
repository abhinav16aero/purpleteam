# RedBlue console — Vigil frontend integration (plan 09 §1)

The unified console extends Vigil's React SPA with two native screens (`engagements`, `posture`) and
a `coordinatorApi` service that talks to the coordinator through the single-origin
`/api/coordinator/*` proxy (backend patch 0006). No new dependency — charts reuse `redesign/shared/`.

## Overlay files (copied in by `setup.sh`)
```
src/services/coordinatorApi.ts                          # the console↔coordinator contract
src/redesign/screens/posture/PostureScreen.tsx          # attacked-vs-detected + MTTD + gap watchlist
src/redesign/screens/engagements/EngagementsScreen.tsx  # launch/monitor + kill switch + SSE timeline
```

## Registration edits (3 small edits to existing files — apply as a tracked patch)

**1. `src/redesign/data/data.ts`** — add the two `ScreenKey`s, nav entries, titles, and RBAC gates:
```ts
export type ScreenKey = … | 'engagements' | 'posture'      // add both

// NAV (insert just below the 'autoops' row):
['target', 'Red Team', 'engagements'],
['shield', 'Posture',  'posture'],

// TITLES:
engagements: ['Red Team', 'Launch and monitor engagements'],
posture:     ['Posture',  'Attacked vs detected, MTTD, coverage gaps'],
```

**2. `src/redesign/SocConsole.tsx`** — import + register + gate:
```ts
import EngagementsScreen from './screens/engagements/EngagementsScreen'
import PostureScreen from './screens/posture/PostureScreen'
// SCREENS map:
engagements: EngagementsScreen,
posture: PostureScreen,
// SCREEN_PERMS (red control plane is privileged; posture is read-mostly):
engagements: 'redteam.operate',
posture:     'posture.read',
```

**3. RBAC seed** — add `redteam.operate`, `redteam.approve`, `posture.read` to Vigil's role seed
(`database/init/06_auth_tables.sql`). Under `DEV_MODE=true` every permission is granted, so the
screens show during dev; the gate is real once `DEV_MODE=false` (mandatory before tenant exposure).

## Real-time
Aggregates poll at 10s (matches `AutoOpsScreen`). The engagement **timeline** is the one SSE stream
(`/api/coordinator/engagements/{id}/events`) consumed via the existing `streamFetch` helper — no
WebSocket. On reconnect the 10s poll reconciles.

## VStrike kill-chain (optional 3-D viz)
Mount VStrike through the existing extension/iframe host, feeding it the coordinator's kill-chain
steps; fall back to a native SVG timeline when VStrike is absent/501 (it is iframe+REST, not WS).
