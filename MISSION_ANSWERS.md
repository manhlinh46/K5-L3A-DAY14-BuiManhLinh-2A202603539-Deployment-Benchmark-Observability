# Day 14 Lab - Mission Answers

> Môi trường: Windows 11 + WSL2 (Ubuntu), Python 3.11.9 (venv), Docker Desktop (WSL integration).
> Mọi output bên dưới là output thật từ lệnh đã chạy; token/secret đã được che.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found (`01-localhost-vs-production/develop/app.py`)

1. **Dòng 17–18:** API key và mật khẩu DB hardcode trong code → push lên GitHub là lộ secret.
2. **Dòng 34:** in secret ra log (`[DEBUG] Using key: sk-hardcoded-...`) → ai đọc được log cũng thấy key.
3. **Dòng 21–22:** `DEBUG`, `MAX_TOKENS` cố định trong code → đổi cấu hình phải sửa code và deploy lại.
4. **Dòng 33–38:** dùng `print` thay vì logging, không có level, không có cấu trúc → khó lọc, khó phân tích.
5. **Không có `/health`** → platform không biết khi nào agent chết để restart.
6. **Dòng 51:** bind `host="localhost"` → chạy trong container thì bên ngoài không gọi vào được.
7. **Dòng 52:** port 8000 cố định → Railway/Render cấp `PORT` qua env sẽ không chạy.
8. **Dòng 53:** `reload=True` → tốn tài nguyên, không an toàn khi chạy production.
9. **Không xử lý shutdown** → request đang chạy bị cắt ngang khi deploy hoặc scale.

### Exercise 1.2: Chạy bản develop

```
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Log server:

```
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.
INFO:     127.0.0.1:52788 - "POST /ask?question=Hello HTTP/1.1" 200 OK
```

Nhận xét: app chạy được nhưng **in secret ra log** và chưa sẵn sàng cho production.

### Exercise 1.3: Chạy bản production và so sánh

```
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":11.4,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:50:15.610684+00:00"}

$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}
```

| Feature | Develop | Production | Why Important? |
|---|---|---|---|
| Config | Hardcode trong code | `os.getenv` trong `config.py`, có giá trị mặc định | Cùng một image chạy được ở dev/staging/prod, chỉ đổi env |
| Secrets | Key nằm trong code, bị in ra log | Đọc từ env / `.env` (đã gitignore), không log | Tránh lộ key qua git và log |
| Health check | Không có | `/health` (liveness), `/ready` (readiness) | Platform biết khi nào restart, khi nào route traffic vào |
| Logging | `print()` | `logging`, dự định format JSON | Đưa được vào log aggregator để lọc / tìm kiếm |
| Host / Port | `localhost:8000` cố định | `0.0.0.0` + biến `PORT` | Chạy được trong container và trên cloud |
| Reload / Debug | `reload=True` luôn bật | Chỉ bật khi `DEBUG=true` | Production cần ổn định, không tự restart |
| Shutdown | Đột ngột | `lifespan` + handler SIGTERM | Request đang xử lý không bị cắt ngang khi deploy |
| Input | Query string, không validate | Body JSON, câu hỏi rỗng → 422 | Báo lỗi rõ ràng cho client |

**Quan sát thêm:** log JSON của bản production không hiện ra (chỉ thấy `WARNING:root:OPENAI_API_KEY not set — using mock LLM`).
Nguyên nhân: `config.py` gọi `logging.warning(...)` **trước** khi `app.py` gọi `logging.basicConfig(...)`, nên root logger đã được cấu hình với format mặc định và mức WARNING; `basicConfig` trong `app.py` không còn tác dụng → format JSON bị bỏ qua và log INFO bị ẩn.
→ Muốn log JSON chắc chắn chạy, nên tự gắn một `logging.Formatter` cho handler (áp dụng ở Part 6).

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11`, bản Python đầy đủ (Debian + công cụ build), khoảng 1 GB.
2. **Working directory:** `/app`. Các lệnh `COPY` / `RUN` / `CMD` sau đó đều chạy trong thư mục này.
3. **Vì sao `COPY requirements.txt` trước rồi mới `COPY` code:** Docker cache theo từng layer. Requirements ít thay đổi nên layer `pip install` được dùng lại từ cache; sửa `app.py` chỉ phải build lại các layer phía sau → build nhanh hơn rất nhiều.
4. **CMD và ENTRYPOINT:** `CMD` là lệnh mặc định, `docker run <image> <lệnh khác>` sẽ ghi đè được; `ENTRYPOINT` là lệnh cố định, tham số truyền vào được nối thêm sau nó. Ở đây dùng `CMD ["python", "app.py"]` (exec form → python là PID 1, nhận được SIGTERM).

