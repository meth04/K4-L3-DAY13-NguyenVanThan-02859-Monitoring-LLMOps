from __future__ import annotations

from pathlib import Path

from scripts import scan_secrets


def test_scan_detects_langfuse_key(tmp_path: Path) -> None:
    target = tmp_path / "leak.txt"
    target.write_text("LANGFUSE_PUBLIC_KEY=pk-lf-12345678-abcd\n", encoding="utf-8")
    findings = scan_secrets.scan_file(target)
    assert any("langfuse_public_key" in f for f in findings)


def test_scan_detects_raw_email(tmp_path: Path) -> None:
    target = tmp_path / "leak.txt"
    target.write_text("contact me at student@example.com please\n", encoding="utf-8")
    findings = scan_secrets.scan_file(target)
    assert any("PII:email" in f for f in findings)


def test_scan_allows_placeholder_assignment(tmp_path: Path) -> None:
    target = tmp_path / "env.example"
    target.write_text("LANGFUSE_SECRET_KEY=your-secret-here\n", encoding="utf-8")
    findings = scan_secrets.scan_file(target)
    assert not any("generic_secret_assign" in f for f in findings)


def test_scan_skips_binary_suffix(tmp_path: Path) -> None:
    target = tmp_path / "image.png"
    target.write_bytes(b"pk-lf-12345678-abcd")
    assert scan_secrets.scan_file(target) == []
