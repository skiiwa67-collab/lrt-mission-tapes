#!/usr/bin/env python3
"""Mission tape load/save/validate + index upsert — stdlib only."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = "lrt.mission_tape.v1"
INDEX_SCHEMA = "lrt.mission_tape_index.v1"
CDN_BASE = "https://raw.githubusercontent.com/skiiwa67-collab/lrt-mission-tapes/main/v1"

VALID_TRUTH = {"observed", "published", "pending"}
VALID_STATUS = {"success", "failure", "partial", "in_flight", "hold"}
VALID_SEVERITY = {"INFO", "WATCH", "FAIL"}
VALID_T0_SOURCE = {"liftoff_observed", "ll2_net", "agency"}

REPO_ROOT = Path(__file__).resolve().parent.parent
V1_DIR = REPO_ROOT / "v1"
INDEX_PATH = V1_DIR / "index.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_root() -> Path:
    return REPO_ROOT


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def validate_tape(tape: Dict[str, Any], strict: bool = False) -> List[str]:
    """Return list of validation errors (empty = OK). Minimal schema check."""
    errs: List[str] = []
    if tape.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA}")
    if not tape.get("id"):
        errs.append("id required")
    if not tape.get("slug"):
        errs.append("slug required")
    truth = tape.get("truth")
    if truth not in VALID_TRUTH:
        errs.append(f"truth must be one of {sorted(VALID_TRUTH)}")
    status = tape.get("status")
    if status is not None and status not in VALID_STATUS:
        errs.append(f"status must be one of {sorted(VALID_STATUS)}")
    if "pending" not in tape or not isinstance(tape["pending"], bool):
        errs.append("pending bool required")
    if "events" not in tape or not isinstance(tape["events"], list):
        errs.append("events list required")
    else:
        for i, ev in enumerate(tape["events"]):
            if not isinstance(ev, dict):
                errs.append(f"events[{i}] must be object")
                continue
            for k in ("id", "t_sec", "title", "severity"):
                if k not in ev:
                    errs.append(f"events[{i}].{k} required")
            if "severity" in ev and ev["severity"] not in VALID_SEVERITY:
                errs.append(f"events[{i}].severity invalid")
            if "t_sec" in ev and not isinstance(ev["t_sec"], (int, float)):
                errs.append(f"events[{i}].t_sec must be number")
    if strict:
        if tape.get("t0_source") and tape["t0_source"] not in VALID_T0_SOURCE:
            errs.append(f"t0_source must be one of {sorted(VALID_T0_SOURCE)}")
    return errs


def touch_updated(tape: Dict[str, Any]) -> Dict[str, Any]:
    tape = dict(tape)
    tape["updated_utc"] = utc_now_iso()
    return tape


def alias_path_for_slug(slug: str) -> Optional[Path]:
    """starship-flight-N → v1/starship/flight-N.json"""
    if slug.startswith("starship-flight-"):
        n = slug[len("starship-flight-") :]
        if n.isdigit():
            return V1_DIR / "starship" / f"flight-{n}.json"
    return None


def uuid_path(uuid: str) -> Path:
    return V1_DIR / f"{uuid}.json"


def resolve_tape_path(
    *,
    uuid: Optional[str] = None,
    slug: Optional[str] = None,
) -> Path:
    """Prefer alias for starship slug; else uuid file; else search index/aliases."""
    if slug:
        alias = alias_path_for_slug(slug)
        if alias and alias.exists():
            return alias
        # scan starship aliases
        star = V1_DIR / "starship"
        if star.is_dir():
            for p in sorted(star.glob("flight-*.json")):
                try:
                    t = load_json(p)
                    if t.get("slug") == slug:
                        return p
                except (OSError, json.JSONDecodeError):
                    continue
    if uuid:
        p = uuid_path(uuid)
        if p.exists():
            return p
        # find by id in aliases
        star = V1_DIR / "starship"
        if star.is_dir():
            for ap in sorted(star.glob("flight-*.json")):
                try:
                    t = load_json(ap)
                    if t.get("id") == uuid:
                        return ap
                except (OSError, json.JSONDecodeError):
                    continue
        return p  # may not exist yet
    raise FileNotFoundError("need --uuid or --slug to resolve tape")


def load_tape(*, uuid: Optional[str] = None, slug: Optional[str] = None) -> Tuple[Dict[str, Any], Path]:
    path = resolve_tape_path(uuid=uuid, slug=slug)
    if not path.exists():
        raise FileNotFoundError(f"tape not found: {path}")
    tape = load_json(path)
    errs = validate_tape(tape)
    if errs:
        raise ValueError("invalid tape at {}: {}".format(path, "; ".join(errs)))
    return tape, path


def upsert_index(tape: Dict[str, Any]) -> None:
    """Upsert pack entry into v1/index.json."""
    slug = tape["slug"]
    alias = alias_path_for_slug(slug)
    if alias:
        rel = str(alias.relative_to(V1_DIR)).replace("\\", "/")
    else:
        rel = f"{tape['id']}.json"

    if INDEX_PATH.exists():
        idx = load_json(INDEX_PATH)
    else:
        idx = {
            "schema": INDEX_SCHEMA,
            "updated_utc": utc_now_iso(),
            "base": CDN_BASE,
            "packs": [],
        }

    packs: List[Dict[str, Any]] = list(idx.get("packs") or [])
    entry = {
        "slug": slug,
        "path": rel,
        "truth": tape.get("truth", "pending"),
        "pending": bool(tape.get("pending", True)),
    }
    if tape.get("id") and not str(tape["id"]).startswith("PENDING"):
        entry["id"] = tape["id"]

    replaced = False
    for i, p in enumerate(packs):
        if p.get("slug") == slug or (entry.get("id") and p.get("id") == entry.get("id")):
            packs[i] = entry
            replaced = True
            break
    if not replaced:
        packs.append(entry)

    packs.sort(key=lambda x: x.get("slug") or "")
    idx["schema"] = INDEX_SCHEMA
    idx["base"] = CDN_BASE
    idx["updated_utc"] = utc_now_iso()
    idx["packs"] = packs
    save_json(INDEX_PATH, idx)


def write_tape(
    tape: Dict[str, Any],
    *,
    write_uuid_file: bool = True,
    write_alias: bool = True,
    update_index: bool = True,
) -> List[Path]:
    """Validate, stamp updated_utc, write uuid + optional alias, upsert index."""
    tape = touch_updated(tape)
    errs = validate_tape(tape)
    if errs:
        raise ValueError("cannot write invalid tape: " + "; ".join(errs))

    written: List[Path] = []
    tid = tape["id"]
    slug = tape["slug"]

    if write_uuid_file and tid and not str(tid).startswith("PENDING"):
        up = uuid_path(tid)
        save_json(up, tape)
        written.append(up)

    if write_alias:
        ap = alias_path_for_slug(slug)
        if ap:
            save_json(ap, tape)
            written.append(ap)
        elif not written:
            # fallback: write by uuid path only already handled; if PENDING write alias-less
            up = uuid_path(tid) if tid else V1_DIR / f"{slug}.json"
            save_json(up, tape)
            written.append(up)

    if update_index:
        upsert_index(tape)

    return written


def git_push_changes(paths: List[Path], message: str) -> Tuple[bool, str]:
    """git add paths, commit, push. Returns (ok, detail). Only if intentional diffs."""
    rels = []
    for p in paths:
        try:
            rels.append(str(p.resolve().relative_to(REPO_ROOT)))
        except ValueError:
            rels.append(str(p))
    # always include index if present
    if INDEX_PATH.exists():
        idx_rel = str(INDEX_PATH.relative_to(REPO_ROOT))
        if idx_rel not in rels:
            rels.append(idx_rel)

    try:
        subprocess.run(
            ["git", "add", "--"] + rels,
            cwd=str(REPO_ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        st = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(REPO_ROOT),
            capture_output=True,
        )
        if st.returncode == 0:
            return False, "no staged changes; skip commit/push"
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(REPO_ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        push = subprocess.run(
            ["git", "push", "origin", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        if push.returncode != 0:
            return False, f"commit ok; push failed: {push.stderr.strip() or push.stdout.strip()}"
        return True, "commit+push ok"
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or str(e)).strip()
        return False, f"git failed: {err}"


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Tape I/O helpers")
    p.add_argument("--validate", metavar="PATH", help="Validate a tape JSON file")
    args = p.parse_args()
    if args.validate:
        t = load_json(Path(args.validate))
        errs = validate_tape(t)
        if errs:
            print("INVALID:")
            for e in errs:
                print(" -", e)
            raise SystemExit(1)
        print("OK", args.validate)
