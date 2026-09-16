#!/usr/bin/env python3
"""Live LL2 poll → pending mission tape updates (status transitions ONLY).

Never invent mid-flight events. On first In Flight: stamp LIFTOFF t_sec=0 if
events empty; set t0_utc from wall clock (liftoff_observed) or keep ll2_net.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ll2  # noqa: E402
import tape_io  # noqa: E402


def resolve_launch(args) -> dict:
    if args.uuid:
        return ll2.fetch_launch(args.uuid)
    if args.search:
        hit = ll2.find_best(args.search)
        if not hit:
            raise SystemExit(f"LL2 search empty: {args.search!r}")
        return ll2.fetch_launch(hit["id"])
    if args.slug:
        # Prefer local tape id, else search from slug
        try:
            tape, _ = tape_io.load_tape(slug=args.slug)
            tid = tape.get("id")
            if tid and not str(tid).startswith("PENDING"):
                return ll2.fetch_launch(tid)
        except FileNotFoundError:
            pass
        # slug starship-flight-14 → "Starship Flight 14"
        q = args.slug.replace("-", " ")
        hit = ll2.find_best(q)
        if not hit:
            raise SystemExit(f"LL2 could not resolve slug {args.slug!r}")
        return ll2.fetch_launch(hit["id"])
    raise SystemExit("need --uuid, --slug, or --search")


def ensure_base_tape(launch: dict, slug_hint: str | None) -> dict:
    """Load existing tape or create sparse pending from LL2."""
    uuid = launch["id"]
    slug = slug_hint or launch.get("slug") or uuid
    try:
        tape, _ = tape_io.load_tape(uuid=uuid)
        return tape
    except FileNotFoundError:
        pass
    try:
        tape, _ = tape_io.load_tape(slug=slug)
        # adopt real uuid if stub had placeholder
        if str(tape.get("id", "")).startswith("PENDING"):
            tape["id"] = uuid
            for s in tape.get("sources") or []:
                if s.get("kind") == "ll2":
                    s["id"] = uuid
        return tape
    except FileNotFoundError:
        pass

    name = launch.get("name") or slug
    family = "starship" if "starship" in (name + slug).lower() else "unknown"
    vehicle = "Starship" if family == "starship" else (launch.get("rocket", {}) or {}).get("configuration", {}).get("name") or "Unknown"
    agency_url = None
    if family == "starship" and slug.startswith("starship-flight-"):
        n = slug.split("-")[-1]
        agency_url = f"https://www.spacex.com/launches/starship-flight-{n}"

    sources = []
    if agency_url:
        sources.append({"kind": "agency", "url": agency_url, "note": "Mission page"})
    sources.append({"kind": "ll2", "id": uuid})

    return {
        "schema": tape_io.SCHEMA,
        "id": uuid,
        "slug": slug,
        "family": family,
        "vehicle": vehicle,
        "name": name,
        "provider": "SpaceX" if family == "starship" else "Unknown",
        "truth": "pending",
        "truth_note": "Live capture from LL2 status only. Mid-flight events stamped by operator (stamp_event.py). Not MCC.",
        "status": ll2.map_ll2_status(launch),
        "t0_utc": launch.get("net"),
        "t0_source": "ll2_net",
        "updated_utc": tape_io.utc_now_iso(),
        "sources": sources,
        "goal": "PERFORMANCE TEST" if family == "starship" else "",
        "outcome": {},
        "events": [],
        "pending": True,
    }


def apply_ll2_transition(tape: dict, launch: dict) -> tuple[dict, list[str]]:
    """Apply LL2 status → tape. Returns (tape, list of change notes). Never invents events except LIFTOFF on first In Flight."""
    notes: list[str] = []
    new_status = ll2.map_ll2_status(launch)
    old_status = tape.get("status")

    # Keep uuid / name fresh
    if tape.get("id") != launch["id"]:
        tape["id"] = launch["id"]
        notes.append(f"id→{launch['id']}")
    if launch.get("name") and tape.get("name") != launch["name"]:
        tape["name"] = launch["name"]
        notes.append("name refreshed")

    # Ensure ll2 source
    sources = list(tape.get("sources") or [])
    if not any(s.get("kind") == "ll2" for s in sources):
        sources.append({"kind": "ll2", "id": launch["id"]})
        tape["sources"] = sources
    else:
        for s in sources:
            if s.get("kind") == "ll2":
                s["id"] = launch["id"]

    if new_status != old_status:
        notes.append(f"status {old_status}→{new_status}")
        tape["status"] = new_status

    # First In Flight: LIFTOFF t=0 if events empty; t0 from wall clock
    if new_status == "in_flight":
        tape["pending"] = True
        tape["truth"] = "pending"
        events = list(tape.get("events") or [])
        if not events:
            prefix = "ss"
            slug = tape.get("slug") or ""
            if slug.startswith("starship-flight-"):
                prefix = f"ss{slug.split('-')[-1]}"
            events = [
                {
                    "id": f"{prefix}_lift",
                    "t_sec": 0,
                    "title": "LIFTOFF",
                    "detail": f"{tape.get('vehicle', 'Vehicle')} stack — observed In Flight (LL2)",
                    "severity": "INFO",
                }
            ]
            tape["events"] = events
            notes.append("LIFTOFF t_sec=0 stamped (events were empty)")
        # t0: only set liftoff_observed if we didn't already lock agency/observed
        prev_src = tape.get("t0_source")
        if prev_src != "agency" and (not tape.get("t0_utc") or prev_src in (None, "ll2_net") or old_status != "in_flight"):
            if old_status != "in_flight":
                # transition into flight → wall clock
                tape["t0_utc"] = tape_io.utc_now_iso()
                tape["t0_source"] = "liftoff_observed"
                notes.append(f"t0_utc set liftoff_observed={tape['t0_utc']}")
        # if still no t0, keep ll2 net
        if not tape.get("t0_utc") and launch.get("net"):
            tape["t0_utc"] = launch["net"]
            tape["t0_source"] = tape.get("t0_source") or "ll2_net"
            notes.append("t0_utc from ll2_net")

    elif new_status in ("success", "failure", "partial"):
        tape["status"] = new_status
        # Keep pending until published timeline locked via lock_published.py
        tape["pending"] = True
        tape["truth"] = "pending"
        if not tape.get("truth_note"):
            tape["truth_note"] = "Terminal LL2 status received; awaiting published/observed timeline lock."
        notes.append(f"terminal {new_status}; pending kept until lock_published")

    elif new_status == "hold":
        tape["status"] = "hold"
        tape["pending"] = True
        tape["truth"] = "pending"
        # refresh NET if still preflight
        if launch.get("net") and tape.get("t0_source") in (None, "ll2_net"):
            if tape.get("t0_utc") != launch["net"]:
                tape["t0_utc"] = launch["net"]
                tape["t0_source"] = "ll2_net"
                notes.append(f"NET refresh {launch['net']}")

    return tape, notes


def one_cycle(args) -> int:
    launch = resolve_launch(args)
    ll2_name = (launch.get("status") or {}).get("name")
    print(f"LL2 {launch['id']}  {launch.get('name')}  status={ll2_name}  net={launch.get('net')}")

    tape = ensure_base_tape(launch, args.slug)
    tape, notes = apply_ll2_transition(tape, launch)

    if not notes and not args.force_write:
        print("No status/event changes.")
        if args.dump:
            print(json.dumps(tape, indent=2))
        return 0

    for n in notes:
        print(" *", n)

    written = tape_io.write_tape(tape)
    print("Wrote:")
    for w in written:
        print(" ", w)

    if args.push:
        msg = f"capture live {tape.get('slug')} status={tape.get('status')}"
        ok, detail = tape_io.git_push_changes(written, msg)
        print(("PUSH OK: " if ok else "PUSH/COMMIT: ") + detail)
        return 0 if ok else 2
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Poll LL2 and update pending mission tape (status transitions only)."
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--uuid", help="LL2 launch uuid")
    g.add_argument("--slug", help="e.g. starship-flight-14")
    g.add_argument("--search", help='e.g. "Starship Flight 14"')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", default=True, help="Single poll (default)")
    mode.add_argument("--watch", action="store_true", help="Poll until Ctrl-C")
    p.add_argument(
        "--interval",
        type=float,
        default=20.0,
        help="Watch interval seconds (Starship gold ~15-30; default 20)",
    )
    p.add_argument("--push", action="store_true", help="git add/commit/push on changes")
    p.add_argument("--force-write", action="store_true", help="Rewrite even if no changes")
    p.add_argument("--dump", action="store_true", help="Print tape JSON when unchanged")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not (args.uuid or args.slug or args.search):
        print("ERROR: provide --uuid, --slug, or --search", file=sys.stderr)
        return 2
    if args.watch:
        print(f"Watching every {args.interval}s (Ctrl-C to stop). Truth only — no invented events.")
        while True:
            try:
                one_cycle(args)
            except KeyboardInterrupt:
                print("\nStopped.")
                return 0
            except Exception as e:
                print(f"ERROR: {e}", file=sys.stderr)
            time.sleep(args.interval)
    return one_cycle(args)


if __name__ == "__main__":
    raise SystemExit(main())
