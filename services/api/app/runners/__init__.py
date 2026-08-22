"""Public runner package.

Re-exports the adapter interface, both implementations, and the runner
factory so callers can do:

    from app.runners import (
        ProxmoxAdapter,
        MockProxmoxAdapter,
        RealProxmoxAdapter,
        Runner,
        RunnerError,
        build_runner,
    )
"""
from app.runners.adapter import (
    CloneSpec,
    ClonedVM,
    ProxmoxAdapter,
    VmState,
)
from app.runners.mock_adapter import MockProxmoxAdapter
from app.runners.real_adapter import RealProxmoxAdapter
from app.runners.runner import (
    Runner,
    RunnerError,
    RunRequest,
    RunResult,
    build_runner,
)

__all__ = [
    "CloneSpec",
    "ClonedVM",
    "MockProxmoxAdapter",
    "ProxmoxAdapter",
    "RealProxmoxAdapter",
    "Runner",
    "RunnerError",
    "RunRequest",
    "RunResult",
    "VmState",
    "build_runner",
]
