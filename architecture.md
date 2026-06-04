# Architecture

> 本文档描述 `myAiVideos` 的整体架构、运行时拓扑、数据流，以及核心治理机制。模块级细节见 `docs/` 下的各 `module_*.md`。

## 1. 概述

`myAiVideos` 是一个自动化短视频生产管线。一条用户指令进入后，系统按七层流水线依次完成：

| 层 | 职责 | 主要技术 |
|---|---|---|
| L1 选题 | 抓取与排序热搜话题 | HTTP 抓取、可做性评估 |
| L2 创意 | 脚本生成、Prompt 编排、一致性锚定 | DeepSeek LLM、Skill 模板 |
| L3 视觉 | 文生图、图生视频、CLIP 一致性门控 | Kling、Chinese-CLIP |
| L4 音频 | TTS、混音、时长规划 | 火山 / MiniMax TTS、Whisper |
| L5 后期 | 音画同步检测与救援、字幕、封面 | FFmpeg |
| L6 分发 | 成片回传 | 飞书 / Webhook |
| L7 优化 | 质量评分、数据回流 | LLM 评估 |

每层独立部署、可单独替换；层间通过明确定义的输入输出契约（Pydantic schema）通信。

## 2. 运行时拓扑

```
                        +-----------+
                        |  Client   |
                        +-----+-----+
                              |
                       HTTP / SSE / WebSocket
                              |
                      +-------v--------+
                      |  Java Gateway  |
                      |  (Spring Boot) |
                      +-------+--------+
                              |
        +---------------------+----------------------+
        |                                            |
        v                                            v
+----------------+                          +------------------+
| FastAPI         |  enqueue jobs           | External AI APIs |
| orchestrator    +------------------+      | (DeepSeek/Kling/ |
| (uvicorn)       |                  |      |  GLM/TTS)        |
+--------+--------+                  |      +------------------+
         |                           |
         | async / sync calls        v
         |                  +-----------------+
         |                  | ARQ Worker      |
         |                  | (async jobs)    |
         |                  +-+---------------+
         |                    |
   +-----v------+      +------v-----+    +---------+
   | PostgreSQL |      |    Redis   |    |  MinIO  |
   | (asyncpg)  |      |  (queue +  |    |(assets) |
   +------------+      |   cache)   |    +---------+
                       +------------+
```

### 容器组成

| 容器 | 用途 |
|---|---|
| `postgres` | 业务主库 |
| `redis` | ARQ 任务队列 + 会话缓存 |
| `orchestrator` | FastAPI 主服务，监听 8000 |
| `worker` | ARQ worker，处理长耗时任务 |
| `minio` | 对象存储（封面、片段） |
| `gateway` | Java 网关，监听 8080 |

## 3. 主流程数据流

```
1.  外部触发（飞书 / HTTP）
        │
2.  api/webhooks.py / api/storyboard_api.py 解析意图
        │
3.  L1_trending: 选题或直接接受用户输入
        │
4.  L2_creative.chains: 生成脚本方案 + Prompt Director 编排
        │
5.  人工或自动确认方案
        │
6.  L2_creative.prompt_director.anchors: 抽取主体视觉锚点
        │
7.  L3_visual.text_to_image: 文生图 + CLIP 一致性评分
        │
8.  L3_visual.image_to_video: 图生视频
        │
9.  L4_audio.voiceover: TTS 配音 + visual_planner 时长规划
        │
10. L5_postprod.av_sync: 音画漂移检测
        │ (drift > 1.2s)
11. L5_postprod.av_sync_rescue: 自动救援（变速 / pad / 旁白重写）
        │
12. L5_postprod.mixer: 字幕、封面、混音、压缩
        │
13. L7_optimization.quality_gate: 质量评分
        │
14. L6_distribution: 成片回传客户端
        │
15. 数据回流到 video_records / video_metrics 供后续推荐
```

## 4. 核心治理机制

### 4.1 中台护城河（Java Gateway）

- **JWT 鉴权**：所有外部请求经网关 `TokenService` 验证
- **LLM Router**：DeepSeek → Qwen → GLM 三模型 failover，区分业务错误（4xx）和上游故障（5xx / timeout）
- **熔断**：Resilience4j 三态（CLOSED / OPEN / HALF_OPEN）保护下游
- **限流**：网关层抵御突发流量
- **计量**：AOP 切面统计 token / 成本，按租户聚合到 `billing_daily`
- **TraceId 注入**：MDC 注入并透传至下游 Python 服务

