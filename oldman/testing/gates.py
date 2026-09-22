"""起一套完全自有的临时环境来跑浏览器门禁：空闲端口、独立 Redis、临时配置、前台服务。

门禁必须只碰自己创建的东西：Redis 不落盘、数据库在临时目录、服务在自己的进程组里，退出时确认整组都
没了。这里是两个演示项目此前各自复制的那套机制；演示脚本只保留自己的配置差异和页面断言。
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REDIS_DATABASE_COUNT = 16
DEFAULT_HOST = "127.0.0.1"
ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "CHROME_BIN",
        "DISPLAY",
        "FIREFOX_BIN",
        "HOME",
        "LD_LIBRARY_PATH",
        "OLDMAN_CHROME_HEADLESS",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
        "XAUTHORITY",
    }
)


class BrowserGateError(RuntimeError):
    """门禁的准备、运行或清理失败。"""


def minimal_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """只保留启动本机工具需要的环境变量，并固定 hash 种子、时区和语言。

    门禁不继承开发机的全部环境：那样一次通过说明不了别的机器也通过。语言也一样——浏览器按
    `LANG`/`LANGUAGE` 决定它请求的 `Accept-Language`，继承开发机的值会让同一个门禁在 zh_TW 的机器上
    看到一套翻译过的界面，而断言写的是英文。
    """
    values = os.environ if source is None else source
    environment = {name: value for name, value in values.items() if name in ENVIRONMENT_ALLOWLIST and value}
    environment.setdefault("HOME", str(Path.home()))
    environment.setdefault("PATH", os.defpath)
    environment["LANG"] = "C.UTF-8"
    environment["LC_ALL"] = "C.UTF-8"
    environment["LANGUAGE"] = "en_US:en"
    environment["PYTHONHASHSEED"] = "0"
    environment["TZ"] = "UTC"
    return environment


def find_free_port(host: str = DEFAULT_HOST) -> int:
    """当前没人用的一个 loopback 端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])


