# Operations Manual

> Covers: Feishu bot integration → end-to-end testing → daily maintenance.
> Companion docs: [`启动-停止脚本.md`](启动-停止脚本.md) (start/stop/logs/troubleshooting), [`../architecture.md`](../architecture.md) (architecture).

**English** | [简体中文](操作使用手册.md)

---

## Table of Contents

- [1. Feishu Bot Integration](#1-feishu-bot-integration)
- [2. Testing](#2-testing)
- [3. Daily Maintenance](#3-daily-maintenance)
- [4. Security](#4-security)
- [5. Upgrade Workflow](#5-upgrade-workflow)

---

## 1. Feishu Bot Integration

> The system receives creation commands through a Feishu custom app and delivers finished videos back to the Feishu chat. The full setup is below.

### 1.1 Create a Feishu Custom App

1. Sign in to [Feishu Open Platform](https://open.feishu.cn) → **Developer Console** → **Create Custom App for Internal Use**
2. Fill app name (e.g. `myAiVideos Bot`), description, icon
3. After creation, take note of:
   - **App ID** (`cli_xxxxxxx`)
   - **App Secret** (`xxxxxxxx...`)

### 1.2 Add Bot Capability

App detail page → **Add Features** → choose **Bot**.

### 1.3 Configure Event Subscription (Webhook)

App detail page → **Event Subscription** → **Request URL**.

Enter your public service URL with path `/webhook/feishu`:

```
https://your-domain.com/webhook/feishu
```

> **Local development**: Feishu **requires a public URL**; `localhost` will not work. Use a tunneling tool like [cpolar](https://www.cpolar.com/), [ngrok](https://ngrok.com/), or [frp](https://github.com/fatedier/frp):
> ```bash
> # cpolar example
> cpolar http 8000
> # Get https://xxxx.cpolar.io and paste it into Feishu console
> ```

**URL verification flow**: Feishu will POST `{"type":"url_verification","challenge":"xxx"}` to the URL; the server must echo back the `challenge`. Our `api/webhooks.py` already implements this:

```python
if body.get("type") == "url_verification":
    return {"challenge": body.get("challenge", "")}
```

Click **Save**. The console showing "verified successfully" means configuration is done.

### 1.4 Subscribe to Message Events

**Event Subscription** → **Add Events** → tick:

| Event | Purpose |
|---|---|
| `im.message.receive_v1` | Receive user messages (required) |
| `im.message.message_read_v1` | Read receipts (optional) |

### 1.5 Configure Permissions

**Permissions** → request the following:

| Permission | Purpose |
|---|---|
| `im:message` | Receive / send messages |
| `im:message.group_at_msg` | Messages @-ing the bot in groups |
| `im:message.p2p_msg` | Direct messages |
| `im:resource` | Upload images / videos / files (required for delivering finished videos) |
| `im:chat` | Read group info (optional) |
| `contact:user.id:readonly` | Resolve user IDs (optional) |

### 1.6 Publish the App

**Version & Release** → create version → submit for approval → wait for admin approval.

### 1.7 Add the Bot to a Chat

- **Group**: Group settings → Add bot → choose the published app
- **DM**: Search the app name in Feishu → start a direct chat

### 1.8 Configure `.env`

```bash
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxx
MY_FEISHU_USER_ID=ou_xxxxxxxxxxxxxxxx   # Optional, restrict replies to a specific user
```

You can get `MY_FEISHU_USER_ID` by @mentioning the bot in a group with "my id", or via the Feishu admin console → Contacts.

### 1.9 Verify the Integration

Restart the orchestrator so the new `.env` is loaded:

```bash
docker compose up -d --force-recreate orchestrator worker
```

Send `hello` to the bot in Feishu. If you receive a command help reply, the integration is working.

Container logs should show:

```
[Webhook] msg_type=text cid=oc_xxx content_keys=['text']
[Webhook] text=hello
[Feishu] sent command help: ...
```

### 1.10 Available Commands

| Command | Behavior |
|---|---|
| `commentary <topic>` | Generate hot-news commentary video |
| `explainer <topic>` | Generate knowledge explainer video |
| `story <topic>` | Generate emotional story video |
| `curiosity <topic>` | Generate strange-fact video |
| `opinion <topic>` | Generate opinion-piece video |
| `trending` | List current hot topics |
| `batch <N>` | Generate N videos in batch |
| `character <name>` | Switch character IP |
| `style <template>` | Switch style template |
| `confirm <plan_no>` | Confirm a script proposal to proceed |
| `continue` | Continue to the next segment after the current one finishes |
| `help` | Show all commands |

> The default Chinese command set is `解说`/`科普`/`故事`/`奇闻`/`观点`. See `config/skills/` and `layers/L2_creative/creative_skills.py` to customize.

---

## 2. Testing

### 2.1 Test Categories

| Type | Scope | Docker required | Costs money |
|---|---|---|---|
| Python unit | Module-local logic, LLM mocked | ❌ | ❌ |
| Python integration | Real DB + Redis | ✅ | ❌ |
| Java unit | Gateway filter / service / controller | ❌ | ❌ |
| Java load (k6) | Rate limit / circuit breaker / failover | ✅ | ❌ |
| End-to-end | Full pipeline with real AI calls | ✅ | ✅ (small) |

### 2.2 Python Tests

```bash
# Full regression
docker compose exec -T orchestrator pytest tests/ -q

# Run a specific file
docker compose exec -T orchestrator pytest tests/test_av_sync_rescue.py -v

# Run a specific case
docker compose exec -T orchestrator pytest tests/test_clip_consistency.py::test_check_consistency_returns_full_result_when_passed -v

# Show print output
docker compose exec -T orchestrator pytest tests/ -v -s

# Coverage
docker compose exec -T orchestrator pytest tests/ --cov=layers --cov=core --cov=api
```

Test conventions:

- Mock all external APIs (LLM, TTS, Kling) in unit tests
- Use `monkeypatch` to inject fake responses; see `tests/test_clip_consistency.py`
- Use `@pytest.mark.asyncio` for async cases

### 2.3 Java Tests

```bash
cd gateway

# Unit + integration
mvn test

# Specific class
mvn test -Dtest=JwtServiceTest

# Build without tests
mvn package -DskipTests

# View reports
ls target/surefire-reports/
```

### 2.4 Load Testing (k6)

Install [k6](https://k6.io/docs/get-started/installation/) on the host:

```bash
# Rate-limit load test
k6 run gateway/tests/ratelimit_k6.js

# Custom VUs and duration
k6 run --vus 50 --duration 30s gateway/tests/ratelimit_k6.js
```

Expected:

- Under normal load: mostly 200
- Over rate limit: 429 responses appear
- Latency stays bounded (no runaway growth)

### 2.5 Manual API Tests

#### Health checks

```bash
curl -s http://localhost:8000/health | jq
curl -s http://localhost:8080/actuator/health | jq
```

#### Simulate a Feishu message (test the main flow without real Feishu)

```bash
curl -X POST http://localhost:8000/webhook/feishu \
  -H "Content-Type: application/json" \
  -d '{
    "type": "event_callback",
    "event": {
      "message": {
        "message_type": "text",
        "chat_id": "test_chat_001",
        "message_id": "test_msg_001",
        "content": "{\"text\":\"explainer what is an LLM\"}"
      }
    }
  }'
```

#### Cross-language trace propagation

```bash
# Send with a custom trace_id; Python should see the same value
curl -si -H "X-Trace-Id: my-test-trace-001" \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/v1/storyboards/PLAN_ID

# Grep both sides
grep "trace=my-test-trace-001" data/logs/*.log
docker compose logs gateway orchestrator | grep "my-test-trace-001"
```

#### Trigger rate limiting

```bash
# Burst the same endpoint with ab or wrk
ab -n 100 -c 20 -H "Authorization: Bearer $TOKEN" \
   http://localhost:8080/api/v1/clips/X/regenerate

# Expect HTTP 429 + Retry-After for some requests
```

### 2.6 Frontend Mock Mode

```bash
cd sl-vue

# Linux/Mac
VITE_USE_MOCK=true npm run dev

# Windows PowerShell
$env:VITE_USE_MOCK = "true"; npm run dev
```

Visit <http://localhost:5173/canvas/MOCK001> to view fixture data without hitting the backend.

### 2.7 End-to-End Smoke Test (real generation)

> ⚠️ Hits real AI services and costs a small amount (~¥0.3-2 / video).

1. Make sure all API keys in `.env` are filled
2. Start the full stack: `docker compose up -d`
3. Send `explainer what is an LLM` in Feishu
4. Follow progress: `tail -f data/logs/orchestrator.log`
5. Wait ~5-10 minutes for the finished video to arrive in Feishu

Expected log milestones:

```
[Webhook] text=explainer what is an LLM
[creative chain] theme=... style=knowledge_explainer
[review chain] GLM review
[evaluator] start
[Feishu] sent video plan
[t2i] submit model=kling-v1-5
[Kling] submit model=kling-v2-5-turbo
[TTS] done
[av_sync] report: ✅ video ... / voiceover ...
[Feishu video] upload ...
```

---

## 3. Daily Maintenance

### 3.1 Health Check (daily)

```bash
# Three endpoints in a single chain
curl -fs http://localhost:8000/health \
  && curl -fs http://localhost:8080/actuator/health \
  && docker compose ps --format json | jq -r '.[] | "\(.Name): \(.State)"'
```

Or via cron:

```cron
# Probe every 5 minutes, email on failure
*/5 * * * * curl -fs http://localhost:8000/health > /dev/null || echo "orchestrator down" | mail -s "ALERT" you@example.com
```

### 3.2 Log Monitoring

```bash
# Errors in the last 10 minutes
docker compose logs --since 10m orchestrator gateway worker \
  | grep -E "ERROR|Traceback|Exception" | tail -30

# Archive size (disk safety)
du -sh data/logs/

# Full trail for one request
grep "trace=b09df48c0b714426" data/logs/*.log
```

**Alert keywords** (recommended to wire into ELK / Grafana Loki):

- `ERROR`, `Traceback`, `CircuitBreaker.*OPEN`
- `AVDriftTooLargeError`, `av_rescue.*failed`
- `Langfuse.*disabled`, `anchors.*extract failed`

### 3.3 Database Maintenance

#### Backup

```bash
# One-off
docker compose exec -T postgres pg_dump -U postgres myaivideos | gzip > backup-$(date +%F).sql.gz

# Cron (daily 3am, keep 14 days)
0 3 * * * docker compose exec -T postgres pg_dump -U postgres myaivideos | gzip > /backup/myaivideos-$(date +\%F).sql.gz && find /backup -name "myaivideos-*.sql.gz" -mtime +14 -delete
```

#### Restore

```bash
gunzip -c backup-2026-05-30.sql.gz | docker compose exec -T postgres psql -U postgres myaivideos
```

#### Stats + optimization

```bash
# Enter psql
docker compose exec -T postgres psql -U postgres -d myaivideos

# Largest tables
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
  FROM pg_catalog.pg_statio_user_tables
 ORDER BY pg_total_relation_size(relid) DESC LIMIT 10;

# Manual vacuum/analyze (Postgres autovacuums by default)
VACUUM ANALYZE;

# Slow queries (requires pg_stat_statements)
SELECT query, calls, total_exec_time, mean_exec_time
  FROM pg_stat_statements
 ORDER BY mean_exec_time DESC LIMIT 10;
```

### 3.4 Redis Monitoring

```bash
# Queue backlog
docker compose exec -T redis redis-cli LLEN arq:queue

# Memory
docker compose exec -T redis redis-cli INFO memory | grep used_memory_human

# Slow log
docker compose exec -T redis redis-cli SLOWLOG GET 10
```

### 3.5 Container / Image Cleanup

```bash
# Disk
df -h
docker system df

# Remove unused images/containers/networks
docker system prune -af

# Clean build cache only
docker builder prune -af

# Old generated videos (> 30 days)
find output -name "*.mp4" -mtime +30 -delete
```

### 3.6 Cost Monitoring

```bash
# Per-tenant per-model cost today
docker compose exec -T postgres psql -U postgres -d myaivideos -c "
SELECT tenant_id, model, total_calls, total_cost_cny, fallback_calls
  FROM billing_daily
 WHERE dt = CURRENT_DATE
 ORDER BY total_cost_cny DESC;
"

# Via gateway API
curl -s http://localhost:8080/api/v1/usage/today \
  -H "Authorization: Bearer $TOKEN" | jq

# Cost-spike alert (recommended Prometheus rule)
# e.g., single tenant exceeds ¥50 / day → alert
```

### 3.7 Langfuse Trace Check (if enabled)

- Sign in to [cloud.langfuse.com](https://cloud.langfuse.com) → Traces
- Filter by trace_id / session_id / tag
- Inspect input/output/duration/cost per call
- Look for anomalies (P99 latency, errors, failover events)

---

## 4. Security

### 4.1 JWT Secret Rotation (every 90 days)

```bash
# 1. Generate a new secret
NEW=$(openssl rand -base64 32)

# 2. Write into .env
sed -i "s|^GATEWAY_AUTH_JWT_SECRET=.*|GATEWAY_AUTH_JWT_SECRET=${NEW}|" .env

# 3. Restart the gateway
docker compose up -d --force-recreate gateway

# 4. Notify clients to re-sign tokens; old tokens are immediately invalid
```

### 4.2 AI Provider API Key Rotation

After rotating in each provider's console, update `.env`, then:

```bash
docker compose up -d --force-recreate orchestrator worker gateway
```

### 4.3 Files That Must Not Enter Git

- `.env` (all secrets)
- `data/logs/` (contains traces with sensitive data)
- `output/` (generated content)
- `data/hf_cache/` (model caches)
- Any document containing tokens / API keys

### 4.4 Port Exposure Principles

| Port | Production guidance |
|---|---|
| 80 / 443 | Public (frontend + necessary APIs only) |
| 8080 (gateway) | **NOT directly public** — front with a reverse proxy |
| 8000 (FastAPI) | **NOT public** — internal network only |
| 5432 / 6379 / 9000 / 9001 | **NOT public** — bind to 127.0.0.1 or internal IP |

### 4.5 Periodic Security Scanning

```bash
# Scan git history for leaks
gitleaks detect --source . --verbose

# Scan images for vulnerabilities
trivy image ai-platform-app:latest
trivy image ai-platform-gateway:latest
```

---

## 5. Upgrade Workflow

### 5.1 Code Upgrade (minor)

```bash
# 1. Pull
git pull

# 2. Decide whether to rebuild / migrate
git log --oneline -10

# 3. Python changes → rebuild
docker compose build orchestrator

# 4. Java changes → rebuild
docker compose build gateway

# 5. Recreate containers with new images
docker compose up -d --force-recreate --no-build orchestrator worker gateway

# 6. Run migrations if schema changed
docker compose exec -T orchestrator alembic upgrade head

# 7. Verify
git rev-parse HEAD                              # Should match remote
docker images ai-platform-app --format '{{.CreatedAt}}'    # Should be recent
curl -s http://localhost:8000/health
curl -s http://localhost:8080/actuator/health
```

### 5.2 Rollback

```bash
# Python
cd /path/to/repo
git log --oneline -10
git checkout <old-SHA>
docker compose build orchestrator
docker compose up -d --force-recreate --no-build orchestrator worker

# DB rollback is risky (most migrations are not reversible):
docker compose exec -T orchestrator alembic stamp <old-revision>
```

### 5.3 Database Schema Change

```bash
# 1. Author the new migration
docker compose exec -T orchestrator alembic revision -m "add foo column"

# 2. Edit the generated versions/xxx_add_foo_column.py

# 3. Validate locally
docker compose exec -T orchestrator alembic upgrade head
docker compose exec -T orchestrator alembic downgrade -1   # Reversible?
docker compose exec -T orchestrator alembic upgrade head

# 4. Run tests
docker compose exec -T orchestrator pytest tests/ -q

# 5. Commit & deploy
git add db/migrations/versions/
git commit -m "feat: add foo column"
```

---

## 6. Related Docs

- [`启动-停止脚本.md`](启动-停止脚本.md) — Cross-platform start / stop / log / troubleshooting
- [`../architecture.md`](../architecture.md) — Overall architecture
- [`../gateway/README.md`](../gateway/README.md) — Java gateway details
- [`../README.md`](../README.md) — Project entry (English)
- [`../README.zh-CN.md`](../README.zh-CN.md) — Project entry (Chinese)

---

## Maintenance Notes

- New Feishu commands → also update §1.10 of this doc
- New test categories → update §2.1
- New maintenance items → update §3
- New security requirements → update §4
