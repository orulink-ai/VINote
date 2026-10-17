"""Smoke-check deployed services, including the frontend reverse proxy."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


class SmokeCheckError(RuntimeError):
    """Raised when a deployment smoke check fails."""


def fetch_url(url: str, timeout: float) -> tuple[int, str, Mapping[str, str]]:
    request = Request(url, headers={"User-Agent": "vinote-smoke-check/1.0"})
    opener = build_opener(ProxyHandler({}))

    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body, dict(response.headers.items())
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body, dict(exc.headers.items())
    except URLError as exc:
        raise SmokeCheckError(f"Request to {url} failed before receiving a response: {exc.reason}") from exc


def _body_preview(body: str, limit: int = 160) -> str:
    compact = " ".join(body.split())
    return compact[:limit]


def _expect_status(name: str, url: str, status: int, expected: int, body: str) -> None:
    if status == expected:
        return

    preview = _body_preview(body)
    if name == "frontend reverse proxy" and status == 502:
        raise SmokeCheckError(
            "Frontend reverse proxy check failed with 502 Bad Gateway at "
            f"{url}. This usually means nginx could not reach the backend upstream. "
            "Verify the backend process/container is running, the upstream host/port is correct, "
            f"and the backend is listening on the interface nginx is targeting. Response preview: {preview}"
        )

    raise SmokeCheckError(
        f"{name.capitalize()} check failed at {url}: expected HTTP {expected}, got {status}. "
        f"Response preview: {preview}"
    )


def _expect_json_field(name: str, url: str, body: str, field: str, expected_value: str | None = None) -> None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SmokeCheckError(f"{name.capitalize()} check at {url} did not return valid JSON.") from exc

    if field not in payload:
        raise SmokeCheckError(f"{name.capitalize()} check at {url} is missing JSON field '{field}'.")

    if expected_value is not None and payload[field] != expected_value:
        raise SmokeCheckError(
            f"{name.capitalize()} check at {url} returned unexpected '{field}' value: {payload[field]!r}."
        )


def run_checks(
    *,
    host: str,
    frontend_port: int,
    backend_port: int,
    docs_port: int | None,
    timeout: float,
) -> list[str]:
    messages: list[str] = []

    backend_url = f"http://{host}:{backend_port}/healthz"
    backend_status, backend_body, _ = fetch_url(backend_url, timeout)
    _expect_status("backend health", backend_url, backend_status, 200, backend_body)
    _expect_json_field("backend health", backend_url, backend_body, "status", "ok")
    messages.append("Backend health endpoint is healthy.")

    frontend_url = f"http://{host}:{frontend_port}/"
    frontend_status, frontend_body, _ = fetch_url(frontend_url, timeout)
    _expect_status("frontend root", frontend_url, frontend_status, 200, frontend_body)
    messages.append("Frontend root is reachable.")

    proxy_url = f"http://{host}:{frontend_port}/api/auth/session"
    proxy_status, proxy_body, _ = fetch_url(proxy_url, timeout)
    _expect_status("frontend reverse proxy", proxy_url, proxy_status, 200, proxy_body)
    _expect_json_field("frontend reverse proxy", proxy_url, proxy_body, "authenticated")
    messages.append("Frontend reverse proxy to /api is healthy.")

    if docs_port is not None:
        docs_url = f"http://{host}:{docs_port}/"
        docs_status, docs_body, _ = fetch_url(docs_url, timeout)
        _expect_status("docs root", docs_url, docs_status, 200, docs_body)
        messages.append("Docs root is reachable.")

    return messages


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Host name or IP to probe.")
    parser.add_argument("--frontend-port", type=int, default=3100, help="Frontend HTTP port.")
    parser.add_argument("--backend-port", type=int, default=8900, help="Backend HTTP port.")
    parser.add_argument("--docs-port", type=int, default=3101, help="Docs HTTP port.")
    parser.add_argument("--skip-docs", action="store_true", help="Skip the docs probe.")
    parser.add_argument("--timeout", type=float, default=5.0, help="Per-request timeout in seconds.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    try:
        messages = run_checks(
            host=args.host,
            frontend_port=args.frontend_port,
            backend_port=args.backend_port,
            docs_port=None if args.skip_docs else args.docs_port,
            timeout=args.timeout,
        )
    except SmokeCheckError as exc:
        print(f"Smoke check failed: {exc}", file=sys.stderr)
        return 1

    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
