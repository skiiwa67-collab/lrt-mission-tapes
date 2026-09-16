# LRT Mission Tape CDN — v1 (Starship gold)

HARD: No Play-per-flight. Historic = published/observed truth. Missing → PENDING REAL TELEMETRY + VID OK. Never label generic family templates as historic truth.

## CDN layout

```
https://<CDN_BASE>/lrt/missions/v1/
  index.json                 # optional manifest of known packs
  <ll2_uuid>.json            # one locked mission tape per LL2 launch id
  starship/
    flight-11.json           # optional alias → same body (slug redirect or duplicate)
    flight-12.json
    flight-13.json
    flight-14.json
```

App config (prefs / BuildConfig):
- `MISSION_TAPE_BASE_URL` = CDN base (https only)
- cache dir: `files/mission_tapes/`
- ETag / If-None-Match on pull

## Pull path (Ada)

1. Resolve id = `LaunchSnapshot.id` (LL2 uuid). Fallback slug only if uuid unknown.
2. `GET {BASE}/{id}.json` (timeout 8s). On 429 backoff once.
3. 200 → parse → cache to disk → `MissionTapeStore.put(id, tape)`.
4. 404 / network fail → keep cache if any; else status `PENDING REAL TELEMETRY`.
5. HISTORIC select / LIVE poll: prefer CDN tape over `FlightEventCatalog` family template when `tape.truth == "observed"|"published"`.
6. If only template available: HUD chip `PENDING REAL TELEMETRY` (not silent).

Live poll (near real-time): while CURRENT watch on bird, poll same URL every 30–60s (Starship gold: 15–30s). Growing event list replaces prior.

## JSON schema `mission-tape.v1`

```json
{
  "schema": "lrt.mission_tape.v1",
  "id": "ll2-uuid-here",
  "slug": "starship-flight-11",
  "family": "starship",
  "vehicle": "Starship",
  "name": "Starship | Flight 11",
  "provider": "SpaceX",
  "truth": "observed",
  "truth_note": "Events stamped from SpaceX webcast + published updates. Not MCC downlink.",
  "status": "success",
  "t0_utc": "2025-01-01T00:00:00Z",
  "t0_source": "liftoff_observed",
  "updated_utc": "2025-01-01T01:00:00Z",
  "sources": [
    {"kind": "webcast", "url": "https://...", "note": "SpaceX"},
    {"kind": "ll2", "id": "ll2-uuid-here"},
    {"kind": "agency", "url": "https://www.spacex.com/...", "note": "Mission page"}
  ],
  "goal": "PERFORMANCE TEST",
  "outcome": {
    "booster": "GULF SPLASH / DESTROYED",
    "ship": "SOFT SPLASH / INDIAN OCEAN",
    "payload": "20 STARLINK V3 DEPLOYED"
  },
  "events": [
    {
      "id": "ss_lift",
      "t_sec": 0,
      "title": "LIFTOFF",
      "detail": "Super Heavy / Starship stack",
      "severity": "INFO"
    },
    {
      "id": "ss_meco",
      "t_sec": 165,
      "title": "BOOSTER MECO",
      "detail": "Super Heavy cutoff",
      "severity": "INFO"
    }
  ],
  "pending": false
}
```

### Field rules

| Field | Rule |
|-------|------|
| `schema` | always `lrt.mission_tape.v1` |
| `id` | LL2 launch uuid — primary key |
| `truth` | `observed` \| `published` \| `pending` |
| `pending` | true → app MUST show PENDING banner; events may be empty/partial |
| `t0_utc` | ISO8601 liftoff (observed preferred over NET) |
| `t0_source` | `liftoff_observed` \| `ll2_net` \| `agency` |
| `events[].t_sec` | seconds from T0; only published/observed marks — **omit unknowns** |
| `events[].severity` | `INFO` \| `WATCH` \| `FAIL` (maps to EventSeverity) |
| `status` | `success` \| `failure` \| `partial` \| `in_flight` \| `hold` |
| Never invent MECO/deploy times. Sparse OK. Fake chopsticks catch = FORBIDDEN for historic truth. |

### Maps to Ada types

`events[]` → `FlightEvent(id, tSec, title, detail, EventSeverity)`  
`FlightEventCatalog.timeline(launch)` → if `MissionTapeStore.get(launch.id)` truth in {observed,published} && !pending → use tape events; else template + PENDING chip.

## Capture pipeline (backend — not Play)

During LIVE (Starship gold maniacal):
1. Poll LL2 status.
2. Stamp events when confirmed (webcast/agency) → PATCH/PUT `{id}.json` on CDN.
3. On terminal Success/Fail → `pending:false`, `truth:observed|published`, lock outcome.
4. App clients pick up on next poll / HISTORIC open.

## Out of scope v1

- Full MCC ALT/MPH downlink (not public)
- Play AAB per flight
- 2yr search depth
- Invented physics curves labeled as truth (gauges may still sim; banner honest)

## Prove

1. Host sample `flight-11` JSON on CDN (published-only sparse OK).
2. App HISTORIC Flight 11 → loads CDN tape; no Soyuz snap (108).
3. Delete/404 tape → PENDING REAL TELEMETRY + VID works.
4. Generic `starship()` template never shown as “historic truth” without PENDING.
