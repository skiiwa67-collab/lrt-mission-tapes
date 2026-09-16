# LRT Mission Tape Capture Pipeline — Command Center ops bible

**HARD RULES (Chris / Elon)**

- **No Play-per-flight.** Phones pull JSON from `raw.githubusercontent.com` (this repo → CDN).
- **Truth only.** Published / observed events. Never invent MECO / deploy / chopsticks.
- **Sparse OK.** Missing → `pending:true` → app shows **PENDING REAL TELEMETRY**; **VID still works**.
- **Starship = gold path.** Flight 14 launch day ~2026-09-22.
- Schema: `lrt.mission_tape.v1` — see `SCHEMA.md` and `v1/starship/flight-13.json`.

CDN URL shape:

```
https://raw.githubusercontent.com/skiiwa67-collab/lrt-mission-tapes/main/v1/<ll2_uuid>.json
https://raw.githubusercontent.com/skiiwa67-collab/lrt-mission-tapes/main/v1/starship/flight-14.json
```

All commands below assume repo root: `cd /path/to/lrt-mission-tapes`.

---

## Pipeline overview

```
PREFLIGHT → LIVE (LL2 poll) → WEBCAST STAMPS → TERMINAL → LOCK → APP/VID
```

| Stage | Who | What |
|-------|-----|------|
| 1 PREFLIGHT | Operator | Resolve LL2 uuid; seed pending tape (alias + uuid file) |
| 2 LIVE | `capture_live.py` | Poll LL2; on In Flight stamp LIFTOFF t=0 if empty; `pending=true` |
| 3 WEBCAST STAMPS | Operator | Confirmed call-outs only via `stamp_event.py` — never guess |
| 4 TERMINAL | `capture_live.py` | LL2 Success/Fail/Partial → update status; **keep pending** until lock |
| 5 LOCK | Operator | Import agency published timeline → `pending=false`, `truth=published\|observed` |
| 6 APP | MissionTapeStore | Polls CDN; growing events replace prior |
| 7 VID | App | Always works even when pending |

---

## 1) PREFLIGHT

Resolve the bird’s LL2 uuid and seed a sparse pending tape.

```bash
# Search LL2
python3 scripts/ll2.py --search "Starship Flight 14"

# Or fetch by uuid once known
python3 scripts/ll2.py --uuid 7d1afb26-6f9c-429b-9ccf-29012fd1e519

# Seed pending stub (writes v1/starship/flight-14.json + v1/<uuid>.json + index)
python3 scripts/seed_pending.py --slug starship-flight-14 --search "Starship Flight 14"

# Dry-run only
python3 scripts/seed_pending.py --slug starship-flight-14 --dry-run
```

**Status mapping (LL2 → tape):** schema allows `success|failure|partial|in_flight|hold` only.
Pre-launch **Go** / **Hold** / TBD → tape `status: "hold"`. **In Flight** → `in_flight`. Terminal as named (`partial` for Partial Failure).

Seed rules:

- `pending: true`, `truth: "pending"`, `events: []` (or LIFTOFF only if known via `--with-liftoff`)
- `goal: "PERFORMANCE TEST"` for Starship
- Do **not** invent mid-flight marks

Optional push after seed:

```bash
python3 scripts/seed_pending.py --slug starship-flight-14 --search "Starship Flight 14" --push
```

---

## 2) LIVE — poll LL2

Watch LL2 status. On first **In Flight**: if `events` empty, stamp **LIFTOFF** `t_sec=0`; set `t0_utc` from wall clock (`t0_source: liftoff_observed`) or keep `ll2_net` until better. Never invent MECO/deploy/etc.

```bash
# One shot
python3 scripts/capture_live.py --slug starship-flight-14 --once

# Starship gold watch (~15–30s; default 20)
python3 scripts/capture_live.py --slug starship-flight-14 --watch --interval 20

# By uuid / search
python3 scripts/capture_live.py --uuid 7d1afb26-6f9c-429b-9ccf-29012fd1e519 --watch --interval 20
python3 scripts/capture_live.py --search "Starship Flight 14" --once

# Auto commit+push when tape changes
python3 scripts/capture_live.py --slug starship-flight-14 --watch --interval 20 --push
```

