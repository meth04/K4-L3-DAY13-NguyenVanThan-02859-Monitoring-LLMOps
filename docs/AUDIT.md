# Audit log — schema, retention và truy vấn minh họa

Tài liệu này mô tả **audit log riêng** của bài lab (bonus mục H). Audit log
tách biệt với structured log nghiệp vụ: `data/logs.jsonl` trả lời "hệ thống
đang làm gì", còn `data/audit.jsonl` trả lời "**ai** đã thay đổi **cái gì**,
**khi nào**, **kết quả ra sao**" cho các hành động control-plane.

## 1. Vì sao cần audit log riêng

- Log nghiệp vụ có thể bị xoay vòng/xóa để tiết kiệm dung lượng; audit log
  phải giữ lâu hơn (retention dài) và chỉ ghi các hành động có tính trách nhiệm.
- Audit log là bằng chứng tuân thủ: bật/tắt incident, promote/rollback prompt,
  thay đổi cấu hình — cần biết ai làm.
- Audit log **không** chứa nội dung người dùng; nó chỉ chứa metadata hành động.

## 2. Vị trí và cấu hình

| Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|
| `AUDIT_LOG_PATH` | `data/audit.jsonl` | Đường dẫn file audit (JSONL, mỗi dòng một record) |
| `AUDIT_RETENTION_DAYS` | `90` | Số ngày giữ bản ghi trước khi được prune |

Cài đặt trong `.env` (không commit `.env`). `data/audit.jsonl` nằm trong
`.gitignore` để không nộp log runtime.

## 3. Schema (schema_version = 1)

Mỗi dòng là một JSON object với các field:

| Field | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `schema_version` | int | ✔ | Phiên bản schema, hiện tại `1` |
| `audit_id` | string | ✔ | ID duy nhất, format `aud-<12 hex>` |
| `ts` | string | ✔ | Thời điểm ISO-8601 UTC, kết thúc bằng `Z` |
| `action` | string | ✔ | Hành động, ví dụ `incident.enable` |
| `actor` | string | ✔ | Chủ thể thực hiện (`operator`, `system`, …) |
| `target` | string \| null | ✔ | Đối tượng bị tác động, ví dụ tên incident |
| `outcome` | string | ✔ | `success` \| `failure` \| `denied` |
| `correlation_id` | string \| null | ✔ | Nối audit ↔ log ↔ trace cùng request |
| `retention_days` | int | ✔ | Số ngày giữ bản ghi này |
| `details` | object | ✔ | Chi tiết phụ, **đã scrub PII** |

> Mọi field chuỗi được chạy qua `app.pii.scrub_text` (kể cả `details` đệ quy)
> trước khi ghi, nên audit log không bao giờ chứa email/số điện thoại/CCCD thô.

## 4. Ghi audit

Audit được ghi tự động từ API:

- `POST /incidents/{name}/enable` → `action = "incident.enable"`
- `POST /incidents/{name}/disable` → `action = "incident.disable"`

hoặc gọi trực tiếp:

```python
from app.audit import write_audit

write_audit(
    "incident.enable",
    actor="operator",
    target="rag_slow",
    correlation_id="req-9bc618e6",
    details={"incidents": {"rag_slow": True}},
)
```

## 5. Retention và dọn dẹp

- Mỗi bản ghi mang `retention_days` (mặc định 90 ngày).
- Dọn bản ghi hết hạn:

```bash
python -m app.audit --prune
# Giữ lại 12 bản ghi, đã xoá 3 bản ghi hết hạn.
```

Hàm `app.audit.prune_audit_log()` trả về `(số giữ lại, số đã xoá)`.

## 6. Truy vấn minh họa

### 6.1. Xem 5 hành động gần nhất

```bash
python - <<'PY'
from app.audit import read_audit
for r in read_audit()[-5:]:
    print(r["ts"], r["actor"], r["action"], r["target"], r["outcome"])
PY
```

### 6.2. Lọc theo hành động và đối tượng (jq)

```bash
# Ai đã bật/tắt incident rag_slow?
jq -c 'select(.action=="incident.disable" and .target=="rag_slow")
       | {ts, actor, outcome, correlation_id}' data/audit.jsonl
```

### 6.3. Nối audit → log → trace theo correlation_id

```bash
# Lấy correlation_id từ audit rồi tìm log và trace cùng request
jq -r 'select(.action=="incident.enable") | .correlation_id' data/audit.jsonl \
  | head -1 \
  | xargs -I{} grep '"correlation_id": "{}"' data/logs.jsonl
```

### 6.4. Thống kê số hành động theo actor (Python)

```python
from collections import Counter
from app.audit import read_audit

counts = Counter(r["actor"] for r in read_audit())
print(counts)  # Counter({'operator': 12})
```

## 7. Kiểm thử

`tests/test_audit.py` kiểm tra: ghi/đọc record, scrub PII trong `details`,
và prune xoá đúng bản ghi hết hạn.

```bash
python -m pytest tests/test_audit.py -q
```
