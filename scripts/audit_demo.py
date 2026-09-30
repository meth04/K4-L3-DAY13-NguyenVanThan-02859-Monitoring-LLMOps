"""Sinh evidence audit log runtime: gọi API control-plane rồi đọc lại audit.

Chạy in-process qua ASGITransport (không cần mở cổng), ghi audit vào file
riêng để không lẫn với data/audit.jsonl thật:

    python scripts/audit_demo.py --out submission/evidence/16-audit-log.txt
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Demo audit log runtime")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    demo_audit = REPO_ROOT / "data" / "_audit_demo.jsonl"
    demo_logs = REPO_ROOT / "data" / "_audit_demo_logs.jsonl"
    for path in (demo_audit, demo_logs):
        if path.exists():
            path.unlink()
    os.environ["AUDIT_LOG_PATH"] = str(demo_audit)
    os.environ["LOG_PATH"] = str(demo_logs)
    os.environ["LANGFUSE_PUBLIC_KEY"] = ""
    os.environ["LANGFUSE_SECRET_KEY"] = ""

    import httpx  # noqa: E402

    from app.audit import prune_audit_log, read_audit  # noqa: E402
    from app.main import app  # noqa: E402

    async def call() -> list[int]:
        transport = httpx.ASGITransport(app=app)
        codes = []
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            codes.append((await client.post("/incidents/rag_slow/enable")).status_code)
            codes.append((await client.post("/incidents/rag_slow/disable")).status_code)
        return codes

    codes = asyncio.run(call())
    records = read_audit(demo_audit)
    kept, removed = prune_audit_log(path=demo_audit)

    lines: list[str] = []
    lines.append("=== Audit log runtime (control-plane actions) ===")
    lines.append(f"POST /incidents/rag_slow/enable  -> {codes[0]}")
    lines.append(f"POST /incidents/rag_slow/disable -> {codes[1]}")
    lines.append("")
    lines.append(f"So ban ghi audit: {len(records)}")
    lines.append("")
    lines.append("--- data/audit.jsonl (2 dong dau) ---")
    for rec in records:
        lines.append(json.dumps(rec, ensure_ascii=False))
    lines.append("")
    lines.append("--- Truy van minh hoa: loc hanh dong + doi tuong ---")
    for rec in records:
        lines.append(
            f"  {rec['ts']}  actor={rec['actor']}  action={rec['action']}  "
            f"target={rec['target']}  outcome={rec['outcome']}  "
            f"correlation_id={rec['correlation_id']}"
        )
    lines.append("")
    lines.append("--- Retention: prune (retention_days=90) ---")
    lines.append(f"Giu lai {kept} ban ghi, da xoa {removed} ban ghi het han.")
    lines.append("")
    lines.append("Nhan xet: audit log ghi doc lap voi log nghiep vu, co schema_version, "
                 "actor/action/target/outcome va correlation_id de noi tiep log/trace.")

    report = "\n".join(lines)
    print(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report + "\n", encoding="utf-8")
        print(f"\nDa ghi {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
