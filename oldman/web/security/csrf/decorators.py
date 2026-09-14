# csrf/decorators.py
from functools import wraps

from oldman.utils.decorators import method_adaptor
from oldman.web.exceptions import Forbidden
from oldman.web.request import Request


def _csrf_protect():
    """
    CSRF 保护装饰器

    自动从 app.ctx.csrf 获取管理器
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(view, request: Request, *args, **kwargs):
            csrf_manager = request.app.ctx.csrf

            token = csrf_manager.get_token_from_request(request)
            if not token:
                raise Forbidden("CSRF token missing")

            is_valid, error_msg = csrf_manager.validate_token(request, token)
            if not is_valid:
                raise Forbidden(f"CSRF validation failed: {error_msg}")
            if view is None:
                return await func(request, *args, **kwargs)
            return await func(view, request, *args, **kwargs)

        return wrapper

    return decorator


# 修改为装饰器工厂结构：接受配置参数，返回装饰器
def _add_csrf_token():
    """
    添加 CSRF token 到请求上下文（用于模板渲染）
    这是一个装饰器工厂，返回一个装饰器。

    使用方式:
        @app.get("/form")
        @add_csrf_token()
        async def show_form(request):
            ...
    """

    def decorator(func):
        """
        这是实际的装饰器，接收被装饰的目标函数 func。
        """

        @wraps(func)
        async def wrapper(view, request: Request, *args, **kwargs):
            """
            这是最终的包装函数，运行时被调用。
            它期望第一个参数是 view (self/None)，第二个是 request。
            """
            csrf_manager = request.app.ctx.csrf

            # 生成并附加 token
            request.ctx.csrf_token = csrf_manager.generate_token(request)
            if view is None:
                return await func(request, *args, **kwargs)
            return await func(view, request, *args, **kwargs)

        # 装饰器返回包装函数
        return wrapper

    # 工厂函数返回装饰器
    return decorator


def csrf_exempt(func):
    """
    CSRF 豁免装饰器

    使用方式:
        @app.post("/webhook")
        @csrf_exempt
        async def webhook(request):
            ...
    """
    func._csrf_exempt = True
    return func


add_csrf_token = method_adaptor(_add_csrf_token)
csrf_protect = method_adaptor(_csrf_protect)
