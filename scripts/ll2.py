#!/usr/bin/env python3
"""Launch Library 2 (LL2) client — stdlib only.

API: https://ll.thespacedevs.com/2.2.0/
Respect rate limits; backoff on 429.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

BASE = "https://ll.thespacedevs.com/2.2.0"
USER_AGENT = "LRT-MissionTapes/1.0 (+https://github.com/skiiwa67-collab/lrt-mission-tapes)"
DEFAULT_TIMEOUT = 20
MAX_RETRIES = 4
BACKOFF_BASE_SEC = 2.0

# LL2 status abbrev / name → mission_tape.v1 status
# Schema enum: success | failure | partial | in_flight | hold
# Pre-launch Go has no schema value → hold (preflight).
STATUS_MAP = {
    "go": "hold",
    "tbd": "hold",
    "tbc": "hold",
    "hold": "hold",
    "in flight": "in_flight",
    "success": "success",
    "failure": "failure",
    "partial failure": "partial",
}


def map_ll2_status(launch: Dict[str, Any]) -> str:
    """Map LL2 status object to tape status enum value."""
    status = launch.get("status") or {}
    abbrev = (status.get("abbrev") or "").strip().lower()
    name = (status.get("name") or "").strip().lower()
    for key in (abbrev, name):
        if key in STATUS_MAP:
            return STATUS_MAP[key]
    # Fallback by substring
    for needle, mapped in (
        ("partial", "partial"),
        ("fail", "failure"),
        ("success", "success"),
        ("flight", "in_flight"),
        ("hold", "hold"),
        ("go", "hold"),
    ):
        if needle in name or needle in abbrev:
            return mapped
    return "hold"


def is_in_flight(launch: Dict[str, Any]) -> bool:
    return map_ll2_status(launch) == "in_flight"


def is_terminal(launch: Dict[str, Any]) -> bool:
    return map_ll2_status(launch) in ("success", "failure", "partial")


def _request(url: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    last_err: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                retry_after = e.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else (
                    BACKOFF_BASE_SEC * (2 ** attempt)
                )
                time.sleep(wait)
                continue
            if e.code >= 500:
                time.sleep(BACKOFF_BASE_SEC * (2 ** attempt))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(BACKOFF_BASE_SEC * (2 ** attempt))
            continue
    raise RuntimeError(f"LL2 request failed after {MAX_RETRIES} tries: {url} ({last_err})")


def fetch_launch(uuid: str) -> Dict[str, Any]:
    """GET /launch/{uuid}/"""
    uuid = uuid.strip()
    if not uuid:
        raise ValueError("uuid required")
    url = f"{BASE}/launch/{urllib.parse.quote(uuid)}/"
    return _request(url)


def search_launches(name: str, limit: int = 10) -> List[Dict[str, Any]]:
    """GET /launch/?search=..."""
    q = urllib.parse.urlencode({"search": name, "limit": str(limit)})
    url = f"{BASE}/launch/?{q}"
    data = _request(url)
    return list(data.get("results") or [])


def find_best(name: str) -> Optional[Dict[str, Any]]:
    """Return first search hit, or None."""
    results = search_launches(name, limit=5)
    return results[0] if results else None


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="LL2 fetch/search helper")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--uuid", help="Launch UUID")
    g.add_argument("--search", help="Search by name")
    args = p.parse_args()
    if args.uuid:
        print(json.dumps(fetch_launch(args.uuid), indent=2))
    else:
        print(json.dumps(search_launches(args.search), indent=2))
