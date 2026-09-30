"""Quét secret và PII thô trong repository trước khi commit/push.

Chỉ dùng thư viện chuẩn để không làm nặng môi trường. Script quét các file
được Git theo dõi (hoặc một thư mục bất kỳ khi truyền `--path`) và fail với
exit code khác 0 nếu phát hiện:

- Khóa Langfuse thật: ``pk-lf-...`` / ``sk-lf-...``.
- Khóa/token phổ biến: AWS access key, Slack token, private key PEM.
- Assignment secret kiểu ``API_KEY=...``, ``SECRET=...``, ``TOKEN=...`` với
  giá trị không rỗng.
- PII thô: email, số điện thoại Việt Nam, CCCD 12 số, số thẻ tín dụng.
- File bị cấm commit: ``.env`` và ``config/challenge.json``.

Dùng trong CI (xem ``.github/workflows/ci.yml``) và có thể gắn pre-commit:

    python scripts/scan_secrets.py            # quét file Git theo dõi
    python scripts/scan_secrets.py --all      # quét cả file chưa track
    python scripts/scan_secrets.py --path .   # quét mọi file trong cây thư mục
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# (tên, regex) — thứ tự không quan trọng.
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "langfuse_public_key": re.compile(r"pk-lf-[0-9a-fA-F-]{8,}"),
    "langfuse_secret_key": re.compile(r"sk-lf-[0-9a-fA-F-]{8,}"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "generic_secret_assign": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[=:]\s*[\"']?([A-Za-z0-9_\-]{12,})"
    ),
}

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[\w.-]+@[\w.-]+\.\w+"),
    "phone_vn": re.compile(r"(?<!\d)(?:\+84|0)(?:[ .-]?\d){9}(?!\d)"),
    "cccd": re.compile(r"\b\d{12}\b"),
    "credit_card": re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
}

# File/dir bỏ qua khi quét.
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".woff", ".woff2"}
# .env cục bộ chứa key thật nhưng đã bị .gitignore; không đọc nội dung để tránh
# in key ra log. Nếu .env bị track, FORBIDDEN_TRACKED sẽ bắt và fail.
SKIP_FILES = {".env"}
# Chỉ .env là file tuyệt đối không được track. config/challenge.json do Lab Coach
# phát hành trong commit upstream nên không tính là vi phạm của học viên.
FORBIDDEN_TRACKED = {".env"}

# File fixture/evidence do lab cung cấp hoặc chứng minh redaction: có chứa PII giả
# theo chủ đích, nên bỏ qua kiểm tra PII (vẫn kiểm tra secret).
PII_ALLOWLIST = {
    "data/sample_queries.jsonl",
    "data/expected_answers.jsonl",
    "tests/test_pii.py",
    "tests/test_validate_logs.py",
    "tests/test_audit.py",
    "tests/test_scan_secrets.py",
    "submission/evidence/04-structured-log.txt",
    "submission/evidence/05-pii-redaction.txt",
    "submission/evidence/12-incident-metric.txt",
    "submission/evidence/13-incident-log.txt",
}

# File test cố ý chứa secret giả để kiểm tra chính bộ quét.
SECRET_ALLOWLIST = {"tests/test_scan_secrets.py"}

# Cho phép các placeholder rõ ràng (ví dụ trong .env.example, docs).
PLACEHOLDER_HINTS = ("your-", "xxx", "example", "<", ">", "changeme", "placeholder")


def _looks_like_placeholder(value: str) -> bool:
    low = value.lower()
    return any(hint in low for hint in PLACEHOLDER_HINTS)


def git_tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [REPO_ROOT / line.strip() for line in out.splitlines() if line.strip()]


def walk_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def scan_file(path: Path) -> list[str]:
    findings: list[str] = []
    if path.name in SKIP_FILES or path.suffix.lower() in SKIP_SUFFIXES:
        return findings
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return findings

    rel = path.relative_to(REPO_ROOT) if REPO_ROOT in path.parents else path
    rel_key = str(rel).replace("\\", "/")
    check_pii = rel_key not in PII_ALLOWLIST
    check_secret = rel_key not in SECRET_ALLOWLIST
    for line_no, line in enumerate(text.splitlines(), start=1):
        if check_secret:
            for name, pattern in SECRET_PATTERNS.items():
                match = pattern.search(line)
                if not match:
                    continue
                captured = match.group(1) if match.groups() else match.group(0)
                if name == "generic_secret_assign" and _looks_like_placeholder(captured):
                    continue
                findings.append(f"{rel}:{line_no}: [SECRET:{name}] {match.group(0)[:60]}")
        if not check_pii:
            continue
        for name, pattern in PII_PATTERNS.items():
            match = pattern.search(line)
            if match:
                findings.append(f"{rel}:{line_no}: [PII:{name}] {match.group(0)[:40]}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quét secret/PII trong repo Day 13")
    parser.add_argument("--all", action="store_true", help="Quét cả file chưa track")
    parser.add_argument("--path", type=Path, default=None, help="Quét cây thư mục")
    args = parser.parse_args(argv)

    if args.path is not None:
        files = walk_files(args.path)
    elif args.all:
        files = walk_files(REPO_ROOT)
    else:
        files = git_tracked_files()

    if not files:
        print("Không có file nào để quét.")
        return 0

    findings: list[str] = []
    forbidden: list[str] = []
    # Chỉ kiểm tra file bị cấm khi quét đúng tập file Git theo dõi.
    if args.path is None and not args.all:
        tracked_names = {str(f.relative_to(REPO_ROOT)).replace("\\", "/") for f in files}
        for name in sorted(FORBIDDEN_TRACKED & tracked_names):
            forbidden.append(f"[FORBIDDEN] File bị cấm commit: {name}")

    for path in files:
        findings.extend(scan_file(path))

    print(f"Đã quét {len(files)} file.")
    for line in forbidden:
        print("  " + line)
    for line in findings:
        print("  " + line)

    total = len(forbidden) + len(findings)
    if total:
        print(f"\nPHÁT HIỆN {total} vấn đề. Hãy xử lý trước khi commit/push.")
        return 1
    print("\nSẠCH: không phát hiện secret/PII thô hoặc file bị cấm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
