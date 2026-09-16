# LRT Mission Tapes

Public CDN for **Live Rocket Tracker** historic/live mission event strings.

- **No Play-per-flight.** Push a JSON here → phones pull on refresh.
- **Truth only.** Published/observed events. Sparse OK. Never invent MECO/deploy.
- Missing/stale pack → app shows **PENDING REAL TELEMETRY** + VID still works.
- Generic family templates in-app are **not** historic truth.

## URL shape

```
https://raw.githubusercontent.com/skiiwa67-collab/lrt-mission-tapes/main/v1/<ll2_uuid>.json
```

Optional Starship aliases under `v1/starship/flight-N.json` (same schema; include `id` = LL2 uuid).

Schema: `lrt.mission_tape.v1` — see `SCHEMA.md`.

Starship = gold path.

## Capture pipeline (ops)

Live / historic tapes are produced by the Command Center scripts — **not** Play uploads.

- **Ops bible:** [`CAPTURE.md`](CAPTURE.md) — PREFLIGHT → LIVE → STAMP → LOCK → CDN
- **Scripts:** [`scripts/`](scripts/) — `seed_pending.py`, `capture_live.py`, `stamp_event.py`, `lock_published.py`, `ll2.py`, `tape_io.py`

```bash
# Flight 14 gold — launch day watch
python3 scripts/capture_live.py --slug starship-flight-14 --watch --interval 20 --push
```