### Exercise 2.2: Build & run

```
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run --rm -d --name agent-dev -p 8000:8000 my-agent:develop
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
$ docker stop agent-dev
```

Container trả lời được vì `02-docker/develop/app.py` đã bind `0.0.0.0` và đọc `PORT` từ env.

### Exercise 2.3: Image size comparison

```
$ for t in develop advanced; do echo "$t: $(( $(docker image inspect -f '{{.Size}}' my-agent:$t) / 1024 / 1024 )) MB"; done
develop: 1590 MB
advanced: 228 MB

$ docker images | grep my-agent
my-agent:advanced   0c4dea645bb0   240MB    57.4MB
my-agent:develop    36cf1c67d988   1.67GB   426MB
```

- **Develop:** 1590 MB
- **Production:** 228 MB
- **Difference:** (1590 − 228) / 1590 ≈ **85.7% nhỏ hơn**

Vì sao nhỏ hơn: base `python:3.11-slim` bỏ compiler, header, docs; stage `builder` (gcc, libpq-dev, cache apt) bị bỏ lại, stage `runtime` chỉ copy `/root/.local` (site-packages) + code.

**Sự cố gặp phải:** mạng chặn HTTP cổng 80 (`401 VG-AuthenticationRequired`) khiến `apt-get update` trong stage builder lỗi → sửa Dockerfile, chuyển nguồn apt sang HTTPS (`sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources`). App chỉ dùng wheel thuần Python nên thực ra không cần gcc.

### Exercise 2.4: Docker Compose stack

```
$ cd 02-docker/production && touch .env.local
$ docker compose -p k5-day14-docker up -d --build
$ docker compose -p k5-day14-docker ps
NAME                       IMAGE                   SERVICE   STATUS                    PORTS
k5-day14-docker-agent-1    k5-day14-docker-agent   agent     Up 20 seconds (healthy)   8000/tcp
k5-day14-docker-nginx-1    nginx:alpine            nginx     Up 19 seconds             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
k5-day14-docker-qdrant-1   qdrant/qdrant:v1.9.0    qdrant    Up 31 seconds (healthy)   6333-6334/tcp
k5-day14-docker-redis-1    redis:7-alpine          redis     Up 30 seconds (healthy)   6379/tcp
```

Kiến trúc:

```
Client ──HTTP :80──▶ nginx (reverse proxy, rate limit 10r/s, security headers)
                       │  proxy_pass http://agent:8000   (network "internal")
                       ▼
                     agent (FastAPI, uvicorn 2 workers, non-root, HEALTHCHECK)
                       │                 │
                       ▼                 ▼
               redis:6379          qdrant:6333
            (session, rate limit)  (vector DB cho RAG)
```

- Chỉ nginx publish port ra host; agent / redis / qdrant chỉ nằm trong network bridge `internal`, gọi nhau bằng tên service (DNS nội bộ của Docker).
- agent `depends_on` redis + qdrant với `condition: service_healthy` → chỉ start khi 2 service kia đã healthy.
- Dữ liệu redis / qdrant giữ trong named volume `redis_data`, `qdrant_data`.

Kết quả test qua Nginx:

