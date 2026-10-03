import asyncio
import signal
from abc import abstractmethod
from typing import Any

from oldman.logging import logger
from oldman.runtime.base import BaseApplication
from oldman.runtime.bootstrap import ServiceBootstrapContext
from oldman.storage import storages
from oldman.tasks.simple import BackgroundTaskManager
from oldman.utils.asyncio_utils import new_event_loop


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

            # 服务自己的事件循环：装了 uvloop 就用它
            self.loop = new_event_loop()
            asyncio.set_event_loop(self.loop)

            # 设置信号处理:在循环开始运行之后才装。uvloop 会丢掉"处理函数已装、循环还没运行"时到达的信号,
            # 服务就收不到那次停止请求;call_soon 排在主任务第一步之前,主任务开始前处理函数已就位。
            # 装上之前到达的 SIGTERM 按默认动作结束进程,与 init()、prepare() 期间相同。
            self.loop.call_soon(self._setup_signal_handlers)

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
        except Exception:
            # With the traceback: an ExceptionGroup's own message only counts its sub-exceptions.
            # Raised on, as a Web service does, so the process exits non-zero and a manager that
            # restarts on failure sees it; a requested stop above still ends normally.
            logger.exception(f"{self.app_name} 运行异常")
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
                    # may release dependencies only after Core handlers have left,
                    # and run while taskiq and NATS are still open.
                    await self.before_stop()
                    await self.after_stop()
            except BaseException as error:
                failure = error
                raise
            finally:
                await self._close_services(failure)

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
        # 停止任务管理器（等待每个任务的取消真正落地）
        await self.task_manager.stop_all()
        logger.info(f"{self.app_name} 停止前清理完成")

    async def after_stop(self) -> None:
        """服务停止后钩子，运行时 taskiq/NATS 仍开着；框架在它之后关闭它们和缓存、Redis、数据库，覆盖时不必调用 super()。"""
        return None

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
                        self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
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
