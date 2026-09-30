from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import audit


def test_write_audit_creates_valid_record(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    record = audit.write_audit(
        "incident.enable",
        actor="operator",
        target="rag_slow",
        correlation_id="req-9bc618e6",
        details={"incidents": {"rag_slow": True}},
        path=path,
    )

    assert record["schema_version"] == 1
    assert record["audit_id"].startswith("aud-")
    assert record["action"] == "incident.enable"
    assert record["actor"] == "operator"
    assert record["target"] == "rag_slow"
    assert record["outcome"] == "success"
    assert record["correlation_id"] == "req-9bc618e6"
    assert record["retention_days"] == audit.DEFAULT_RETENTION_DAYS
    assert record["ts"].endswith("Z")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["audit_id"] == record["audit_id"]


def test_write_audit_scrubs_pii_in_details(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    audit.write_audit(
        "user.contact",
        actor="operator",
        target="ticket-1",
        details={"email": "student@example.com", "note": "call 0987654321"},
        path=path,
    )

    raw = path.read_text(encoding="utf-8")
    assert "student@example.com" not in raw
    assert "0987654321" not in raw
    assert "[REDACTED_EMAIL]" in raw
    assert "[REDACTED_PHONE_VN]" in raw


def test_prune_audit_log_removes_expired_records(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    old_ts = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat().replace(
        "+00:00", "Z"
    )
    fresh = audit.write_audit(
        "incident.disable", actor="operator", target="rag_slow", path=path
    )
    # Ghi đè một bản ghi cũ hơn retention để kiểm tra prune.
    path.write_text(
        json.dumps({**fresh, "ts": old_ts, "audit_id": "aud-old"}) + "\n"
        + json.dumps(fresh) + "\n",
        encoding="utf-8",
    )

    kept, removed = audit.prune_audit_log(path=path)

    assert kept == 1
    assert removed == 1
    remaining = audit.read_audit(path)
    assert [r["audit_id"] for r in remaining] == [fresh["audit_id"]]


def test_read_audit_missing_file_returns_empty(tmp_path: Path) -> None:
    assert audit.read_audit(tmp_path / "does-not-exist.jsonl") == []