```
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":29.0,"version":"2.0.0","timestamp":"2026-11-25T08:06:21.192256"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Log agent:

```
agent-1  | INFO:     Started server process [8]
agent-1  | INFO:     Started server process [9]
agent-1  | INFO:     127.0.0.1:47698 - "GET /health HTTP/1.1" 200 OK
agent-1  | INFO:     172.20.0.5:51330 - "GET /health HTTP/1.1" 200 OK
agent-1  | {"time":"2026-11-25 08:06:27,257","level":"INFO","msg":"{"event": "request", "q_len": 21}"}
agent-1  | INFO:     172.20.0.5:51344 - "POST /ask HTTP/1.1" 200 OK
```

Quan sát:
- Header `Server: nginx` + các security header → request **đi qua Nginx** rồi mới tới agent.
- Request `/ask` đến từ `172.20.0.5` (container nginx); các dòng `127.0.0.1 GET /health` là HEALTHCHECK của Docker gọi từ trong container.
- 2 dòng `Started server process [8]` / `[9]` = 2 worker uvicorn (`--workers 2`).
- **Lỗi log:** dòng `"msg":"{"event": "request", "q_len": 21}"` **không phải JSON hợp lệ** — message đã `json.dumps` rồi lại bị nhét vào một format string JSON khác nên dấu `"` không được escape. Part 6 cần Formatter `json.dumps` toàn bộ bản ghi log.

---

## Part 3: Cloud Deployment

> Theo CHECKPOINTS (K5), Part 3 deploy luôn agent Part 6 (CP6).

### Exercise 3.1 / 3.2: Deploy nền tảng chính

- Platform: _TODO (Railway / Render)_
- URL: _TODO_
- Kết quả 4 lệnh tự kiểm (CP6):

```
TODO: /health → 200, /ready → 200, /ask không key → 401, /ask có key → 200
```

- Screenshot: `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

### So sánh `railway.toml` và `render.yaml`

_TODO_

### Exercise 3.3: Cloud Run CI/CD pipeline

_TODO: 3–5 dòng mô tả các bước trong `cloudbuild.yaml` và `service.yaml`_

---

## Part 4: API Security

### Exercise 4.1: API Key (`04-api-gateway/develop`, `AGENT_API_KEY=secret-key-123`)

```
--- 1. Không key
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

--- 2. Sai key
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

--- 3. Đúng key
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Nhận xét: key đọc từ env `AGENT_API_KEY`, kiểm qua `APIKeyHeader(name="X-API-Key")` dùng làm dependency của `/ask`. Bản này phân biệt thiếu key (401) và sai key (403); hợp đồng Part 6 yêu cầu **cả hai đều trả 401**.

### Exercise 4.2: JWT (`04-api-gateway/production`)

```
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
{"access_token":"eyJ...<đã che>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJ...<đã che>"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'      # không token
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer eyJ...<đã che>" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). ...","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}
```

JWT chứa `sub` (username), `role`, `iat`, `exp` (60 phút), ký HS256 → server không cần lưu session, chỉ verify chữ ký + hạn.

### Exercise 4.3: Rate limiting (user: 10 req / 60 s, sliding window)

```
req  1 → 200
...
req  9 → 200
req 10 → 429
...
req 15 → 429

HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795594840
retry-after: 43
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":43}}
```

- 429 xuất hiện từ request thứ 10 vì request `/ask` ở bước 4.2 đã tính là request thứ 1 trong cửa sổ 60 s.
- Hạn chế: limiter lưu trong RAM (deque theo user) → mỗi worker / instance đếm riêng, restart là mất.

### Exercise 4.4: Cost guard

```
$ curl -s http://localhost:8000/me/usage -H "Authorization: Bearer eyJ...<đã che>"
{"user_id":"student","date":"2026-11-25","requests":10,"input_tokens":20,"output_tokens":308,"cost_usd":0.000188,"budget_usd":1.0,"budget_remaining_usd":0.999812,"budget_used_pct":0.0}
```

- Chi phí = `input_tokens/1000 × $0.00015 + output_tokens/1000 × $0.0006` (giá gpt-4o-mini).
- `check_budget()` gọi **trước** LLM: user vượt $1/ngày → **402**; tổng toàn hệ thống vượt $10/ngày → **503**; đạt 80% budget → log cảnh báo. `record_usage()` gọi **sau** LLM vì lúc đó mới biết số token thật.
- Request bị 429 không gọi LLM nên không bị tính tiền (`requests` = 10, không phải 15).
- Hạn chế: state trong dict RAM, reset theo ngày nhưng mất khi restart, không chia sẻ giữa instance → Part 6 chuyển sang Redis (key `cost:<ngày>`, `INCRBYFLOAT`).
- **Bug quan sát được:** response `/ask` trả `budget_remaining_usd` = `usage.total_cost_usd` (`app.py:160`), tức là số **đã tiêu** chứ không phải số còn lại; `/me/usage` tính đúng (`0.999812`).
- Rate limit bảo vệ **tốc độ** (chống spam / DoS), cost guard bảo vệ **tiền** (vài request rất dài vẫn có thể đốt hết budget) → cần cả hai.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop`)

```
$ curl -s http://localhost:8000/
{"message":"AI Agent with health checks!"}

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":15.3,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:27:36.771887+00:00","checks":{"memory":{"status":"ok","used_percent":6.8}}}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}

