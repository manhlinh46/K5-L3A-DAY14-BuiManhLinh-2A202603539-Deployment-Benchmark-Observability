# Deployment Information

## Public URL

https://agent-production-707915a9.up.railway.app

## Platform

**Railway**, project `lab14`, environment `production`, region `iad`:

| Service | Nguồn | Vai trò |
|---|---|---|
| `agent` | `06-lab-complete/` (Dockerfile multi-stage, `railway.toml`) | FastAPI agent Part 6, uvicorn 2 workers |
| `Redis` | Railway Database (`redis:8.2`, volume `/data`) | State của rate limiter + cost guard |

Agent kết nối Redis qua private network `redis.railway.internal:6379` (biến tham chiếu `${{Redis.REDIS_URL}}`); Redis không mở ra Internet.

## Test Commands

Đặt biến trước khi chạy (key **không** ghi trong repo, lưu ngoài repo ở `~/.day14_cloud_key`):

```bash
BASE=https://agent-production-707915a9.up.railway.app
AGENT_API_KEY=$(cat ~/.day14_cloud_key)
```

### Health Check

```bash
curl $BASE/health
# {"status":"ok","environment":"production"}
```

### Readiness (Redis)

```bash
curl $BASE/ready
# {"ready":true,"redis":"ok"}
```

### API Test — không có key → 401

```bash
curl -i -X POST $BASE/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
# HTTP/1.1 401 Unauthorized
```

### API Test — có key → 200

```bash
curl -X POST $BASE/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
# {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"input_tokens":4,"output_tokens":21,"cost_usd":1.32e-05}}
```

### Tự kiểm CP6 (chỉ in mã HTTP)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả (chạy 3 vòng liên tiếp, 2026-11-25):

```
round 1: health=200 ready=200 nokey=401 key=200
round 2: health=200 ready=200 nokey=401 key=200
round 3: health=200 ready=200 nokey=401 key=200
```

`python check_production_ready.py --public-url https://agent-production-707915a9.up.railway.app`:

```
✅ Public URL: GET https://agent-production-707915a9.up.railway.app/health → 200
```

## Environment Variables Set

Đặt trên Railway (service `agent` → Variables / `railway variables --set`), **không** ghi trong code:

| Biến | Giá trị |
|---|---|
| `AGENT_API_KEY` | secret ngẫu nhiên 32 ký tự (`secrets.token_urlsafe(24)`), chỉ lưu trên Railway |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` (tham chiếu tới service Redis) |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `PORT` | Railway tự cấp; app nghe theo `${PORT:-8000}` trong CMD của Dockerfile |

## Deploy steps (Railway CLI, chạy trong WSL)

```bash
railway login --browserless
cd 06-lab-complete
railway init                       # project lab14
railway add --database redis
railway add --service agent        # service riêng cho agent
railway service agent              # link thư mục với service agent
railway variables --set "AGENT_API_KEY=..." --set 'REDIS_URL=${{Redis.REDIS_URL}}' \
                  --set "ENVIRONMENT=production" --set "RATE_LIMIT_PER_MINUTE=10" --set "DAILY_BUDGET_USD=1.0"
railway up --detach
railway domain
```

### Sự cố và cách xử lý

1. **`railway.exe` bị Windows Application Control chặn** → dùng Railway CLI bản Linux trong WSL.
2. **`railway add --database redis` tự link thư mục với Redis** → `railway up` lần đầu deploy nhầm code lên service Redis (build fail, Redis vẫn chạy image cũ) → tạo service `agent` riêng và `railway service agent` trước khi deploy.
3. **Build fail: `header key "exclude-patterns" contains value with non-printable ASCII characters`** — BuildKit từ xa của Railway gửi pattern của `.dockerignore` qua header gRPC, chỉ chấp nhận ASCII. Các file ignore có comment tiếng Việt có dấu / ký tự kẻ khung. Đã chuyển comment sang ASCII; vì CLI vẫn upload theo gốc repo git, bản deploy cuối được upload từ một thư mục sạch chỉ gồm `Dockerfile`, `.dockerignore`, `requirements.txt`, `railway.toml`, `app/`, `utils/`:
   ```bash
   railway up ~/day14-deploy --path-as-root --service agent --detach
   ```

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
