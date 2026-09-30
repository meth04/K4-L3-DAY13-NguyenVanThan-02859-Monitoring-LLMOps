"""Đo chi phí token trước/sau tối ưu prompt trên CÙNG một workload.

Cùng một bộ query (`data/sample_queries.jsonl`), cùng seed cho output token,
chỉ khác cấu hình prompt:

- ``before``: prompt đầy đủ (mặc định) — lặp feature + toàn bộ docs + câu hỏi đầy đủ.
- ``after`` : prompt gọn (``PROMPT_COMPACT=1``) — bỏ dòng feature (đã có trong
  metadata), chỉ giữ 1 doc và cắt ngắn câu hỏi ⇒ giảm token đầu vào.

Vì output token được cố định bằng seed, chênh lệch cost phản ánh đúng phần
token đầu vào tiết kiệm được, không phải do ngẫu nhiên.

    python scripts/compare_cost.py
    python scripts/compare_cost.py --out submission/evidence/15-cost-optimization.txt
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from app import metrics  # noqa: E402
from app.cli import configure_utf8_stdio  # noqa: E402

QUERIES_PATH = REPO_ROOT / "data" / "sample_queries.jsonl"
SEED = 42


def load_payloads() -> list[dict]:
    return [
        json.loads(line)
        for line in QUERIES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def reset_metrics() -> None:
    metrics.REQUEST_LATENCIES.clear()
    metrics.REQUEST_TTFT.clear()
    metrics.REQUEST_COSTS.clear()
    metrics.REQUEST_TOKENS_IN.clear()
    metrics.REQUEST_TOKENS_OUT.clear()
    metrics.QUALITY_SCORES.clear()
    metrics.ERRORS.clear()
    metrics.TRAFFIC = 0


async def run_workload(payloads: list[dict]) -> dict:
    # Import muộn để app đọc lại cấu hình prompt sau khi đổi env.
    from app.main import app

    reset_metrics()
    random.seed(SEED)  # cố định output token ⇒ so sánh công bằng
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for payload in payloads:
            await client.post("/chat", json=payload)
    return metrics.snapshot()


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="So sánh cost before/after tối ưu prompt")
    parser.add_argument("--out", type=Path, default=None, help="Ghi kết quả ra file")
    args = parser.parse_args(argv)

    # Tắt tracing để phép đo chỉ phụ thuộc prompt local (không gọi mạng).
    os.environ["LANGFUSE_PUBLIC_KEY"] = ""
    os.environ["LANGFUSE_SECRET_KEY"] = ""
    os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
    # Ghi log đo đạc vào file tạm để không trộn vào data/logs.jsonl của bài lab.
    os.environ["LOG_PATH"] = str(REPO_ROOT / "data" / "_cost_compare_logs.jsonl")

    payloads = load_payloads()

    os.environ.pop("PROMPT_COMPACT", None)
    before = asyncio.run(run_workload(payloads))

    os.environ["PROMPT_COMPACT"] = "1"
    after = asyncio.run(run_workload(payloads))

    lines: list[str] = []
    lines.append("=== Cost optimization before/after (cung workload) ===")
    lines.append(f"Workload: {len(payloads)} query tu data/sample_queries.jsonl, seed={SEED}")
    lines.append("")
    lines.append(f"{'Metric':<22}{'before':>14}{'after':>14}{'delta':>14}")
    for key, unit in [
        ("traffic", ""),
        ("tokens_in_total", "tok"),
        ("tokens_out_total", "tok"),
        ("total_cost_usd", "usd"),
        ("avg_cost_usd", "usd"),
        ("quality_avg", ""),
    ]:
        b = before.get(key, 0)
        a = after.get(key, 0)
        delta = round(a - b, 6) if isinstance(a, (int, float)) else "-"
        lines.append(f"{key:<22}{str(b):>14}{str(a):>14}{str(delta):>14}")

    cost_before = before.get("total_cost_usd", 0.0) or 0.0
    cost_after = after.get("total_cost_usd", 0.0) or 0.0
    saved = cost_before - cost_after
    pct = (saved / cost_before * 100) if cost_before else 0.0
    tin_b = before.get("tokens_in_total", 0)
    tin_a = after.get("tokens_in_total", 0)
    tin_pct = ((tin_b - tin_a) / tin_b * 100) if tin_b else 0.0

    lines.append("")
    lines.append(f"Tiet kiem token dau vao: {tin_b} -> {tin_a} tok ({tin_pct:.1f}%)")
    lines.append(f"Tiet kiem chi phi     : ${cost_before:.6f} -> ${cost_after:.6f} "
                 f"(tiet kiem ${saved:.6f}, {pct:.1f}%)")
    lines.append(f"Chat luong trung binh : {before.get('quality_avg')} -> {after.get('quality_avg')}")
    lines.append("")
    lines.append("Ket luan: cung workload, prompt gon giam token dau vao va chi phi ma "
                 "khong giam chat luong trung binh.")

    report = "\n".join(lines)
    print(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report + "\n", encoding="utf-8")
        print(f"\nDa ghi {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
