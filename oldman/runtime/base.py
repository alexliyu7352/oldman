import asyncio
import fcntl
import inspect
import os
import re
import signal
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from signal import SIG_IGN
from typing import TYPE_CHECKING, Any, Self

from oldman.i18n import gettext_noop
from oldman.logging import (
    LoggingRuntime,
    get_active_runtime,
    init_logging,
    logger,
)
from oldman.runtime._process_group import GroupIdentity, group_members, leader_is_alive, service_process_group, stop_process_group
from oldman.runtime.bootstrap import (
    ServiceBootstrapContext,
    _get_bootstrap_context,
)
from oldman.storage import storages
from oldman.utils.asyncio_utils import new_event_loop

if TYPE_CHECKING:
    from oldman.cli import Command
    from oldman.web.routing import WebApp

PublicCommandEntry = tuple[Callable, str]

#: The service this process runs; read it through ``BaseApplication.current()``.
_current_service: "BaseApplication | None" = None

#: PID file descriptors this process holds locked (a service's, or an App command's).
_held_locks: set[int] = set()


def _close_inherited_locks() -> None:
    """In a forked child, close the inherited PID file descriptors without unlocking them.

    A flock belongs to the open file, so a child keeping the descriptor would keep the service or
    command "running" after its main process had gone (`multiprocessing` forks by default on Linux
    before Python 3.14). Unlocking would release the parent's lock too, so the child only closes.
    The framework's own children are spawned and never inherit the descriptors.
    """
    for fd in _held_locks:
        try:
            os.close(fd)
        except OSError:
            pass
    _held_locks.clear()


os.register_at_fork(after_in_child=_close_inherited_locks)


