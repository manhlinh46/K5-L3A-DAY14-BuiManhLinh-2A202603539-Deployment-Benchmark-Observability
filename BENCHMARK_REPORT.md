# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ report JSON / CSV / screenshot thật, không ước lượng.
> JSON gốc: `reports/` (copy từ `06-lab-complete/benchmark-observability/develop/reports/`).

**Họ tên:** Bùi Mạnh Linh — 2A202603539
**Ngày chạy:** 2026-11-25
**Môi trường:** Laptop AMD Ryzen 9 8940HX, 32 GB RAM, Windows 11 + WSL2 Ubuntu (32 vCPU, 15 GB RAM cấp cho WSL), Python 3.11.9. Agent develop chạy 1 process uvicorn; `load_test.py` chạy trên cùng máy.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Một LLM call của mock mất ~150–250 ms; 500 ms cho phép thêm retrieval + mạng mà người dùng vẫn thấy "tức thì". Đặt theo p95 chứ không theo avg để bắt được tail latency (mục 2.2). Đây cũng là ngưỡng mặc định của `load_test.py --slo-p95-ms`. |
| Error rate `/ask` | < 2 % | Upstream LLM của mock lỗi ngẫu nhiên ~1 % (`MOCK_ERROR_RATE=0.01`); 2 % chừa biên cho dao động thống kê mà vẫn phát hiện được khi tỉ lệ lỗi tăng gấp đôi. Error budget = 2 % số request. |
| Accuracy trên golden dataset | ≥ 85 % (CI), 100 % cho bản release | 85 % là ngưỡng chặn merge trong CI (`.github/workflows/eval.yml`). Với bản release sau khi sửa KB, dùng `--min-accuracy 1.0` + không có regression so với baseline. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Lệnh: `python load_test.py --url http://localhost:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json` (`MOCK_SLOW_RATE` mặc định 0.03).

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.26 | 191.9 | 221.7 | 1701.5 | 1.00 % (3/300 × 503) | ✅ PASS |
| 10 | 37.24 | 190.3 | 221.1 | 1700.4 | 1.00 % (3/300 × 503) | ✅ PASS |
| 50 | 51.78 | 305.8 | 2671.5 | 4045.9 | 1.67 % (5/300 × 503) | ❌ FAIL (p95) |
| 100 | 40.95 | 1428.9 | 5130.2 | 5602.2 | 1.33 % (4/300 × 503) | ❌ FAIL (p95) |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

- **Từ 1 → 10: gần tuyến tính** (4.26 → 37.24 RPS, ×8.7 khi concurrency ×10), p50/p95 gần như không đổi (~190 / ~221 ms). Mock LLM chỉ `await asyncio.sleep(...)` nên event loop xử lý song song 10 request mà không request nào phải chờ. Đúng định luật Little: RPS ≈ concurrency / latency = 10 / 0.23 s ≈ 43.
- **Từ 10 → 50: bão hoà.** RPS chỉ tăng thêm 39 % (37.24 → 51.78) trong khi concurrency ×5; p95 nhảy từ 221 ms lên **2671.5 ms**. Agent develop chạy **1 process uvicorn / 1 event loop**: phần CPU của mỗi request (parse JSON, Pydantic, Prometheus, ghi log JSON) cộng với client load test chạy cùng máy làm request phải xếp hàng; thời gian chờ trong hàng đợi cộng thẳng vào latency.
- **Từ 50 → 100: RPS còn giảm** (51.78 → 40.95), p50 lên 1428.9 ms, p95 5130.2 ms. Quá điểm bão hoà, thêm concurrency chỉ làm hàng đợi dài thêm và tăng overhead chuyển ngữ cảnh, không tăng throughput.
- Error rate ổn định ~1–1.7 % ở mọi mức: lỗi đến từ upstream giả lập (`MOCK_ERROR_RATE=0.01`, mã 503), không phải do quá tải.
- Kết luận: 1 instance develop chịu được khoảng **~40–50 RPS** trước khi vi phạm SLO p95 500 ms; muốn hơn phải scale ngang (nhiều worker / instance sau load balancer — mục 5).

