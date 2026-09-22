"""Sanic-backed Oldman Web application runtime."""

from __future__ import annotations

import multiprocessing
from collections.abc import Mapping
from functools import partial
from importlib.util import find_spec
from multiprocessing.util import Finalize
from pathlib import Path
from typing import Any, ClassVar, cast

from sanic import Request as SanicRequest
from sanic import Sanic
from sanic.mixins.listeners import ListenerEvent
from sanic.worker.loader import AppLoader
from sanic_ext import Config, Extend
from sanic_ext.extensions.base import Extension
from sanic_ext.extensions.health.extension import HealthExtension
from sanic_ext.extensions.http.extension import HTTPExtension
from sanic_ext.extensions.injection.extension import InjectionExtension
from sanic_ext.extensions.openapi.extension import OpenAPIExtension
from sanic_ext.extensions.templating.extension import TemplatingExtension

import oldman.conf as conf
import oldman.web.messages as messages
from oldman.cache import memory_cache
from oldman.conf.constants import _find_project_root
from oldman.db import db_manager
from oldman.logging import ChildLoggingContext, logger
from oldman.providers.redis import redis_client
from oldman.runtime.base import BaseApplication
from oldman.runtime.bootstrap import (
    ServiceBootstrapContext,
    bootstrap_service,
)
from oldman.runtime.discovery import get_service_definition, load_service_class
from oldman.storage import storages
from oldman.tasks.simple import BackgroundTaskManager
from oldman.web.errors import OldmanErrorHandler
from oldman.web.routing import WebApp
from oldman.web.session import SessionData, session
from oldman.web.sse import sse


def prepare_process_context() -> None:
    """Let Sanic establish its multiprocessing method before logging starts."""
    if Sanic.START_METHOD_SET:
        return

    expected = Sanic._get_startup_method()
    actual = multiprocessing.get_start_method(allow_none=True)
    if actual is None:
        # Sanic must create the global context before application initialization
        # can construct any other multiprocessing primitives.
        Sanic._set_startup_method()
        return
    if actual != expected:
        raise RuntimeError(f"Sanic requires multiprocessing start method {expected!r}, but {actual!r} is already active")

    # Sanic rejects an already-set context even when it is the expected one.
    Sanic.START_METHOD_SET = True


def _package_locale_root(package_name: str) -> Path | None:
    """Return one importable package's locale directory without importing it."""
    spec = find_spec(package_name)
    if spec is None or not spec.submodule_search_locations:
        return None
    package_root = Path(next(iter(spec.submodule_search_locations)))
    locale_root = package_root / "locales"
    return locale_root if locale_root.is_dir() else None


def _translation_catalog_roots(application: WebApplication) -> tuple[Path, ...]:
    """Build project and installed-App roots in configured override order."""
    roots = [Path(conf.PROJECT_BASE_PATH) / "locales"]
    for package_name in application.bootstrap_context.apps.packages:
        locale_root = _package_locale_root(package_name)
        if locale_root is not None:
            roots.append(locale_root)
    return tuple(dict.fromkeys(roots))


