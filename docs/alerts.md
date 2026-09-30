# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Alert 1

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` — SLI latency P95 của `response_sent.latency_ms` (tốt khi `latency_ms <= 3000`)
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` liên tục trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời; nếu kéo dài sẽ ăn vào error budget 0.5% của SLO
- Ba bước kiểm tra đầu tiên:
  1. Mở panel `latency` trên dashboard, xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó theo `event == "response_sent"`, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh span `retrieval` và `generation` để xem bước nào bất thường.
- Mitigation tạm thời: nếu span `retrieval` phình to → kiểm tra practice scenario `rag_slow` (tắt scenario); nếu span `generation` phình to → rollback prompt về label `baseline`/`production`; nếu do tải → giảm concurrency khi demo.
- Owner: `student-2A202602859`

## Alert 2

- Tên: `HighErrorRate`
- Severity: `critical`
- Duration: `3m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: guardrail `error_rate_pct_max: 2` — SLI là tỉ lệ `request_failed / request_received`
- Điều kiện và thời gian duy trì: `error_rate_pct > 2%` liên tục trong 3 phút
- Ảnh hưởng tới người dùng: một phần request trả lỗi, người dùng không nhận được câu trả lời; đây là mức nghiêm trọng vì lỗi trực tiếp chặn chức năng
- Ba bước kiểm tra đầu tiên:
  1. Mở panel `errors`, xem `error_rate` và breakdown theo `error_type` để biết loại lỗi chiếm ưu thế.
  2. Lọc `data/logs.jsonl` theo `event == "request_failed"`, gom theo `error_type` và lấy `correlation_id` của một request lỗi.
  3. Mở trace cùng `correlation_id` trên Langfuse, tìm span báo lỗi (thường là `retrieval` hoặc `generation`) và đọc `metadata`/`prompt_fetch_error`.
- Mitigation tạm thời: nếu lỗi từ một practice scenario (ví dụ `tool_fail`) → tắt scenario; nếu lỗi do prompt fetch từ Langfuse → app đã có local fallback, kiểm tra biến `LANGFUSE_PROMPT_*`; nếu lỗi do input → thêm validation.
- Owner: `student-2A202602859`

## Alert 3

- Tên: `RetrievalSuccessDrop`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: guardrail `retrieval_success_rate_pct_min: 90` — SLI là `tool_success_rate_pct` (retrieval) trên `response_sent.tool_success`
- Điều kiện và thời gian duy trì: `tool_success_rate_pct < 90%` liên tục trong 5 phút
- Ảnh hưởng tới người dùng: câu trả lời mất ngữ cảnh tài liệu, chất lượng giảm dù request vẫn "thành công" — dễ bị bỏ sót nếu chỉ nhìn latency/error
- Ba bước kiểm tra đầu tiên:
  1. Mở panel `errors` (thành phần retrieval success) và panel `quality`, xác nhận retrieval giảm kèm quality giảm.
  2. Lọc `data/logs.jsonl` theo `event == "response_sent" and tool_success == false`, lấy `correlation_id` và xem `doc_count`.
  3. Mở trace cùng `correlation_id`, kiểm tra span `retrieval` (`doc_count`, `retrieval_success`) và đối chiếu với `generation`.
- Mitigation tạm thời: nếu do practice scenario `tool_fail` → tắt scenario; nếu do dữ liệu/query → kiểm tra mock RAG và input; tạm thời hạ ưu tiên trả lời dựa trên tài liệu và ghi rõ "no context" thay vì trả lời sai.
- Owner: `student-2A202602859`