### 2.2 Tail latency

Lệnh: bật lại v2 với `MOCK_SLOW_RATE=<x>`, `python load_test.py --url http://localhost:8002 --requests 300 --concurrency 20 --out reports/load_v2_slow_<x>.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 194.2 | 228.1 | 242.3 |
| 0.03 (mặc định) | 263.4 | 245.6 | 1703.9 |
| 0.1 | 366.9 | 1693.7 | 1715.1 |

(Thêm: RPS lần lượt 99.46 / 60.33 / 44.92; error rate 1.00 % / 0.67 % / 2.33 %; SLO PASS / PASS / FAIL.)

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

- **p99 nhạy nhất ở mức 3 %:** từ 0 → 0.03, p99 tăng **×7** (242.3 → 1703.9 ms) trong khi avg chỉ tăng 36 % (194.2 → 263.4 ms) và p95 gần như không đổi (228.1 → 245.6 ms). Lý do: 3 % request bị cộng thêm 1500 ms; 3 % > 1 % nên p99 rơi đúng vào nhóm chậm, còn p95 (5 % chậm nhất) vẫn chủ yếu là request bình thường.
- **Ở mức 10 %, p95 cũng vọt** lên 1693.7 ms (10 % > 5 %), SLO p95 500 ms bị vi phạm; avg vẫn chỉ 366.9 ms — nhìn avg sẽ tưởng hệ thống vẫn ổn, trong khi cứ 10 người dùng có 1 người chờ gần 2 giây.
- **Average che giấu tail latency:** nó trộn 90–97 % request nhanh với vài request rất chậm thành một con số "trông bình thường". Người dùng cảm nhận theo request chậm nhất họ gặp, nên SLO phải đặt theo percentile (p95/p99).
- RPS giảm (99.46 → 44.92) vì load test là vòng kín 20 worker: request chậm giữ chỗ của worker lâu hơn → ít request hoàn thành mỗi giây. Error rate 2.33 % ở mức 0.1 là dao động ngẫu nhiên của `MOCK_ERROR_RATE` 1 % trên mẫu 300 request (7 lỗi), không do request chậm gây ra.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Lệnh:
```bash
python eval/run_eval.py --url http://localhost:8001 --out reports/eval_v1.json
python eval/run_eval.py --url http://localhost:8002 --out reports/eval_v2.json --baseline reports/eval_v1.json
# sau khi sửa KNOWLEDGE_BASE và bật lại v2:
python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json
```

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35 % (1/23) | 91.3 % (21/23) | 100 % (23/23) |
| Avg tokens / câu | 56.6 | 108.8 | 116.3 |
| Tổng cost (USD) | 0.000397 | 0.000757 | 0.000813 |
| Cost / câu đúng (USD) | 0.00039735 | 0.00003607 | 0.00003537 |
| Latency p50 / p95 (ms) | 162.9 / 187.8 | 184.8 / 212.8 | 186.1 / 213.5 |
| Quality gate | FAIL (ngưỡng 80 %) | PASS (ngưỡng 80 %, 0 regression) | PASS (ngưỡng 100 %, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `scaling-03` — "Kubernetes HPA scale dựa trên những chỉ số nào?" | `cpu`, `memory`, `custom metrics` | Retrieval không khớp tài liệu nào (KB không có gì về Kubernetes) nên v2 trả câu chung chung. Thêm entry `(["hpa", "kubernetes", "autoscal"], "Kubernetes HPA ... dựa trên mức dùng CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi ...")` vào `KNOWLEDGE_BASE`. |
| `security-02` — "JWT khác gì API key trong xác thực?" | `token`, `hết hạn`, `chữ ký` | Tương tự, KB không có tài liệu về JWT. Thêm entry `(["jwt", "xác thực"], "API key là chuỗi bí mật cố định, không tự hết hạn ... JWT là token có chữ ký số ..., chứa ... thời điểm hết hạn (exp) ...")`. |

Từ khoá kích hoạt (`hpa`, `kubernetes`, `autoscal`, `jwt`, `xác thực`) không xuất hiện trong 21 câu còn lại nên không làm đổi tài liệu được retrieve của câu nào khác → **0 regression** (eval cuối: "Câu được cải thiện: 2, Câu bị regression: 0"). Không sửa `golden_dataset.jsonl`. Cùng thay đổi đã chép sang `production/utils/mock_llm.py` cho stack Docker ở Bước 2.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- v2 (RAG) đưa tài liệu retrieve được vào prompt → **gấp ~1.9 lần token và cost mỗi câu** (56.6 → 108.8 token; tổng cost 0.000397 → 0.000757 USD) và **chậm hơn ~25 ms ở p95** (187.8 → 212.8 ms: bước retrieval ~20 ms + prompt dài hơn).
- Đổi lại accuracy tăng từ 4.35 % lên 91.3 %, nên **cost / câu đúng giảm ~11 lần** (0.00039735 → 0.00003607 USD). Cost / câu là chỉ số sai lệch: v1 rẻ hơn mỗi câu nhưng gần như toàn trả lời vô dụng; cái cần tối ưu là chi phí cho mỗi câu trả lời *đúng*.
- Sửa KB làm prompt của 2 câu dài thêm (avg tokens 108.8 → 116.3, cost +0.000056 USD) nhưng cost / câu đúng còn giảm nhẹ (0.00003607 → 0.00003537) vì 2 câu đó giờ trả lời đúng.
- Latency tăng thêm của v2 nhỏ so với SLO 500 ms → trade-off rất đáng.

**Quality gate trong CI:**

Chạy v1 với baseline là v2 (giả lập một PR làm hỏng agent):

```
$ python eval/run_eval.py --url http://localhost:8001 --baseline reports/eval_v2.json
  Accuracy      : 4.3%  (1/23)
  ⚠️  Câu bị regression : 20 ['docker-01', 'docker-02', 'probe-01', ...]
  Quality gate (accuracy ≥ 80%, không regression): ❌ FAIL