$ curl -s -X POST "http://localhost:8000/ask?question=Hello"      # mock LLM ~3 giây
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

- **Liveness (`/health`)**: "process còn sống không?" → luôn 200 khi process chạy được. Fail → platform **restart** container.
- **Readiness (`/ready`)**: "có nhận traffic được chưa?" → 503 khi đang khởi động, đang shutdown hoặc dependency (DB / Redis) chưa sẵn sàng. Fail → load balancer **ngừng gửi traffic** vào instance này nhưng không restart.
- Nếu gộp chung: Redis chết → `/health` fail → platform restart liên tục mọi instance dù restart không sửa được Redis. Tách ra thì chỉ ngừng route traffic tới khi Redis hồi phục.
- `in_flight_requests: 1` vì middleware `track_requests` đếm cả chính request `/ready` đang xử lý.

### Exercise 5.2: Graceful shutdown

Client — gửi request ~3 s, 1 s sau gửi SIGTERM (cùng một dòng):

```
$ curl -s -w '\n→ HTTP %{http_code}\n' -X POST "http://localhost:8000/ask?question=Long%20task" & sleep 1; pkill -TERM -f "python app.py"; wait
[1] 10565
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
→ HTTP 200
```

Server:

```
2026-11-25 15:38:54,922 INFO ✅ Agent is ready!
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Shutting down
INFO:     127.0.0.1:53226 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-25 15:38:59,621 INFO 🔄 Graceful shutdown initiated...
2026-11-25 15:38:59,621 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [10546]
2026-11-25 15:38:59,621 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

Phân tích:
- SIGTERM tới khi request đang xử lý → uvicorn in `Shutting down`, **ngừng nhận kết nối mới** nhưng vẫn chờ request đang chạy xong → client vẫn nhận **HTTP 200**, không bị cắt ngang.
- Sau khi request xong, uvicorn chạy phần sau `yield` trong `lifespan`: đặt `_is_ready = False` (để `/ready` trả 503, LB ngừng gửi traffic), chờ `_in_flight_requests` về 0 (tối đa 30 s, `timeout_graceful_shutdown=30`) rồi thoát.
- Dòng `Received signal 15` của `handle_sigterm` xuất hiện **sau cùng**, sau cả `Finished server process`: trong lúc chạy, uvicorn tạm thay handler SIGTERM của app bằng handler riêng; khi tắt xong nó khôi phục handler cũ và phát lại tín hiệu → handler của app chỉ chạy khi mọi thứ đã xong, không tham gia vào quá trình shutdown. Nếu handler tự viết mà không trả quyền cho uvicorn thì process có thể không bao giờ tắt → Part 6 dùng `lifespan` thay vì tự đăng ký `signal.signal`.

### Exercise 5.3: Stateless design

- Anti-pattern: `conversation_history = {}` trong RAM. Khi chạy 3 instance, mỗi instance có RAM riêng → request sau rơi vào instance khác sẽ không thấy history; restart / scale-down / deploy mới là mất toàn bộ state.
- `05-scaling-reliability/production/app.py` lưu history theo `session_id` trong **Redis** (`/chat`, `/chat/{session_id}/history`) → mọi instance đọc / ghi cùng một nơi, instance trở thành "có thể vứt bỏ" (disposable), scale ngang thoải mái.

### Exercise 5.4: Load balancing (Nginx + 3 agent)

```
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
$ for i in $(seq 1 10); do curl -s -X POST http://localhost:8080/chat -H "Content-Type: application/json" -d "{\"question\": \"Request $i\"}" | python -c "import sys,json; print('served_by:', json.load(sys.stdin).get('served_by'))"; done
served_by: instance-f4b1a1
served_by: instance-3a5009
served_by: instance-f35a85
served_by: instance-f4b1a1
served_by: instance-3a5009
served_by: instance-f35a85
served_by: instance-f4b1a1
served_by: instance-3a5009
served_by: instance-f35a85
served_by: instance-f4b1a1

