<#
.SYNOPSIS
    本地一键启动：Python 后端（orchestrator + worker + postgres + redis）+ sl-vue 前端。
    可选 -WithGateway 追加 Java 网关（场景 C）。

.DESCRIPTION
    跨电脑可用：项目根由脚本自身位置（$PSScriptRoot 的上一级）自动推导，不写死绝对路径。
    换电脑只需 clone 仓库 + 放好 .env，直接跑本脚本即可。

.PARAMETER WithGateway
    追加启动 Java gateway（http://localhost:8080），用于测 JWT / TraceId / failover / 计量全链路。

.PARAMETER NoFrontend
    只起后端，不起前端（纯调 API / webhook 时用）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start-local.ps1
    powershell -ExecutionPolicy Bypass -File scripts\start-local.ps1 -WithGateway
#>
[CmdletBinding()]
param(
    [switch]$WithGateway,
    [switch]$NoFrontend
)

$ErrorActionPreference = "Stop"

# ── 路径自动推导（跨电脑核心）─────────────────────────────────────────────
$PROJECT_ROOT = Split-Path -Parent $PSScriptRoot
$FRONTEND_DIR = Join-Path $PROJECT_ROOT "sl-vue"
$COMPOSE      = Join-Path $PROJECT_ROOT "docker-compose.yaml"
$ENV_FILE     = Join-Path $PROJECT_ROOT ".env"

function Info($m)  { Write-Host $m -ForegroundColor Cyan }
function Ok($m)    { Write-Host $m -ForegroundColor Green }
function Warn($m)  { Write-Host $m -ForegroundColor Yellow }
function Fail($m)  { Write-Host $m -ForegroundColor Red }

Write-Host ""
Info "==== 项目根: $PROJECT_ROOT ===="

# ── 0/6 前置检查 ──────────────────────────────────────────────────────────
Info "==== 0/6 前置检查 ===="

# Docker 在跑？
try { docker info *> $null } catch {
    Fail "❌ Docker 没启动，请先打开 Docker Desktop"; exit 1
}
Ok "  Docker 运行中"

# compose 文件存在？
if (-not (Test-Path $COMPOSE)) { Fail "❌ 找不到 $COMPOSE"; exit 1 }

# .env 存在？
if (-not (Test-Path $ENV_FILE)) {
    Fail "❌ 缺 .env 文件：$ENV_FILE"
    Warn "   从老电脑拷一份过来（含 DEEPSEEK_API_KEY / GLM / KLING / TTS / FEISHU 等 key）"
    exit 1
}
Ok "  .env 已就绪"

# 经验坑3：docker-compose.yaml 用 ${GATEWAY_AUTH_JWT_SECRET:?...} 强制要求该值，
# 缺失会让整个 compose 解析失败（即使你没起 gateway 服务也照样阻塞 postgres/redis/orchestrator）。
# 这里自动检测+补齐，避免本地/换电脑踩坑（强随机 base64，符合 >=32 字节要求）。
if (-not (Select-String -Path $ENV_FILE -Pattern "^GATEWAY_AUTH_JWT_SECRET=" -Quiet)) {
    Warn "  .env 缺 GATEWAY_AUTH_JWT_SECRET（compose 必填项），自动生成强随机 secret 追加..."
    $bytes = New-Object byte[] 32
    (New-Object System.Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes)
    $secret = [Convert]::ToBase64String($bytes)
    Add-Content -Path $ENV_FILE -Value "`nGATEWAY_AUTH_JWT_SECRET=$secret" -Encoding utf8
    Ok "  ✅ 已追加 GATEWAY_AUTH_JWT_SECRET（44 字符 base64）"
}

# 前端依赖（提前判断，避免后面卡）
$needNpmInstall = (-not $NoFrontend) -and (-not (Test-Path (Join-Path $FRONTEND_DIR "node_modules")))

# ── 1/6 启动 Postgres + Redis ─────────────────────────────────────────────
Info "==== 1/6 启动 Postgres + Redis ===="
docker compose -f $COMPOSE up -d postgres redis
Start-Sleep -Seconds 5

# ── 2/6 首次 build Python 镜像 ────────────────────────────────────────────
# 经验坑1：Docker Desktop 开 containerd 镜像存储时，`compose up` 内联 build
# 偶发"镜像没 tag/未 load 进镜像库"，导致每次 up 都从头重 build（ffmpeg+ML 依赖巨慢）。
# 对策：显式 build 一次 → 验证 `docker images` 真有 tag → 后续 up 一律 --no-build。
Info "==== 2/6 检查 Python 镜像 ===="
$imageExists = docker images -q ai-platform-app:latest
if (-not $imageExists) {
    Warn "  首次运行，build Python 镜像（含 ffmpeg + faster-whisper/librosa 等重型依赖，5-15 分钟，请勿中断）..."
    docker compose -f $COMPOSE build orchestrator
    # 验证镜像确实 tag 上了（containerd 存储下偶发 build 完不落库）
    $imageExists = docker images -q ai-platform-app:latest
    if (-not $imageExists) {
        Fail "❌ build 完成但 ai-platform-app:latest 没出现在镜像库"
        Warn "   多半是 Docker Desktop 的 containerd 镜像存储问题。手动重试一次："
        Warn "   docker compose build orchestrator; docker images ai-platform-app"
        exit 1
    }
    Ok "  镜像已构建并落库：ai-platform-app:latest"
} else {
    Ok "  镜像已存在（如改过 Python 代码，需手动 docker compose build orchestrator）"
}

