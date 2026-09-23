#!/bin/sh
# 容器入口：先把库整备到「可用」再起服务。
#
# 这一步其实已经**不是必需**了 —— 服务自己的启动引导（app/services/bootstrap.py）
# 会做同样的事，见下方说明。这里显式跑一次的理由只有一个：
# 让容器的启动日志里**先**出现「建表 / 管理员 / 厂商目录」的明确输出，
# 而不是混在 uvicorn 的日志里；排查「为什么界面上没有厂商」时省一轮猜测。
#
# 为什么不再单独调 llmbridge-catalog
# ---------------------------------
# 旧版是 seed → catalog → serve 三步，其中 catalog 的实现在源码树的 scripts/ 下，
# **不进 wheel**，镜像里若没拷 scripts/ 就会失败（旧脚本还专门为此写了告警）。
# 现在 seed 已经包含厂商目录预置，且实现搬进了包内，不再依赖 scripts/。
# 两处调用同一份实现 = 不会出现「命令跑过了但界面还是空的」这种不一致。
set -e

echo "[entrypoint] 初始化：建表 + 默认管理员 + 评测样本 + 厂商接入目录（全部幂等）..."
# 失败不阻断启动：容器可能被用来跑已有数据库，此时一切早已就绪。
# 但必须显式告警，否则控制台「一家厂商都没有」会被误判成前端缺陷。
if ! llmbridge-seed; then
    echo "[entrypoint][WARN] 初始化失败，界面可能看不到厂商、也登录不了。" >&2
    echo "[entrypoint][WARN] 常见原因：DATABASE_URL 不可达（检查 db 服务是否就绪）。" >&2
    echo "[entrypoint][WARN] 服务仍会启动，并在 lifespan 里再试一次同样的引导。" >&2
fi

echo "[entrypoint] 启动：$*"
exec "$@"
