from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request


@dataclass(frozen=True)
class CheckResult:
    name: str
    url: str
    ok: bool
    detail: str


def _fetch_json(url: str, timeout: float) -> tuple[bool, str]:
    try:
        with request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            if response.status < 200 or response.status >= 300:
                return False, f"HTTP {response.status}: {body[:200]}"
            try:
                parsed: Any = json.loads(body)
            except json.JSONDecodeError:
                return False, f"expected JSON, got: {body[:200]}"
            if parsed.get("status") != "ok":
                return False, f"unexpected JSON payload: {parsed!r}"
            return True, "ok"
    except error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        return False, str(exc)


def _fetch_text(url: str, timeout: float) -> tuple[bool, str]:
    try:
        with request.urlopen(url, timeout=timeout) as response:
            body = response.read(200).decode("utf-8", errors="replace")
            if response.status < 200 or response.status >= 300:
                return False, f"HTTP {response.status}: {body[:200]}"
            return True, "ok"
    except error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        return False, str(exc)


def _wait_for_check(name: str, url: str, timeout: float, deadline: float, json_health: bool) -> CheckResult:
    last_detail = "not checked"
    while time.monotonic() < deadline:
        ok, detail = _fetch_json(url, timeout) if json_health else _fetch_text(url, timeout)
        if ok:
            return CheckResult(name=name, url=url, ok=True, detail=detail)
        last_detail = detail
        time.sleep(1)
    return CheckResult(name=name, url=url, ok=False, detail=last_detail)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-check a running RAG stack.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000/api/health")
    parser.add_argument("--frontend-url", default="http://127.0.0.1")
    parser.add_argument("--timeout", type=float, default=3.0, help="Per-request timeout in seconds.")
    parser.add_argument("--wait", type=float, default=30.0, help="Total wait time in seconds.")
    parser.add_argument("--skip-frontend", action="store_true", help="Only check the backend health endpoint.")
    args = parser.parse_args()

    deadline = time.monotonic() + args.wait
    checks = [
        _wait_for_check("backend", args.backend_url, args.timeout, deadline, json_health=True),
    ]
    if not args.skip_frontend:
        checks.append(_wait_for_check("frontend", args.frontend_url, args.timeout, deadline, json_health=False))

    for item in checks:
        status = "PASS" if item.ok else "FAIL"
        print(f"[{status}] {item.name}: {item.url} ({item.detail})")

    return 0 if all(item.ok for item in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
