"""Audit log riêng cho các hành động control-plane / quyết định vận hành.

Khác với structured log nghiệp vụ (`data/logs.jsonl`), audit log ghi lại
*ai* làm *gì*, *lên đối tượng nào*, *kết quả ra sao* — phục vụ truy vết
trách nhiệm (accountability) và tuân thủ. Audit log:

- Là file JSONL riêng, độc lập với log nghiệp vụ (`AUDIT_LOG_PATH`).
- Có `schema_version` cố định và bộ field bắt buộc (xem `docs/AUDIT.md`).
- Luôn scrub PII trước khi ghi (tái dùng `app.pii.scrub_text`).
- Có chính sách lưu trữ (`retention_days`) và hàm `prune_audit_log` để dọn
  bản ghi hết hạn.

Chạy dọn log hết hạn:

    python -m app.audit --prune
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .pii import scrub_text

AUDIT_SCHEMA_VERSION = 1
DEFAULT_RETENTION_DAYS = 90

# Đọc tại import; tests có thể monkeypatch thuộc tính module này.
AUDIT_LOG_PATH = Path(os.getenv("AUDIT_LOG_PATH", "data/audit.jsonl"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _scrub_value(value: Any) -> Any:
    """Đệ quy scrub mọi chuỗi trong cấu trúc trước khi ghi audit."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub_value(v) for v in value]
    return value


def _retention_days() -> int:
    try:
        return int(os.getenv("AUDIT_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS)))
    except ValueError:
        return DEFAULT_RETENTION_DAYS


def write_audit(
    action: str,
    *,
    actor: str,
    target: str | None = None,
    outcome: str = "success",
    correlation_id: str | None = None,
    details: dict[str, Any] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Ghi một bản ghi audit và trả về record đã ghi.

    `details` được scrub PII đệ quy trước khi serialize, nên audit log không
    bao giờ chứa email/số điện thoại/CCCD thô kể cả khi caller truyền vào.
    """
    record: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "audit_id": f"aud-{uuid.uuid4().hex[:12]}",
        "ts": _iso(_now()),
        "action": scrub_text(action),
        "actor": scrub_text(actor),
        "target": scrub_text(target) if target is not None else None,
        "outcome": outcome,
        "correlation_id": correlation_id,
        "retention_days": _retention_days(),
        "details": _scrub_value(details or {}),
    }

    out_path = Path(path) if path is not None else AUDIT_LOG_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_audit(path: Path | None = None) -> list[dict[str, Any]]:
    in_path = Path(path) if path is not None else AUDIT_LOG_PATH
    if not in_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in in_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def prune_audit_log(
    *,
    now: datetime | None = None,
    path: Path | None = None,
) -> tuple[int, int]:
    """Xoá bản ghi cũ hơn `retention_days`. Trả về (giữ lại, đã xoá)."""
    now = now or _now()
    in_path = Path(path) if path is not None else AUDIT_LOG_PATH
    records = read_audit(in_path)
    kept: list[dict[str, Any]] = []
    removed = 0
    for record in records:
        days = record.get("retention_days", DEFAULT_RETENTION_DAYS)
        try:
            cutoff = now - timedelta(days=int(days))
        except (TypeError, ValueError):
            cutoff = now - timedelta(days=DEFAULT_RETENTION_DAYS)
        try:
            ts = datetime.fromisoformat(str(record.get("ts", "")).replace("Z", "+00:00"))
        except ValueError:
            ts = None
        if ts is not None and ts < cutoff:
            removed += 1
            continue
        kept.append(record)

    if removed:
        in_path.parent.mkdir(parents=True, exist_ok=True)
        with in_path.open("w", encoding="utf-8") as handle:
            for record in kept:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(kept), removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quản trị audit log Day 13")
    parser.add_argument("--prune", action="store_true", help="Xoá bản ghi hết hạn")
    parser.add_argument("--path", type=Path, default=None, help="Đường dẫn audit log")
    args = parser.parse_args(argv)

    if args.prune:
        kept, removed = prune_audit_log(path=args.path)
        print(f"Giữ lại {kept} bản ghi, đã xoá {removed} bản ghi hết hạn.")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
