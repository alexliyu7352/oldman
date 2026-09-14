import asyncio
import atexit
import fcntl
import inspect
import os
import re
import signal
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import contextmanager
from signal import SIG_IGN
from typing import TYPE_CHECKING, Any

from oldman.i18n import gettext_noop
from oldman.logging import (
    LoggingRuntime,
    get_active_runtime,
    init_logging,
    logger,
)
from oldman.runtime.bootstrap import (
    ServiceBootstrapContext,
    _get_bootstrap_context,
)
from oldman.storage import storages

if TYPE_CHECKING:
    from oldman.cli import Command

PublicCommandEntry = tuple[Callable, str]


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
                )
            )
        return cls._run_sync_command(bound_func, *args, **kwargs)

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
            )
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
        return os.path.join(
            settings.process.pid_dir,
            f"{service_id}_{safe_command_name}.pid",
        )

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
        os.makedirs(os.path.dirname(pid_path), exist_ok=True)

        flags = os.O_RDWR | os.O_CREAT
        fd: int | None = None
        try:
            fd = os.open(pid_path, flags, 0o644)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pid = ""
            if fd is not None:
                os.lseek(fd, 0, os.SEEK_SET)
                pid = os.read(fd, 64).decode(errors="ignore").strip()
                os.close(fd)
            logger.error("%s command %s already started, pid: %s", cls.get_service_name(), command_name, pid or "unknown")
            sys.exit(1)
        except Exception:
            if fd is not None:
                os.close(fd)
            raise

        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)
        logger.info("%s command %s pid: %s", cls.get_service_name(), command_name, os.getpid())
        return fd

    @classmethod
    def delete_command_pid_file(cls, pid_path: str, fd: int) -> None:
        """删除当前进程持有的命令级 pid 文件。"""
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            pid = os.read(fd, 64).decode(errors="ignore").strip()
            if pid == str(os.getpid()) and os.path.exists(pid_path):
                try:
                    os.remove(pid_path)
                except FileNotFoundError:
                    pass
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

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
            try:
                await self.after_command(command_name, *args, **kwargs)
            except BaseException as error:
                if command_error is None:
                    command_error = error
                    raise
                logger.exception("%s 异步命令 %s 清理失败，保留命令原始异常", self.app_name, command_name)
            finally:
                try:
                    await self._close_publishers(command_error)
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
        """异步一次性命令结束后的生命周期钩子，命令异常时也会执行。"""
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
        self.background_tasks = []
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

        self.logger_level = application_settings.logging.level
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
        self._pid_cleanup_callback: Callable[[], None] | None = None

        if os.getppid() == 1:
            self._pid_cleanup_callback = self.delete_pid_file
            atexit.register(self._pid_cleanup_callback)

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

    def create_pid_file(self) -> None:
        """
        Create PID file
        """
        pid = str(os.getpid())
        if not os.path.exists(os.path.dirname(self.pid_file_path)):
            os.makedirs(os.path.dirname(self.pid_file_path))
        with open(self.pid_file_path, "w") as f:
            f.write(pid)
        logger.info(f"{self.app_name} main progress pid: {pid}")

    def delete_pid_file(self) -> None:
        """
        Delete PID file
        """
        logger.info(f"{self.app_name} shutdown, pid: {os.getpid()}")
        if os.path.exists(self.pid_file_path):
            os.remove(self.pid_file_path)

    def check_pid_status(self) -> None:
        """
        Check if process is already running
        """
        if os.path.exists(self.pid_file_path):
            with open(self.pid_file_path) as f:
                pid = f.read()
            if pid and os.path.exists(f"/proc/{pid}"):
                logger.error(f"{self.app_name} already started, pid: {pid}")
                sys.exit(1)
            else:
                self.create_pid_file()
        else:
            self.create_pid_file()

    def start(self, *args: Any, **kwargs: Any) -> None:
        """
        Start the application
        """
        self.check_pid_status()
        self.run(*args, **kwargs)

    def stop(self, *args: Any, **kwargs: Any) -> int:
        """
        Stop the application
        """
        if os.path.exists(self.pid_file_path):
            with open(self.pid_file_path) as f:
                pid = int(f.read())
            if os.path.exists(f"/proc/{pid}"):
                pid = int(pid)
                os.kill(pid, signal.SIGTERM)
                logger.info(f"{self.app_name} stop success")
            else:
                logger.error(f"{self.app_name} not running")
                return 0
            return pid
        else:
            logger.error(f"{self.app_name} not running")
            return 0

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
        """
        Restart the application
        """
        pid = self.stop(*args, **kwargs)
        if pid <= 0:
            time.sleep(5)
        else:
            while True:
                if os.path.exists(f"/proc/{pid}"):
                    time.sleep(1)
                else:
                    break
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
        try:
            self._run_registered_pid_cleanup()
        finally:
            self.logging_runtime.close()

    def _run_registered_pid_cleanup(self) -> None:
        """Run a registered PID cleanup before logging closes, never again at exit."""
        callback = self._pid_cleanup_callback
        if callback is None:
            return
        self._pid_cleanup_callback = None
        atexit.unregister(callback)
        callback()