def port_is_open(port: int, host: str = DEFAULT_HOST) -> bool:
    """端口是否已经有人在监听。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.5)
        try:
            connection.connect((host, port))
        except OSError:
            return False
    return True


def process_group_exists(process_group: int) -> bool:
    """进程组是否还存在（清理后必须为 False）。"""
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def redis_database_url(redis_url: str, database: int) -> str:
    """在门禁自有的 Redis 上选一个逻辑库。"""
    parsed = urlsplit(redis_url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise BrowserGateError("Gate Redis URL must be a concrete Redis URL")
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", parsed.query, parsed.fragment))


def _terminate_group(process: subprocess.Popen[Any], *, grace: float = 8, kill_wait: float = 5) -> None:
    """Signal the whole process group and wait for it, not only for its leader.

    领导进程先退出、同组进程还活着是常见情况（Sanic 主进程异常退出，worker 还占着监听端口）：
    只在 `poll() is None` 时发信号的话，这种情况一个信号都不发，端口和 worker 会一直留在机器上，
    事后只剩一句"进程组仍在"的报错。
    """
    for number, timeout in ((signal.SIGTERM, grace), (signal.SIGKILL, kill_wait)):
        try:
            os.killpg(process.pid, number)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is None:
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    continue
            if not process_group_exists(process.pid):
                return
            time.sleep(0.1)


@contextmanager
def owned_redis_server(state_root: Path, *, environment: Mapping[str, str], host: str = DEFAULT_HOST) -> Iterator[str]:
    """起一个不落盘的 Redis，并在退出时证明进程组和端口都已释放。"""
    executable = shutil.which("redis-server", path=environment.get("PATH"))
    if executable is None:
        raise BrowserGateError("This gate requires redis-server")
    state_root.mkdir(parents=True, exist_ok=True)
    port = find_free_port(host)
    log_handle = (state_root / "redis.log").open("wb")
    process = subprocess.Popen(
        [
            executable,
            "--bind",
            host,
            "--port",
            str(port),
            "--save",
            "",
            "--appendonly",
            "no",
            "--daemonize",
            "no",
            "--dir",
            str(state_root),
            "--pidfile",
            str(state_root / "redis.pid"),
        ],
        cwd=state_root,
        env=dict(environment),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise BrowserGateError(f"Redis exited before listening: {process.returncode}")
            if port_is_open(port, host):
                break
            time.sleep(0.1)
        else:
            raise BrowserGateError("Redis did not become ready")
        yield f"redis://{host}:{port}"
    finally:
        _terminate_group(process, grace=5)
        log_handle.close()
        if process_group_exists(process.pid) or port_is_open(port, host):
            raise BrowserGateError("Gate-owned Redis was not fully cleaned up")


def gate_settings(
    example_file: Path,
    state_root: Path,
    *,
    service_port: int,
    redis_url: str,
    namespace: str,
    database_name: str = "gate.sqlite3",
    static_dir: Path | None = None,
    host: str = DEFAULT_HOST,
    customize: Callable[[dict], None] | None = None,
) -> Path:
    """把项目的 `web_settings.example.yaml` 改写成一份只指向临时目录的完整配置。

    `redis` 下的**每一个**别名都被改写到门禁自己那台 Redis 的一个独立 database：项目的别名数量各不
    相同（EPG 还有 CACHE 和 TASKIQ），漏掉一个就会让门禁读写开发机上的真实 Redis。

    `namespace` 用于 session 前缀和 Cookie 名，两个门禁同时跑也不会互相登出；`customize` 收到整个
    payload，用来改项目自己的键（关掉 taskiq、指定模板目录……）。
    """
    from ruamel.yaml import YAML

    payload = YAML(typ="safe", pure=True).load(example_file.read_text(encoding="utf-8"))
    payload["core"]["data_dir"] = str(state_root / "data")
    payload["logging"]["dir"] = str(state_root / "logs")
    payload["process"]["pid_dir"] = str(state_root / "pids")
    payload["database"]["url"] = f"sqlite+aiosqlite:///{state_root / database_name}"
    aliases = sorted(payload.get("redis") or {})
    if len(aliases) > REDIS_DATABASE_COUNT:
        raise BrowserGateError(f"门禁 Redis 只有 {REDIS_DATABASE_COUNT} 个 database，配置里有 {len(aliases)} 个别名")
    for database, alias in enumerate(aliases):
        payload["redis"][alias]["redis_url"] = redis_database_url(redis_url, database)
    web = payload["web"]
    web["listen_host"] = host
    web["listen_port"] = service_port
    web["workers"] = 1
    web["access_log"] = False
    web["security"]["secret_key"] = secrets.token_urlsafe(48)
    web["security"]["fingerprint"]["aes_secret_key"] = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    web["session"]["prefix"] = f"{namespace}_session:"
    web["session"]["user_prefix"] = f"{namespace}_user:"
    web["session"]["cookie_name"] = f"{namespace}_sid"
    web["sse"]["heartbeat_interval"] = 0.5
    web["sse"]["session_check_interval"] = 0.5
    web["static"]["dir"] = str(static_dir if static_dir is not None else state_root / "static-source")
    web["static"]["root"] = str(state_root / "static")
    payload["storages"]["default"]["options"]["location"] = str(state_root / "media")
    if customize is not None:
        customize(payload)

    config_file = state_root / "web_settings.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    yaml = YAML()
    with config_file.open("w", encoding="utf-8") as output:
        yaml.dump(payload, output)
    return config_file


class FirstUseInteraction:
    """迁移只允许回答“这是首次使用”，其它询问都算门禁接线错误。"""

    is_interactive = False

    def choose(self, prompt: str, choices: tuple[str, ...]) -> str:
        if "internal migration state" in prompt and "first use" in choices:
            return "first use"
        raise BrowserGateError(f"Unexpected migration choice: {prompt}")

    def confirm(self, prompt: str, *, default: bool = False) -> bool:
        del default
        raise BrowserGateError(f"Unexpected migration confirmation: {prompt}")

    def text(self, prompt: str, *, default: str) -> str:
        del default
        raise BrowserGateError(f"The browser gate must not generate migrations: {prompt}")


def migrate_gate_database(config_file: Path, state_root: Path, *, project_root: Path, service: str = "web") -> None:
    """在临时目录里搭一个最小项目，把已评审的迁移应用到门禁自己的数据库。"""
    from oldman.db.migrations.commands import migrate
    from oldman.db.migrations.project import load_migration_project

    migration_root = state_root / "migration-project"
    (migration_root / "data").mkdir(parents=True, exist_ok=True)
    (migration_root / "services").mkdir(parents=True, exist_ok=True)
    shutil.copy2(project_root / "pyproject.toml", migration_root / "pyproject.toml")
    shutil.copy2(config_file, migration_root / "data" / f"{service}_settings.yaml")
    (migration_root / "services" / f"{service}.py").write_text(
        "from oldman.runtime.web import WebApplication\n\n\nclass WebService(WebApplication):\n    pass\n",
        encoding="utf-8",
    )
    migrate(load_migration_project(migration_root), FirstUseInteraction())


def ensure_gate_admin(
    config_file: Path,
    *,
    environment: Mapping[str, str],
    project_root: Path,
    username: str,
    password: str,
    email: str = "oldman@example.com",
    service: str = "web",
) -> None:
    """通过公开的 bootstrap 与 ensure_superuser 建出门禁要用的管理员。"""
    source = f"""
