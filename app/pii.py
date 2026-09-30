from __future__ import annotations

import hashlib
import re

PII_PATTERNS: dict[str, str] = {
    "email": r"[\w\.-]+@[\w\.-]+\.\w+",
    "phone_vn": r"(?<!\d)(?:\+84|0)(?:[ .-]?\d){9}(?!\d)",
    "cccd": r"\b\d{12}\b",
    "credit_card": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
    # Bổ sung: hộ chiếu Việt Nam (1 chữ cái + 7 chữ số) và CMND 9 số cũ.
    "passport_vn": r"\b[A-Z]\d{7}\b",
    "cmnd_9": r"\b\d{9}\b",
}

# Ghi chú thiết kế: cố ý KHÔNG thêm pattern cho "địa chỉ" dạng văn xuôi
# (số nhà/đường/phường/quận) vì regex thô sẽ redact nhầm câu trả lời bình thường
# mà không thực sự bảo vệ dữ liệu. Muốn che địa chỉ cần NER/structured field,
# nằm ngoài phạm vi lab này.


def scrub_text(text: str) -> str:
    safe = text
    for name, pattern in PII_PATTERNS.items():
        safe = re.sub(pattern, f"[REDACTED_{name.upper()}]", safe)
    return safe


def summarize_text(text: str, max_len: int = 80) -> str:
    safe = scrub_text(text).strip().replace("\n", " ")
    return safe[:max_len] + ("..." if len(safe) > max_len else "")


def hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
