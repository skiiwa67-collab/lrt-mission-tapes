#!/usr/bin/env python3
"""Seed a sparse pending mission tape stub (Starship gold = Flight 14)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ll2  # noqa: E402
import tape_io  # noqa: E402


def build_stub(
    *,
    uuid: str,
    slug: str,
    name: str,
    family: str,
    vehicle: str,
    provider: str,
    goal: str,
    t0_utc: str | None,
    t0_source: str,
    status: str,
    agency_url: str | None,
    with_liftoff: bool,
) -> dict:
    sources = []
    if agency_url:
        sources.append({"kind": "agency", "url": agency_url, "note": "Mission page"})
    sources.append({"kind": "ll2", "id": uuid})

    events = []
    if with_liftoff:
        prefix = "ss"
        if slug.startswith("starship-flight-"):
            n = slug.split("-")[-1]
            prefix = f"ss{n}"
        events.append(
            {
                "id": f"{prefix}_lift",
                "t_sec": 0,
                "title": "LIFTOFF",
                "detail": f"{vehicle} stack",
                "severity": "INFO",
            }
        )

    tape = {
        "schema": tape_io.SCHEMA,
        "id": uuid,
        "slug": slug,
        "family": family,
        "vehicle": vehicle,
        "name": name,
        "provider": provider,
        "truth": "pending",
        "truth_note": (
            "Sparse pending stub. No invented mid-flight events. "
            "App shows PENDING REAL TELEMETRY until published/observed lock. VID OK."
        ),
        "status": status,
        "t0_source": t0_source,
        "updated_utc": tape_io.utc_now_iso(),
        "sources": sources,
        "goal": goal,
        "outcome": {},
        "events": events,
        "pending": True,
    }
    if t0_utc:
        tape["t0_utc"] = t0_utc
    return tape


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Seed sparse pending mission tape (never invent mid-flight events)."
    )
    p.add_argument("--uuid", help="LL2 launch uuid (or PENDING_LL2_UUID)")
    p.add_argument("--slug", default="starship-flight-14")
    p.add_argument("--search", help="Resolve uuid via LL2 search")
    p.add_argument("--name", default=None, help="Display name (default from slug/LL2)")
    p.add_argument("--family", default="starship")
    p.add_argument("--vehicle", default="Starship")
    p.add_argument("--provider", default="SpaceX")
    p.add_argument("--goal", default="PERFORMANCE TEST")
    p.add_argument(
        "--status",
        default="hold",
        choices=sorted(tape_io.VALID_STATUS),
        help="Preflight: hold (Go maps to hold in schema). in_flight only after live.",
    )
    p.add_argument("--t0-utc", default=None, help="ISO Z NET or liftoff if known")
    p.add_argument(
        "--t0-source",
        default="ll2_net",
        choices=sorted(tape_io.VALID_T0_SOURCE),
    )
    p.add_argument(
        "--agency-url",
        default=None,
        help="Agency mission page URL",
    )
    p.add_argument(
        "--with-liftoff",
        action="store_true",
        help="Include LIFTOFF t_sec=0 only (still pending truth)",
    )
    p.add_argument("--dry-run", action="store_true", help="Print JSON; do not write")
    p.add_argument("--push", action="store_true", help="git add/commit/push after write")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    uuid = args.uuid
    name = args.name
    t0_utc = args.t0_utc
    agency_url = args.agency_url
    status = args.status

    if args.search and not uuid:
        hit = ll2.find_best(args.search)
        if not hit:
            print(f"ERROR: LL2 search found nothing for {args.search!r}", file=sys.stderr)
            return 1
        uuid = hit["id"]
        name = name or hit.get("name")
        t0_utc = t0_utc or hit.get("net")
        status = ll2.map_ll2_status(hit) if args.status == "hold" else status
        print(f"LL2 resolved: {uuid}  status={hit.get('status',{}).get('name')}  net={hit.get('net')}")

    if not uuid:
        # Flight 14 gold default: try LL2, else placeholder
        if args.slug == "starship-flight-14":
            hit = ll2.find_best("Starship Flight 14")
            if hit:
                uuid = hit["id"]
                name = name or hit.get("name")
                t0_utc = t0_utc or hit.get("net")
                if args.status == "hold":
                    status = ll2.map_ll2_status(hit)
                print(f"LL2 resolved F14: {uuid}  net={hit.get('net')}")
            else:
                uuid = "PENDING_LL2_UUID"
                print("WARN: LL2 search failed; using PENDING_LL2_UUID", file=sys.stderr)
        else:
            print("ERROR: --uuid or --search required (unless default F14)", file=sys.stderr)
            return 1

    if not name:
        if args.slug.startswith("starship-flight-"):
            n = args.slug.split("-")[-1]
            name = f"Starship | Flight {n}"
        else:
            name = args.slug

    if not agency_url and args.family == "starship" and args.slug.startswith("starship-flight-"):
        n = args.slug.split("-")[-1]
        agency_url = f"https://www.spacex.com/launches/starship-flight-{n}"

    tape = build_stub(
        uuid=uuid,
        slug=args.slug,
        name=name,
        family=args.family,
        vehicle=args.vehicle,
        provider=args.provider,
        goal=args.goal,
        t0_utc=t0_utc,
        t0_source=args.t0_source,
        status=status,
        agency_url=agency_url,
        with_liftoff=args.with_liftoff,
    )

    if args.dry_run:
        print(json.dumps(tape, indent=2, ensure_ascii=False))
        return 0

    written = tape_io.write_tape(tape)
    print("Wrote:")
    for w in written:
        print(" ", w)
    print(" ", tape_io.INDEX_PATH)

    if args.push:
        ok, detail = tape_io.git_push_changes(written, f"seed pending tape {args.slug}")
        print(("PUSH OK: " if ok else "PUSH/COMMIT: ") + detail)
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