$ docker compose -p k5-day14-scaling logs agent | grep -i "POST /chat" | tail -12
agent-3  | INFO:     172.20.0.6:51172 - "POST /chat HTTP/1.1" 200 OK
agent-3  | INFO:     172.20.0.6:51172 - "POST /chat HTTP/1.1" 200 OK
agent-3  | INFO:     172.20.0.6:51172 - "POST /chat HTTP/1.1" 200 OK
agent-2  | INFO:     172.20.0.6:55574 - "POST /chat HTTP/1.1" 200 OK
agent-2  | INFO:     172.20.0.6:55574 - "POST /chat HTTP/1.1" 200 OK
agent-2  | INFO:     172.20.0.6:55574 - "POST /chat HTTP/1.1" 200 OK
agent-1  | INFO:     172.20.0.6:57934 - "POST /chat HTTP/1.1" 200 OK
agent-1  | INFO:     172.20.0.6:57934 - "POST /chat HTTP/1.1" 200 OK
agent-1  | INFO:     172.20.0.6:57934 - "POST /chat HTTP/1.1" 200 OK
agent-1  | INFO:     172.20.0.6:57934 - "POST /chat HTTP/1.1" 200 OK
```

- Nginx chia request theo **round-robin**: 3 instance lần lượt f4b1a1 → 3a5009 → f35a85, 10 request chia 4 / 3 / 3.
- Mọi request tới agent đều từ cùng IP `172.20.0.6` (container nginx) — client không gọi thẳng agent; mỗi agent dùng lại 1 kết nối keepalive từ nginx (cùng source port).
- Chỉ nginx publish cổng 8080 ra host; 3 agent + redis chỉ nằm trong network `agent_net`.
- Dockerfile Part 5 cũng gặp lỗi mạng chặn HTTP khi `apt-get` → đã chuyển nguồn apt sang HTTPS như Part 2.

### Exercise 5.5: Test stateless

**Lần 1 — 3 instance:**

```
$ python test_stateless.py
Session ID: 2e7870b7-326e-4f7e-8b35-cbe5294a8b1c

Request 1: [instance-3a5009]   Q: What is Docker?
Request 2: [instance-f35a85]   Q: Why do we need containers?
Request 3: [instance-f4b1a1]   Q: What is Kubernetes?
Request 4: [instance-3a5009]   Q: How does load balancing work?
Request 5: [instance-f35a85]   Q: What is Redis used for?

