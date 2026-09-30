from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

try:
    from langfuse import get_client, observe, propagate_attributes

    LANGFUSE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - chỉ dùng khi chưa cài requirements
    LANGFUSE_SDK_AVAILABLE = False

    def observe(*args: Any, **kwargs: Any):
        def decorator(func):
            return func

        return decorator

    class _DummyClient:
        def update_current_span(self, **kwargs: Any) -> None:
            return None

        def update_current_generation(self, **kwargs: Any) -> None:
            return None

    def get_client():
        return _DummyClient()

    @contextmanager
    def propagate_attributes(**kwargs: Any):
        yield


def get_langfuse_client():
    return get_client()


class _NullObservation:
    """Observation rỗng dùng khi client không hỗ trợ hoặc tracing bị tắt.

    Nhờ vậy code nghiệp vụ có thể luôn dùng `with start_observation(...)`
    mà không cần rẽ nhánh, và các test dùng fake client tối giản vẫn chạy được.
    """

    def update(self, **kwargs: Any) -> "_NullObservation":
        return self

    def __enter__(self) -> "_NullObservation":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False


def start_observation(client: Any, **kwargs: Any):
    """Trả về context manager cho một child observation (Langfuse v4).

    Nếu client không có `start_as_current_observation` (ví dụ khi SDK chưa cài
    hoặc test dùng fake client), trả về no-op để không làm hỏng request.
    """
    starter = getattr(client, "start_as_current_observation", None)
    if starter is None:
        return _NullObservation()
    try:
        return starter(**kwargs)
    except Exception:  # pragma: no cover - tracing là best-effort, không được làm fail request
        return _NullObservation()


def tracing_enabled() -> bool:
    return LANGFUSE_SDK_AVAILABLE and bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )
