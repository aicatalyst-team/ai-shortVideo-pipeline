# Gateway (Java)

> **AI 中台的统一对外门面 (Java)。**
> Spring Boot 3.5 + Java 21 + WebFlux + JWT + 多模型 failover + 限流熔断 + 全链路 Trace。
>
> 作为 `myAiVideos` 主仓库的子模块，承担鉴权、限流、熔断、计量、可观测一系列横切关注点，对下游 FastAPI 编排服务做反向代理与治理。

---

## 1. 一图速览

```text
┌────────────────────────────────────────────────────────────────┐
│ Client / Bot / CLI                                              │
└────────────────────────────────┬──────────────────────────────┘
                                 │ HTTPS + JWT + X-Trace-Id
┌────────────────────────────────▼──────────────────────────────┐
│  gateway (本子目录)                                             │
│                                                                 │
│   ┌─ TraceIdFilter ────── 全链路 X-Trace-Id 透传                │
│   ├─ JwtAuthFilter ────── HS256 JWT，注入 userId / tenantId    │
│   ├─ AuditLogFilter ───── 每请求 method/path/status/latency    │
│   ├─ RateLimitFilter ──── 用户级 + 全局 双层令牌桶              │
│   ├─ LlmRouter ────────── DeepSeek → Qwen → GLM failover       │
│   ├─ KlingCircuitBreaker ─ 5xx >30% 熔断 60s + 降级             │
│   └─ UsageMeterAspect ──── AOP 切面计量 → llm_calls 表          │
└────────────────────────────────┬──────────────────────────────┘
                                 │ WebClient + retry + jitter + TraceId 透传
┌────────────────────────────────▼──────────────────────────────┐
│  Python FastAPI orchestrator (主仓 layers/)                    │
│  L1 选题 · L2 创意 · L3 视觉 · L4 音频 · L5 后期 · L6 分发 · L7 优化│
└────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心能力

| 能力 | 实现 | 测试 |
|------|------|------|
| **JWT 鉴权 (HS256)** | [`JwtService.java`](src/main/java/com/miniapp/gateway/auth/JwtService.java) · 密钥强制 ≥ 32 bytes，过期/无效自动拒绝 | ✅ |
| **JWT WebFilter** | [`JwtAuthFilter.java`](src/main/java/com/miniapp/gateway/auth/JwtAuthFilter.java) · Bearer 解析 → 注入 userId/tenantId 到 exchange + MDC，白名单直通 | ✅ |
| **全链路 TraceId** | [`TraceIdFilter.java`](src/main/java/com/miniapp/gateway/trace/TraceIdFilter.java) · 入参透传 / 缺失生成 UUID32 / 响应头回显 / MDC 注入 | ✅ |
| **审计日志** | [`AuditLogFilter.java`](src/main/java/com/miniapp/gateway/audit/AuditLogFilter.java) · method/path/status/latency/user/tenant/trace 七字段，JSON 出 stdout | — |
| **WebClient 容错** | [`WebClientConfig.java`](src/main/java/com/miniapp/gateway/config/WebClientConfig.java) · 超时 + 5xx 指数退避重试 + jitter + 4xx 不重试 + TraceId 透传 | ✅ |
| **多模型 failover** | [`LlmRouter.java`](src/main/java/com/miniapp/gateway/llm/LlmRouter.java) · DeepSeek → Qwen → GLM，429/5xx/timeout 切换 | ✅ |
| **熔断降级** | Resilience4j · CLOSED/HALF_OPEN/OPEN 三态 + 事件监听 | ✅ |
| **限流** | [`RateLimitFilter.java`](src/main/java/com/miniapp/gateway/ratelimit/RateLimitFilter.java) · 用户级 + 全局令牌桶 + Prometheus 指标 | ✅ |
| **计量计费** | [`UsageMeterAspect.java`](src/main/java/com/miniapp/gateway/usage/UsageMeterAspect.java) · AOP 切面 → `llm_calls` + `billing_daily` 聚合 + Caffeine 缓存 | ✅ |
| **SSE 进度流** | [`JobStreamController.java`](src/main/java/com/miniapp/gateway/sse/JobStreamController.java) · 长任务进度推送 + 活跃连接数指标 | ✅ |
| **帧上传** | [`FrameController.java`](src/main/java/com/miniapp/gateway/frame/FrameController.java) · MinIO + 异步落库 | ✅ |

---

## 3. 技术栈

| 层 | 选型 | 选型理由 |
|----|------|---------|
| **运行时** | Java 21 (LTS) | virtual threads 支持 |
| **框架** | Spring Boot 3.5 + WebFlux | 响应式，原生支持 SSE 长连接 |
| **鉴权** | jjwt 0.12.6 HS256 | MVP 自签 token，生产可平滑切 RS256+KMS |
| **HTTP 客户端** | Reactor Netty + WebClient | 异步非阻塞 + 重试/超时 |
| **熔断 / 限流** | Resilience4j + Bucket4j | 业界标准、可观测性好 |
| **缓存** | Caffeine | 本地高性能；可扩 Redis 分布式 |
| **指标** | Prometheus + Actuator | 与运维体系无缝对接 |
| **构建** | Maven 3.9 | parent POM 复用 Spring Boot 依赖管理 |
| **容器** | Multi-stage Dockerfile | maven:3.9-eclipse-temurin-21 → eclipse-temurin:21-jre-alpine |
| **测试** | JUnit 5 + AssertJ + Mockito + MockWebServer | 单元 / 集成 / 压测 (k6) 全覆盖 |

---

## 4. API 路由

| 方法 | 路径 | 鉴权 | 透传 / 行为 |
|------|------|-----|--------|
| `GET` | `/actuator/health` | 公开 | 健康检查 |
| `GET` | `/actuator/info` | 公开 | 服务信息 |
| `GET` | `/actuator/metrics` | JWT | Spring 指标 |
| `GET` | `/actuator/prometheus` | 公开 (生产建议走内网) | Prometheus 抓取 |
| `POST` | `/internal/llm/chat` | JWT | LLM 多模型路由 |
| `GET` | `/api/v1/storyboards/{planId}` | JWT | 透传到 Python `/api/v1/storyboards/{planId}` |
| `POST` | `/api/v1/clips/{id}/regenerate` | JWT + 限流 | 入 Python ARQ 队列 |
| `GET` | `/api/v1/jobs/{job_id}/stream` | JWT | SSE 进度推送 |
| `POST` | `/api/v1/frames/upload` | JWT | MinIO 帧上传 |
| `GET` | `/api/v1/usage/today` | JWT | 当日 token / 成本累计 |

---

## 5. 快速验证

### 5.1 启动（推荐：通过主仓 docker-compose）

```bash
# 在主仓根目录
docker compose up -d --build gateway
```

### 5.2 独立启动

```bash
cd gateway
docker build -t ai-platform-gateway:latest .
docker run -p 8080:8080 \
  -e GATEWAY_AUTH_JWT_SECRET="$(openssl rand -base64 32)" \
  -e GATEWAY_UPSTREAM_PYTHON_BASE_URL="http://host.docker.internal:8000" \
  ai-platform-gateway:latest
```

### 5.3 健康检查 + TraceId 双向

```bash
$ curl -si http://localhost:8080/actuator/health
HTTP/1.1 200 OK
X-Trace-Id: 6f376a968ff34c5aa6bd64879cfd947b   ← 自动生成
{"status":"UP"}

$ curl -si -H "X-Trace-Id: my-trace-001" http://localhost:8080/actuator/health
HTTP/1.1 200 OK
X-Trace-Id: my-trace-001                       ← 透传客户端值
```

### 5.4 JWT 鉴权

```bash
# 无 token → 401
$ curl -si http://localhost:8080/api/v1/storyboards/X
HTTP/1.1 401 Unauthorized
{"error":"unauthorized","message":"missing or malformed Authorization header","trace_id":"..."}

# 用 Python 签 token
$ TOKEN=$(python -c "import jwt,time; print(jwt.encode({'sub':'u1','tenant_id':'t1','iat':int(time.time()),'exp':int(time.time())+3600}, 'your-32+-bytes-secret', algorithm='HS256'))")

$ curl -si -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/storyboards/X
HTTP/1.1 404 Not Found        ← 透传到 Python，Python 返回 404
```

---

## 6. 工程化要点

### WebClient 容错

```java
// 5xx 自动重试，指数退避 + jitter 防雪崩
.retryWhen(
    Retry.backoff(retryMaxAttempts, Duration.ofMillis(retryInitialBackoffMs))
        .jitter(0.5)
        .filter(ex -> ex instanceof WebClientResponseException wre
                && wre.getStatusCode().is5xxServerError())
)
```

- **超时分层**：connect 5s + response 30s（应用层可调）
- **退避 + jitter**：100ms → 200ms（±50% 随机扰动），防"雪崩重试同步打满"
- **4xx 不重试**：业务错误重试无意义
- **TraceId 自动透传**：MDC 里的 traceId 写到下游请求头，可观测系统能串完整链路

### JWT 鉴权

- **白名单优先判定**：`/actuator/**` 等公开端点直通
- **解析失败 / 过期**：返回结构化 401 JSON，含 `trace_id` 方便排查
- **principal 注入**：用 `exchange.getAttributes()` 写入 userId / tenantId
- **MDC 标记**：tenantId 进入 logback，每行日志带 `[tenant=...]` 前缀

### Filter 执行顺序

```
HIGHEST_PRECEDENCE      → TraceIdFilter      ← 必须最先，401 也要带 trace_id
HIGHEST_PRECEDENCE + 10 → JwtAuthFilter      ← 鉴权
... 业务 Controller ...
LOWEST_PRECEDENCE       → AuditLogFilter     ← 最后，能拿到最终 status
```

---

## 7. 测试

```bash
# 单元 + 集成
mvn test

# 限流压测（需要 k6）
k6 run tests/ratelimit_k6.js
```

---

## 8. 配置

主要环境变量（前缀 `GATEWAY_`，详细见 `src/main/resources/application.yml`）：

| 变量 | 用途 | 必填 |
|---|---|---|
| `GATEWAY_AUTH_JWT_SECRET` | JWT 签名密钥（≥ 32 字节） | ✅ |
| `GATEWAY_UPSTREAM_PYTHON_BASE_URL` | FastAPI orchestrator 地址 | ✅ |
| `GATEWAY_STORAGE_MINIO_*` | MinIO 连接信息 | 用帧上传时 |
| `DEEPSEEK_API_KEY` / `QWEN_API_KEY` / `GLM_API_KEY` | LLM 提供商密钥 | 用 LLM 调用时 |
| `KLING_ACCESS_KEY` / `KLING_SECRET_KEY` | 视频生成 | 用 Kling 时 |

---

## 9. 关联文档

- 主仓 [`architecture.md`](../architecture.md) — 整体架构与数据流
- 主仓 [`docs/启动-停止脚本.md`](../docs/启动-停止脚本.md) — 跨平台启停 / 日志 / 排障
- `docs/sse_deployment.md` — SSE 部署注意事项（Nginx 反向代理配置）

---

## License

MIT — 详见主仓 [`LICENSE`](../LICENSE)。
