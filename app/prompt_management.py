from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


DEFAULT_PROMPT_TEMPLATE = "Feature={{feature}}\nDocs={{docs}}\nQuestion={{message}}"

# Prompt gọn dùng cho tối ưu chi phí (bật bằng PROMPT_COMPACT=1). Bỏ dòng
# "Feature=" vì feature đã có trong metadata/log, và giới hạn còn 1 doc +
# cắt ngắn câu hỏi để giảm token đầu vào trên cùng workload.
COMPACT_PROMPT_TEMPLATE = "Docs={{docs}}\nQ={{message}}"
COMPACT_MAX_DOCS = 1
COMPACT_MAX_MESSAGE_CHARS = 120


@dataclass(frozen=True)
class ResolvedPrompt:
    text: str
    name: str
    label: str
    version: str
    source: str
    managed_prompt: Any | None = None
    fetch_error: str | None = None


def _compile_local_prompt(*, feature: str, docs: list[str], message: str) -> str:
    if os.getenv("PROMPT_COMPACT") == "1":
        compact_docs = docs[:COMPACT_MAX_DOCS]
        compact_message = message[:COMPACT_MAX_MESSAGE_CHARS]
        return (
            COMPACT_PROMPT_TEMPLATE.replace("{{docs}}", "\n".join(compact_docs))
            .replace("{{message}}", compact_message)
        )
    return (
        DEFAULT_PROMPT_TEMPLATE.replace("{{feature}}", feature)
        .replace("{{docs}}", "\n".join(docs))
        .replace("{{message}}", message)
    )


def resolve_prompt(
    client: Any,
    *,
    feature: str,
    docs: list[str],
    message: str,
    enabled: bool,
) -> ResolvedPrompt:
    name = os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    label = os.getenv("LANGFUSE_PROMPT_LABEL", "production")
    text = _compile_local_prompt(feature=feature, docs=docs, message=message)
    if enabled:
        try:
            managed_prompt = client.get_prompt(
                name,
                label=label,
                type="text",
                fallback=DEFAULT_PROMPT_TEMPLATE,
                cache_ttl_seconds=60,
                fetch_timeout_seconds=2,
                max_retries=0,
            )
            if getattr(managed_prompt, "is_fallback", False):
                return ResolvedPrompt(
                    text=text,
                    name=name,
                    label=label,
                    version="local-v1",
                    source="local-fallback",
                    fetch_error="LangfuseFallback",
                )
            return ResolvedPrompt(
                text=managed_prompt.compile(
                    feature=feature,
                    docs="\n".join(docs),
                    message=message,
                ),
                name=name,
                label=label,
                version=str(managed_prompt.version),
                source="langfuse",
                managed_prompt=managed_prompt,
            )
        except Exception as exc:  # Langfuse là dependency ngoài; app phải có fallback local
            return ResolvedPrompt(
                text=text,
                name=name,
                label=label,
                version="local-v1",
                source="local-fallback",
                fetch_error=type(exc).__name__,
            )

    return ResolvedPrompt(
        text=text,
        name=name,
        label=label,
        version="local-v1",
        source="local",
    )
