#!/usr/bin/env python3
"""Operator stamp of a confirmed webcast/agency call-out onto a mission tape.

Never guess times. Dedup by event id. Optional --push.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tape_io  # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Stamp one confirmed event onto a mission tape (dedup by id)."
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--uuid")
    g.add_argument("--slug")
    p.add_argument("--id", required=True, help="Event id e.g. ss14_meco")
    p.add_argument("--t_sec", type=float, required=True, help="Seconds from T0 (confirmed)")
    p.add_argument("--title", required=True)
    p.add_argument("--detail", default="")
    p.add_argument(
        "--severity",
        default="INFO",
        choices=sorted(tape_io.VALID_SEVERITY),
    )
    p.add_argument("--push", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    tape, path = tape_io.load_tape(uuid=args.uuid, slug=args.slug)

    # Normalize t_sec: prefer int when whole number
    t = args.t_sec
    t_sec: int | float = int(t) if float(t).is_integer() else float(t)

    ev = {
        "id": args.id,
        "t_sec": t_sec,
        "title": args.title,
        "detail": args.detail,
        "severity": args.severity,
    }

    events = list(tape.get("events") or [])
    replaced = False
    for i, existing in enumerate(events):
        if existing.get("id") == args.id:
            events[i] = ev
            replaced = True
            break
    if not replaced:
        events.append(ev)

    events.sort(key=lambda e: (e.get("t_sec", 0), e.get("id") or ""))
    tape["events"] = events
    # Stamping confirmed call-outs: still pending until lock unless already locked
    if tape.get("pending") is not False:
        tape["pending"] = True
        if tape.get("truth") not in ("published", "observed"):
            tape["truth"] = "pending"

    if args.dry_run:
        import json

        print(json.dumps(ev, indent=2))
        print(f"would {'replace' if replaced else 'append'} on {path} ({len(events)} events)")
        return 0

    written = tape_io.write_tape(tape)
    action = "replaced" if replaced else "appended"
    print(f"{action} event {args.id} t_sec={t_sec} → {len(events)} events")
    for w in written:
        print(" ", w)

    if args.push:
        ok, detail = tape_io.git_push_changes(
            written, f"stamp {args.id} on {tape.get('slug')} t={t_sec}"
        )
        print(("PUSH OK: " if ok else "PUSH/COMMIT: ") + detail)
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
