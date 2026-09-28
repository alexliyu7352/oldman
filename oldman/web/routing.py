"""Oldman names and helpers for Sanic routing."""

from __future__ import annotations

import importlib
from glob import glob
from importlib import import_module, util
from inspect import getmembers
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, TypeVar

from sanic import Sanic as WebApp
from sanic.blueprints import Blueprint

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


_Handler = TypeVar("_Handler", bound="Callable[..., object]")

#: 本进程还没有 Web 服务器时记下的登记,按记下的顺序排列。``WebApplication.init()`` 建好应用、
#: 导入视图之前一次补上并清空。
_pending_registrations: list[Callable[[WebApp], object]] = []


def _running_server() -> WebApp | None:
    """本进程运行的服务建好的 Web 应用;还没有就是 None。不报错。"""
    from oldman.runtime.base import BaseApplication

    running = BaseApplication.current()
    return None if running is None else running.runtime_app


def _register_pending_routes(app: WebApp) -> None:
    """把没有服务器时记下的登记补到 ``app`` 上,然后清空,不会补第二次。"""
    pending = list(_pending_registrations)
    _pending_registrations.clear()
    for register in pending:
        register(app)


class Router:
    """注册路由的入口。应用在 ``views.py`` 里用它,不接触底层服务器实例。

    这一层存在的理由是**边界**,不是便利。它取代的 ``get_app()`` 返回的是整个
    Sanic 实例,于是三件事同时发生:``app`` 一词在项目里有了两个意思(``apps.py``
    里的 ``app`` 是 :class:`~oldman.apps.config.AppConfig`,``views.py`` 里的
    ``app`` 是服务器)、底层服务器成为公开 API 的一部分、而使用者拿到的权限远超
    它真正需要的「注册一条路由」。

    实测框架、脚手架、文档与 Demo 中 ``get_app()`` 的**全部**用法都是注册路由,
    没有一处访问 ``app.ctx`` 或 ``app.config``——所以这里只暴露路由方法。
    运行期要取服务对象,用服务类的 ``current()``。

    **导入视图模块永远不会因为还没有服务器而失败。** 本进程的服务已经建好应用时,
    登记立即生效;还没有时(shell、只 bootstrap 的脚本、App 命令,以及服务构造之前就被
    导入的模块),登记先记下,``WebApplication.init()`` 在导入视图之前一次补上。没有
    Web 服务的进程里,记下的登记永远不会生效。代价是路由名重复这类错误要到建应用时才报,
    仍在启动阶段。

    框架承诺的参数只有 ``uri`` 与 ``name``(实测也只用到这两个)。其余关键字原样
    转交底层服务器,**不属于本框架的契约**:底层换了它们就可能变。
    """

    __slots__ = ()

    @staticmethod
    def _register(register: Callable[[WebApp], object]) -> None:
        """有服务器就立即登记,没有就记下,等 ``WebApplication.init()`` 补上。"""
        server = _running_server()
        if server is None:
            _pending_registrations.append(register)
        else:
            register(server)

    def _decorator(self, route_on: Callable[[WebApp], Callable[..., object]]) -> Callable[[_Handler], _Handler]:
        """把一个「在服务器上登记」的装饰器变成可以先记下的装饰器;原样返回处理器。"""

        def decorator(handler: _Handler) -> _Handler:
            self._register(lambda server: route_on(server)(handler))
            return handler

        return decorator

    def add_route(self, handler: _Handler, uri: str, *, name: str | None = None, **kwargs: object) -> _Handler:
        """注册一个处理器,通常是类视图的 ``as_view()`` 结果。"""
        self._register(lambda server: server.add_route(handler, uri, name=name, **kwargs))  # type: ignore[arg-type]
        return handler

    def route(self, uri: str, methods: Iterable[str], *, name: str | None = None, **kwargs: object) -> Callable[[_Handler], _Handler]:
        """按给定方法集注册。单一方法优先用下面的同名快捷方法。"""
        return self._decorator(lambda server: server.route(uri, methods=methods, name=name, **kwargs))  # type: ignore[arg-type,return-value]

    def websocket(self, uri: str, *, name: str | None = None, **kwargs: object) -> Callable[[_Handler], _Handler]:
        """注册 WebSocket 路由。"""
        return self._decorator(lambda server: server.websocket(uri, name=name, **kwargs))  # type: ignore[arg-type,return-value]

    def get(self, uri: str, *, name: str | None = None, **kwargs: object) -> Callable[[_Handler], _Handler]:
        """注册 GET 路由。"""
        return self._decorator(lambda server: server.get(uri, name=name, **kwargs))  # type: ignore[arg-type,return-value]

    def post(self, uri: str, *, name: str | None = None, **kwargs: object) -> Callable[[_Handler], _Handler]:
        """注册 POST 路由。"""
        return self._decorator(lambda server: server.post(uri, name=name, **kwargs))  # type: ignore[arg-type,return-value]

    def put(self, uri: str, *, name: str | None = None, **kwargs: object) -> Callable[[_Handler], _Handler]:
        """注册 PUT 路由。"""
        return self._decorator(lambda server: server.put(uri, name=name, **kwargs))  # type: ignore[arg-type,return-value]

    def patch(self, uri: str, *, name: str | None = None, **kwargs: object) -> Callable[[_Handler], _Handler]:
        """注册 PATCH 路由。"""
        return self._decorator(lambda server: server.patch(uri, name=name, **kwargs))  # type: ignore[arg-type,return-value]

    def delete(self, uri: str, *, name: str | None = None, **kwargs: object) -> Callable[[_Handler], _Handler]:
        """注册 DELETE 路由。"""
        return self._decorator(lambda server: server.delete(uri, name=name, **kwargs))  # type: ignore[arg-type,return-value]

    def head(self, uri: str, *, name: str | None = None, **kwargs: object) -> Callable[[_Handler], _Handler]:
        """注册 HEAD 路由。"""
        return self._decorator(lambda server: server.head(uri, name=name, **kwargs))  # type: ignore[arg-type,return-value]

    def options(self, uri: str, *, name: str | None = None, **kwargs: object) -> Callable[[_Handler], _Handler]:
        """注册 OPTIONS 路由。"""
        return self._decorator(lambda server: server.options(uri, name=name, **kwargs))  # type: ignore[arg-type,return-value]