class WebApplication(BaseApplication):
    """Base application for Oldman services served by Sanic."""

    name = "web"
    SESSION_MODEL: ClassVar[type[SessionData]] = SessionData

    def __init__(
        self,
        app_name: str | None = None,
        pid_file_path: str | None = None,
        log_file_path: str | None = None,
        config: ServiceBootstrapContext | None = None,
    ) -> None:
        """Initialize the Sanic primary as the sole rotation coordinator owner."""
        prepare_process_context()
        super().__init__(
            app_name,
            pid_file_path,
            log_file_path,
            config,
        )
        self.task_manager = BackgroundTaskManager()
        self._app: Sanic | None = None

    @property
    def runtime_app(self) -> WebApp | None:
        """Return the initialized Web application without requiring a Sanic import."""
        return self._app

    def get_ext_config(self) -> Mapping[str, Any] | None:
        """Return Sanic-Ext configuration supplied by a concrete service."""
        return None

    def get_extension(self) -> list[Extension | type[Extension]] | None:
        """Return the default Sanic-Ext extension set."""
        return [
            InjectionExtension,
            OpenAPIExtension,
            HTTPExtension,
            HealthExtension,
            TemplatingExtension,
        ]

    def get_runtime_config(self) -> dict[str, Any] | None:
        """Return low-level Sanic configuration overrides."""
        return None

    def init(self) -> None:
        """Create and configure the Sanic application owned by this service."""
        request_class: type[SanicRequest] | None = None
        settings = self.bootstrap_context.settings
        if settings.i18n.use_i18n_path:
            from oldman.web.i18n.request import I18nRequest

            request_class = I18nRequest

        app_options: dict[str, Any] = {
            "strict_slashes": True,
            "configure_logging": False,
        }
        if request_class is not None:
            app_options["request_class"] = request_class
        self._app = Sanic(
            self.app_name,
            error_handler=OldmanErrorHandler(),
            **app_options,
        )
        self._app.ctx.oldman_app_registry = self.bootstrap_context.apps
        # Handlers spawn fire-and-forget work here; the worker cancels it in before_server_stop.
        self._app.ctx.tasks = self.task_manager

        ext_config = self.get_ext_config()
        if ext_config is not None:
            runtime_ext_config = ext_config if isinstance(ext_config, Config) else Config(**dict(ext_config))
            if runtime_ext_config.LOGGING:
                raise ValueError("Sanic-Ext logging conflicts with Oldman's logging runtime")
            Extend(
                self._app,
                config=runtime_ext_config,
                extensions=self.get_extension(),
                built_in_extensions=False,
            )

        self._app.update_config(
            {
                "RESPONSE_TIMEOUT": settings.web.response_timeout,
                "REQUEST_TIMEOUT": settings.web.request_timeout,
                "KEEP_ALIVE_TIMEOUT": settings.web.keep_alive_timeout,
                "REAL_IP_HEADER": settings.web.real_ip_header,
                "PROXIES_COUNT": settings.web.proxies_count,
                "FORWARDED_SECRET": settings.web.forwarded_secret,
                "FALLBACK_ERROR_FORMAT": settings.web.fallback_error_format,
                "WEBSOCKET_MAX_SIZE": settings.web.websocket_max_size,
                "WEBSOCKET_PING_INTERVAL": settings.web.websocket_ping_interval,
                "WEBSOCKET_PING_TIMEOUT": settings.web.websocket_ping_timeout,
                "AUTO_EXTEND": False,
                "NO_COLOR": True,
            }
        )
        runtime_config = self.get_runtime_config()
        if runtime_config:
            self._app.update_config(runtime_config)
        # Sanic must not pre-color records that may also reach plain file sinks.
        self._app.update_config({"NO_COLOR": True})

        if settings.web.messages.enabled:
            messages.init_app(self._app)
        if settings.web.session.enabled:
            session.init_app(
                self._app,
                session_model=self.SESSION_MODEL,
            )
        storages.init_app(self._app)
        # SSE route decorators are loaded with application views, so bind their
        # process-local extension before importing registered application modules.
        sse.init_app(self._app)

        self.bootstrap_context.apps.load_models()
        self.bootstrap_context.apps.load_views()
        if settings.nats_bus.enabled and settings.nats_bus.consume:
            self.bootstrap_context.apps.load_events()

        if settings.web.static.url and settings.web.static.root:
            self._app.static(settings.web.static.url, settings.web.static.root, name="static")

        self._app.register_listener(
            self._services_before_server_start if settings.taskiq.enabled or settings.nats_bus.enabled else self.before_server_start,
            "before_server_start",
        )
        self._app.register_listener(
            self._services_after_server_start if settings.nats_bus.enabled else self.after_server_start,
            "after_server_start",
        )
        self._app.register_listener(
            self._services_after_server_stop if settings.taskiq.enabled or settings.nats_bus.enabled else self.after_server_stop,
            "after_server_stop",
        )
        self._app.register_listener(
            self._services_before_server_stop if settings.nats_bus.enabled else self.before_server_stop,
            "before_server_stop",
        )
        self._app.register_listener(
            self.main_process_ready,
            ListenerEvent.MAIN_PROCESS_READY,
        )
        if settings.i18n.use_i18n:
            from oldman.web.middlewares.i18n import cleanup_i18n, install_i18n

            self._app.register_middleware(install_i18n, "request")
            self._app.register_middleware(cast(Any, cleanup_i18n), "response")

        logger.info("Registered routes:")
        for _key, route in self._app.router.routes_all.items():
            logger.info(
                "[%s] url is: %s method is: %s",
                route.name,
                route.uri,
                route.methods,
            )
        self._setup_system_signals()

    async def main_process_ready(self, app: WebApp) -> None:
        """Run after the Sanic primary process is ready."""
        return None

    async def before_server_start(self, app: WebApp) -> None:
        """Initialize request-time Web services inside each server worker."""
        app.ctx.is_running = True
        settings = self.bootstrap_context.settings
        if settings.i18n.use_i18n:
            from oldman.web.i18n.translation import (
                build_i18n_url_with_request,
                translation,
            )

            translation.initialize(
                app,
                settings.i18n,
                catalog_roots=_translation_catalog_roots(self),
                public_domain=settings.web.domain,
                static_url=settings.web.static.url,
            )

            if settings.i18n.use_i18n_path and hasattr(app.ext, "environment"):
                app.ext.environment.globals["url_for"] = build_i18n_url_with_request

    async def after_server_start(self, app: WebApp) -> None:
        """Run after one Sanic server worker starts."""
        return None

    async def _services_before_server_start(self, app: WebApp) -> None:
        """Prepare sending in the actual worker; failed startup has no stop hook guarantee."""
        try:
            await self._start_nats()
            await self._start_taskiq()
            await self.before_server_start(app)
        except BaseException as error:
            await self._close_publishers(error)
            raise

    async def _services_after_server_start(self, app: WebApp) -> None:
        """Start Core handlers only after the user has initialized their dependencies."""
        try:
            await self.after_server_start(app)
            await self._start_nats_consuming()
        except BaseException as error:
            await self._close_publishers(error)
            raise

    async def _services_before_server_stop(self, app: WebApp) -> None:
        """End handlers before user cleanup; a failed hook may prevent Sanic's next phase."""
        try:
            await self._stop_nats_consuming()
            await self.before_server_stop(app)
        except BaseException as error:
            await self._close_publishers(error)
            raise

    async def _services_after_server_stop(self, app: WebApp) -> None:
        """Close taskiq and NATS first, then the resources their shutdown hooks may still use.

        Taskiq 的 shutdown 钩子可能还要写一条收尾记录：`after_server_stop` 已经关掉数据库引擎的话，
        `get_session()` 会惰性重建一个新引擎，而那一个到进程退出都没人关——正好是这段清理想消灭的东西。
        """
        failure: BaseException | None = None
        try:
            await self._close_publishers()
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                await self.after_server_stop(app)
            except BaseException:
                if failure is None:
                    raise
                logger.exception("Worker resource cleanup failed; preserving the publisher error")

    async def before_server_stop(self, app: WebApp) -> None:
        """Cancel worker-owned background tasks before resources are closed."""
        app.ctx.is_running = False
        await self.task_manager.stop_all()

    async def after_server_stop(self, app: WebApp) -> None:
        """Close worker resources while preserving Sanic's final log records."""
        try:
            await memory_cache.close()
        finally:
            try:
                await redis_client.close()
            finally:
                # The engine belongs to the worker too: leaving it open keeps database
                # connections until the process dies, which a reload or a restart notices.
                await db_manager.close()
        logger.info("%s server worker resources closed", self.app_name)

    def create_app(self) -> WebApp:
        """Initialize and return this service's Sanic application."""
        self.init()
        if self._app is None:
            raise RuntimeError("Failed to create app")
        self._app.name = self.app_name
        return self._app

    def prepare_server(self, app: WebApp) -> None:
        """Configure Sanic's listener from the `web` settings.

        `single_process` 是**推导**出来的而不是写死的：写死 True 的话，配了多 worker 或 auto_reload
        的服务会被 Sanic 在 `prepare()` 里直接拒绝（RuntimeError）。要注意它到这里也只参与那条校验——
        真正据此选 `serve_single` 的是 `app.run()`，而这里走的是 `Sanic.serve()`，进程模型始终由
        WorkerManager 决定。想要别的接法就覆盖这个方法，仍然可以调 `super().prepare_server(app)`。
        """
        web = conf.settings.web
        app.prepare(
            host=web.listen_host,
            port=web.listen_port,
            debug=web.debug,
            motd=False,
            auto_reload=web.auto_reload,
            workers=web.workers,
            access_log=web.access_log,
            single_process=web.workers <= 1 and not web.auto_reload,
        )

    def run(self, *args: Any, **kwargs: Any) -> None:
        """Create the primary app and enter Sanic's server lifecycle."""
        del args, kwargs
        try:
            primary = self.create_app()
            factory = partial(
                _create_sanic_app_factory,
                self.bootstrap_context.service_module,
                self.bootstrap_context.config_file,
                self.app_name,
                self.logging_runtime.child_context,
            )
            loader = AppLoader(factory=factory)
            self.prepare_server(primary)

            settings = self.bootstrap_context.settings
            logger.warning("Starting %s service", self.app_name)
            logger.warning("Listening on %s", primary.serve_location)
            logger.warning("Data directory: %s", settings.core.data_dir)
            logger.warning("Logs directory: %s", settings.logging.dir)
            Sanic.serve(primary=primary, app_loader=loader)
        except Exception as exc:
            logger.error("Error while running the server: %r", exc)
            raise
        finally:
            # Sanic.serve returns only after its WorkerManager joined workers.
            self._close_logging()


def _create_sanic_app_factory(
    service_module: str,
    config_file: str | Path,
    app_name: str,
    child_context: ChildLoggingContext,
) -> Sanic:
    """Bootstrap one spawned worker before importing its service module."""
    worker_runtime = child_context.install()
    try:
        bootstrap_context = bootstrap_service(
            service_module,
            config_file=config_file,
        )
        definition = get_service_definition(
            service_module,
            _find_project_root(),
        )
        cls = cast(type[WebApplication], load_service_class(definition))
        instance = cls(app_name, config=bootstrap_context)
        app = instance.create_app()
        # Sanic writes its final worker record after after_server_stop, so the
        # process finalizer owns the writer shutdown.
        Finalize(None, worker_runtime.close, exitpriority=100)
        return app
    except BaseException:
        worker_runtime.close()
        raise


__all__ = ["WebApplication"]
