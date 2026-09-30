"""Dựng dashboard 6 panel từ data/logs.jsonl.

Không dùng thư viện ngoài: script đọc structured log, tính đúng các phép tổng hợp
trong config/dashboard.yaml rồi xuất một trang HTML tự chứa (inline SVG).

    python scripts/build_dashboard.py
    python scripts/build_dashboard.py --out submission/evidence/dashboard.html
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio  # noqa: E402
from app.metrics import percentile  # noqa: E402

LOG_PATH = REPO_ROOT / "data" / "logs.jsonl"
DEFAULT_OUT = REPO_ROOT / "submission" / "evidence" / "dashboard.html"
WINDOW_MINUTES = 60
REFRESH_SECONDS = 30


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"Không tìm thấy {path}. Hãy chạy API và load test trước.")
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not records:
        raise SystemExit(f"{path} không có bản ghi JSON hợp lệ.")
    return records


def parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def bucket_minute(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%H:%M")


def esc(value: object) -> str:
    return html.escape(str(value))


def bar_chart(pairs: list[tuple[str, float]], unit: str, color: str, height: int = 150) -> str:
    if not pairs:
        return '<p class="empty">Không có dữ liệu trong cửa sổ.</p>'
    width = max(320, 46 * len(pairs))
    peak = max(v for _, v in pairs) or 1.0
    bars = []
    for i, (label, value) in enumerate(pairs):
        h = max(2.0, (value / peak) * (height - 34))
        x = 30 + i * 46
        bars.append(
            f'<rect x="{x}" y="{height - 24 - h:.1f}" width="30" height="{h:.1f}" rx="3" fill="{color}"/>'
            f'<text x="{x + 15}" y="{height - 28 - h:.1f}" class="val" text-anchor="middle">{value:g}</text>'
            f'<text x="{x + 15}" y="{height - 8}" class="ax" text-anchor="middle">{esc(label)}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">'
        f'<line x1="0" y1="{height - 24}" x2="{width}" y2="{height - 24}" stroke="#3a4250"/>'
        + "".join(bars)
        + f'<text x="0" y="12" class="unit">{esc(unit)}</text></svg>'
    )


def line_chart(points: list[tuple[str, float]], unit: str, color: str, height: int = 150) -> str:
    if not points:
        return '<p class="empty">Không có dữ liệu trong cửa sổ.</p>'
    width = max(320, 60 * len(points))
    peak = max(v for _, v in points) or 1.0
    step = (width - 60) / max(1, len(points) - 1)
    coords = [
        (30 + i * step, height - 30 - (v / peak) * (height - 55)) for i, (_, v) in enumerate(points)
    ]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(coords))
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>'
        f'<text x="{x:.1f}" y="{y - 8:.1f}" class="val" text-anchor="middle">{v:g}</text>'
        for (x, y), (_, v) in zip(coords, points)
    )
    labels = "".join(
        f'<text x="{x:.1f}" y="{height - 8}" class="ax" text-anchor="middle">{esc(label)}</text>'
        for (x, _), (label, _) in zip(coords, points)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">'
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"/>'
        + dots
        + labels
        + f'<text x="0" y="12" class="unit">{esc(unit)}</text></svg>'
    )


def stat_tile(label: str, value: str, target: str, ok: bool) -> str:
    cls = "ok" if ok else "bad"
    return (
        f'<div class="tile {cls}"><span class="tile-label">{esc(label)}</span>'
        f'<span class="tile-value">{esc(value)}</span>'
        f'<span class="tile-target">ngưỡng: {esc(target)}</span></div>'
    )


def build_html(records: list[dict]) -> str:
    api_records = [r for r in records if r.get("service") == "api"]
    received = [r for r in api_records if r.get("event") == "request_received"]
    sent = [r for r in api_records if r.get("event") == "response_sent"]
    failed = [r for r in api_records if r.get("event") == "request_failed"]

    timestamps = [t for t in (parse_ts(r.get("ts", "")) for r in api_records) if t]
    newest = max(timestamps) if timestamps else datetime.now(timezone.utc)
    window_start = newest - timedelta(minutes=WINDOW_MINUTES)

    def in_window(record: dict) -> bool:
        ts = parse_ts(record.get("ts", ""))
        return ts is not None and ts >= window_start

    sent_w = [r for r in sent if in_window(r)]
    received_w = [r for r in received if in_window(r)]

    # --- Panel latency ---
    latencies = [int(r.get("latency_ms") or 0) for r in sent_w]
    ttfts = [int(r.get("ttft_ms") or 0) for r in sent_w]
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    ttft_p95 = percentile(ttfts, 95)

    # --- Panel traffic ---
    traffic: dict[str, int] = defaultdict(int)
    for r in received_w:
        ts = parse_ts(r.get("ts", ""))
        if ts:
            traffic[bucket_minute(ts)] += 1
    traffic_pairs = sorted(traffic.items())

    # --- Panel errors ---
    error_rate = (len(failed) / len(received) * 100) if received else 0.0
    error_breakdown = Counter(r.get("error_type") or "unknown" for r in failed)
    tool_records = [r for r in sent if r.get("tool_success") is not None]
    tool_ok = [r for r in tool_records if r.get("tool_success") is True]
    retrieval_success = (len(tool_ok) / len(tool_records) * 100) if tool_records else 100.0

    # --- Panel cost ---
    cost_by_min: dict[str, float] = defaultdict(float)
    for r in sent_w:
        ts = parse_ts(r.get("ts", ""))
        if ts:
            cost_by_min[bucket_minute(ts)] += float(r.get("cost_usd") or 0.0)
    cost_pairs = [(k, round(v, 6)) for k, v in sorted(cost_by_min.items())]
    total_cost = sum(float(r.get("cost_usd") or 0.0) for r in sent_w)

    # --- Panel tokens ---
    tokens_in = sum(int(r.get("tokens_in") or 0) for r in sent_w)
    tokens_out = sum(int(r.get("tokens_out") or 0) for r in sent_w)

    # --- Panel quality ---
    quality = [float(r.get("quality_score") or 0.0) for r in sent_w if r.get("quality_score") is not None]
    quality_avg = sum(quality) / len(quality) if quality else 0.0

    span = f"{window_start.strftime('%Y-%m-%d %H:%M')} → {newest.strftime('%Y-%m-%d %H:%M')} UTC"

    panels = [
        (
            "latency",
            "Latency percentiles and TTFT",
            "Request có chậm không? P50/P95/P99 và TTFT đang ở mức nào?",
            stat_tile("P50", f"{p50:.0f} ms", "—", True)
            + stat_tile("P95", f"{p95:.0f} ms", "≤ 3000 ms", p95 <= 3000)
            + stat_tile("P99", f"{p99:.0f} ms", "—", True)
            + stat_tile("TTFT P95", f"{ttft_p95:.0f} ms", "—", True)
            + bar_chart(
                [("P50", p50), ("P95", p95), ("P99", p99), ("TTFT P95", ttft_p95)],
                "ms",
                "#5b9dff",
            ),
        ),
        (
            "traffic",
            "Request traffic",
            "Hệ thống đang nhận bao nhiêu request theo thời gian?",
            stat_tile("Tổng request", f"{len(received)}", "—", True)
            + stat_tile(
                "Rate trung bình",
                f"{(len(received_w) / WINDOW_MINUTES):.2f} req/phút",
                "≥ 1 req/phút",
                (len(received_w) / WINDOW_MINUTES) >= 1,
            )
            + bar_chart(traffic_pairs, "requests / phút", "#39c2a5"),
        ),
        (
            "errors",
            "Error rate and retrieval success",
            "Error rate có tăng không, retrieval có đang fail không?",
            stat_tile("Error rate", f"{error_rate:.2f} %", "≤ 2 %", error_rate <= 2)
            + stat_tile(
                "Retrieval success",
                f"{retrieval_success:.1f} %",
                "≥ 90 %",
                retrieval_success >= 90,
            )
            + bar_chart(
                [(k, float(v)) for k, v in sorted(error_breakdown.items())] or [("(không có lỗi)", 0.0)],
                "số lỗi theo error_type",
                "#ff6b6b",
            ),
        ),
        (
            "cost",
            "Cost over time",
            "Chi phí có tăng bất thường không?",
            stat_tile("Tổng cost", f"${total_cost:.4f}", "≤ $2.50", total_cost <= 2.5)
            + stat_tile(
                "Cost / request",
                f"${(total_cost / len(sent_w) if sent_w else 0):.6f}",
                "—",
                True,
            )
            + line_chart(cost_pairs, "usd / phút", "#ffb454"),
        ),
        (
            "tokens",
            "Input and output tokens",
            "Input/output token có dài bất thường không?",
            stat_tile("Tokens in", f"{tokens_in:,}", "—", True)
            + stat_tile("Tokens out", f"{tokens_out:,}", "—", True)
            + stat_tile(
                "Tổng tokens",
                f"{tokens_in + tokens_out:,}",
                "≤ 50,000",
                (tokens_in + tokens_out) <= 50000,
            )
            + bar_chart(
                [("input", float(tokens_in)), ("output", float(tokens_out))],
                "tokens",
                "#b18cff",
            ),
        ),
        (
            "quality",
            "Quality proxy",
            "Quality proxy có giảm dưới mức chấp nhận được không?",
            stat_tile("Quality trung bình", f"{quality_avg:.2f}", "≥ 0.75", quality_avg >= 0.75)
            + stat_tile("Số mẫu", f"{len(quality)}", "—", True)
            + bar_chart([("mean", quality_avg)], "score 0–1", "#4dd4ac"),
        ),
    ]

    cards = []
    for panel_id, title, question, body in panels:
        cards.append(
            f'<section class="panel" id="{panel_id}">'
            f'<header><h2>{esc(title)}</h2><span class="qid">panel: {esc(panel_id)}</span></header>'
            f'<p class="question">{esc(question)}</p>{body}</section>'
        )

    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Day 13 Dashboard — 6 panel</title>
<style>
  :root {{
    --bg: #0f131a; --card: #171d27; --line: #2a3341; --fg: #e7edf5;
    --muted: #97a3b4; --ok: #4dd4ac; --bad: #ff6b6b;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 24px; background: var(--bg); color: var(--fg);
         font: 14px/1.5 "Segoe UI", system-ui, sans-serif; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .meta {{ color: var(--muted); margin: 0 0 20px; font-size: 13px; }}
  .meta code {{ color: var(--fg); }}
  .grid {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); }}
  .panel {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px; }}
  .panel header {{ display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }}
  .panel h2 {{ font-size: 15px; margin: 0; }}
  .qid {{ color: var(--muted); font-size: 11px; white-space: nowrap; }}
  .question {{ color: var(--muted); font-size: 12px; margin: 4px 0 12px; }}
  .tile {{ display: inline-flex; flex-direction: column; gap: 2px; margin: 0 14px 12px 0; }}
  .tile-label {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }}
  .tile-value {{ font-size: 19px; font-weight: 600; }}
  .tile-target {{ font-size: 11px; color: var(--muted); }}
  .tile.ok .tile-value {{ color: var(--ok); }}
  .tile.bad .tile-value {{ color: var(--bad); }}
  .chart {{ width: 100%; height: auto; display: block; }}
  .val {{ fill: var(--fg); font-size: 11px; }}
  .ax {{ fill: var(--muted); font-size: 11px; }}
  .unit {{ fill: var(--muted); font-size: 11px; }}
  .empty {{ color: var(--muted); font-style: italic; }}
</style>
</head>
<body>
  <h1>K4-L3B Day 13 — Monitoring &amp; LLMOps dashboard</h1>
  <p class="meta">
    Nguồn dữ liệu: <code>data/logs.jsonl</code> ·
    Time range: <code>{WINDOW_MINUTES} phút</code> ({esc(span)}) ·
    Refresh: <code>{REFRESH_SECONDS}s</code> ·
    Tổng bản ghi: <code>{len(records)}</code>
  </p>
  <div class="grid">
    {''.join(cards)}
  </div>
</body>
</html>
"""


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Dựng dashboard 6 panel từ structured log")
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    records = load_records(args.log)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_html(records), encoding="utf-8")
    print(f"Đã ghi dashboard: {args.out} ({len(records)} bản ghi)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