Total requests: 5
Instances used: {'instance-f35a85', 'instance-3a5009', 'instance-f4b1a1'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Lần 2 — sau `docker stop k5-day14-scaling-agent-1` (còn 2 instance):**

```
$ python test_stateless.py
Session ID: 6a68a10e-f505-438d-8351-c93addc7e523

Request 1: [instance-3a5009]
Request 2: [instance-f35a85]
Request 3: [instance-3a5009]
Request 4: [instance-f35a85]
Request 5: [instance-3a5009]

Instances used: {'instance-3a5009', 'instance-f35a85'}
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

Giải thích:
- 5 câu hỏi của cùng một session được 3 instance khác nhau phục vụ, nhưng history vẫn đủ 10 message (5 user + 5 assistant) → state không nằm trong RAM của instance nào mà nằm trong Redis.
- Khi tắt 1 instance (f4b1a1), Nginx tự chuyển traffic sang 2 instance còn lại, không có request nào lỗi, history vẫn nguyên vẹn → hệ thống chịu được mất instance.
- Nếu lưu history trong dict RAM, history sẽ bị chia mảnh theo instance (mỗi instance chỉ thấy câu nó phục vụ) và mất hẳn phần của instance bị tắt.

---

## Part 6: Final Project — `check_production_ready.py`

> Chạy trong `06-lab-complete/` (WSL2, có Docker): `python check_production_ready.py`

```
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số chi tiết từ output đầy đủ: image **273 MB**, build 40 s; rate limit trả 429 sau đúng 5 request (`RATE_LIMIT_PER_MINUTE=5`) và vẫn 429 sau khi restart agent (state trong Redis); cost guard trả 402 ở request đầu tiên khi budget ≈ 0; `docker stop` thoát exit code 0 trong 0.9 s.

### Thiết kế chính

| File | Cách làm |
|---|---|
| `app/config.py` | Mọi cấu hình đọc bằng `os.getenv` (dataclass + `default_factory`); `AGENT_API_KEY` mặc định rỗng → không có key thì mọi `/ask` bị 401 |
| `app/redis_client.py` | `redis.from_url()` chỉ tạo pool, không kết nối lúc import → container khởi động được khi chưa có Redis; timeout 1–2 s để `/ready` trả 503 nhanh |
| `app/auth.py` | `APIKeyHeader("X-API-Key", auto_error=False)` → tự trả **401** cho cả thiếu và sai key; so sánh bằng `secrets.compare_digest` (chống timing attack) |
| `app/rate_limiter.py` | Sliding window 60 s bằng Redis sorted set, `ZREMRANGEBYSCORE → ZADD → ZCARD → EXPIRE` trong một transaction (atomic giữa 2 worker); vượt → **429** + `Retry-After`; key Redis là hash của API key, không lưu key thô |
| `app/cost_guard.py` | `INCRBYFLOAT` vào key `cost:YYYY-MM-DD` (UTC, TTL 2 ngày); `check_budget()` trước khi gọi LLM → **402**, `record_cost()` sau khi gọi |
| `app/main.py` | `JsonFormatter` tự gắn vào logger `agent` (`propagate=False`) → mỗi dòng là một JSON; middleware log `method/path/status/ms`; `/health` không đụng Redis, `/ready` ping Redis; `RedisError` → 503 JSON, lỗi khác → 500 JSON, không lộ stack trace; graceful shutdown bằng `lifespan` (không tự đăng ký signal handler) |
| `Dockerfile` | 2 stage: builder tạo `/opt/venv`, runtime copy venv + code; `python:3.11-slim`, user `app` non-root, `HEALTHCHECK`, `CMD sh -c "exec uvicorn ... --port ${PORT:-8000} --workers 2"` (`exec` → uvicorn là PID 1); không cần `apt-get` |
| `docker-compose.yml` | agent (build) + `redis:7-alpine` có healthcheck; `REDIS_URL=redis://redis:6379/0`, `depends_on: condition: service_healthy`, `.env` với `required: false` |

---

## AI log

| Phần | Hỏi AI (Claude Code) gì | Nhận được gì | Tự làm / tự kiểm tra |
|---|---|---|---|
| CP0 | Hướng dẫn từng bước làm bài, setup WSL2 + Docker | Lộ trình theo checkpoint, cách cài Python 3.11 bằng `uv`, bật WSL integration | Tự chạy lệnh cài đặt, xác nhận `os.name == posix`, `hello-world` chạy được |
| Part 1 | Vì sao log JSON bản production không hiện | Giải thích `basicConfig` bị vô hiệu do `config.py` log trước; gợi ý bảng so sánh | Tự chạy 2 bản, tự viết lại bảng bằng lời của mình |
| Part 2 | Lỗi `401 VG-AuthenticationRequired` khi build | Nguyên nhân mạng chặn HTTP; sửa Dockerfile chuyển apt sang HTTPS; cách đo size bằng `docker image inspect` | Tự build lại, tự đo size, tự tính % |
| Part 4 | Dựng lại 2 terminal, soạn lệnh test 401/403/200/429 | Lệnh curl + vòng lặp; chỉ ra bug `budget_remaining_usd` | Tự chạy, tự che token, đối chiếu với code |
| Part 5 | Soạn lệnh test 5.1–5.5, vì sao lần đầu gọi nhầm app | Phát hiện app Part 4 còn chiếm cổng 8000; lệnh test graceful shutdown trên 1 dòng | Tự chạy lại, đối chiếu log server/client |
| Format | Định dạng lại file `MISSION_ANSWERS.md` | Bố cục theo mẫu checklist, gom output vào code block | Tự rà lại nội dung và số liệu |
| Part 6 | Viết code cho các TODO trong `06-lab-complete/` theo hợp đồng của script chấm | Code `config/auth/redis_client/rate_limiter/cost_guard/main`, Dockerfile, compose, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml` | Đọc hiểu từng file, chạy `check_production_ready.py` bản đầy đủ → PASS 12/12, tự test tay bằng `docker compose up` |