#: 进程级路由注册入口。``from oldman.web import router``
router = Router()


def autodiscover(app: WebApp, *module_names: str | ModuleType, recursive: bool = False) -> None:
    """Discover and register blueprints from one or more modules."""
    package = app.__module__
    blueprints: set[Blueprint] = set()
    imported_paths: set[str] = set()

    def find_blueprints(module: ModuleType) -> None:
        """Collect Blueprint instances defined or imported by one module."""
        for _, member in getmembers(module):
            if isinstance(member, Blueprint):
                blueprints.add(member)

    for module in module_names:
        if isinstance(module, str):
            imported_module = import_module(module, package)
            if imported_module.__file__:
                imported_paths.add(imported_module.__file__)
            module = imported_module
        find_blueprints(module)

        if recursive and module.__file__:
            base = Path(module.__file__).parent
            for path in glob(f"{base}/**/*.py", recursive=True):
                if path in imported_paths:
                    continue
                name = "module"
                if "__init__" in path:
                    *_, name, _ = path.split("/")
                spec = util.spec_from_file_location(name, path)
                if spec and spec.loader:
                    discovered_module = util.module_from_spec(spec)
                    imported_paths.add(path)
                    spec.loader.exec_module(discovered_module)
                    find_blueprints(discovered_module)

    for blueprint in blueprints:
        app.blueprint(blueprint)


def import_app_modules(package_name: str, suffixes: tuple[str, ...] = ("models", "views")) -> None:
    """Import conventional modules from an application package."""
    importlib.import_module(package_name)
    for suffix in suffixes:
        module_name = f"{package_name}.{suffix}"
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise


__all__ = ["Router", "WebApp", "autodiscover", "import_app_modules", "router"]
