#!/usr/bin/env python3
"""Safe, read-only black-box contract probe for disposable Wings nodes."""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import ssl
import statistics
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any


MAX_RESPONSE_BYTES = 1024 * 1024
CONFIRMATION = "these-are-disposable-nodes"
CASES = (
    ("system_without_auth", "GET", "/api/system?v=2", "none", {401, 403}),
    ("system_with_bad_auth", "GET", "/api/system?v=2", "bad", {401, 403}),
    ("system", "GET", "/api/system?v=2", "valid", {200}),
    ("servers", "GET", "/api/servers", "valid", {200}),
)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


HTTP_OPENER = urllib.request.build_opener(
    NoRedirectHandler(),
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
)


@dataclass(frozen=True)
class Target:
    name: str
    base_url: str
    token: str


@dataclass
class Observation:
    case: str
    method: str
    path: str
    expected_statuses: list[int]
    statuses: list[int]
    passed: bool
    samples: int
    successes: int
    failures: int
    min_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float | None
    content_type: str | None
    json_type: str | None
    json_schema: list[str]
    error_types: list[str]


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None

    ordered = sorted(values)
    index = max(0, math.ceil(percentile_value * len(ordered)) - 1)
    return round(ordered[index], 3)


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def schema_paths(value: Any, prefix: str = "$") -> list[str]:
    """Return value-free JSON shape paths so reports cannot leak node data."""

    paths = [f"{prefix}:{type_name(value)}"]
    if isinstance(value, dict):
        for key in sorted(value):
            paths.extend(schema_paths(value[key], f"{prefix}.{key}"))
    elif isinstance(value, list) and value:
        paths.extend(schema_paths(value[0], f"{prefix}[]"))

    return paths


