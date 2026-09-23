#!/usr/bin/env bash
#
# =============================================================================
#  LLM 路由中转系统（llmbridge）· Apple container 部署脚本 —— macOS
# =============================================================================
#
#  前置：Apple Silicon Mac + macOS 26 或更高 + Apple `container` 1.1.0+
#        （安装：brew install container，或从 https://github.com/apple/container/releases 下载）
#
#  用法（在仓库根目录执行）：
#    ./deploy/apple-container.sh init       # 检查环境并构建镜像
#    ./deploy/apple-container.sh up         # 启动容器
#    ./deploy/apple-container.sh status     # 查看状态与访问地址
#
#  子命令：
#    init        检查 container CLI、生成密钥、构建镜像
#    up          启动容器（首次用会自动先跑一次 init）
#    status      查看容器与镜像状态、健康检查结果
#    logs        跟随输出容器日志
#    shell       进入容器内的 shell
#    restart     重启容器
#    down        停止并删除容器（**保留数据目录**）
#    purge       down 之后连同数据目录一起删除（不可恢复）
#    upgrade     拉取最新代码并重建镜像、重启（数据保留）
#    help        显示本帮助
#
#  可调环境变量：
#    LLMBRIDGE_DATA_DIR   数据目录（默认 <仓库根>/llmbridge-data）
#    LLMBRIDGE_PORT       宿主机端口（默认 8000）
#    LLMBRIDGE_BIND       监听地址（默认 127.0.0.1；对外暴露改 0.0.0.0 并自备反代）
#    LLMBRIDGE_TAG        镜像标签（默认 1.0.0）
#
#  为什么默认单容器 + SQLite：
#    Apple container 是逐容器手工编排的（没有 compose 那样的依赖编排与健康检查等待），
#    让它同时管 PostgreSQL + Redis + 应用三层，启动时序得自己写轮询，脆弱且难排障。
#    本方式定位是「本地开发与人工运维」（生产请用方式二的 Docker Compose），
#    因此默认单容器 + SQLite 落数据卷 —— 零依赖、启动即用、数据可迁移。
#    需要 PostgreSQL 时：先用 container 起一个 pg 实例，再把它的连接串写进 .env
#    的 DATABASE_URL（见下方「切 PostgreSQL」说明）。
# =============================================================================

set -euo pipefail

