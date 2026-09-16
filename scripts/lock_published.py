#!/usr/bin/env python3
"""Lock a mission tape from agency/SpaceX published (or observed) timeline.

Merges events from a JSON file (array or full tape), sets pending=false,
truth=published|observed, optional status/outcome. Never invents times —
caller supplies the published file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tape_io  # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Merge published/observed events and lock tape (pending=false)."
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--uuid")
    g.add_argument("--slug")
    p.add_argument(
        "--from",
        dest="from_path",
        required=True,
        metavar="PATH",
        help="JSON file: event array OR full tape body to merge",
    )
    p.add_argument(
        "--truth",
        default="published",
        choices=["published", "observed"],
    )
    p.add_argument("--truth-note", default=None)
    p.add_argument(
        "--status",
        default=None,
        choices=sorted(tape_io.VALID_STATUS),
    )
    p.add_argument("--t0-utc", default=None)
    p.add_argument(
        "--t0-source",
        default=None,
        choices=sorted(tape_io.VALID_T0_SOURCE),
    )
    p.add_argument(
        "--outcome-json",
        default=None,
        help='Outcome object JSON e.g. \'{"booster":"...","ship":"..."}\'',
    )
    p.add_argument(
        "--replace-events",
        action="store_true",
        help="Replace events entirely from --from (default: merge/upsert by id)",
    )
    p.add_argument("--push", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def load_events_or_tape(path: Path) -> tuple[list, dict]:
    """Return (events, overlay_fields_from_full_tape)."""
    data = tape_io.load_json(path)
    if isinstance(data, list):
        return data, {}
    if isinstance(data, dict):
        events = list(data.get("events") or [])
        overlay = {}
        for k in (
            "status",
            "t0_utc",
            "t0_source",
            "outcome",
            "truth_note",
            "name",
            "goal",
            "sources",
        ):
            if k in data and data[k] is not None:
                overlay[k] = data[k]
        return events, overlay
    raise ValueError("--from must be a JSON array or object")


def merge_events(existing: list, incoming: list, replace: bool) -> list:
    if replace:
        merged = list(incoming)
    else:
        by_id = {e["id"]: e for e in existing if isinstance(e, dict) and "id" in e}
        for e in incoming:
            if not isinstance(e, dict) or "id" not in e:
                raise ValueError("each event needs id")
            by_id[e["id"]] = e
        merged = list(by_id.values())
    merged.sort(key=lambda e: (e.get("t_sec", 0), e.get("id") or ""))
    return merged


def main(argv=None) -> int:
    args = parse_args(argv)
    tape, path = tape_io.load_tape(uuid=args.uuid, slug=args.slug)
    incoming, overlay = load_events_or_tape(Path(args.from_path))

    # Validate incoming events minimally
    for i, e in enumerate(incoming):
        for k in ("id", "t_sec", "title", "severity"):
            if k not in e:
                print(f"ERROR: incoming events[{i}] missing {k}", file=sys.stderr)
                return 1
        if e["severity"] not in tape_io.VALID_SEVERITY:
            print(f"ERROR: bad severity {e['severity']}", file=sys.stderr)
            return 1

    tape["events"] = merge_events(list(tape.get("events") or []), incoming, args.replace_events)

    for k, v in overlay.items():
        if k == "sources":
            # merge sources by kind+url/id
            existing = list(tape.get("sources") or [])
            for s in v:
                if s not in existing:
                    existing.append(s)
            tape["sources"] = existing
        else:
            tape[k] = v

    if args.status:
        tape["status"] = args.status
    if args.t0_utc:
        tape["t0_utc"] = args.t0_utc
    if args.t0_source:
        tape["t0_source"] = args.t0_source
    if args.outcome_json:
        tape["outcome"] = json.loads(args.outcome_json)
    if args.truth_note:
        tape["truth_note"] = args.truth_note
    elif not tape.get("truth_note"):
        tape["truth_note"] = (
            f"Events locked from agency/published timeline ({args.truth}). Not MCC downlink."
        )

    tape["truth"] = args.truth
    tape["pending"] = False

    errs = tape_io.validate_tape(tape, strict=True)
    if errs:
        print("ERROR invalid after lock:", "; ".join(errs), file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps(tape, indent=2, ensure_ascii=False))
        return 0

    written = tape_io.write_tape(tape)
    print(f"LOCKED {tape.get('slug')} truth={tape['truth']} pending=false events={len(tape['events'])}")
    for w in written:
        print(" ", w)

    if args.push:
        ok, detail = tape_io.git_push_changes(
            written, f"lock published {tape.get('slug')} truth={args.truth}"
        )
        print(("PUSH OK: " if ok else "PUSH/COMMIT: ") + detail)
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