def validate_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("target URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("target URL must not contain credentials, query, or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("non-loopback targets must use HTTPS")

    return base_url.rstrip("/")


def request_once(
    target: Target,
    method: str,
    path: str,
    auth_mode: str,
    timeout: float,
) -> tuple[int | None, float, str | None, Any | None, str | None]:
    headers = {"Accept": "application/json", "User-Agent": "NekoHosting-Wings-Lab/1"}
    if auth_mode == "valid":
        headers["Authorization"] = f"Bearer {target.token}"
    elif auth_mode == "bad":
        headers["Authorization"] = "Bearer intentionally-invalid-lab-token"

    request = urllib.request.Request(
        f"{target.base_url}{path}", method=method, headers=headers
    )
    started = time.monotonic()
    status: int | None = None
    content_type: str | None = None
    payload: bytes = b""

    try:
        with HTTP_OPENER.open(request, timeout=timeout) as response:
            status = response.status
            content_type = response.headers.get_content_type()
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        status = error.code
        content_type = error.headers.get_content_type()
        payload = error.read(MAX_RESPONSE_BYTES + 1)
    except (TimeoutError, urllib.error.URLError, OSError) as error:
        elapsed = (time.monotonic() - started) * 1000
        return None, elapsed, None, None, type(error).__name__

    elapsed = (time.monotonic() - started) * 1000
    if len(payload) > MAX_RESPONSE_BYTES:
        return status, elapsed, content_type, None, "ResponseTooLarge"

    decoded: Any | None = None
    if payload and content_type == "application/json":
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return status, elapsed, content_type, None, "InvalidJson"

    return status, elapsed, content_type, decoded, None


def probe_target(target: Target, samples: int, timeout: float) -> list[Observation]:
    observations: list[Observation] = []

    for case, method, path, auth_mode, expected_statuses in CASES:
        case_samples = samples if auth_mode == "valid" else 1
        statuses: list[int] = []
        durations: list[float] = []
        errors: list[str] = []
        shape: list[str] = []
        json_kind: str | None = None
        content_type: str | None = None

        for _ in range(case_samples):
            status, duration, response_type, payload, error = request_once(
                target, method, path, auth_mode, timeout
            )
            durations.append(duration)
            if status is not None:
                statuses.append(status)
            if error:
                errors.append(error)
            if response_type:
                content_type = response_type
            if payload is not None and not shape:
                json_kind = type_name(payload)
                shape = schema_paths(payload)

        successes = sum(status in expected_statuses for status in statuses)
        failures = case_samples - successes
        observations.append(
            Observation(
                case=case,
                method=method,
                path=path,
                expected_statuses=sorted(expected_statuses),
                statuses=statuses,
                passed=failures == 0,
                samples=case_samples,
                successes=successes,
                failures=failures,
                min_ms=round(min(durations), 3) if durations else None,
                p50_ms=round(statistics.median(durations), 3) if durations else None,
                p95_ms=percentile(durations, 0.95),
                max_ms=round(max(durations), 3) if durations else None,
                content_type=content_type,
                json_type=json_kind,
                json_schema=shape,
                error_types=sorted(set(errors)),
            )
        )

    return observations


def comparison(observations: dict[str, list[Observation]]) -> dict[str, Any]:
    catwings = {item.case: item for item in observations["catwings"]}
    calagopus = {item.case: item for item in observations["calagopus"]}
    cases: dict[str, Any] = {}

    for case in sorted(catwings.keys() & calagopus.keys()):
        left = catwings[case]
        right = calagopus[case]
        requires_response_compatibility = case in {"system", "servers"}
        same_json_type = left.json_type == right.json_type
        catwings_schema_supported = set(left.json_schema) <= set(right.json_schema)
        compatible = left.passed and right.passed
        if requires_response_compatibility:
            compatible = compatible and same_json_type and catwings_schema_supported
        cases[case] = {
            "both_passed": left.passed and right.passed,
            "same_json_type": same_json_type,
            "same_json_schema": left.json_schema == right.json_schema,
            "catwings_schema_supported": catwings_schema_supported,
            "compatible": compatible,
            "catwings_p50_ms": left.p50_ms,
            "calagopus_p50_ms": right.p50_ms,
        }

    return {
        "cases": cases,
        "all_contracts_passed": all(v["compatible"] for v in cases.values()),
    }


def atomic_write_json(path: pathlib.Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".contract-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catwings-url", default=os.getenv("CATWINGS_LAB_URL"))
    parser.add_argument("--calagopus-url", default=os.getenv("CALAGOPUS_LAB_URL"))
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument(
        "--confirm-disposable",
        help=f"must equal {CONFIRMATION!r}; prevents accidental production probes",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.confirm_disposable != CONFIRMATION:
        raise SystemExit(
            f"refusing to probe: pass --confirm-disposable {CONFIRMATION} only for disposable nodes"
        )
    if not 1 <= args.samples <= 100:
        raise SystemExit("samples must be between 1 and 100")
    if not 0.25 <= args.timeout <= 30:
        raise SystemExit("timeout must be between 0.25 and 30 seconds")

    raw_targets = {
        "catwings": (args.catwings_url, os.getenv("CATWINGS_LAB_TOKEN")),
        "calagopus": (args.calagopus_url, os.getenv("CALAGOPUS_LAB_TOKEN")),
    }
    targets: dict[str, Target] = {}
    for name, (base_url, token) in raw_targets.items():
        if not base_url or not token:
            raise SystemExit(
                f"{name} lab URL and token must be supplied through lab environment variables"
            )
        try:
            validated_url = validate_base_url(base_url)
        except ValueError as error:
            raise SystemExit(f"invalid {name} lab URL: {error}") from error
        targets[name] = Target(name, validated_url, token)

    observed = {
        name: probe_target(target, args.samples, args.timeout)
        for name, target in targets.items()
    }
    report = {
        "format_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "safety": {
            "mode": "read-only",
            "redirects_followed": False,
            "response_values_retained": False,
            "target_urls_retained": False,
            "tokens_retained": False,
        },
        "latency": {"connection_model": "cold-request; no persistent connection"},
        "engines": {
            name: [asdict(item) for item in items] for name, items in observed.items()
        },
        "comparison": comparison(observed),
    }
    atomic_write_json(args.output, report)

    return 0 if report["comparison"]["all_contracts_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
