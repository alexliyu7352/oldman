"""Compare the legacy JSON payload path with typed MessagePack serialization.

Run explicitly with::

    uv run python -m tests.performance.session_benchmark

This is a local serialization benchmark, not an end-to-end Redis or multi-worker
Web benchmark.  It protects the hot local work added by snapshot comparison; the
consumer-level Web benchmark remains part of the later S2 integration stage.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable
from typing import Any

import msgspec
import ujson

from oldman.serializers import MsgspecModel
from oldman.web.session import SessionData

DEFAULT_ITERATIONS = 100_000
DEFAULT_ROUNDS = 7


class BenchmarkProfile(MsgspecModel, kw_only=True):
    """Representative nested session profile."""

    roles: list[str] = msgspec.field(default_factory=list)


class BenchmarkSessionData(SessionData, kw_only=True):
    """Representative Admin-like typed session payload."""

    display_name: str = ""
    login_time: int = 0
    ip: str = ""
    profile: BenchmarkProfile = msgspec.field(default_factory=BenchmarkProfile)


def _parser() -> argparse.ArgumentParser:
    """Build the intentionally small benchmark command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    return parser


def _measure(operation: Callable[[], object], iterations: int, rounds: int) -> dict[str, float]:
    """Measure wall and CPU time per operation across repeated batches."""
    wall_samples: list[float] = []
    cpu_samples: list[float] = []
    for _round in range(rounds):
        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        for _iteration in range(iterations):
            operation()
        cpu_samples.append((time.process_time() - cpu_started) / iterations)
        wall_samples.append((time.perf_counter() - wall_started) / iterations)
    return {
        "wall_ns_median": statistics.median(wall_samples) * 1_000_000_000,
        "wall_ns_max": max(wall_samples) * 1_000_000_000,
        "cpu_ns_median": statistics.median(cpu_samples) * 1_000_000_000,
        "cpu_ns_max": max(cpu_samples) * 1_000_000_000,
    }


def _payloads() -> tuple[dict[str, Any], BenchmarkSessionData]:
    """Return semantically equivalent legacy and typed payloads."""
    legacy = {
        "user_id": 123,
        "is_active": True,
        "username": "alice",
        "display_name": "Alice Example",
        "is_staff": True,
        "is_superuser": False,
        "login_time": 1_754_000_000,
        "ip": "203.0.113.25",
        "profile": {"roles": ["staff", "editor", "auditor"]},
        "_session_expiry": 2_592_000,
    }
    typed = BenchmarkSessionData(
        expiry=2_592_000,
        user_id=123,
        is_active=True,
        username="alice",
        display_name="Alice Example",
        is_staff=True,
        is_superuser=False,
        login_time=1_754_000_000,
        ip="203.0.113.25",
        profile=BenchmarkProfile(roles=["staff", "editor", "auditor"]),
    )
    return legacy, typed


def run(iterations: int, rounds: int) -> dict[str, object]:
    """Run each serialization path and return machine-readable measurements."""
    if iterations <= 0 or rounds <= 0:
        raise ValueError("iterations and rounds must be greater than zero")

    legacy, typed = _payloads()
    legacy_json = ujson.dumps(legacy)
    typed_snapshot = typed.to_msgpack()
    data_decoder = msgspec.msgpack.Decoder(type=BenchmarkSessionData)

    def legacy_encode() -> str:
        """Encode the legacy dict and embedded expiry once."""
        return ujson.dumps(legacy)

    def legacy_decode() -> dict[str, Any]:
        """Decode the legacy JSON value into an untyped dict."""
        return ujson.loads(legacy_json)

    def typed_snapshot_encode() -> bytes:
        """Encode the current model once for response modification detection."""
        return typed.to_msgpack()

    def typed_decode() -> BenchmarkSessionData:
        """Decode the direct Redis value as its exact application model."""
        return data_decoder.decode(typed_snapshot)

    operations = {
        "legacy_json_encode": legacy_encode,
        "legacy_json_decode": legacy_decode,
        "typed_unchanged_snapshot_encode": typed_snapshot_encode,
        "typed_session_decode": typed_decode,
    }
    results = {name: _measure(operation, iterations, rounds) for name, operation in operations.items()}
    return {
        "iterations_per_round": iterations,
        "rounds": rounds,
        "payload_bytes": {
            "legacy_json": len(legacy_json.encode("utf-8")),
            "typed_messagepack_session": len(typed_snapshot),
        },
        "results": results,
    }


def main() -> None:
    """Parse arguments, execute the benchmark, and print stable JSON."""
    arguments = _parser().parse_args()
    print(json.dumps(run(arguments.iterations, arguments.rounds), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