While live: `status=in_flight`, `pending=true`, `truth=pending`.

---

## 3) WEBCAST STAMPS — human confirmed only

Operator hears/sees a confirmed call-out (SpaceX webcast / agency) → stamp exact `t_sec`. **Never guess.**

```bash
python3 scripts/stamp_event.py \
  --slug starship-flight-14 \
  --id ss14_meco \
  --t_sec 165 \
  --title "BOOSTER MECO" \
  --detail "Super Heavy cutoff — webcast confirmed" \
  --severity INFO

# Optional push to CDN
python3 scripts/stamp_event.py --slug starship-flight-14 \
  --id ss14_hot --t_sec 168 --title "HOT-STAGE" --detail "Confirmed" --severity INFO --push
```

Dedup by event `id` (re-stamp replaces). Severity: `INFO|WATCH|FAIL`.

---

## 4) TERMINAL

When LL2 flips to Success / Failure / Partial Failure, `capture_live.py` updates `status` but **keeps `pending:true`** until the published timeline is locked. Do not claim historic truth from LL2 status alone.

---

## 5) LOCK — agency / published timeline

When SpaceX (or observed log) publishes a timeline, merge and lock:

```bash
# events.json = [ {id,t_sec,title,detail,severity}, ... ]  OR a full tape object
python3 scripts/lock_published.py \
  --slug starship-flight-14 \
  --from /path/to/published_events.json \
  --truth published \
  --status success \
  --t0-utc 2026-09-22T12:15:00Z \
  --t0-source agency \
  --outcome-json '{"booster":"...","ship":"...","payload":"..."}' \
  --replace-events \
  --push
```

Sets `pending=false`, `truth=published` (or `observed`), upserts `v1/index.json`.

---

## 6) APP / 7) VID

- `MissionTapeStore` already polls the CDN URL; growing `events` replace prior cache.
- If `pending:true` or missing pack → HUD **PENDING REAL TELEMETRY**.
- **VID always works** even when pending / sparse.

---

## Flight 14 gold checklist (launch day ~2026-09-22)

LL2 uuid (as of preflight resolve): `7d1afb26-6f9c-429b-9ccf-29012fd1e519`  
Alias: `v1/starship/flight-14.json`  
Agency page: `https://www.spacex.com/launches/starship-flight-14`

- [ ] **T-24h:** Confirm uuid still valid (`ll2.py --uuid …`). Refresh NET on pending tape.
- [ ] **T-2h:** `capture_live.py --slug starship-flight-14 --watch --interval 20 --push` running.
- [ ] **Liftoff:** Confirm LIFTOFF event present (`t_sec=0`); note `t0_utc` / `liftoff_observed`.
- [ ] **Ascent:** Stamp only **confirmed** webcast call-outs (`stamp_event.py`). Skip unknowns.
- [ ] **Terminal:** Let LL2 update status; leave `pending=true`.
- [ ] **Post:** When SpaceX timeline published → `lock_published.py --from … --truth published --push`.
- [ ] **Verify CDN:** open raw GitHub URL; phone HISTORIC/LIVE shows events or PENDING + VID OK.

---

## Script map

| Script | Role |
|--------|------|
| `scripts/ll2.py` | Fetch/search LL2 (`/2.2.0/`); 429 backoff |
| `scripts/tape_io.py` | Load/save/validate v1 JSON; index upsert; optional git push helper |
| `scripts/seed_pending.py` | Create sparse pending stub |
| `scripts/capture_live.py` | LL2 poll → status transitions only |
| `scripts/stamp_event.py` | Operator confirmed event stamp |
| `scripts/lock_published.py` | Merge published timeline; `pending=false` |

Help: `python3 scripts/<name>.py --help`
