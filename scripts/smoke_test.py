"""Simple smoke test for local running service.

Usage:
    python scripts/smoke_test.py

Default target:
    http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


BASE_URL = "http://127.0.0.1:8000"


def check_health(base_url: str = BASE_URL) -> int:
    url = f"{base_url}/health"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            status_code = response.getcode()
            payload = response.read().decode("utf-8")
            data = json.loads(payload)
    except urllib.error.URLError as exc:
        print(f"[FAIL] GET {url} failed: {exc}")
        return 1

    if status_code != 200:
        print(f"[FAIL] GET {url} returned status {status_code}")
        return 1

    if data.get("status") != "ok":
        print(f"[FAIL] Unexpected health payload: {data}")
        return 1

    print(f"[PASS] GET {url} -> 200, payload={data}")
    print(f"[INFO] Open Swagger docs manually: {base_url}/docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(check_health(sys.argv[1] if len(sys.argv) > 1 else BASE_URL))