# 不用 dirname —— 最小化/异常的 bash 环境里可能没有它
# （本项目开发机的 Git Bash 就报 dirname: command not found）。纯参数展开即可。
case "$0" in
    */*) _self_dir="${0%/*}" ;;
    *)   _self_dir="." ;;
esac
REPO_ROOT="$(cd "$_self_dir/.." && pwd)"
IMAGE_NAME="llmbridge"
IMAGE_TAG="${LLMBRIDGE_TAG:-1.0.0}"
IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_NAME="llmbridge"
DATA_DIR="${LLMBRIDGE_DATA_DIR:-$REPO_ROOT/llmbridge-data}"
HOST_PORT="${LLMBRIDGE_PORT:-8000}"
BIND_ADDR="${LLMBRIDGE_BIND:-127.0.0.1}"
DOCKERFILE="$REPO_ROOT/deploy/Dockerfile"
ENV_FILE="$DATA_DIR/.env"

if [ -t 1 ]; then
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
    C_BLUE=$'\033[36m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
    C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_BOLD=""; C_OFF=""
fi
info() { printf '%s[信息]%s %s\n' "$C_BLUE"   "$C_OFF" "$*"; }
ok()   { printf '%s[完成]%s %s\n' "$C_GREEN"  "$C_OFF" "$*"; }
warn() { printf '%s[警告]%s %s\n' "$C_YELLOW" "$C_OFF" "$*" >&2; }
die()  { printf '%s[失败]%s %s\n' "$C_RED"    "$C_OFF" "$*" >&2; exit 1; }
step() { printf '\n%s==> %s%s\n' "$C_BOLD" "$*" "$C_OFF"; }

# =============================================================================
#  环境检查
# =============================================================================

check_env() {
    [ "$(uname -s)" = "Darwin" ] || die "本脚本仅支持 macOS。Linux 请用 deploy/install.sh，通用容器请用 deploy/docker-compose.yml。"

    if [ "$(uname -m)" != "arm64" ]; then
        warn "当前架构为 $(uname -m)，Apple container 面向 Apple Silicon；仍可尝试，但不受支持。"
    fi

    if ! command -v container >/dev/null 2>&1; then
        cat >&2 <<'EOF'
[失败] 未找到 Apple `container` 命令。

安装方式（任选其一）：
  brew install container
  # 或从 https://github.com/apple/container/releases 下载 .pkg 安装

要求：Apple Silicon Mac + macOS 26+，container 1.1.0 或更高版本。
装完先执行一次 `container system start`，再重跑本脚本。
EOF
        exit 1
    fi

    local ver
    # || true 兜住 head 提前关管道产生的 SIGPIPE（pipefail 下会算失败）。
    ver="$(container --version 2>/dev/null | head -n 1 || true)"
    info "container CLI：${ver:-未知}"

    # 容器系统（服务端）没起来时，后续 build/run 会报晦涩的连接错误，先显式拉起。
    if ! container system status >/dev/null 2>&1; then
        info "启动 container 系统服务..."
        container system start >/dev/null 2>&1 || \
            die "container system start 失败。请手动执行一次并查看输出。"
    fi
    ok "container 运行时就绪"
}

# =============================================================================
#  密钥与配置
# =============================================================================

gen_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 32 | tr -d '\n'
    else
        LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 43
    fi
}

ensure_env() {
    mkdir -p "$DATA_DIR"
    if [ -f "$ENV_FILE" ]; then
        info "复用既有配置：$ENV_FILE"
        grep -q '^ENCRYPTION_MASTER_KEY=.\+' "$ENV_FILE" || \
            die "既有配置缺少 ENCRYPTION_MASTER_KEY。请补上后再运行，否则已存厂商密钥无法解密。"
        return 0
    fi
    umask 077
    cat > "$ENV_FILE" <<EOF
# 由 deploy/apple-container.sh 于 $(date '+%Y-%m-%d %H:%M:%S') 生成
# 含明文密钥，权限 600，请勿提交 git。
#
# 容器内路径 /data 已挂载到宿主机的：${DATA_DIR}
DATABASE_URL=sqlite:////data/llmbridge.db

AUTO_BOOTSTRAP=true
REDIS_URL=

ALLOW_LOCAL_BASE_URL=false
JWT_SECRET=$(gen_secret)
JWT_EXPIRE_SECONDS=86400
ENCRYPTION_MASTER_KEY=$(gen_secret)

JUDGE_PROVIDER=mock
JEV_API_KEY=
JEV_BASE_URL=https://api.typesafe.ai/v1/systemone
DECIDER_TIMEOUT_MS=3000
ROUTE_CONFIDENCE_THRESHOLD_T2=0.5

# 首次安装模型池为空，请先在控制台「模型池」页添加模型，再把其 id 填到这里。
DEFAULT_MODEL_ID=1
REQUEST_TIMEOUT_MS=30000
ROUTE_CACHE_TTL=3600

LOG_BATCH_SIZE=50
LOG_FLUSH_SECONDS=1.0
ENABLE_TOOL_EXECUTION=false
TOOL_RESULT_MAX_CHARS=8000
EOF
    chmod 600 "$ENV_FILE"
    ok "已生成配置：$ENV_FILE（密钥为随机值）"
}

# 把 .env 逐行转成 `-e KEY=VALUE` 参数，供 container run 使用。
#
# 用数组而不是「拼字符串再交给 shell 做 word splitting」：后者的值是单个 base64 串
# 时看着没事，一旦用户手改出带空格的值（如 JWT_SECRET="a b"）就会被拆成多个参数，
# 现象是容器起来了但配置莫名错位 —— 这类问题极难排查，直接从源头避免。
ENV_ARGS=()
load_env_args() {
    ENV_ARGS=()
    local line key val
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in ''|'#'*) continue ;; esac
        key="${line%%=*}"
        val="${line#*=}"
        [ -n "$key" ] || continue
        # POSTGRES_PASSWORD / HTTP_PORT 只服务于 Docker Compose，单容器形态用不上。
        case "$key" in POSTGRES_PASSWORD|HTTP_PORT) continue ;; esac
        case "$val" in *" "*) warn "配置项 $key 的值含空格，容器内可能被截断，请改用引号或去掉空格。" ;; esac
        ENV_ARGS+=(-e "${key}=${val}")
    done < "$ENV_FILE"
}

# =============================================================================
#  镜像
# =============================================================================

build_image() {
    [ -f "$DOCKERFILE" ] || die "未找到 Dockerfile：$DOCKERFILE"
    step "构建镜像 $IMAGE_REF"
    info "构建上下文：$REPO_ROOT（首次构建需拉取 python:3.13-slim 基础镜像，约 1~3 分钟）"
    container build -f "$DOCKERFILE" -t "$IMAGE_REF" "$REPO_ROOT" \
        || die "镜像构建失败。请确认 container 系统已启动（container system start）。"
    ok "镜像已构建：$IMAGE_REF"
}

image_exists() {
    # 匹配刻意放宽到「镜像名出现过即可」：Apple container 各版本 `image ls` 的列宽与
    # 分隔符不完全一致，按「名字 + tag」精确匹配容易误判成不存在（表现为每次 up 都重建镜像）。
    # 宁可多构建一次，也不要因输出格式差异跳过必要的构建。
    container image ls 2>/dev/null | grep -q "${IMAGE_NAME}"
}

# =============================================================================
#  容器生命周期
# =============================================================================

container_running() {
    container ls 2>/dev/null | grep -q "[[:space:]]${CONTAINER_NAME}[[:space:]]"
}

do_init() {
    step "初始化"
    check_env
    ensure_env
    build_image
    cat <<EOF

${C_GREEN}初始化完成${C_OFF}，下一步执行：

  ./deploy/apple-container.sh up

EOF
}

do_up() {
    step "启动容器"
    check_env
    if ! image_exists; then
        info "镜像 $IMAGE_REF 不存在，先执行 init"
        ensure_env
        build_image
    else
        ensure_env
    fi

    if container_running; then
        info "容器 $CONTAINER_NAME 已在运行，改为重启以应用最新配置"
        container stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
        container rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi

    info "数据目录：$DATA_DIR（容器内 /data，删除容器不影响数据）"
    load_env_args
    # ${ENV_ARGS[@]+"${ENV_ARGS[@]}"}：空数组在 set -u + bash 3.2（macOS 自带）下的安全展开写法，
    # 直接写 "${ENV_ARGS[@]}" 会报 unbound variable。
    # 卷挂载用 -v（若你的 container 版本不认短选项，改成 --volume 即可）。
    container run -d \
        --name "$CONTAINER_NAME" \
        -p "${BIND_ADDR}:${HOST_PORT}:8000" \
        -v "${DATA_DIR}:/data" \
        ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} \
        "$IMAGE_REF" >/dev/null \
        || die "容器启动失败。请查看：container logs $CONTAINER_NAME"

    ok "容器已启动"
    wait_healthy
    print_access
}

wait_healthy() {
    local i=1 url="http://127.0.0.1:${HOST_PORT}/health"
    info "健康检查：$url"
    while [ "$i" -le 30 ]; do
        if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
            ok "服务已就绪（第 ${i} 次探测）"
            return 0
        fi
        # 容器已退出就没必要再等，直接报出来。
        if ! container_running; then
            warn "容器已退出，查看日志：container logs $CONTAINER_NAME"
            return 1
        fi
        sleep 1
        i=$((i + 1))
    done
    warn "30 秒内未就绪。查看日志：container logs $CONTAINER_NAME"
    return 1
}

print_access() {
    cat <<EOF

${C_GREEN}${C_BOLD}已启动${C_OFF}

  控制台   http://127.0.0.1:${HOST_PORT}/admin
  默认账号 admin / admin123  ${C_RED}（首次登录后立即修改）${C_OFF}
  数据目录 ${DATA_DIR}
  配置文件 ${ENV_FILE}
  日志     ./deploy/apple-container.sh logs

${C_YELLOW}模型池初始为空是有意设计${C_OFF}
  接入通道已预置 13 家厂商 / 24 条通道，填 API Key 即可接入；
  模型需在「模型池」页手动添加（能用哪些模型取决于你的账号）。
  添加后把模型 id 填进 ${ENV_FILE} 的 DEFAULT_MODEL_ID 并重启。

EOF
}

do_status() {
    step "状态"
    echo "--- 容器 ---"
    container ls 2>/dev/null | grep -E "(^ID|${CONTAINER_NAME})" || warn "未找到容器 $CONTAINER_NAME"
    echo "--- 镜像 ---"
    container image ls 2>/dev/null | grep -E "(^NAME|${IMAGE_NAME})" || warn "未找到镜像 $IMAGE_REF"
    echo "--- 健康检查 ---"
    if curl -fsS --max-time 3 "http://127.0.0.1:${HOST_PORT}/health" 2>/dev/null; then
        echo
        ok "服务正常：http://127.0.0.1:${HOST_PORT}"
    else
        warn "健康检查失败（容器可能未启动）"
    fi
}

do_down() {
    step "停止并移除容器"
    if container_running; then
        container stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
        container rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
        ok "容器已移除"
    else
        info "容器未在运行"
    fi
    info "数据目录已保留：$DATA_DIR"
    info "重新启动：./deploy/apple-container.sh up"
}

do_purge() {
    do_down
    warn "即将删除数据目录：$DATA_DIR"
    printf '确认？数据不可恢复 [y/N] '
    read -r ans
    case "$ans" in
        y|Y|yes|YES) rm -rf "$DATA_DIR"; ok "已删除 $DATA_DIR" ;;
        *) info "已取消，数据保留。" ;;
    esac
    info "如需删除镜像：container image rm $IMAGE_REF"
}

do_upgrade() {
    step "升级"
    if [ -d "$REPO_ROOT/.git" ]; then
        ( cd "$REPO_ROOT" && git pull --ff-only ) || warn "git pull 失败（本地有改动？），继续用当前代码重建镜像。"
    else
        info "非 git 工作树，跳过拉取；直接重建镜像。"
    fi
    build_image
    do_up
}

# =============================================================================
#  入口
# =============================================================================

show_usage() {
    # 打印文件头部的注释块。用 shell 内建而非 awk —— 有些环境确实没有 awk
    # （本项目开发机的 Git Bash 就是，awk/head/wc 全缺），那样 `--help` 会是空白。
    if [ ! -f "$0" ]; then
        echo "llmbridge Apple container 部署脚本。完整用法见 README.md 或 deploy/apple-container.sh 头部注释。"
        exit 0
    fi
    local lineno=0 line
    while IFS= read -r line || [ -n "$line" ]; do
        lineno=$((lineno + 1))
        [ "$lineno" -eq 1 ] && continue        # 跳过 shebang
        case "$line" in
            "# "*) printf '%s\n' "${line#"# "}" ;;
            "#"*)  printf '%s\n' "${line#"#"}" ;;
            *)     break ;;
        esac
    done < "$0"
    exit 0
}

case "${1:-help}" in
    init)    do_init ;;
    up)      do_up ;;
    status)  do_status ;;
    logs)    exec container logs -f "$CONTAINER_NAME" ;;
    shell)   exec container exec -it "$CONTAINER_NAME" /bin/sh ;;
    restart) container stop "$CONTAINER_NAME" >/dev/null 2>&1 || true; do_up ;;
    down)    do_down ;;
    purge)   do_purge ;;
    upgrade) do_upgrade ;;
    help|-h|--help) show_usage ;;
    *) die "未知子命令：$1（可用：init/up/status/logs/shell/restart/down/purge/upgrade/help）" ;;
esac
