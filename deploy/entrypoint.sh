#!/bin/sh
# 容器入口：先把库整备到「可用」再起服务。
#
# 顺序不能反 —— 服务先起来而表还没建，日志里会是一串 psycopg 的
# UndefinedTable，看起来像连接问题，实际只是没初始化。
set -e

echo "[entrypoint] 1/2 建表 + 种子数据（幂等）..."
llmbridge-seed

echo "[entrypoint] 2/2 预置内置厂商目录（幂等）..."
# 失败不阻断启动：容器可能被用来跑已有数据库，此时目录早已灌好；
# 但必须显式告警，否则控制台「一家厂商都没有」会被误判成前端缺陷。
if ! llmbridge-catalog --report /tmp/catalog_report.txt; then
    echo "[entrypoint][WARN] 厂商目录预置失败，控制台可能看不到任何厂商。" >&2
    echo "[entrypoint][WARN] 常见原因：DATABASE_URL 不可达，或 scripts/ 未随镜像拷入。" >&2
fi

echo "[entrypoint] 启动：$*"
exec "$@"