# ── 3/6 启动 orchestrator + worker ────────────────────────────────────────
# --no-build：镜像已就绪，禁止 up 再触发隐式 build（避免重复巨型构建）
Info "==== 3/6 启动 orchestrator + worker ===="
docker compose -f $COMPOSE up -d --no-build orchestrator worker
Start-Sleep -Seconds 8

# ── 4/6 alembic 迁移 ──────────────────────────────────────────────────────
# 经验坑2：orchestrator 启动时 init_db.create_all() 已建全部表，全新库里
# alembic_version 是空的 → `upgrade head` 从头跑 DDL 撞 "relation already exists"。
# 对策：upgrade 失败时自动 fallback 到 `stamp head`（标记迁移已应用，不重跑 DDL）。
Info "==== 4/6 跑 alembic 迁移 ===="
# PS5.1 坑：$ErrorActionPreference=Stop 下，用 2>&1 接住原生命令的 stderr，
# 任何 stderr 行（哪怕只是 docker 的 deprecation 警告）都会被包成 NativeCommandError 抛出。
# 这里临时降到 Continue，把 stdout+stderr 合并捕获，再用退出码判定，避免误杀。
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$migText = (docker compose -f $COMPOSE exec -T orchestrator alembic upgrade head 2>&1 | Out-String)
$migExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($migExit -ne 0 -and $migText -match "already exists|DuplicateTable") {
    Warn "  检测到 create_all 已建表（全新库常见），改用 alembic stamp head 兜底..."
    docker compose -f $COMPOSE exec -T orchestrator alembic stamp head
    Ok "  已 stamp 到 head（表结构由 create_all 提供，迁移版本对齐）"
} elseif ($migExit -ne 0) {
    Warn "  alembic upgrade 报错（非建表冲突），请手动排查："
    Write-Host $migText -ForegroundColor DarkGray
} else {
    Ok "  迁移已到 head"
}

# ── 5/6 可选 Java gateway ─────────────────────────────────────────────────
if ($WithGateway) {
    Info "==== 5/6 启动 Java gateway（首次 build 10-15 分钟）===="
    docker compose -f $COMPOSE up -d gateway
    Start-Sleep -Seconds 15
} else {
    Info "==== 5/6 跳过 Java gateway（加 -WithGateway 启用场景 C）===="
}

# ── 6/6 前端 ──────────────────────────────────────────────────────────────
if ($NoFrontend) {
    Info "==== 6/6 跳过前端（-NoFrontend）===="
} else {
    Info "==== 6/6 启动前端 ===="
    if ($needNpmInstall) {
        Warn "  首次运行，npm install（3-5 分钟）..."
        Push-Location $FRONTEND_DIR
        npm install
        Pop-Location
    }
    # 新窗口起 dev，这样关掉本脚本窗口前端仍存活
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$FRONTEND_DIR'; npm run dev"
}

# ── 健康检查 ──────────────────────────────────────────────────────────────
Start-Sleep -Seconds 3
Info "==== 健康检查 ===="
try {
    $h = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 5
    Ok "  Python API: $($h.Content)"
} catch {
    Warn "  Python API 暂未就绪（容器可能还在启动，稍等 10 秒后访问 http://localhost:8000/health）"
}
if ($WithGateway) {
    try {
        $g = Invoke-WebRequest -Uri "http://localhost:8080/actuator/health" -UseBasicParsing -TimeoutSec 5
        Ok "  Java Gateway: $($g.Content)"
    } catch {
        Warn "  Gateway 暂未就绪（Spring Boot 启动慢，30 秒后再访问 http://localhost:8080/actuator/health）"
    }
}

Write-Host ""
Ok   "==== ✅ 启动完成 ===="
Write-Host "  Python API:   http://localhost:8000/health" -ForegroundColor White
if (-not $NoFrontend) { Write-Host "  前端:         http://localhost:5173" -ForegroundColor White }
if ($WithGateway)     { Write-Host "  Java Gateway: http://localhost:8080/actuator/health" -ForegroundColor White }
Write-Host "  容器状态:     docker compose ps" -ForegroundColor Gray
Write-Host "  停止:         powershell -ExecutionPolicy Bypass -File scripts\stop-local.ps1" -ForegroundColor Gray
Write-Host ""
