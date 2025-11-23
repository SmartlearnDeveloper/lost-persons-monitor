#!/usr/bin/env python3
"""Quick connectivity test for the dockerized Lost Persons Monitor stack."""
from __future__ import annotations

import json
from typing import Iterable, Tuple
from urllib import error, request


ServiceCheck = Tuple[str, str, bool]

CHECKS: Iterable[ServiceCheck] = (
    ("producer", "http://localhost:40140/", False),
    ("dashboard", "http://localhost:40145/", False),
    ("case_manager", "http://localhost:40150/cases?limit=1", True),
    ("kafka_connect", "http://localhost:40125/connectors", True),
)


def run_check(name: str, url: str, expect_json: bool) -> bool:
    try:
        with request.urlopen(url, timeout=5) as response:
            payload = response.read().decode("utf-8")
            if expect_json:
                json.loads(payload)
        print(f"[OK]   {name:12s} {url}")
        return True
    except (error.URLError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {name:12s} {url} -> {exc}")
        return False


def main() -> None:
    failures = [run_check(name, url, expect_json) for name, url, expect_json in CHECKS]
    if not all(failures):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