→ exit code 1
```

`run_eval.py` trả **exit code 1** khi accuracy dưới `--min-accuracy` hoặc có câu regression so với `--baseline`, và **0** khi đạt. Job `.github/workflows/eval.yml` chạy agent v2 (`MOCK_ERROR_RATE=0` để không flaky) rồi chạy `run_eval.py --min-accuracy 0.85 --baseline reports/eval_v2_fixed.json`; exit code 1 làm step fail → job fail → khi bật branch protection "Require status checks to pass" cho `main`, PR không merge được.

### Phụ lục — Exercise 7.1: metrics của agent

`curl -s http://localhost:8002/metrics` sau 1 request `/ask` (agent v2):

```
http_requests_total{method="POST",route="/ask",status="200"} 1.0
http_request_duration_seconds_count{method="POST",route="/ask"} 1.0
http_request_duration_seconds_sum{method="POST",route="/ask"} 0.21452527600013127
llm_request_duration_seconds_bucket{le="0.2",model="mock-llm-small"} 1.0
llm_tokens_total{model="mock-llm-small",type="input"} 91.0
llm_tokens_total{model="mock-llm-small",type="output"} 55.0
llm_cost_usd_total{model="mock-llm-small"} 4.6649999999999996e-05
agent_info{model="mock-llm-small",version="v2"} 1.0
```