import asyncio
import sys
from oldman import bootstrap_service

bootstrap_service({service!r}, config_file=sys.argv[1])

from oldman.auth import ensure_superuser
from oldman.auth.apps import app as auth_app
from oldman.db import db_manager

async def main():
    try:
        await ensure_superuser(
            sys.argv[2],
            sys.argv[3],
            sys.argv[4],
            auth_settings=auth_app.settings,
            db_manager=db_manager,
        )
    finally:
        await db_manager.close()

asyncio.run(main())
"""
    subprocess.run(
        [sys.executable, "-c", source, str(config_file), username, password, email],
        cwd=project_root,
        env=dict(environment),
        check=True,
    )


def service_command(config_file: Path, *, service: str = "web") -> list[str]:
    """前台启动一个服务的命令，走的是正常的 bootstrap 与服务发现路径。"""
    source = (
        "import sys; "
        "from pathlib import Path; "
        "from oldman import bootstrap_service; "
        "from oldman.runtime.discovery import get_service_definition, load_service_class; "
        f"bootstrap_service({service!r}, config_file=sys.argv[1]); "
        f"definition=get_service_definition({service!r}, Path.cwd()); "
        "service=load_service_class(definition); "
        "service.execute_command('start')"
    )
    return [sys.executable, "-c", source, str(config_file)]


@contextmanager
def owned_service(
    config_file: Path,
    *,
    environment: Mapping[str, str],
    project_root: Path,
    service: str = "web",
    name: str = "service",
) -> Iterator[subprocess.Popen[bytes]]:
    """起一个门禁自有的前台服务进程组，退出时确认整组已经回收。"""
    log_file = config_file.parent / f"{name}.log"
    log_handle = log_file.open("wb")
    process = subprocess.Popen(
        service_command(config_file, service=service),
        cwd=project_root,
        env=dict(environment),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        yield process
    finally:
        _terminate_group(process)
        log_handle.close()
        if process_group_exists(process.pid):
            raise BrowserGateError(f"{name} process group {process.pid} remains after cleanup")


def wait_for_service(
    process: subprocess.Popen[bytes],
    service_port: int,
    *,
    host: str = DEFAULT_HOST,
    timeout: float = 30,
    name: str = "service",
) -> None:
    """等服务开始监听；进程提前退出算失败，不能一直等到超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BrowserGateError(f"{name} exited before listening: {process.returncode}")
        if port_is_open(service_port, host):
            return
        time.sleep(0.1)
    raise BrowserGateError(f"{name} did not listen on port {service_port}")


def run_browser_child(
    command: Sequence[str],
    *,
    environment: Mapping[str, str],
    project_root: Path,
    browser: str,
    timeout: float = 180,
    label: str = "gate",
) -> dict:
    """跑真实浏览器子进程，并要求它输出干净的成功载荷。

    console 错误、page 错误和坏响应都必须是空的：浏览器里出过错，就不算通过。
    """
    child = subprocess.Popen(
        list(command),
        cwd=project_root,
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # 卡住的子进程下面还挂着浏览器：只杀它自己的话，headless 浏览器和它的 profile 会留下来。
        _terminate_group(child)
        stdout, stderr = child.communicate()
        if stderr:
            print(stderr, file=sys.stderr, end="")
        raise BrowserGateError(f"{label} {browser} gate timed out after {timeout:g}s") from exc
    completed = subprocess.CompletedProcess(command, child.returncode, stdout, stderr)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    if completed.returncode != 0:
        raise BrowserGateError(f"{label} {browser} gate failed: {completed.stdout[-4000:]}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise BrowserGateError(f"{label} browser child returned invalid JSON") from exc
    if (
        not isinstance(result, dict)
        or result.get("ok") is not True
        or result.get("browser") != browser
        or result.get("consoleErrors") != []
        or result.get("pageErrors") != []
        or result.get("badResponses") != []
    ):
        raise BrowserGateError(f"{label} browser result was not clean: {result}")
    print(completed.stdout, end="")
    return result


__all__ = [
    "DEFAULT_HOST",
    "ENVIRONMENT_ALLOWLIST",
    "BrowserGateError",
    "FirstUseInteraction",
    "ensure_gate_admin",
    "find_free_port",
    "gate_settings",
    "migrate_gate_database",
    "minimal_environment",
    "owned_redis_server",
    "owned_service",
    "port_is_open",
    "process_group_exists",
    "redis_database_url",
    "run_browser_child",
    "service_command",
    "wait_for_service",
]