### 4.2 AI 质量门控（编排层）

| 阶段 | 机制 | 文件 |
|---|---|---|
| 脚本生成 | LLM 输出 JSON schema 校验、失败自动重稿 | `layers/L2_creative/chains.py` |
| 多段一致性 | Prompt 锚定：抽取首段视觉锚点强制注入后续段 | `layers/L2_creative/prompt_director/anchors.py` |
| 关键帧一致性 | Chinese-CLIP 评分 + 阈值告警 | `layers/L3_visual/clip_consistency.py` |
| 视频文字伪影 | GLM-4V 抽样检测画面中是否含可读字幕 | `layers/L3_visual/image_to_video.py` |
| 音画同步 | 漂移三档分类（pass / soft_fix / hard_fail） | `layers/L5_postprod/av_sync.py` |
| 音画自动救援 | 4 档策略链（atempo / pad / 旁白重写 / hard_fail） | `layers/L5_postprod/av_sync_rescue.py` |

### 4.3 可观测

- **trace_id 透传**：HTTP Header `X-Trace-Id` → Java MDC → Python `contextvars`
- **结构化日志**：`core/logging_setup.py` 统一 INFO 级别 + 滚动归档（`/app/data/logs/*.log`，10×50MB）
- **Langfuse 上报**：`@observe` 装饰器自动埋点 LLM 调用，输入/输出/耗时/成本可视化

### 4.4 异步任务

- ARQ + Redis 队列承载所有长耗时调用（视频生成 5-10 min）
- HTTP 请求立即返回任务 ID，前端通过 SSE 订阅进度
- `core/scheduler.py` 定义任务函数与定时任务（cron）

## 5. 数据持久化

主要表：

| 表 | 用途 |
|---|---|
| `plans` | 脚本方案、评估结果 |
| `storyboards` | 分镜板与锚点 |
| `clips` | 段级数据（image_prompt / kling_prompt / 状态 / 评分） |
| `frame_assets` | 关键帧 / 尾帧资产引用 |
| `generation_sessions` | 端到端会话与逐段审核事件 |
| `jobs` | ARQ 异步任务记录 |
| `llm_calls` | 每次 LLM 调用的请求 / 响应 / failover 链路 |
| `billing_daily` | 按租户 / 日聚合 token / 成本 |
| `trending_topics` | 热搜话题缓存 |
| `video_records` / `video_metrics` | 成片归档与数据回流 |

完整 schema 见 `db/models.py` 与 `db/migrations/versions/`。

## 6. 配置体系

| 类别 | 位置 |
|---|---|
| 风格模板 | `config/style_templates/*.yaml` |
| 角色 IP | `config/characters.yaml` + `config/character_refs/*.png` |
| 场景预设 | `config/environments.yaml` |
| Skill | `config/skills/*.yaml` |
| 应用配置 | `config/settings.py`（Pydantic Settings，从 `.env` 加载） |

## 7. 部署原则

- **代码变更必须重建镜像**：`docker compose build` 后再 `up -d --force-recreate --no-build`
- **数据库变更必须迁移**：`alembic upgrade head`，全新库可 `stamp head`
- **配置变更可热生效**：`.env` 修改后只需重建容器
- **不要使用 `docker compose restart`** 部署新代码 —— 它不重 build

## 8. 扩展点

| 想做 | 入口 |
|---|---|
| 接入新的 LLM 模型 | `integrations/llm_client.py` 或 Java 网关 `LlmRouter` |
| 接入新的 TTS | `layers/L4_audio/voiceover.py` 增加 provider |
| 增加新的视频风格 | `config/style_templates/` 新增 yaml |
| 增加新的 Skill | `config/skills/` 新增 yaml + `layers/L2_creative/creative_skills.py` 注册 |
| 自定义 Prompt 编排 | `layers/L2_creative/prompt_director/` |
| 自定义质量门控 | `layers/L3_visual/clip_consistency.py` 或 `layers/L5_postprod/av_sync_rescue.py` |