def _lock_pid_file(path: str) -> int:
    """Open `path` and lock it; the locked descriptor, or BlockingIOError while another process holds it.

    The lock is held on a raw descriptor, not a file object: a forked child closes the descriptor,
    and a file object would later close whatever file had reused the number. A holder removes its
    file before releasing the lock, so a lock taken on a file no longer at `path` counts for
    nothing: open the path again.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(3):
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
        if _same_file(fd, path):
            _held_locks.add(fd)
            return fd
        os.close(fd)
    raise RuntimeError(f"{path} kept being replaced while it was being locked")


def _same_file(fd: int, path: str) -> bool:
    """Whether `fd` still refers to the file now at `path`."""
    try:
        current = os.stat(path)
    except FileNotFoundError:
        return False
    held = os.fstat(fd)
    return (held.st_dev, held.st_ino) == (current.st_dev, current.st_ino)


def _read_pid(fd: int) -> int:
    content = os.pread(fd, 64, 0).decode(errors="ignore").strip()
    return int(content) if content.isascii() and content.isdigit() else 0


def _pid_in(path: str) -> str:
    """The PID written in `path`, for a message; empty when unreadable."""
    try:
        return Path(path).read_text(encoding="ascii", errors="ignore").strip()
    except OSError:
        return ""


def _write_pid(fd: int, pid: int) -> None:
    os.ftruncate(fd, 0)
    os.pwrite(fd, str(pid).encode(), 0)
    os.fsync(fd)


def _release_pid_file(fd: int, path: str, *, before_unlock: Callable[[], None] | None = None) -> None:
    """Remove `path`, run `before_unlock`, then close the locked descriptor, which unlocks it.

    A no-op for a descriptor not held. Whoever holds the lock is the only one using the file,
    whatever number it holds: a start that failed before writing its pid leaves nothing behind. The
    file goes before the lock, and only while it is still the file at `path` (see _lock_pid_file). A
    forked child has closed its copies of the parent's descriptors (see _close_inherited_locks) and
    must not remove the parent's file.
    """
    if fd not in _held_locks:
        return
    _held_locks.discard(fd)
    try:
        try:
            if _same_file(fd, path):
                os.remove(path)
        except FileNotFoundError:
            pass
        if before_unlock is not None:
            before_unlock()
    finally:
        os.close(fd)


class BaseApplication(ABC):
    """
    BaseApplication - 服务基类
    提供服务生命周期和服务级命令执行。
    """

    # 服务名称可覆盖；稳定标识只来自已选择的服务模块名。
    SERVICE_NAME: str | None = None

    @classmethod
    def get_service_id(cls) -> str:
        """Return the module name selected by the process bootstrap."""
        return _get_bootstrap_context().service_module

    @classmethod
    def get_service_name(cls) -> str:
        """获取服务名称"""
        return cls.SERVICE_NAME or cls.get_service_id().capitalize()

    @classmethod
    def get_default_commands(cls) -> dict[str, PublicCommandEntry]:
        """
        获取默认命令
        子类可以覆盖此方法以提供不同的默认命令
        """
        return {
            "start": (cls.start, gettext_noop("Start service.")),
            "stop": (cls.stop, gettext_noop("Stop service.")),
            "restart": (cls.restart, gettext_noop("Restart service.")),
        }

    @classmethod
    def execute_command(cls, command_name: str, *args: Any, **kwargs: Any) -> Any:
        """Execute one service command declared by ``get_default_commands``."""
        commands = cls.get_default_commands()
        if command_name not in commands:
            raise ValueError(f"未知命令: {command_name}，可用命令: {', '.join(commands.keys())}")

        instance = cls(f"{cls.__name__}")
        bound_func = getattr(instance, command_name)
        if cls._is_async_callable(bound_func):
            return asyncio.run(
                instance._run_async_cli_command(
                    command_name,
                    bound_func,
                    *args,
                    **kwargs,
                ),
                loop_factory=new_event_loop,
            )
        try:
            return cls._run_sync_command(bound_func, *args, **kwargs)
        finally:
            # The logging of the instance built for this command ends with the command; a service's
            # run() has closed it already. start, stop and restart leave it to this: called on
            # current(), the instance a running service, worker or App command logs through, they
            # must not end that process's logging.
            if not instance._logging_closed:
                instance._close_logging()

    @classmethod
    def execute_app_command(
        cls,
        command: "Command",
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute one App command inside the existing async CLI lifecycle."""
        if command.check_pid:
            with cls.command_pid_guard(command.name):
                return cls._execute_app_command_body(command, *args, **kwargs)
        return cls._execute_app_command_body(command, *args, **kwargs)

    @classmethod
    def _execute_app_command_body(
        cls,
        command: "Command",
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Construct the selected service and run one validated App command."""
        instance = cls(f"{cls.__name__}_{command.name}")
        instance.configure_command_logging(
            command.name,
            stdout_to_stderr=command.raw_stdout,
        )
        return asyncio.run(
            instance._run_async_cli_command(
                command.name,
                command.handle,
                *args,
                **kwargs,
            ),
            loop_factory=new_event_loop,
        )

    @classmethod
    @contextmanager
    def command_pid_guard(cls, command_name: str):
        """命令级 pid 守卫，只限制同一个服务下的同名 command 并发。"""
        pid_path = cls.get_command_pid_path(command_name)
        fd = cls.create_command_pid_file(pid_path, command_name)
        try:
            yield
        finally:
            cls.delete_command_pid_file(pid_path, fd)

    @classmethod
    def get_command_pid_path(cls, command_name: str) -> str:
        """获取命令级 pid 文件路径。"""
        service_id = cls.safe_pid_name(cls.get_service_id())
        safe_command_name = cls.safe_pid_name(command_name)
        settings = _get_bootstrap_context().settings
        # A dot, which service module names cannot hold ([a-z][a-z0-9_]*): "a_b.pid" is service a_b's
        # own file, "a.b.pid" command b of service a. Absolute, as a service's own: a relative pid_dir
        # must not follow a command that changes its working directory.
        return os.path.abspath(os.path.join(settings.process.pid_dir, f"{service_id}.{safe_command_name}.pid"))

    @staticmethod
    def safe_pid_name(value: str) -> str:
        """把 service/command 名称转换为安全 pid 文件名片段。"""
        safe_name = re.sub(r"[^0-9A-Za-z_.-]+", "_", value.strip()).strip("._-")
        if not safe_name:
            raise ValueError("command name cannot be converted to a safe pid file name")
        return safe_name

    @classmethod
    def create_command_pid_file(cls, pid_path: str, command_name: str) -> int:
        """创建命令级 pid 文件并持有非阻塞文件锁。"""
        try:
            fd = _lock_pid_file(pid_path)
        except BlockingIOError:
            logger.error("%s command %s already started, pid: %s", cls.get_service_name(), command_name, _pid_in(pid_path) or "unknown")
            sys.exit(1)
        _write_pid(fd, os.getpid())
        logger.info("%s command %s pid: %s", cls.get_service_name(), command_name, os.getpid())
        return fd

    @classmethod
    def delete_command_pid_file(cls, pid_path: str, fd: int) -> None:
        """删除当前进程持有的命令级 pid 文件并放锁。"""
        _release_pid_file(fd, pid_path)

    @staticmethod
    def _is_async_callable(func: Callable) -> bool:
        """判断命令入口是否为异步 callable。"""
        target = inspect.unwrap(func)
        if inspect.iscoroutinefunction(target):
            return True
        if not callable(target):
            return False
        return inspect.iscoroutinefunction(inspect.unwrap(target.__call__))

    @staticmethod
    def _run_sync_command(func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        执行同步服务命令。

        同步服务命令不进入异步生命周期。如果包装器返回 coroutine，说明服务把
        async 方法伪装成了同步函数，会导致生命周期和事件循环边界不清晰。
        """
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if close:
                close()
            raise TypeError("同步服务 command 返回了 awaitable；请直接定义 async 服务方法。")
        return result

    async def _run_async_cli_command(self, command_name: str, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        执行异步一次性 CLI 命令。

        异步 command 会进入 command 级生命周期，并在同一个事件循环中执行
        before_command、命令主体和 after_command。

        同步服务 command 在 execute_command 中直接调用，不进入这里。App command
        固定为 async，因此全部使用本生命周期。
        """
        command_error: BaseException | None = None
        try:
            storages.init_app()
            await self._start_nats()
            await self._start_taskiq()
            await self.before_command(command_name, *args, **kwargs)
            return await func(*args, **kwargs)
        except BaseException as exc:
            command_error = exc
            raise
        finally:
            # after_command 在 taskiq/NATS 仍开着时运行，可以发消息、投任务；框架自己的收尾在它之后。
            try:
                await self.after_command(command_name, *args, **kwargs)
            except BaseException as error:
                if command_error is None:
                    command_error = error
                    raise
                logger.exception("%s 异步命令 %s 清理失败，保留命令原始异常", self.app_name, command_name)
            finally:
                try:
                    await self._close_services(command_error)
                finally:
                    self._close_logging()

    async def _start_nats(self) -> None:
        """Own a sending connection before business hooks, without importing events."""
        if not self.bootstrap_context.settings.nats_bus.enabled:
            return
        self._nats_error = None
        try:
            from oldman.providers.nats import bus

            await bus._connect()
            self._nats_started = True
        except BaseException as error:
            self._nats_error = error
            raise

    async def _start_nats_consuming(self) -> None:
        """Only a fully initialized long-running service starts its declared handlers."""
        if not self._nats_started or not self.bootstrap_context.settings.nats_bus.consume:
            return
        try:
            from oldman.providers.nats import bus

            await bus._start_consuming()
        except BaseException as error:
            self._nats_error = error
            raise

    async def _stop_nats_consuming(self, original_error: BaseException | None = None) -> None:
        """End handlers before business resources; keep sending available to hooks."""
        if not self._nats_started:
            return
        from oldman.providers.nats import bus

        try:
            await bus._stop_consuming()
        except BaseException as error:
            self._nats_error = error
            if original_error is None:
                raise
            logger.exception("NATS receiver cleanup failed; preserving the original service error")

    async def _close_nats(self, original_error: BaseException | None = None) -> None:
        """Close this lifecycle's connection, including after a business hook failure."""
        if not self._nats_started:
            return
        self._nats_started = False
        from oldman.providers.nats import bus

        try:
            await bus.stop()
        except BaseException as error:
            self._nats_error = error
            if original_error is None:
                raise
            logger.exception("NATS final cleanup failed; preserving the original service error")

    async def _close_publishers(self, original_error: BaseException | None = None) -> None:
        """Taskiq shutdown hooks may still use Core NATS; close it last on every path."""
        try:
            await self._close_taskiq(original_error)
        except BaseException as error:
            original_error = error
            raise
        finally:
            await self._close_nats(original_error)

    async def _close_services(self, original_error: BaseException | None = None) -> None:
        """The framework's own cleanup, after the service's stop hook, on every entry point and outcome.

        Taskiq and NATS close first: their shutdown hooks may still publish or write through the
        database. Then the model cache's pending invalidations, which need Redis. Last the memory
        cache, the Redis clients and the database engine: closing them any earlier lets a later
        ``get_session()`` build an engine nobody closes. The service's own stop hook runs before all
        of this, so it can still publish, enqueue tasks and use the database.

        Every step runs whatever failed before it. With ``original_error`` the failures are logged;
        without one the first is raised once every step has run.
        """
        from oldman.db.sqlalchemy.cache import wait_for_invalidations

        first_error: BaseException | None = None
        for step in (lambda: self._close_publishers(original_error), wait_for_invalidations, self._close_shared_resources):
            try:
                await step()
            except BaseException as error:
                if original_error is None and first_error is None:
                    first_error = error
                else:
                    logger.exception("%s 收尾失败，保留最先出现的异常", self.app_name)
        if first_error is not None:
            raise first_error

    async def _close_shared_resources(self) -> None:
        """关闭进程共享的缓存、Redis 和数据库引擎。

        每个都要关：留着数据库连接不放，下一次启动或者重启会看到连接数不降。
        """
        from oldman.cache import memory_cache
        from oldman.db import db_manager
        from oldman.providers.redis import redis_client

        try:
            await memory_cache.close()
        finally:
            try:
                await redis_client.close()
            finally:
                await db_manager.close()
        logger.info("%s 的缓存、Redis 与数据库连接已关闭", self.app_name)

    async def _start_taskiq(self) -> None:
        """Manage publication only; task discovery belongs to Worker/Scheduler."""
        if not self.bootstrap_context.settings.taskiq.enabled:
            return
        self._taskiq_error = None
        try:
            from oldman.tasks.distributed import broker
            from oldman.tasks.distributed.broker import startup_broker

            await startup_broker(broker)
            self._taskiq_started = True
        except BaseException as error:
            self._taskiq_error = error
            raise

    async def _close_taskiq(self, original_error: BaseException | None = None) -> None:
        """Close only this lifecycle's successful startup, preserving prior errors."""
        if not self._taskiq_started:
            return
        self._taskiq_started = False
        from oldman.tasks.distributed import broker

        try:
            await broker.shutdown()
        except BaseException as error:
            if original_error is None:
                self._taskiq_error = error
                raise
            logger.exception("Taskiq publisher cleanup failed; preserving the original service error")

    def configure_command_logging(
        self,
        command_name: str,
        *,
        stdout_to_stderr: bool = False,
    ) -> None:
        """Switch an async CLI command instance to command-level log files."""
        log_file_name = self.safe_pid_name(command_name).lower().replace("-", "_")
        self.log_file_name = log_file_name
        self.logging_runtime = init_logging(
            log_file_name,
            logger_path=self.log_file_path,
            logger_level=self.logger_level,
            config=(
                {
                    "formatters": {
                        "generic": {"stream": "ext://sys.stderr"},
                    },
                    "handlers": {
                        "console": {"stream": "ext://sys.stderr"},
                    },
                }
                if stdout_to_stderr
                else None
            ),
        )
        self.log_config = self.logging_runtime.log_config
        self._logging_closed = False

    async def before_command(self, command_name: str, *args: Any, **kwargs: Any) -> None:
        """异步一次性命令执行前的生命周期钩子。"""
        return None

    async def after_command(self, command_name: str, *args: Any, **kwargs: Any) -> None:
        """异步一次性命令结束后的生命周期钩子，命令异常时也会执行。

        运行时 taskiq/NATS 仍开着；框架在它之后关闭它们和缓存、Redis、数据库，覆盖时不必调用 super()。
        """
        return None

    @classmethod
    def get_all_services(cls) -> dict[str, type["BaseApplication"]]:
        """
        获取所有服务类
        通过反射查找所有 BaseApplication 的子类
        """
        services = {}

        def _get_subclasses(base_cls):
            """递归获取所有子类"""
            for subclass in base_cls.__subclasses__():
                # 检查是否为抽象类（有抽象方法的类不应该被实例化）
                if not getattr(subclass, "__abstractmethods__", None):
                    service_id = subclass.get_service_id()
                    services[service_id] = subclass
                # 递归查找子类的子类
                _get_subclasses(subclass)

        _get_subclasses(cls)
        return services

    def __init__(
        self,
        app_name: str | None = None,
        pid_file_path: str | None = None,
        log_file_path: str | None = None,
        config: ServiceBootstrapContext | None = None,
    ) -> None:
        """
        Initialize application
        :param app_name: Name of the application
        :param pid_file_path: Path to PID file
        :param log_file_path: Path to log file
        :param config: Configuration object
        """
        self.bootstrap_context = (
            config if config is not None else _get_bootstrap_context()
        )
        if not app_name:
            app_name = self.get_service_name()
        file_name = self.safe_pid_name(
            self.bootstrap_context.service_module
        ).lower()
        self.app_name = app_name
        self.log_file_path = log_file_path
        self.log_file_name = file_name
        self._should_exit = False
        self._taskiq_started = False
        self._taskiq_error: BaseException | None = None
        self._nats_started = False
        self._nats_error: BaseException | None = None
        application_settings = self.bootstrap_context.settings

        if pid_file_path:
            self.pid_file_path = pid_file_path
        else:
            self.pid_file_path = os.path.join(application_settings.process.pid_dir, f"{file_name}.pid")
        # Absolute: a relative pid_dir must not follow a service that changes its working directory.
        self.pid_file_path = os.path.abspath(self.pid_file_path)
        self._pid_fd: int | None = None

        self.logger_level = application_settings.logging.resolved_level(debug=application_settings.core.debug)
        if not self.log_file_path:
            self.log_file_path = application_settings.logging.dir
        self._logging_closed = False
        # A child context owns the process-local writers already. Reinitializing here
        # would incorrectly start a rotation coordinator inside the child process.
        active_runtime = get_active_runtime()
        if (
            active_runtime is not None
            and active_runtime.process_id == os.getpid()
            and not active_runtime.closed
            and active_runtime.installed_from_context
        ):
            self.logging_runtime: LoggingRuntime = active_runtime
        else:
            self.logging_runtime = init_logging(
                self.log_file_name,
                logger_path=self.log_file_path,
                logger_level=self.logger_level,
            )
        self.log_config = self.logging_runtime.log_config

        # bootstrap_service() refuses a second service in one process, so a later instance
        # is always the same service again and simply takes the place of the earlier one.
        global _current_service
        _current_service = self

    @classmethod
    def current(cls) -> Self | None:
        """Return the service this process runs if it is a ``cls``, otherwise None.

        It only looks the service up and never constructs one. Every process that runs a
        service constructs one instance of it before anything else: the command line does
        for service and App commands, and each Sanic worker does for itself. A shell, a
        script that only calls bootstrap_service(), and Taskiq worker processes construct
        none, so the answer there is None.

        Call it inside functions. A module-level ``svc = WebService.current()`` is fixed
        when the module is imported, and the command line imports App commands and the
        service module's own imports before it constructs the service — those modules
        would keep None after the service runs.

        Reusable Apps do not know the project's service class; they ask
        ``BaseApplication.current()`` or ``WebApplication.current()``.
        """
        running = _current_service
        return running if isinstance(running, cls) else None

    @property
    def runtime_app(self) -> "WebApp | None":
        """The Web server application this service created, or None when it has none.

        WebApplication overrides this. It is defined here as well so that code holding
        ``BaseApplication.current()`` can ask any service without a cast: a service that
        serves no HTTP answers None.
        """
        return None

    @abstractmethod
    def init(self) -> None:
        """
        Initialize the application (to be implemented by subclasses)
        :return:
        """
        raise NotImplementedError

    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> None:
        """
        Run the application (to be implemented by subclasses)
        """
        raise NotImplementedError

    def _setup_system_signals(self) -> None:
        """
        Setup signal handlers
        """
        # Ignore SIGHUP
        signal.signal(signal.SIGHUP, SIG_IGN)

    @property
    def _identity_path(self) -> Path:
        """The running service's identity record, beside its PID file (see oldman.runtime._process_group)."""
        return Path(self.pid_file_path).with_suffix(".identity.json")

    def _stop_timeout(self) -> float:
        """How long stop waits for the service's process group before killing it."""
        return self.bootstrap_context.settings.process.stop_timeout

    def delete_pid_file(self) -> None:
        """Remove this run's records and release the lock; a no-op for an instance that holds no lock.

        Under the lock nothing else uses the PID file, so it goes whatever it holds. The identity
        record goes only when it is this run's: when start refused because the previous run's
        processes survive, that run's record stays for stop to report. Silent: it runs after the
        service has closed its logging.
        """
        fd, self._pid_fd = self._pid_fd, None
        if fd is None:
            return
        # The PID file first, then the identity record, both before the lock goes: a stop never finds
        # this run's PID file without its record (see start). A start that locks a fresh file at the
        # path in between still reads this run's record and is refused while this process lives.
        _release_pid_file(fd, self.pid_file_path, before_unlock=self._remove_own_identity)

    def _remove_own_identity(self) -> None:
        """Remove the identity record if it is this process's run."""
        try:
            if GroupIdentity.from_json(self._identity_path.read_text(encoding="utf-8")).pid == os.getpid():
                self._identity_path.unlink()
        except (OSError, ValueError, TypeError):
            pass  # No record, or one that is not this run's to judge: stop deals with an unreadable one.

    def _write_identity(self, identity: GroupIdentity) -> None:
        """Replace the identity record in one step: a reader finds the whole previous record or the whole new one."""
        temporary = self._identity_path.with_name(f"{self._identity_path.name}.{os.getpid()}.tmp")
        try:
            with open(temporary, "w", encoding="utf-8") as record:
                record.write(identity.to_json())
                record.flush()
                os.fsync(record.fileno())
            os.replace(temporary, self._identity_path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    @contextmanager
    def _records_lock(self) -> Iterator[bool]:
        """Hold the PID file lock and yield True while no run holds it, or yield False while one does.

        Records removed under the lock are never those of a run that has just started. The PID file
        itself goes when the lock is released (see _release_pid_file). A start that tries to lock it in
        that moment is refused as already running: microseconds, and only while a stop cleans up.
        """
        try:
            fd = _lock_pid_file(self.pid_file_path)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            _release_pid_file(fd, self.pid_file_path)

    def _refuse_surviving_group(self) -> None:
        """Refuse to start while processes of the previous run are still alive.

        The PID file lock was free, so that run's main process is gone, but processes it started
        (Sanic workers whose primary was killed) may still hold its port. A new identity record would
        put them out of stop's reach. A free lock with the main process alive means the running
        service's PID file was removed or replaced: that group is the service itself.
        """
        try:
            previous = GroupIdentity.from_json(self._identity_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            # No record, or an unreadable one: nothing to check. Accepted: a running service whose PID
            # file was removed and whose record is unreadable is not seen here (two outside faults).
            return
        survivors = group_members(previous)
        if survivors and leader_is_alive(previous):
            raise RuntimeError(
                f"{self.app_name} is still running (main process {previous.pid}), but its PID file {self.pid_file_path} "
                "was removed or replaced, so this start could not see it. Use stop, which finds it by its identity record."
            )
        if survivors:
            raise self._orphaned_run(previous, survivors)

    def _orphaned_run(self, identity: GroupIdentity, survivors: tuple[int, ...]) -> RuntimeError:
        """A run whose main process is gone while processes it started live on: neither start nor stop may take it."""
        return RuntimeError(
            f"{self.app_name}: the main process of its last run is gone, but processes it started are still alive "
            f"in process group {identity.pgid}: {', '.join(map(str, survivors))}. "
            f"Stop them with `kill -TERM -{identity.pgid}`, then start the service again."
        )

    def start(self, *args: Any, **kwargs: Any) -> None:
        """Run the service, holding its PID file lock and identity record for its whole run.

        Running means the PID file is locked: the kernel releases the lock however the process ends,
        so a PID file left behind, or its number reused by another process, never looks like a running
        service; a child the service forks closes its copy of the lock. The service owns a process
        group, so stop can wait for, and past its deadline kill, every process the run started; a
        child that leaves the group itself (setsid, setpgid) is the service's own to end. Linux only:
        the identity comes from /proc and the boot id.
        """
        try:
            self._pid_fd = _lock_pid_file(self.pid_file_path)
        except BlockingIOError:
            holder = _pid_in(self.pid_file_path) or "unknown"
            raise RuntimeError(f"{self.app_name} is already running, pid: {holder}") from None
        try:
            self._refuse_surviving_group()
            with service_process_group() as identity:
                self._group_identity = identity
                # The identity first: stop goes by it, so no moment has a pid without an identity to verify it.
                self._write_identity(identity)
                _write_pid(self._pid_fd, identity.pid)
                logger.info(f"{self.app_name} main process pid: {identity.pid}")
                self.run(*args, **kwargs)
        finally:
            self.delete_pid_file()

    def stop(self, *args: Any, **kwargs: Any) -> int:
        """Stop the running service and return once its whole process group has exited.

        SIGTERM goes to the service's main process; the group is killed after `_stop_timeout()`
        seconds. Returns the main process's pid, which the CLI prints, or 0 when nothing runs.
        """
        try:
            recorded = self._identity_path.read_text(encoding="utf-8")
            identity = GroupIdentity.from_json(recorded)
        except FileNotFoundError:
            return self._stop_without_identity()
        except (ValueError, TypeError) as error:
            return self._stop_with_unreadable_identity(error)
        members = group_members(identity)
        running = bool(members)
        if running and not leader_is_alive(identity):
            raise self._orphaned_run(identity, members)
        if running and identity.pgid == os.getpgrp():
            raise RuntimeError(f"{self.app_name}: stop cannot be called from inside the running service, whose process group it would signal")
        if running:
            forced = stop_process_group(identity, self._stop_timeout())
            logger.info(f"{self.app_name} stopped{' after the stop deadline' if forced else ''}")
        else:
            logger.info(f"{self.app_name} is not running; removing the records of its last run")
        self._remove_records(recorded)
        return identity.pid if running else 0

    def _remove_records(self, recorded: str) -> None:
        """After a stop, remove the records that still describe the group it stopped.

        A run that ends normally removes its own; one that was killed cannot. A run that has started
        since holds the lock, and the records are its: leave them.
        """
        with self._records_lock() as free:
            if not free:
                return
            # Unlike a run's own exit, the identity record goes while the PID file still holds the
            # lock at the path: the group is gone, so a start that locked a fresh file could pass its
            # checks and replace the record between this read and the unlink. Accepted instead: a
            # stop arriving in these microseconds finds the PID file without a record and refuses
            # with the "earlier version" message.
            try:
                if self._identity_path.read_bytes() == recorded.encode():
                    self._identity_path.unlink()
            except FileNotFoundError:
                pass

    def _stop_without_identity(self) -> int:
        """Without an identity record nothing runs, unless its PID file names a process stop cannot verify.

        A start writes its identity before its pid, so an empty PID file belongs to a start still on
        its way, or to one killed before it wrote anything.
        """
        if _pid_in(self.pid_file_path):
            raise RuntimeError(
                f"{self.pid_file_path} has no identity record beside it: it was written by an earlier "
                "version or by hand, and its pid cannot be verified. Stop that process with the version "
                "that started it, or remove the file if nothing runs."
            )
        logger.info(f"{self.app_name} is not running")
        return 0

    def _stop_with_unreadable_identity(self, error: Exception) -> int:
        """An identity record that is empty or broken: edited by hand, or damaged on disk (start replaces it whole).

        While no run holds the lock it is a leftover: remove it and report the service as not running,
        so restart goes on. While a run holds it, stop cannot verify which group to signal.

        Accepted: if the running service's PID file was removed as well, the lock at the path is free,
        so this reports the service as not running, and start, which cannot read the record either
        (see _refuse_surviving_group), starts a second run. It takes two outside faults at once.
        """
        with self._records_lock() as free:
            if free:
                self._identity_path.unlink(missing_ok=True)
                logger.info(f"{self.app_name} is not running; removed its unreadable identity record {self._identity_path} ({error})")
                return 0
        raise RuntimeError(
            f"{self.app_name} is running (its PID file is locked), but its identity record {self._identity_path} cannot be "
            f"read ({error}), so stop cannot verify which process group to signal and sends nothing. End its main process "
            f"(pid {_pid_in(self.pid_file_path) or 'not written yet'}) with `kill -TERM <pid>`."
        )

    @staticmethod
    def stop_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
        try:
            if not loop:
                loop = asyncio.get_event_loop()
            if loop and loop.is_running():
                loop.call_soon_threadsafe(loop.stop)  # type: ignore
        except Exception as e:
            logger.error(f"Error stopping loop: {repr(e)}")

    def restart(self, *args: Any, **kwargs: Any) -> None:
        """Stop the running service, waiting until its group has exited, then start a new run."""
        self.stop(*args, **kwargs)
        self.start(*args, **kwargs)

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        """
        Shutdown the application
        """
        logger.info(f"Shutting down {self.app_name}")
        self._close_logging()
        sys.exit(0)

    def _close_logging(self) -> None:
        """Close this application's logging runtime once after its final record."""
        if self._logging_closed:
            return
        self._logging_closed = True
        self.logging_runtime.close()
