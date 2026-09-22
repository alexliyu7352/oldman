"""本地校验门禁用的测试工具：真实浏览器、进程树、PNG 证据。

这些是仓库自己的门禁脚本和演示项目共用的东西，不是运行时依赖：只用标准库，导入它不会拉起服务，
也不会读配置。放在框架里是因为演示项目此前各复制了一份，改一处要改三处。
"""

from oldman.testing.browser import (
    BrowserResult,
    BrowserVerificationError,
    CDPClient,
    ChromePage,
    WebSocket,
    capture_screenshot,
    clear_origin,
    configure_viewport,
    find_chrome,
    find_free_port,
    launch_chrome,
    navigate,
    save_screenshot,
)
from oldman.testing.duplication import (
    duplicate_functions,
    forbidden_attributes,
    forbidden_imports,
    identical_files,
)
from oldman.testing.gates import (
    BrowserGateError,
    ensure_gate_admin,
    gate_settings,
    minimal_environment,
    owned_redis_server,
    owned_service,
    run_browser_child,
    wait_for_service,
)
from oldman.testing.png_evidence import PngEvidence, PngEvidenceError, require_png
from oldman.testing.process_tree import (
    ProcessTreeError,
    ProcessTreeTracker,
    child_subreaper,
    linux_process_table,
    tracked_popen,
    tracked_process_tree,
)

__all__ = [
    "BrowserGateError",
    "BrowserResult",
    "BrowserVerificationError",
    "CDPClient",
    "ChromePage",
    "WebSocket",
    "PngEvidence",
    "PngEvidenceError",
    "ProcessTreeError",
    "ProcessTreeTracker",
    "child_subreaper",
    "configure_viewport",
    "capture_screenshot",
    "clear_origin",
    "duplicate_functions",
    "ensure_gate_admin",
    "find_chrome",
    "find_free_port",
    "forbidden_attributes",
    "forbidden_imports",
    "gate_settings",
    "identical_files",
    "launch_chrome",
    "linux_process_table",
    "minimal_environment",
    "navigate",
    "owned_redis_server",
    "owned_service",
    "require_png",
    "run_browser_child",
    "save_screenshot",
    "tracked_popen",
    "tracked_process_tree",
    "wait_for_service",
]
