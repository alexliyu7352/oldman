"""Measure paired filesystem and memory storage workloads without enforcing thresholds.

Run explicitly with::

    .venv/bin/python tests/performance/storage_benchmark.py

Every output line is one stable JSON object suitable for later collection.  The
benchmark validates operation results, but elapsed time and throughput are
observations rather than release gates.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from collections import defaultdict
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Iterator
from concurrent.futures import Executor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from unittest.mock import patch

import aiofiles
from aiofiles.threadpool.binary import AsyncBufferedIOBase

from oldman.storage.backends.filesystem import FileSystemStorage
from oldman.storage.backends.memory import InMemoryStorage
from oldman.storage.base import Storage

type BackendName = Literal["filesystem", "memory"]
type VariantName = Literal[
    "filesystem_storage",
    "filesystem_direct",
    "filesystem_atomic_reference",
    "memory_storage",
]
type JsonObject = dict[str, Any]

DEFAULT_SIZES = (1024, 1_048_576, 16_777_216)
DEFAULT_CHUNK_KIB = 256
DEFAULT_CONCURRENCY = 4
DEFAULT_ROUNDS = 5
MAX_SAMPLE_LOGICAL_BYTES = 256 * 1024 * 1024
BACKENDS: tuple[BackendName, ...] = ("filesystem", "memory")
VARIANTS: tuple[VariantName, ...] = (
    "filesystem_storage",
    "filesystem_direct",
    "filesystem_atomic_reference",
    "memory_storage",
)
SCENARIOS = (
    "bytes_save",
    "stream_save",
    "stream_read",
    "overwrite",
    "same_name_concurrent",
    "different_name_concurrent",
)
SCENARIO_VARIANTS: dict[str, tuple[VariantName, ...]] = {
    "bytes_save": VARIANTS,
    "stream_save": VARIANTS,
    "stream_read": (
        "filesystem_storage",
        "filesystem_direct",
        "memory_storage",
    ),
    "overwrite": VARIANTS,
    "same_name_concurrent": (
        "filesystem_storage",
        "memory_storage",
    ),
    "different_name_concurrent": VARIANTS,
}
COMPARISON_BASELINES: tuple[VariantName, ...] = (
    "filesystem_direct",
    "filesystem_atomic_reference",
)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _sizes(value: str) -> tuple[int, ...]:
    parts = value.split(",")
    if not parts or any(not part.strip() for part in parts):
        raise argparse.ArgumentTypeError("must be comma-separated positive integers")
    parsed = tuple(_positive_int(part.strip()) for part in parts)
    if len(set(parsed)) != len(parsed):
        raise argparse.ArgumentTypeError("sizes must not contain duplicate values")
    return parsed


def _validate_resource_budget(sizes: tuple[int, ...], concurrency: int) -> None:
    largest_sample = max(sizes) * concurrency
    if largest_sample > MAX_SAMPLE_LOGICAL_BYTES:
        raise ValueError(f"largest concurrent sample is {largest_sample} bytes; it exceeds the 256 MiB sample limit")


def _execution_order(round_number: int) -> tuple[tuple[str, VariantName], ...]:
    scenarios = SCENARIOS if round_number % 2 else tuple(reversed(SCENARIOS))
    ordered: list[tuple[str, VariantName]] = []
    for scenario in scenarios:
        variants = SCENARIO_VARIANTS[scenario]
        if round_number % 2 == 0:
            variants = tuple(reversed(variants))
        ordered.extend((scenario, variant) for variant in variants)
    return tuple(ordered)


def _git_output(*arguments: str, repository: Path | None = None) -> str | None:
    working_directory = repository or Path(__file__).resolve().parents[2]
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=working_directory,
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _git_tracked_dirty(repository: Path | None = None) -> bool | None:
    status = _git_output(
        "status",
        "--porcelain",
        "--untracked-files=no",
        "--",
        ".",
        ":(exclude)docs/internal/benchmarks/**",
        repository=repository,
    )
    return None if status is None else bool(status)


def _environment_record(root: Path) -> JsonObject:
    filesystem = os.statvfs(root)
    return {
        "record": "environment",
        "schema_version": 4,
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "temporary_directory": str(root),
        "filesystem_device": os.stat(root).st_dev,
        "filesystem_block_size": filesystem.f_frsize,
        "filesystem_available_bytes": filesystem.f_bavail * filesystem.f_frsize,
        "git_revision": _git_output("rev-parse", "HEAD"),
        "git_tracked_dirty": _git_tracked_dirty(),
    }


def _configuration_record(
    sizes: tuple[int, ...],
    chunk_kib: int,
    concurrency: int,
    rounds: int,
    *,
    sample_isolation: str = "subprocess",
) -> JsonObject:
    return {
        "record": "configuration",
        "sizes_bytes": list(sizes),
        "chunk_size_bytes": chunk_kib * 1024,
        "concurrency": concurrency,
        "rounds": rounds,
        "sample_isolation": sample_isolation,
        "backends": list(BACKENDS),
        "variants": list(VARIANTS),
        "scenarios": list(SCENARIOS),
        "scenario_variants": {scenario: list(variants) for scenario, variants in SCENARIO_VARIANTS.items()},
        "max_sample_logical_bytes": MAX_SAMPLE_LOGICAL_BYTES,
        "filesystem_location_prepared_before_timing": True,
    }


def _resource_usage() -> tuple[float, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime, usage.ru_stime


def _current_rss_bytes() -> int | None:
    try:
        fields = Path("/proc/self/statm").read_text(encoding="ascii").split()
        resident_pages = int(fields[1])
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None
    return resident_pages * page_size


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    multiplier = 1 if sys.platform == "darwin" else 1024
    return int(peak * multiplier)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        type=_sizes,
        default=DEFAULT_SIZES,
        help="comma-separated positive byte sizes",
    )
    parser.add_argument("--chunk-kib", type=_positive_int, default=DEFAULT_CHUNK_KIB)
    parser.add_argument("--concurrency", type=_positive_int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--rounds", type=_positive_int, default=DEFAULT_ROUNDS)
    parser.add_argument("--output", type=Path, help="atomically write a complete NDJSON copy")
    parser.add_argument("--worker-spec", help=argparse.SUPPRESS)
    return parser


class _Counters:
    def __init__(self) -> None:
        self.executor_calls = 0
        self.data_io_calls = 0
        self.data_chunks = 0


@contextmanager
def _instrument(variant: VariantName, counters: _Counters) -> Iterator[None]:
    if variant == "memory_storage":
        yield
        return

    loop = asyncio.get_running_loop()
    real_run_in_executor = loop.run_in_executor
    real_read = AsyncBufferedIOBase.read
    real_write = AsyncBufferedIOBase.write

    def counted_run_in_executor(
        executor: Executor | None,
        function: Callable[..., Any],
        *args: Any,
    ) -> asyncio.Future[Any]:
        counters.executor_calls += 1
        return real_run_in_executor(executor, function, *args)

    async def counted_read(file: AsyncBufferedIOBase, size: int = -1) -> bytes:
        counters.data_io_calls += 1
        return await real_read(file, size)

    async def counted_write(file: AsyncBufferedIOBase, data: bytes) -> int:
        counters.data_io_calls += 1
        return await real_write(file, data)

    with (
        patch.object(loop, "run_in_executor", new=counted_run_in_executor),
        patch.object(AsyncBufferedIOBase, "read", new=counted_read),
        patch.object(AsyncBufferedIOBase, "write", new=counted_write),
    ):
        yield


async def _producer(size: int, chunk_size: int, counters: _Counters) -> AsyncIterator[bytes]:
    full_chunk = b"x" * min(size, chunk_size)
    remaining = size
    while remaining:
        chunk = full_chunk if remaining >= len(full_chunk) else full_chunk[:remaining]
        counters.data_chunks += 1
        yield chunk
        remaining -= len(chunk)


def _make_storage(
    variant: VariantName,
    location: Path,
    chunk_size: int,
) -> Storage:
    if variant == "filesystem_storage":
        return FileSystemStorage(location, chunk_size=chunk_size)
    if variant == "memory_storage":
        return InMemoryStorage(chunk_size=chunk_size)
    raise ValueError(f"variant does not use Storage: {variant}")


def _variant_identity(variant: VariantName) -> tuple[BackendName, str]:
    if variant == "memory_storage":
        return "memory", "storage"
    if variant == "filesystem_direct":
        return "filesystem", "direct"
    if variant == "filesystem_atomic_reference":
        return "filesystem", "atomic_reference"
    return "filesystem", "storage"


async def _prepare_operation(
    storage: Storage,
    scenario: str,
    *,
    size: int,
    chunk_size: int,
    concurrency: int,
    payload: bytes,
    counters: _Counters,
) -> tuple[Callable[[], Awaitable[int]], Callable[[], Awaitable[None]]]:
    async def verify_size(name: str, expected_size: int = size) -> None:
        info = await storage.stat(name)
        if info.size != expected_size:
            raise RuntimeError(f"wrong stored size for {name}: {info.size} != {expected_size}")

    async def verify_content(name: str, expected_content: bytes) -> None:
        offset = 0
        async with await storage.open(name) as stored:
            async for chunk in stored:
                end = offset + len(chunk)
                if chunk != expected_content[offset:end]:
                    raise RuntimeError(f"wrong stored content for {name}")
                offset = end
        if offset != len(expected_content):
            raise RuntimeError(f"wrong stored content for {name}")

    if scenario == "bytes_save":

        async def operation() -> int:
            counters.data_chunks += 1
            await storage.save("bytes.bin", payload)
            return size

        async def verify() -> None:
            await verify_size("bytes.bin")

        return operation, verify

    if scenario == "stream_save":

        async def operation() -> int:
            await storage.save("stream.bin", _producer(size, chunk_size, counters))
            return size

        async def verify() -> None:
            await verify_size("stream.bin")

        return operation, verify

    if scenario == "stream_read":
        await storage.save("read.bin", payload)

        async def operation() -> int:
            read_size = 0
            async with await storage.open("read.bin") as stored:
                async for chunk in stored:
                    counters.data_chunks += 1
                    read_size += len(chunk)
            if read_size != size:
                raise RuntimeError(f"wrong streaming read size: {read_size} != {size}")
            return read_size

        async def verify() -> None:
            return None

        return operation, verify

    if scenario == "overwrite":
        await storage.save("overwrite.bin", b"old")

        async def operation() -> int:
            counters.data_chunks += 1
            await storage.save("overwrite.bin", payload, overwrite=True)
            return size

        async def verify() -> None:
            await verify_size("overwrite.bin")
            await verify_content("overwrite.bin", payload)

        return operation, verify

    if scenario == "same_name_concurrent":
        saved_names: list[str] = []

        async def operation() -> int:
            counters.data_chunks += concurrency
            names = await asyncio.gather(*(storage.save("shared.bin", payload) for _index in range(concurrency)))
            if len(set(names)) != concurrency:
                raise RuntimeError("same-name concurrent saves did not produce unique names")
            saved_names.extend(names)
            return size * concurrency

        async def verify() -> None:
            for name in saved_names:
                await verify_size(name)

        return operation, verify

    if scenario == "different_name_concurrent":
        names = [f"item-{index}.bin" for index in range(concurrency)]

        async def operation() -> int:
            counters.data_chunks += concurrency
            saved = await asyncio.gather(*(storage.save(name, payload) for name in names))
            if saved != names:
                raise RuntimeError("different-name concurrent saves changed requested names")
            return size * concurrency

        async def verify() -> None:
            for name in names:
                await verify_size(name)

        return operation, verify

    raise ValueError(f"unknown scenario: {scenario}")


async def _prepare_direct_operation(
    location: Path,
    scenario: str,
    *,
    size: int,
    chunk_size: int,
    concurrency: int,
    payload: bytes,
    counters: _Counters,
) -> tuple[Callable[[], Awaitable[int]], Callable[[], Awaitable[None]]]:
    async def write_bytes(name: str, content: bytes) -> str:
        async with aiofiles.open(location / name, "wb") as file:
            await file.write(content)
        return name

    async def verify_size(name: str, expected_size: int = size) -> None:
        status = await asyncio.to_thread((location / name).stat)
        if status.st_size != expected_size:
            raise RuntimeError(f"wrong direct file size for {name}: {status.st_size} != {expected_size}")

    async def verify_content(name: str, expected_content: bytes) -> None:
        offset = 0
        async with aiofiles.open(location / name, "rb") as file:
            while chunk := await file.read(chunk_size):
                end = offset + len(chunk)
                if chunk != expected_content[offset:end]:
                    raise RuntimeError(f"wrong direct file content for {name}")
                offset = end
        if offset != len(expected_content):
            raise RuntimeError(f"wrong direct file content for {name}")

    if scenario == "bytes_save":

        async def operation() -> int:
            counters.data_chunks += 1
            await write_bytes("bytes.bin", payload)
            return size

        async def verify() -> None:
            await verify_size("bytes.bin")

        return operation, verify

    if scenario == "stream_save":

        async def operation() -> int:
            async with aiofiles.open(location / "stream.bin", "wb") as file:
                async for chunk in _producer(size, chunk_size, counters):
                    await file.write(chunk)
            return size

        async def verify() -> None:
            await verify_size("stream.bin")

        return operation, verify

    if scenario == "stream_read":
        await write_bytes("read.bin", payload)

        async def operation() -> int:
            read_size = 0
            async with aiofiles.open(location / "read.bin", "rb") as file:
                while chunk := await file.read(chunk_size):
                    counters.data_chunks += 1
                    read_size += len(chunk)
            if read_size != size:
                raise RuntimeError(f"wrong direct streaming read size: {read_size} != {size}")
            return read_size

        async def verify() -> None:
            return None

        return operation, verify

    if scenario == "overwrite":
        await write_bytes("overwrite.bin", b"old")

        async def operation() -> int:
            counters.data_chunks += 1
            await write_bytes("overwrite.bin", payload)
            return size

        async def verify() -> None:
            await verify_size("overwrite.bin")
            await verify_content("overwrite.bin", payload)

        return operation, verify

    if scenario == "different_name_concurrent":
        names = [f"item-{index}.bin" for index in range(concurrency)]

        async def operation() -> int:
            counters.data_chunks += concurrency
            saved = await asyncio.gather(*(write_bytes(name, payload) for name in names))
            if saved != names:
                raise RuntimeError("direct concurrent saves changed requested names")
            return size * concurrency

        async def verify() -> None:
            for name in names:
                await verify_size(name)

        return operation, verify

    raise ValueError(f"direct variant does not support scenario: {scenario}")


async def _prepare_atomic_operation(
    location: Path,
    scenario: str,
    *,
    size: int,
    chunk_size: int,
    concurrency: int,
    payload: bytes,
    counters: _Counters,
) -> tuple[Callable[[], Awaitable[int]], Callable[[], Awaitable[None]]]:
    async def write_atomic(
        name: str,
        content: bytes | AsyncIterable[bytes],
        *,
        overwrite: bool = False,
    ) -> str:
        descriptor, temporary_path = await asyncio.to_thread(
            tempfile.mkstemp,
            prefix=".oldman-benchmark-reference-",
            dir=location,
        )
        temporary = Path(temporary_path)
        output: AsyncBufferedIOBase | None = None
        descriptor_owned = True
        temporary_exists = True
        try:
            output = cast(
                AsyncBufferedIOBase,
                await aiofiles.open(descriptor, "wb", closefd=True),
            )
            descriptor_owned = False
            if isinstance(content, bytes):
                await output.write(content)
            else:
                async for chunk in content:
                    await output.write(chunk)
            await output.close()
            output = None

            target = location / name
            if overwrite:
                await asyncio.to_thread(os.replace, temporary, target)
                temporary_exists = False
            else:
                await asyncio.to_thread(
                    os.link,
                    temporary,
                    target,
                    follow_symlinks=False,
                )
                await asyncio.to_thread(temporary.unlink)
                temporary_exists = False
            return name
        finally:
            if output is not None:
                await output.close()
            if descriptor_owned:
                await asyncio.to_thread(os.close, descriptor)
            if temporary_exists:
                await asyncio.to_thread(temporary.unlink, missing_ok=True)

    async def verify_size(name: str, expected_size: int = size) -> None:
        status = await asyncio.to_thread((location / name).stat)
        if status.st_size != expected_size:
            raise RuntimeError(f"wrong atomic file size for {name}: {status.st_size} != {expected_size}")

    async def verify_content(name: str, expected_content: bytes) -> None:
        offset = 0
        async with aiofiles.open(location / name, "rb") as file:
            while chunk := await file.read(chunk_size):
                end = offset + len(chunk)
                if chunk != expected_content[offset:end]:
                    raise RuntimeError(f"wrong atomic file content for {name}")
                offset = end
        if offset != len(expected_content):
            raise RuntimeError(f"wrong atomic file content for {name}")

    if scenario == "bytes_save":

        async def operation() -> int:
            counters.data_chunks += 1
            await write_atomic("bytes.bin", payload)
            return size

        async def verify() -> None:
            await verify_size("bytes.bin")

        return operation, verify

    if scenario == "stream_save":

        async def operation() -> int:
            await write_atomic(
                "stream.bin",
                _producer(size, chunk_size, counters),
            )
            return size

        async def verify() -> None:
            await verify_size("stream.bin")

        return operation, verify

    if scenario == "overwrite":
        await write_atomic("overwrite.bin", b"old")

        async def operation() -> int:
            counters.data_chunks += 1
            await write_atomic("overwrite.bin", payload, overwrite=True)
            return size

        async def verify() -> None:
            await verify_size("overwrite.bin")
            await verify_content("overwrite.bin", payload)

        return operation, verify

    if scenario == "different_name_concurrent":
        names = [f"item-{index}.bin" for index in range(concurrency)]

        async def operation() -> int:
            counters.data_chunks += concurrency
            saved = await asyncio.gather(*(write_atomic(name, payload) for name in names))
            if saved != names:
                raise RuntimeError("atomic concurrent saves changed requested names")
            return size * concurrency

        async def verify() -> None:
            for name in names:
                await verify_size(name)

        return operation, verify

    raise ValueError(f"atomic variant does not support scenario: {scenario}")


async def _sample(
    variant: VariantName,
    scenario: str,
    *,
    size: int,
    chunk_size: int,
    concurrency: int,
    round_number: int,
    root: Path,
) -> JsonObject:
    process_rss_before = _current_rss_bytes()
    tracemalloc.start()
    try:
        prefix = f"{variant}-{size}-{scenario}-{round_number}-"
        with tempfile.TemporaryDirectory(dir=root, prefix=prefix) as sample_directory:
            location = Path(sample_directory) / "storage"
            if variant != "memory_storage":
                await asyncio.to_thread(location.mkdir, parents=True, exist_ok=True)
            payload = b"" if scenario == "stream_save" else b"x" * size
            counters = _Counters()
            if variant == "filesystem_direct":
                operation, verify = await _prepare_direct_operation(
                    location,
                    scenario,
                    size=size,
                    chunk_size=chunk_size,
                    concurrency=concurrency,
                    payload=payload,
                    counters=counters,
                )
            elif variant == "filesystem_atomic_reference":
                operation, verify = await _prepare_atomic_operation(
                    location,
                    scenario,
                    size=size,
                    chunk_size=chunk_size,
                    concurrency=concurrency,
                    payload=payload,
                    counters=counters,
                )
            else:
                storage = _make_storage(variant, location, chunk_size)
                operation, verify = await _prepare_operation(
                    storage,
                    scenario,
                    size=size,
                    chunk_size=chunk_size,
                    concurrency=concurrency,
                    payload=payload,
                    counters=counters,
                )

            with _instrument(variant, counters):
                user_cpu_before, system_cpu_before = _resource_usage()
                started = time.perf_counter()
                processed_bytes = await operation()
                elapsed = time.perf_counter() - started
                user_cpu_after, system_cpu_after = _resource_usage()
            _current, peak = tracemalloc.get_traced_memory()
            peak_process_rss = _peak_rss_bytes()
            await verify()

            user_cpu = user_cpu_after - user_cpu_before
            system_cpu = system_cpu_after - system_cpu_before
            cpu_seconds = user_cpu + system_cpu
            mib_per_second = processed_bytes / (1024 * 1024) / elapsed
            backend, implementation = _variant_identity(variant)
            result = {
                "record": "sample",
                "variant": variant,
                "backend": backend,
                "implementation": implementation,
                "size_bytes": size,
                "scenario": scenario,
                "round": round_number,
                "elapsed_seconds": elapsed,
                "mib_per_second": mib_per_second,
                "user_cpu_seconds": user_cpu,
                "system_cpu_seconds": system_cpu,
                "cpu_seconds": cpu_seconds,
                "cpu_to_wall_ratio": cpu_seconds / elapsed,
                "process_rss_before_bytes": process_rss_before,
                "peak_process_rss_bytes": peak_process_rss,
                "peak_process_rss_delta_bytes": max(
                    0,
                    peak_process_rss - (process_rss_before or peak_process_rss),
                ),
                "executor_call_count": counters.executor_calls,
                "data_io_call_count": counters.data_io_calls,
                "data_chunk_count": counters.data_chunks,
                "peak_python_allocation_bytes": peak,
                "worker_pid": os.getpid(),
            }
    finally:
        tracemalloc.stop()
        gc.collect()
    return result


async def _isolated_sample(
    variant: VariantName,
    scenario: str,
    *,
    size: int,
    chunk_size: int,
    concurrency: int,
    round_number: int,
    root: Path,
) -> JsonObject:
    spec = {
        "variant": variant,
        "scenario": scenario,
        "size": size,
        "chunk_size": chunk_size,
        "concurrency": concurrency,
        "round_number": round_number,
        "root": str(root),
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.performance.storage_benchmark",
        "--worker-spec",
        json.dumps(spec, separators=(",", ":")),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    except TimeoutError as error:
        process.kill()
        await process.wait()
        raise RuntimeError(f"benchmark sample worker timed out: {variant}/{scenario}") from error

    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"benchmark sample worker failed: {variant}/{scenario}: {message}")
    lines = stdout.decode("utf-8").splitlines()
    if len(lines) != 1:
        raise RuntimeError(f"benchmark sample worker returned {len(lines)} records: {variant}/{scenario}")
    try:
        record = json.loads(lines[0])
    except json.JSONDecodeError as error:
        raise RuntimeError(f"benchmark sample worker returned invalid JSON: {variant}/{scenario}") from error
    if (
        not isinstance(record, dict)
        or record.get("record") != "sample"
        or record.get("variant") != variant
        or record.get("scenario") != scenario
        or record.get("size_bytes") != size
        or record.get("round") != round_number
    ):
        raise RuntimeError(f"benchmark sample worker identity mismatch: {variant}/{scenario}")
    return record


async def _run_worker(encoded_spec: str) -> JsonObject:
    try:
        spec = json.loads(encoded_spec)
        variant = spec["variant"]
        scenario = spec["scenario"]
        if variant not in VARIANTS or variant not in SCENARIO_VARIANTS[scenario]:
            raise ValueError("unsupported variant/scenario pair")
        return await _sample(
            variant,
            scenario,
            size=int(spec["size"]),
            chunk_size=int(spec["chunk_size"]),
            concurrency=int(spec["concurrency"]),
            round_number=int(spec["round_number"]),
            root=Path(spec["root"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("invalid benchmark worker specification") from error


def _median_records(samples: list[JsonObject]) -> list[JsonObject]:
    grouped: defaultdict[tuple[str, int, str], list[JsonObject]] = defaultdict(list)
    for sample in samples:
        grouped[(sample["variant"], sample["size_bytes"], sample["scenario"])].append(sample)

    medians: list[JsonObject] = []
    for (variant, size, scenario), group in sorted(grouped.items()):
        medians.append(
            {
                "record": "median",
                "variant": variant,
                "backend": group[0]["backend"],
                "implementation": group[0]["implementation"],
                "size_bytes": size,
                "scenario": scenario,
                "rounds": len(group),
                "elapsed_seconds": statistics.median(float(sample["elapsed_seconds"]) for sample in group),
                "mib_per_second": statistics.median(float(sample["mib_per_second"]) for sample in group),
                "user_cpu_seconds": statistics.median(float(sample["user_cpu_seconds"]) for sample in group),
                "system_cpu_seconds": statistics.median(float(sample["system_cpu_seconds"]) for sample in group),
                "cpu_seconds": statistics.median(float(sample["cpu_seconds"]) for sample in group),
                "cpu_to_wall_ratio": statistics.median(float(sample["cpu_to_wall_ratio"]) for sample in group),
                "process_rss_before_bytes": statistics.median(int(sample["process_rss_before_bytes"] or 0) for sample in group),
                "peak_process_rss_bytes": statistics.median(int(sample["peak_process_rss_bytes"]) for sample in group),
                "peak_process_rss_delta_bytes": statistics.median(int(sample["peak_process_rss_delta_bytes"]) for sample in group),
                "executor_call_count": statistics.median(int(sample["executor_call_count"]) for sample in group),
                "data_io_call_count": statistics.median(int(sample["data_io_call_count"]) for sample in group),
                "data_chunk_count": statistics.median(int(sample["data_chunk_count"]) for sample in group),
                "peak_python_allocation_bytes": statistics.median(int(sample["peak_python_allocation_bytes"]) for sample in group),
            }
        )
    return medians


def _safe_ratio(numerator: float | int, denominator: float | int) -> float | None:
    denominator_value = float(denominator)
    if denominator_value <= 0:
        return None
    return float(numerator) / denominator_value


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0.0 <= percentile <= 1.0:
        raise ValueError("percentile must be between zero and one")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def _comparison_records(
    samples: list[JsonObject],
    medians: list[JsonObject],
) -> list[JsonObject]:
    sample_index: dict[tuple[str, int, str, int], JsonObject] = {}
    rounds_by_group: defaultdict[tuple[str, int, str], set[int]] = defaultdict(set)
    for sample in samples:
        key = (
            str(sample["variant"]),
            int(sample["size_bytes"]),
            str(sample["scenario"]),
            int(sample["round"]),
        )
        if key in sample_index:
            raise RuntimeError(f"duplicate benchmark sample: {key}")
        sample_index[key] = sample
        rounds_by_group[key[:3]].add(key[3])

    indexed = {(str(median["variant"]), int(median["size_bytes"]), str(median["scenario"])): median for median in medians}
    comparisons: list[JsonObject] = []
    for storage in medians:
        if storage["variant"] != "filesystem_storage":
            continue
        size = int(storage["size_bytes"])
        scenario = str(storage["scenario"])
        storage_group = ("filesystem_storage", size, scenario)
        for baseline_variant in COMPARISON_BASELINES:
            baseline_group = (baseline_variant, size, scenario)
            baseline = indexed.get(baseline_group)
            if baseline is None:
                continue

            storage_rounds = rounds_by_group[storage_group]
            baseline_rounds = rounds_by_group[baseline_group]
            if storage_rounds != baseline_rounds:
                raise RuntimeError(f"paired rounds differ for {size}/{scenario}/{baseline_variant}")

            def paired_ratios(
                field: str,
                paired_rounds: set[int],
                paired_storage_group: tuple[str, int, str],
                paired_baseline_group: tuple[str, int, str],
            ) -> list[float]:
                ratios: list[float] = []
                for round_number in sorted(paired_rounds):
                    storage_sample = sample_index[(*paired_storage_group, round_number)]
                    baseline_sample = sample_index[(*paired_baseline_group, round_number)]
                    ratio = _safe_ratio(storage_sample[field], baseline_sample[field])
                    if ratio is None:
                        raise RuntimeError(
                            f"non-positive paired baseline {field}: {paired_storage_group[1]}/{paired_storage_group[2]}/{round_number}"
                        )
                    ratios.append(ratio)
                return ratios

            paired_arguments = (storage_rounds, storage_group, baseline_group)
            wall_ratios = paired_ratios("elapsed_seconds", *paired_arguments)
            throughput_ratios = paired_ratios("mib_per_second", *paired_arguments)
            cpu_ratios = paired_ratios("cpu_seconds", *paired_arguments)
            comparisons.append(
                {
                    "record": "comparison",
                    "comparison_method": "median_of_paired_round_ratios",
                    "size_bytes": storage["size_bytes"],
                    "scenario": storage["scenario"],
                    "rounds": storage["rounds"],
                    "paired_rounds": len(storage_rounds),
                    "baseline_variant": baseline["variant"],
                    "baseline_implementation": baseline["implementation"],
                    "storage_elapsed_seconds": storage["elapsed_seconds"],
                    "baseline_elapsed_seconds": baseline["elapsed_seconds"],
                    "wall_time_ratio": statistics.median(wall_ratios),
                    "wall_time_ratio_p25": _percentile(wall_ratios, 0.25),
                    "wall_time_ratio_p75": _percentile(wall_ratios, 0.75),
                    "storage_mib_per_second": storage["mib_per_second"],
                    "baseline_mib_per_second": baseline["mib_per_second"],
                    "throughput_ratio": statistics.median(throughput_ratios),
                    "storage_user_cpu_seconds": storage["user_cpu_seconds"],
                    "baseline_user_cpu_seconds": baseline["user_cpu_seconds"],
                    "storage_system_cpu_seconds": storage["system_cpu_seconds"],
                    "baseline_system_cpu_seconds": baseline["system_cpu_seconds"],
                    "storage_cpu_seconds": storage["cpu_seconds"],
                    "baseline_cpu_seconds": baseline["cpu_seconds"],
                    "cpu_time_ratio": statistics.median(cpu_ratios),
                    "cpu_time_ratio_p25": _percentile(cpu_ratios, 0.25),
                    "cpu_time_ratio_p75": _percentile(cpu_ratios, 0.75),
                    "storage_cpu_to_wall_ratio": storage["cpu_to_wall_ratio"],
                    "baseline_cpu_to_wall_ratio": baseline["cpu_to_wall_ratio"],
                    "cpu_to_wall_ratio_delta": float(storage["cpu_to_wall_ratio"]) - float(baseline["cpu_to_wall_ratio"]),
                    "storage_peak_python_allocation_bytes": storage["peak_python_allocation_bytes"],
                    "baseline_peak_python_allocation_bytes": baseline["peak_python_allocation_bytes"],
                    "peak_python_allocation_bytes_delta": int(storage["peak_python_allocation_bytes"])
                    - int(baseline["peak_python_allocation_bytes"]),
                    "storage_peak_process_rss_bytes": storage["peak_process_rss_bytes"],
                    "baseline_peak_process_rss_bytes": baseline["peak_process_rss_bytes"],
                    "storage_peak_process_rss_delta_bytes": storage["peak_process_rss_delta_bytes"],
                    "baseline_peak_process_rss_delta_bytes": baseline["peak_process_rss_delta_bytes"],
                    "peak_process_rss_delta_bytes_delta": int(storage["peak_process_rss_delta_bytes"])
                    - int(baseline["peak_process_rss_delta_bytes"]),
                    "storage_executor_call_count": storage["executor_call_count"],
                    "baseline_executor_call_count": baseline["executor_call_count"],
                    "executor_call_count_delta": int(storage["executor_call_count"]) - int(baseline["executor_call_count"]),
                    "storage_data_io_call_count": storage["data_io_call_count"],
                    "baseline_data_io_call_count": baseline["data_io_call_count"],
                    "storage_data_chunk_count": storage["data_chunk_count"],
                    "baseline_data_chunk_count": baseline["data_chunk_count"],
                }
            )
    return comparisons


def _write_records(path: Path, records: list[JsonObject]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=path.parent,
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            for record in records:
                output.write(json.dumps(record, sort_keys=True))
                output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


async def run(
    sizes: tuple[int, ...],
    chunk_kib: int,
    concurrency: int,
    rounds: int,
    *,
    isolate_samples: bool = True,
) -> list[JsonObject]:
    _validate_resource_budget(sizes, concurrency)
    chunk_size = chunk_kib * 1024
    samples: list[JsonObject] = []
    records: list[JsonObject] = []

    def emit(record: JsonObject) -> None:
        records.append(record)
        print(json.dumps(record, sort_keys=True), flush=True)

    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        emit(_environment_record(root))
        emit(
            _configuration_record(
                sizes,
                chunk_kib,
                concurrency,
                rounds,
                sample_isolation="subprocess" if isolate_samples else "in_process",
            )
        )
        sample_runner = _isolated_sample if isolate_samples else _sample
        for size in sizes:
            for round_number in range(1, rounds + 1):
                for scenario, variant in _execution_order(round_number):
                    sample = await sample_runner(
                        variant,
                        scenario,
                        size=size,
                        chunk_size=chunk_size,
                        concurrency=concurrency,
                        round_number=round_number,
                        root=root,
                    )
                    samples.append(sample)
                    emit(sample)

    medians = _median_records(samples)
    for median in medians:
        emit(median)
    for comparison in _comparison_records(samples, medians):
        emit(comparison)
    return records


def main() -> None:
    arguments = _parser().parse_args()
    if arguments.worker_spec is not None:
        record = asyncio.run(_run_worker(arguments.worker_spec))
        print(json.dumps(record, sort_keys=True), flush=True)
        return
    records = asyncio.run(
        run(
            arguments.sizes,
            arguments.chunk_kib,
            arguments.concurrency,
            arguments.rounds,
        )
    )
    if arguments.output is not None:
        _write_records(arguments.output, records)


if __name__ == "__main__":
    main()
