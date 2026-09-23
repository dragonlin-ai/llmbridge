<#
.SYNOPSIS
    在 Windows 上启动 LLM 路由中转网关（后端）。

.DESCRIPTION
    本脚本存在的原因只有一个：把「必须带正确的 --loop」这件事固化下来。

    Windows 上 uvicorn 默认用 ProactorEventLoop，而 psycopg3 主动拒绝它。
    省略 --loop 的症状是「服务起来了、/health 返回 200，但一访问数据库就 500」，
    极难往事件循环上联想。脚本优先调用 llmbridge-serve（内置了正确工厂），
    退回裸 uvicorn 时也会补上 --loop。

.EXAMPLE
    .\deploy\windows\start-backend.ps1
    .\deploy\windows\start-backend.ps1 -BindHost 0.0.0.0 -Port 8080
    .\deploy\windows\start-backend.ps1 -Reload          # 开发用，改代码自动重启
#>
[CmdletBinding()]
param(
    [string]$BindHost = '127.0.0.1',
    [int]$Port = 8000,
    [int]$Workers = 1,
    [switch]$Reload
)

$ErrorActionPreference = 'Stop'

# 仓库根 = 本脚本的上两级（deploy\windows\ → deploy\ → 仓库根）
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host "找不到虚拟环境：$python" -ForegroundColor Red
    Write-Host '请先在仓库根执行：' -ForegroundColor Yellow
    Write-Host '    python -m venv .venv'
    Write-Host '    .\.venv\Scripts\python.exe -m pip install -e ".[dev]"'
    exit 1
}

if (-not (Test-Path (Join-Path $root '.env'))) {
    Write-Host '未找到 .env —— 将回落到代码内置默认值（SQLite 兜底库）。' -ForegroundColor Yellow
    Write-Host '首次部署请先执行：  Copy-Item .env.example .env  ' -ForegroundColor Yellow
}

$serveExe = Join-Path $root '.venv\Scripts\llmbridge-serve.exe'
if (Test-Path $serveExe) {
    $exe = $serveExe
    $exeArgs = @('--host', $BindHost, '--port', "$Port", '--workers', "$Workers")
    if ($Reload) { $exeArgs += '--reload' }
}
else {
    Write-Host 'llmbridge-serve 不存在（尚未 pip install -e .），改用 uvicorn 直启。' -ForegroundColor Yellow
    $exe = $python
    $exeArgs = @(
        '-m', 'uvicorn', 'app.main:app',
        '--host', $BindHost,
        '--port', "$Port",
        '--loop', 'app.core.eventloop:selector_loop_factory'
    )
    if ($Reload) { $exeArgs += '--reload' }
}

Write-Host ("启动：{0} {1}" -f $exe, ($exeArgs -join ' ')) -ForegroundColor Cyan
Write-Host ("健康检查：http://{0}:{1}/health" -f $BindHost, $Port) -ForegroundColor DarkGray
& $exe @exeArgs
