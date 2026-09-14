import asyncio
import signal
from abc import abstractmethod
from typing import Any

from oldman.cache import memory_cache
from oldman.logging import logger
from oldman.providers.redis import redis_client
from oldman.runtime.base import BaseApplication
from oldman.runtime.bootstrap import ServiceBootstrapContext
from oldman.storage import storages
from oldman.tasks.simple import BackgroundTaskManager


class SimpleApplication(BaseApplication):
    """通用服务应用基类"""

    def __init__(
        self,
        app_name: str | None = None,
        pid_file_path: str | None = None,
        log_file_path: str | None = None,
        config: ServiceBootstrapContext | None = None,
    ) -> None:
        """Initialize the service and its main-process logging runtime."""
        super().__init__(
            app_name,
            pid_file_path,
            log_file_path,
            config,
        )
        self.task_manager = BackgroundTaskManager()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._main_task: asyncio.Task[None] | None = None
        self._stopping = False

    def init(self) -> None:
        """初始化应用"""
        storages.init_app()
        self.bootstrap_context.apps.load_models()
        logger.info(f"{self.app_name} 初始化完成")
        self._setup_system_signals()

    @abstractmethod
    def prepare(self) -> None:
        """服务启动前的准备工作，子类需实现"""
        raise NotImplementedError

    def run(self, *args: Any, **kwargs: Any) -> None:
        """运行服务"""
        try:
            self.init()
            # Only this receiving runtime loads events. Taskiq Scheduler reuses
            # init(), but owns a different, sending-only run() implementation.
            config = self.bootstrap_context.settings.nats_bus
            if config.enabled and config.consume:
                self.bootstrap_context.apps.load_events()
            self.prepare()
            logger.info(f"Starting {self.app_name} service")

            # 获取或创建事件循环
            try:
                self.loop = asyncio.get_event_loop()
            except RuntimeError:
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)

            # 设置信号处理
            self._setup_signal_handlers()

            # 运行主服务
            self._main_task = self.loop.create_task(self._run_async(*args, **kwargs))
            self.loop.run_until_complete(self._main_task)

        except asyncio.CancelledError as error:
            # A requested stop cancels the root, not the event loop or all handlers.
            if not self._should_exit:
                raise
            if self._nats_error is not None and not isinstance(self._nats_error, asyncio.CancelledError):
                raise self._nats_error from error
        except KeyboardInterrupt:
            logger.info(f"{self.app_name} 收到中断信号，准备退出")
        except Exception as e:
            logger.error(f"{self.app_name} 运行异常: {e}")
            # Keep existing business-error behavior, but required connection or
            # cleanup failures cannot report successful startup.
            if e is self._taskiq_error or self._nats_error is not None:
                raise
        finally:
            self._cleanup()

    async def _run_async(self, *args: Any, **kwargs: Any) -> None:
        """异步运行入口"""
        failure: BaseException | None = None
        try:
            await self._start_nats()
            await self._start_taskiq()
            # 启动前钩子
            await self.before_start()
            await self._start_nats_consuming()

            # 运行主逻辑
            await self.main(*args, **kwargs)
        except BaseException as error:
            failure = error
            raise
        finally:
            self._stopping = True
            try:
                try:
                    await self._stop_nats_consuming(failure)
                finally:
                    # Hooks keep their original order and exception behavior. They
                    # may release dependencies only after Core handlers have left.
                    await self.before_stop()
                    await self.after_stop()
            except BaseException as error:
                failure = error
                raise
            finally:
                await self._close_publishers(failure)

    @abstractmethod
    async def main(self, *args: Any, **kwargs: Any) -> None:
        """主异步入口，子类需实现具体逻辑"""
        raise NotImplementedError

    async def before_start(self) -> None:
        """服务启动前钩子"""
        logger.info(f"{self.app_name} 启动前准备完成")

    async def before_command(self, command_name: str, *args: Any, **kwargs: Any) -> None:
        """一次性命令执行前的轻量生命周期钩子。"""
        logger.info(f"{self.app_name} 命令 {command_name} 启动前准备完成")

    async def before_stop(self) -> None:
        """服务停止前钩子"""
        self._should_exit = True
        # 取消所有后台任务
        for task in self.background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # 停止任务管理器
        self.task_manager.stop_all_sync()
        logger.info(f"{self.app_name} 停止前清理完成")

    async def after_stop(self) -> None:
        """服务停止后钩子"""
        await memory_cache.close()
        await redis_client.close()
        logger.info(f"{self.app_name} 停止后清理完成")

    async def after_command(self, command_name: str, *args: Any, **kwargs: Any) -> None:
        """一次性命令执行后的轻量生命周期钩子。"""
        await memory_cache.close()
        await redis_client.close()
        logger.info(f"{self.app_name} 命令 {command_name} 执行后清理完成")

    def add_background_task(self, coro, *args, **kwargs) -> None:
        """添加后台任务"""
        if self.loop and self.loop.is_running():
            task = self.loop.create_task(coro(*args, **kwargs))
            self.background_tasks.append(task)
        else:
            task = asyncio.create_task(coro(*args, **kwargs))
            self.background_tasks.append(task)

    def _setup_signal_handlers(self) -> None:
        """设置信号处理器"""
        if self.loop:
            for sig in (signal.SIGTERM, signal.SIGINT):
                self.loop.add_signal_handler(sig, self._handle_exit_signal, sig)

    def _handle_exit_signal(self, sig) -> None:
        """Request ordered async shutdown, without interrupting an active cleanup."""
        logger.info(f"{self.app_name} 收到信号 {sig}，准备退出")
        self._request_shutdown()

    def _request_shutdown(self) -> None:
        """Cancel only the root once; its finally owns subscriber and resource cleanup."""
        self._should_exit = True
        if self._main_task is not None and not self._stopping and not self._main_task.cancelling():
            self._main_task.cancel()

    def _cleanup(self) -> None:
        """清理事件循环，并在最后一条清理日志之后关闭日志 runtime。"""
        try:
            if self.loop and not self.loop.is_closed():
                try:
                    # 取消所有未完成的任务
                    pending = asyncio.all_tasks(self.loop)
                    for task in pending:
                        task.cancel()

                    # 等待任务完成
                    if pending:
                        self.loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                except Exception as e:
                    logger.error(f"清理任务时出错: {e}")
                finally:
                    self.loop.close()
        finally:
            # 即使事件循环关闭失败，也必须释放当前进程持有的日志资源。
            self._close_logging()

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        """优雅关闭服务"""
        logger.info(f"Shutting down {self.app_name}")
        if self.loop and self.loop.is_running():
            self._request_shutdown()
            return
        super().shutdown(*args, **kwargs)
