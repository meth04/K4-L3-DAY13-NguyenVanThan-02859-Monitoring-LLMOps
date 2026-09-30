# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Nguyễn Văn Thân
- **MSSV:** 2A202602859
- **Lớp:** K4-L3B
- **Repository URL:** https://github.com/meth04/K4-L3-DAY13-NguyenVanThan-02859-Monitoring-LLMOps
- **Commit SHA cuối:** `c48910f` (commit nội dung đầy đủ — gồm code, evidence 01–14 và báo cáo này; xem `git log -1 --format=%H`)
- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1` (cohort K4, incident `rag_slow`, seed `1312`, affected_feature `monitoring`, SLO `latency_threshold_ms = 2000`)
- **Tên project Langfuse cá nhân:** `day13-k4-l3b-2A202602859`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.txt` |
| Log validator | `evidence/02-log-validator.txt` |
| Dashboard validator | `evidence/03-dashboard-validator.txt` |
| Structured log | `evidence/04-structured-log.txt` |
| PII redaction | `evidence/05-pii-redaction.txt` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10-prompt-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.txt` |
| Incident log | `evidence/13-incident-log.txt` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 | **100/100** | Đủ 4 hạng mục: JSON schema, correlation ID, enrichment, PII |
| `validate_dashboard.py` | 6/6 | **6/6** | Giữ nguyên 6 panel đúng contract |
| `pytest` | 22 passed | **22 passed** | Không hồi quy sau khi thêm tracing/PII |
| Số traces hợp lệ | 0 | **25** | Trace tạo từ project cá nhân `day13-k4-l3b-2A202602859`; có root `day13-agent-request` + span `lab-agent-run`/`retrieval`/`generation` |
| Số PII leak | 3 (email trong `message_preview`) | **0** | Scrubber chạy trước khi ghi file |
| Latency P95 / TTFT P95 | 151 ms / 50 ms | 151 ms / 50 ms (bình thường) | Ở scenario `rag_slow` P95 vọt lên 2653 ms, TTFT không đổi |
| Retrieval success rate | 100% | 100% (khi tắt scenario) | Đo từ `tool_success` trên `response_sent` |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` (`app/middleware.py`) đọc header `x-request-id`; nếu có thì dùng, nếu không thì sinh `req-<8 hex>` bằng `uuid4`. ID được `bind_contextvars(correlation_id=...)` nên structlog tự gắn vào **mọi** event log trong cùng request, đồng thời ghi vào `request.state.correlation_id` để truyền xuống agent và trả lại trong header `x-request-id` của response. Đầu mỗi request gọi `clear_contextvars()` để không rò context giữa các request.
- **Các metadata được ghi vào structured log:** `service`, `env`, `feature`, `session_id`, `user_id_hash` (băm, không lưu ID thô), `model`, `correlation_id`, `ts` (ISO-8601 UTC). Event `response_sent` thêm `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** `app/pii.py` định nghĩa `PII_PATTERNS` (email, điện thoại VN, CCCD 12 số, số thẻ tín dụng, hộ chiếu VN, CMND 9 số) và hàm `scrub_text` thay bằng nhãn `[REDACTED_*]`. Trong `app/logging_config.py`, processor `scrub_event` được đăng ký **trước** `JsonlFileProcessor`/`JSONRenderer`, nên mọi giá trị chuỗi (kể cả trong `payload`) đều được scrub trước khi serialize ra `data/logs.jsonl`. `summarize_text()` cắt ngắn preview và scrub trước khi đưa vào log/trace.
- **Cách kiểm chứng kết quả:** `evidence/04-structured-log.txt` cho thấy một request có đủ `correlation_id` + enrichment; `evidence/05-pii-redaction.txt` cho thấy 5 mẫu PII giả (email/điện thoại/CCCD/CMND/thẻ/hộ chiếu) đều bị che, và `grep` trên `data/logs.jsonl` cho 0 email thô. `validate_logs.py` báo `Potential PII leaks detected: 0`.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** `app/tracing.py` dùng `get_client()` của Langfuse SDK v4, cấu hình qua `.env` với `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` của project `day13-k4-l3b-2A202602859`. Mỗi trace mang `environment`, `tags=[lab, feature, model]` và `metadata.correlation_id`, nên có thể đối chiếu ngược với log. Tổng cộng **25 trace** được tạo trong project cá nhân — xem `evidence/06-trace-list.png`, `07-trace-waterfall.png`, `08-trace-metadata.png`.
- **Cấu trúc root/retrieval/generation observations:** `LabAgent.run` được bọc `@observe(name="lab-agent-run", as_type="agent")`; bên trong lần lượt mở hai child observation: `retrieval` (`as_type="retriever"`, output `doc_count`, `retrieval_success`) và `generation` (`as_type="generation"`, `model`, `usage_details` token, `cost_details`, metadata prompt + `ttft_ms`). `propagate_attributes(trace_name="day13-agent-request", ...)` đặt tên trace và user/session.
- **Cách nối trace với log:** `correlation_id` được đưa vào `metadata` của cả trace và span, đồng thời xuất hiện trên mọi dòng log; đây là khóa để chứng minh log và trace thuộc cùng một request.
- **Prompt name:** `day13-chat` (`LANGFUSE_PROMPT_NAME`).
- **Version/label baseline:** label `baseline` — prompt trả lời ngắn, không bắt buộc dùng context.
- **Version/label candidate:** label `candidate` — prompt yêu cầu dùng retrieved context và trả lời súc tích.
- **Trace ID của mỗi version** (đối chiếu qua `correlation_id` trong metadata và log):
  - label `baseline` (v1): `85ee0ed0039ecc810939560dc2300571` — `req-ea1a956f`
  - label `candidate` (v2): `e066564d673a4dbaefac5d5fb3d622d1` — `req-29bc5f2b`; `a63d9995965a45e54bb03897603cd4ec` — `req-2d0e8eaa`
  - `production` **sau promote** (v2): `181a98de0045f83f41a816c0a9edb16b` — `req-c95d884a`
  - `production` **sau rollback** (v1): `a8ad2fc9af0a24d861ec6f36d019c5c6` — `req-0edcf767`; `06992849c212de929b8736b71a7d111d` — `req-ca3f16f8`; `c743a2c7c5d78baa933e91fad2dd4136` — `req-d9ac73ed`
  - (Khi Langfuse chưa kịp propagate label, một số request rơi vào fallback local `vlocal-v1`, ví dụ `0f20cae065a4a6910feee8bbdebfcd16` — `req-2adc1306`.)
- **Ảnh evidence prompt:** `evidence/09-prompt-versions.png` (danh sách version `day13-chat`), `evidence/10-prompt-rollback.png` (trạng thái label sau rollback: `production`→v1, `candidate`→v2, `baseline`→v1).
- **Cách promote và rollback `production`:** `app/prompt_management.py` resolve prompt theo `LANGFUSE_PROMPT_LABEL` (mặc định `production`). Promote = gán label `production` cho version candidate trong Langfuse; rollback = gán lại `production` cho version baseline. Khi Langfuse không khả dụng, app dùng prompt local fallback nên request không gãy.

> **Trạng thái:** code tracing và prompt resolution đã hoàn thiện, pass 22 test, và **25 trace** đã được tạo trong project Langfuse cá nhân `day13-k4-l3b-2A202602859`. Evidence ảnh 06–10 và 14 đã có trong `submission/evidence/`.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** `config/dashboard.yaml` khai báo đúng 6 panel `latency`, `traffic`, `errors`, `cost`, `tokens`, `quality`; `validate_dashboard.py` xác nhận 6/6. Dashboard runtime được dựng từ chính `data/logs.jsonl` bằng `scripts/build_dashboard.py` (chỉ dùng thư viện chuẩn, xuất HTML tự chứa + SVG inline), mỗi panel có tiêu đề, câu hỏi vận hành, số liệu, đơn vị, time range 60 phút và ngưỡng/SLO line — xem `evidence/11-dashboard-overview.png`.
- **SLO và lý do chọn:** SLO chính `fast_successful_requests`: SLI tốt khi `event == "response_sent" and latency_ms <= 3000`, tổng là `request_received`, target 99.5% trong cửa sổ 28 ngày. Chọn ngưỡng 3000 ms vì baseline P95 chỉ ~151 ms (rộng hơn ~20 lần, tránh báo động giả) nhưng vẫn bắt được sự cố thật: scenario `rag_slow` đẩy P95 lên ~2653 ms và đỉnh ~8000 ms.
- **Cách tính error budget:** error budget = 100% − 99.5% = 0.5% trong 28 ngày. Với 10,000 request thì tối đa 50 request được phép lỗi hoặc chậm hơn 3000 ms. Error budget cháy nhanh (burn rate cao) là tín hiệu phải dừng release và điều tra.
- **Ba alert và runbook tương ứng:** `config/alert_rules.yaml` định nghĩa ba alert symptom-based, mỗi alert có `severity`, `condition`, `duration`, `owner` (`student-2A202602859`), kênh Slack `#k4-l3b-alerts` và runbook:
  1. `HighLatencyP95` (warning, `p95(latency_ms) > 3000ms` trong 5m) → `docs/alerts.md#alert-1`
  2. `HighErrorRate` (critical, `error_rate_pct > 2%` trong 3m) → `docs/alerts.md#alert-2`
  3. `RetrievalSuccessDrop` (warning, `tool_success_rate_pct < 90%` trong 5m) → `docs/alerts.md#alert-3`

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1` (cohort K4, incident `rag_slow`, seed `1312`, affected_feature `monitoring`, SLO `latency_threshold_ms = 2000`).
- **Cách chạy:** `python scripts/inject_incident.py` (không kèm `--scenario`, đọc `config/challenge.json`) để bật đúng incident của challenge, rồi `python scripts/load_test.py --challenge --concurrency 5` để bắn đúng 5 query challenge.
- **Khoảng thời gian điều tra:** incident window `2026-09-30T04:04:29Z`–`2026-09-30T04:04:43Z` (UTC); chạy và thu evidence ngày `2026-09-30T04:05Z`. Chi tiết trong `evidence/12-incident-metric.txt`.
- **Triệu chứng từ metrics:** `/health` báo `incidents.rag_slow=true`; `/metrics` in-incident cho `latency_p95 = 2654 ms` (vượt SLO 2000 ms) trong khi `latency_p50 = 154 ms`, `ttft_p95 = 51 ms` **không đổi**, `error_breakdown = {}` rỗng. 5 request challenge có latency 7992–13312 ms. P95 vọt lên 154 → 2654 ms nhưng TTFT và error rate đứng yên ⇒ thời gian bị tiêu tốn **trước** khi LLM sinh token, tức ở bước retrieval.
- **Log line và correlation ID liên quan:** `evidence/13-incident-log.txt` — 5 dòng `response_sent` (feature `monitoring`) đều có `latency_ms` 2653–2654, `ttft_ms` 50, `tool_name=retrieval`, `tool_success=true`. Chọn correlation ID `req-9bc618e6` (session `k4-l3b-challenge-s02`, query "How should an engineer investigate tail latency?") làm mốc nối sang trace.
- **Trace ID và span gây ảnh hưởng:** trace `f71427c0ce80a45dd1d5cc9271d23ddb` (project cá nhân `day13-k4-l3b-2A202602859`, session `k4-l3b-challenge-s02`, correlation_id `req-9bc618e6`) — waterfall `lab-agent-run` **2.654 s**, trong đó span **`retrieval` = 2.501 s** còn span `generation` chỉ **0.152 s**. `latency_ms` lớn nhưng `ttft_ms` nhỏ xác nhận nút thắt ở retrieval, không phải LLM sinh token. Ảnh: `evidence/14-incident-trace.png`.
- **Root cause:** incident `rag_slow` chèn `time.sleep(2.5)` trong `app/mock_rag.py::retrieve`, làm span retrieval chậm ~2.5 s mỗi request; không phải lỗi LLM, prompt hay hạ tầng.
- **Fix action:** tắt incident bằng `python scripts/inject_incident.py --disable`; `/health` trở lại `incidents.rag_slow=false` và latency về mức baseline (P95 ~153 ms).
- **Preventive measure:** alert `HighLatencyP95` (5m) và `RetrievalSuccessDrop` (5m) bắt sớm; runbook `docs/alerts.md#alert-1` hướng dẫn dashboard → log theo `correlation_id` → trace để khoanh vùng span retrieval trước khi tắt scenario/rollback. Bổ sung SLO `latency_threshold_ms = 2000` (chặt hơn SLO nội bộ 3000 ms) để phát hiện sớm suy giảm ở bước retrieval.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** đặt `scrub_event` **trước** processor ghi file trong `app/logging_config.py`. Nếu scrub sau khi ghi thì PII đã lọt vào `data/logs.jsonl`/audit; scrub trước bảo đảm nguyên tắc "không có PII thô ở mọi đầu ra" ở tầng kiến trúc, không phụ thuộc việc nhớ gọi scrub tại từng chỗ log.
- **Một lỗi/blocker đã gặp:** (1) `pip install -r requirements.txt` thất bại vì resolver backtrack qua nhiều phiên bản `langfuse` không tương thích trên Python 3.13 (`Could not find a version that satisfies wrapt<3,>=1.14`); (2) `AttributeError: 'RecordingLangfuseClient' object has no attribute 'start_as_current_observation'` khi test dùng fake client tối giản; (3) `.env` chưa có key Langfuse nên `tracing_enabled=false`.
- **Cách tìm nguyên nhân và xử lý:** (1) cài riêng `langfuse==4.15.6` trước (kéo theo `wrapt`) rồi cài phần còn lại; (2) thêm helper `start_observation()` trong `app/tracing.py` dùng `getattr` + `_NullObservation` no-op để code nghiệp vụ không phụ thuộc client đầy đủ và tracing vẫn best-effort — sau đó 22/22 test pass; (3) tạo project Langfuse cá nhân `day13-k4-l3b-2A202602859`, dán `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` vào `.env` (không commit) — từ đó tracing bật và tạo được 25 trace.
- **Cách hiểu luồng Metrics → Logs → Traces:** metrics trả lời "có gì bất thường và khi nào" (nhanh, rẻ, tổng hợp); khi metric chỉ ra khoảng thời gian, log cho biết "request nào" qua `correlation_id`; trace cùng `correlation_id` cho biết "bước nào" gây ra vấn đề. Ba tầng giảm dần độ rộng và tăng dần chi tiết, dẫn tới root cause.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:** prompt là một phần "code" của LLM nên cần version + label để promote/rollback có kiểm soát; token/cost là chỉ số chi phí gắn trực tiếp với chất lượng output (prompt dài/candidate sinh nhiều token ⇒ tốn hơn); SLO/error budget biến "chất lượng dịch vụ" thành ngưỡng định lượng để quyết định khi nào dừng release; rollback là hành động giảm thiểu nhanh nhất khi metric xấu sau khi đổi prompt.
- **Điều quan trọng nhất đã học:** quan sát (observability) là năng lực thiết kế từ đầu — correlation ID, scrub-before-write, span tree và ngưỡng SLO phải được cài trong code, không thể "gắn thêm" sau khi sự cố xảy ra.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:** (1) challenge CP3 chính thức đã chạy xong (`day13-k4-l3b-monitoring-llmops-v1`, incident `rag_slow`) và được chứng minh đầy đủ bằng chuỗi metric → log → trace → root cause trong mục §7; (2) dashboard runtime dựng bằng script chuẩn-thư-viện từ `data/logs.jsonl` thay vì Grafana vì lab không cấp hạ tầng dashboard ngoài.

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident evidence nối đúng metric → log (metric: `12-incident-metric.txt`; log: `13-incident-log.txt`).
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [x] URL repo và commit SHA cuối đã sẵn sàng để nộp trên LMS/Codelabs: `https://github.com/meth04/K4-L3-DAY13-NguyenVanThan-02859-Monitoring-LLMOps` @ `c48910f`.
