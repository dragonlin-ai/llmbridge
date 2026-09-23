<#
.SYNOPSIS
    本地开发一键启动：后端（独立窗口）+ 控制台前端 Vite（当前窗口）。

.DESCRIPTION
    开发态下前端跑 Vite dev server（5173），由 vite.config.ts 里的 proxy
    把 /v1 与 /admin 转发到后端 8000 —— 因此前端代码里全部使用相对路径，
    生产换成 nginx 同源代理后无需改任何一行业务代码。

    注意 vite 必须显式绑 127.0.0.1：默认只监听 IPv6 的 localhost，
    IPv4 访问会「连接被拒」。

.EXAMPLE
    .\deploy\windows\start-dev.ps1
    .\deploy\windows\start-dev.ps1 -BackendPort 8001 -WebPort 5174
#>
[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$WebPort = 5173
)

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$webDir = Join-Path $root 'admin-web'

if (-not (Test-Path (Join-Path $webDir 'node_modules'))) {
    Write-Host 'admin-web\node_modules 不存在，正在安装前端依赖（首次约需 1-2 分钟）...' -ForegroundColor Yellow
    Push-Location $webDir
    try { & npm.cmd ci } finally { Pop-Location }
}

# 后端放独立窗口，便于单独看后端日志（判定器探活、上游报错都在那里）。
$backendPs1 = Join-Path $PSScriptRoot 'start-backend.ps1'
Write-Host '在新窗口启动后端...' -ForegroundColor Cyan
Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', $backendPs1,
    '-BindHost', '127.0.0.1', '-Port', "$BackendPort"
)

Start-Sleep -Seconds 3

Write-Host ("控制台前端：http://127.0.0.1:{0}" -f $WebPort) -ForegroundColor Cyan
Write-Host ("后端健康检查：http://127.0.0.1:{0}/health" -f $BackendPort) -ForegroundColor DarkGray
Write-Host '默认账号：admin / admin123 —— 首次登录后请立即改密。' -ForegroundColor Yellow

Push-Location $webDir
try {
    # --host 127.0.0.1 不可省：vite 默认只绑 IPv6 localhost，IPv4 探测会失败。
    & npm.cmd run dev -- --host 127.0.0.1 --port "$WebPort"
}
finally { Pop-Location }