1. **Counter:** `http_requests_total`, `llm_tokens_total`, `llm_cost_usd_total` — chỉ tăng. **Gauge:** `agent_in_flight_requests` (tăng khi request vào, giảm khi xong), `agent_info` (= 1, mang label version/model). **Histogram:** `http_request_duration_seconds`, `llm_request_duration_seconds` — gồm `_bucket{le=...}`, `_sum`, `_count`, dùng `histogram_quantile` để tính p95/p99.
2. **Label `route` dùng `route.path` (template):** nếu dùng `request.url.path`, mỗi URL lạ bot quét (`/wp-admin`, `/.env`, `/a1b2c3`…) tạo một time series mới cho mỗi tổ hợp method × route × status (và mỗi bucket của histogram) → **cardinality bùng nổ**, Prometheus tốn RAM, query chậm, có thể OOM. Dùng template thì mọi URL không khớp gom vào `route="unmatched"`, số series cố định.
3. **Metric mới `agent_question_length_chars`** (Histogram, bucket 20/50/100/200/500/1000/2000, đã thêm vào `develop/app.py`). Sau 1 câu hỏi 40 ký tự:

```
agent_question_length_chars_bucket{le="20.0"} 0.0
agent_question_length_chars_bucket{le="50.0"} 1.0
agent_question_length_chars_count 1.0
agent_question_length_chars_sum 40.0
```

Dùng Histogram thay vì label `length=...` vì độ dài có vô số giá trị → label sẽ làm cardinality bùng nổ.

---

## 4. Observability stack (production)

Stack: `docker compose -p k5-day14-observability up -d --build` trong `production/` (agent ×2 sau Nginx, Prometheus, Grafana, Jaeger, Locust). Tải nền cho mục 4: Locust headless 30 user (`-u 30 -r 5`), ~18.5 req/s. Mỗi container agent giới hạn 0.5 CPU / 256 MB, 1 uvicorn worker.

