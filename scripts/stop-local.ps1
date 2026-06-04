<#
.SYNOPSIS
    停止本地全部服务：Docker 容器（postgres/redis/orchestrator/worker/gateway）+ 前端 dev。

.DESCRIPTION
    跨电脑可用：项目根由 $PSScriptRoot 自动推导。
    数据库 volume 默认保留（不删 DB 数据）。彻底清重置见文末提示。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\stop-local.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "SilentlyContinue"

$PROJECT_ROOT = Split-Path -Parent $PSScriptRoot
$COMPOSE      = Join-Path $PROJECT_ROOT "docker-compose.yaml"

function Info($m) { Write-Host $m -ForegroundColor Cyan }
function Ok($m)   { Write-Host $m -ForegroundColor Green }
function Gray($m) { Write-Host $m -ForegroundColor Gray }

Write-Host ""
Info "==== 停止 Docker 服务 ===="
docker compose -f $COMPOSE stop

Info "==== 关闭前端 Node 进程（端口 5173）===="
$nodeProc = Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty OwningProcess
if ($nodeProc) {
    Stop-Process -Id $nodeProc -Force
    Ok "  ✅ 前端已停（PID $nodeProc）"
} else {
    Gray "  前端未运行"
}

Write-Host ""
Ok   "==== ✅ 全部停止 ===="
Gray "  DB 数据已保留（pgdata/redisdata volume）"
Gray "  彻底清重置（⚠️ 删 DB 数据）: docker compose down -v"
Write-Host ""