**Sửa lỗi trước khi chạy được:** container agent crash `ModuleNotFoundError: No module named 'uvicorn'` — Dockerfile cài `pip install --user` rồi copy vào `/home/agent/.local`, nhưng user `agent` được tạo với `useradd -d /app` nên Python tìm user site-packages ở `/app/.local`. Thêm `ENV PYTHONUSERBASE=/home/agent/.local` vào `production/Dockerfile` (đúng cảnh báo ở CODE_LAB Part 6 Step 8).

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals) — [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian) — [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`) — [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với 2 alert đang **firing** (`AgentHighErrorRate` = 0.2028, `AgentHighLatencyP95` = 1.903 s) — [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png)

**Exercise 7.4 — đọc dashboard (30 user, 2 instance):**

1. **p95 = 293.81 ms, avg ≈ 237 ms** (Traffic 18.5 req/s, Error rate 0.98 %). p95 chỉ cao hơn avg ~57 ms → phần lớn request có latency rất đồng đều (LLM mock ~150–250 ms). Nhưng đường **p99 nằm ở ~1.9 s**, vượt xa p95: đó là ~3 % request bị `MOCK_SLOW_RATE` làm chậm thêm 1.5 s — tail latency mà avg và cả p95 không thấy.
2. **Requests/s theo instance:** 2 đường (`172.21.0.7`, `172.21.0.8`) gần như trùng nhau → Nginx round-robin chia đều traffic.
3. **Input tokens/s > output tokens/s** (đo bằng Prometheus: 1455.5 vs 772.6 tokens/s): prompt = system prompt + tài liệu retrieve được (RAG) + câu hỏi, dài hơn câu trả lời; v2 còn thêm context nên input càng lớn.
4. **`curl http://localhost:8080/metrics` → 404:** Nginx chặn `/metrics`, không public ra Internet (lộ thông tin nội bộ, ai cũng scrape được). Prometheus scrape thẳng từng container agent trong network nội bộ `obs_net`.

**Quan sát thêm:** ngay ở trạng thái bình thường, `LLMCostBurnRateHigh` đã **firing** — cost ước tính **$2.44/giờ** (30 user liên tục) > ngưỡng $2/giờ. Ngưỡng alert phải được hiệu chỉnh theo tải thực tế, nếu không sẽ thành alert "luôn đỏ" và bị bỏ qua (alert fatigue).

### 4.2 Thí nghiệm "phá hệ thống"

Cách đo: ghi `.env` → `docker compose -p k5-day14-observability up -d agent` (t = 0) → cứ 5 s hỏi `GET /api/v1/alerts` của Prometheus, ghi thời điểm chuyển `pending` và `firing`. Locust 30 user chạy suốt.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (error rate 21.2 %) | **89 s** (pending sau 28 s + `for: 1m`) | Golden Signals → **Error rate** chuyển đỏ; "LLM calls theo kết quả" (đường `error` tăng) |
| B | `MOCK_SLOW_RATE=0.3` (giữ A) | `AgentHighLatencyP95` (p95 = 1.90 s) | **144 s** (pending sau 23 s + `for: 2m`) | "Latency /ask — p50/p95/p99": p95, p99 vọt lên ~1.9 s, p50/avg tăng ít; RPS tụt 19 → 15.3 req/s |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | **146 s** (pending sau 29 s + `for: 2m`) | "Cost burn rate (USD/giờ)": $2.44 → **$16.59** sau 2.5 phút và còn tăng ($18.72 lúc 17:39, vì `rate[5m]` còn lẫn dữ liệu cũ); p95 0.29 → 0.70 s (latency ×2.5) |
| D | `docker pause` agent-1 | `AgentInstanceDown` (`up` = 1/2) | **46 s** (pending sau 16 s + `for: 30s`) | "Instances up" 2 → 1, "Requests/s theo instance" còn 1 đường. **Error rate vẫn xanh (0.54 %)** trong khi Nginx ghi **27 lỗi 504** (timeout 10 s) |
| E | `AGENT_VERSION=v1` | **Không có** (sau 2 phút; `LLMCostBurnRateHigh` còn tự hết firing) | — | "Retrieval hit ratio" mất hẳn (18.6 hit/s → không còn series); "Tokens/s" giảm một nửa (input 1455 → 687, output 773 → 374); bảng "Phiên bản đang chạy" đổi sang v1; cost/giờ $2.45 → $1.18 |

Ghi chú thêm:
- Thời gian firing ≈ thời gian để `rate[...]` vượt ngưỡng (~20–30 s) + `for`. `for` chống báo động giả nhưng làm chậm phát hiện; alert critical (instance down) dùng `for` ngắn hơn.
- Ở B, request chậm làm RPS giảm nên cost/giờ tụt xuống $1.73 → `LLMCostBurnRateHigh` hết firing: một sự cố có thể "che" alert khác.
- D: `docker pause` (không phải `stop`) để container vẫn còn trong DNS nhưng không trả lời → `up == 0`. 504 xảy ra ở Nginx (chờ quá `proxy_read_timeout 10s` rồi `proxy_next_upstream` sang instance còn lại), request chưa bao giờ được agent xử lý xong nên metric của agent không đếm → cần giám sát thêm ở tầng load balancer / synthetic check từ bên ngoài.
- Khi reset cấu hình, `docker compose up -d` tạo lại **cả 2 agent cùng lúc** → Nginx log **225 lỗi 502** ("no live upstreams") trong vài giây: deploy kiểu recreate gây downtime, production cần rolling update (thay từng instance, chờ `/ready`).

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đây là lỗi **chất lượng**, không phải lỗi hạ tầng: agent vẫn trả 200, nhanh hơn và rẻ hơn (eval ở mục 3: accuracy v1 chỉ 4.35 % so với 100 %). Cách phát hiện:
1. **Chặn từ trước khi deploy:** quality gate trong CI (`run_eval.py --baseline`, `.github/workflows/eval.yml`) — v1 có 20 câu regression → exit code 1 → không merge được.
2. **Alert trên metric "chất lượng proxy":** retrieval hit ratio (`sum(rate(agent_retrieval_total{result="hit"}[5m])) / sum(rate(agent_retrieval_total[5m])) < 0.8`), hoặc tokens/request giảm đột ngột, hoặc `agent_info` đổi version ngoài lịch deploy.
3. **Online eval:** định kỳ chạy golden dataset vào production (synthetic check) hoặc chấm mẫu ngẫu nhiên câu trả lời thật bằng LLM-as-judge, export thành metric accuracy và alert khi giảm.
4. **Tín hiệu người dùng:** tỉ lệ thumbs-down / hỏi lại / bỏ ngang; canary so sánh version mới với version cũ trước khi rollout toàn bộ.

### 4.3 Debug bằng trace

Trace chậm nhất (Jaeger → Lookup by Trace ID, ảnh `screenshots/jaeger-slow-trace.png`):

- `trace_id`: `121452a029c67235b6640ab418d85313`
- Tổng thời gian: **1722.0 ms** (`POST /ask`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small` (1698.7 ms, 98.6 %)**; `agent.retrieve_context` chỉ 20.3 ms (1.2 %). → Chậm nằm ở upstream LLM (request rơi vào nhóm `MOCK_SLOW_RATE`), không phải code của agent hay retrieval. Tags: `gen_ai.request.model = mock-llm-small`, `gen_ai.usage.input_tokens = 95`, `gen_ai.usage.output_tokens = 55`.
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep 121452a029c67235b6640ab418d85313`):

```json
{"ts": "2026-11-25T10:14:56.297841+00:00", "level": "INFO", "service": "observable-agent", "instance": "9e3b8677f7ac", "event": "llm_call", "trace_id": "121452a029c67235b6640ab418d85313", "span_id": "c77b6536afa66c50", "request_id": "a77c92401950", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1698.9}
{"ts": "2026-11-25T10:14:56.298503+00:00", "level": "INFO", "service": "observable-agent", "instance": "9e3b8677f7ac", "event": "http_request", "trace_id": "121452a029c67235b6640ab418d85313", "span_id": "c77b6536afa66c50", "request_id": "a77c92401950", "method": "POST", "route": "/ask", "status": 200, "ms": 1721.2}
```

Trace lỗi (ảnh `screenshots/jaeger-error-trace.png`): `trace_id` `49a6ff323ae81094280bf0714bc43ac0`, `POST /ask` → **503** sau 96.1 ms; span `chat mock-llm-small` (74.9 ms) có `error=true`, `error.type = upstream_unavailable` và event `exception` (`utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`, kèm stacktrace). Log tương ứng:

```json
{"ts": "2026-11-25T10:21:58.980706+00:00", "level": "INFO", "service": "observable-agent", "instance": "9e3b8677f7ac", "event": "llm_error", "trace_id": "49a6ff323ae81094280bf0714bc43ac0", "span_id": "2f715e49e9850631", "request_id": "4fbcc42dcd3a", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Lệnh (theo CHECKPOINTS CP8): `docker compose -p k5-day14-observability run --rm locust -f /mnt/locust/locustfile.py --host http://nginx --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_<n>`, với `--scale agent=1` rồi `--scale agent=3` (kiểm tra trước: 6 request chia đều 2/2/2 cho 3 instance). Số liệu hàng `POST /ask` trong `benchmark-results/scale_<n>_stats.csv`:

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59.26 | 200 | 280 | 1700 | 66 / 7033 (0.94 %) |
| 3 | 59.30 | 200 | 270 | 1700 | 79 / 7039 (1.12 %) |

(Avg 249.5 ms vs 242.1 ms. Hàng `Aggregated` gồm cả `/health`: 65.08 vs 65.49 req/s.)

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

- **Gần như không cải thiện:** RPS 59.26 → 59.30, p95 280 → 270 ms, p99 giữ 1700 ms. Failures ~1 % ở cả hai là lỗi 503 giả lập (`MOCK_ERROR_RATE=0.01`), không do quá tải.
- **Nút thắt 1 — chính bộ tạo tải (closed-loop):** mỗi user Locust chờ `between(0.5, 2)` s (trung bình 1.25 s) sau mỗi response ~0.24 s → mỗi user tối đa ~0.67 req/s → 100 user ≈ 67 req/s tổng, khớp với 65 req/s đo được. Throughput bị giới hạn bởi số user × think time, không phải bởi server: 1 instance chưa bão hoà nên thêm instance không có tác dụng.
- **Nút thắt 2 — latency của upstream LLM:** p50/p95 do thời gian gọi LLM quyết định (~120 ms + jitter + token), p99 do 3 % request chậm thêm 1.5 s. Scale ngang chỉ tăng **khả năng chịu tải**, không làm từng LLM call nhanh hơn — panel "LLM latency p95" giữ ~195–200 ms dù 1 hay 3 instance. Agent chủ yếu `await` (I/O-bound), nên 1 container 0.5 CPU đã đủ cho ~60 req/s.
- Muốn thấy lợi ích của scale phải đẩy tải tới điểm bão hoà của 1 instance (nhiều user hơn / giảm think time, như ở mục 2.1 khi concurrency 50 làm p95 vọt lên 2.7 s), lúc đó 3 instance sẽ giữ p95 thấp còn 1 instance thì không. Còn tail latency do upstream thì phải xử lý bằng timeout + retry/hedging, cache, hoặc model nhanh hơn.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Average nói dối, percentile mới phản ánh trải nghiệm:** chỉ 3 % request chậm đã đẩy p99 lên ×7 trong khi avg tăng 36 % (mục 2.2); SLO và alert phải đặt theo p95/p99. Benchmark cũng phải hiểu mô hình tải: Locust closed-loop với think time làm "scale 3 instance" trông vô ích, vì nút thắt nằm ở bộ tạo tải và upstream LLM chứ không phải server.
  2. **Metrics, traces, logs bổ trợ nhau qua `trace_id`:** metrics/alert báo *có* vấn đề (p95 > 1 s), trace chỉ ra *ở đâu* (98.6 % thời gian nằm ở span LLM), log JSON cùng `trace_id` cho chi tiết từng request. Mỗi tầng chỉ thấy những gì chính nó xử lý — lỗi 504 ở Nginx không hề xuất hiện trong error rate của agent.
  3. **Hạ tầng xanh ≠ agent đúng:** đổi sang v1 làm accuracy rơi từ 100 % xuống 4.35 % nhưng mọi alert đều im lặng, thậm chí alert cost tự tắt. Chất lượng phải được đo riêng bằng eval trên golden dataset, gắn vào CI làm quality gate (exit code chặn merge) và theo dõi "cost / câu đúng" thay vì "cost / câu".
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - **Chất lượng:** alert retrieval hit ratio < 80 %; online eval định kỳ (golden dataset qua endpoint thật / LLM-as-judge trên mẫu traffic) export thành `agent_eval_accuracy`, alert khi giảm; alert khi `agent_info` đổi version ngoài cửa sổ deploy.
  - **Tầng ngoài:** metric/alert ở Nginx (tỉ lệ 5xx/504 của load balancer) và synthetic check từ bên ngoài gọi URL public mỗi phút.
  - **SLO theo error budget:** multi-window burn-rate alert (vd tiêu 2 % budget trong 1 giờ) thay vì ngưỡng tĩnh; hiệu chỉnh `LLMCostBurnRateHigh` theo tải thật (hiện firing ngay ở tải bình thường $2.44/giờ) và thêm alert budget theo ngày/tháng.
  - **LLM-specific:** `llm_requests_total{status="error"}` theo provider/error type (429 vs 503) để phân biệt rate limit của provider; tokens/request p95 để bắt prompt phình to; saturation (`agent_in_flight_requests` gần giới hạn) để autoscale trước khi p95 vỡ.
  - **Deploy:** rolling update có kiểm `/ready` để tránh đợt 502 khi tạo lại toàn bộ instance (đã thấy 225 lỗi 502 trong lab).
