#!/usr/bin/env bash
#
# =============================================================================
#  LLM 路由中转系统（llmbridge）· Docker Compose 一键部署脚本
# =============================================================================
#
#  用法：
#    # 远程（自动下载源码到 ./llmbridge 并起容器）
#    curl -sSL https://raw.githubusercontent.com/dragonlin-ai/llmbridge/main/deploy/docker-deploy.sh | bash
#
#    # 仓库内（用当前源码）
#    bash deploy/docker-deploy.sh
#
#    # 容器库形态（**不需要源码**，全部镜像从容器库拉取）
#    bash deploy/docker-deploy.sh --image
#    curl -sSL .../deploy/docker-deploy.sh | bash -s -- --image
#
#  子命令：
#    (无) / deploy   准备配置 + 构建前端 + 启动全部服务
#    status          查看容器状态与健康检查
#    logs            跟随日志（可跟服务名：logs api）
#    down            停止并移除容器（保留数据卷）
#    upgrade         拉取最新代码 + 重建镜像 + 重启（数据保留）
#    purge           停止并**删除数据卷**（不可恢复，二次确认）
#
#  选项：
#    --dir <path>       部署目录（默认 ./llmbridge；目录内已是仓库时直接复用）
#    --ref <ref>        源码版本：分支 / tag（默认 main）
#    --port <n>         控制台对外端口（默认 80）
#    --pg-password <p>  PostgreSQL 密码（默认随机 32 位）
#    --skip-frontend    跳过前端构建（仅在你已有 admin-web/dist 时使用）
#    --image            容器库形态：不下载源码、不构建前端，只取编排文件 +
#                       生成 .env + 拉取镜像。需先发布镜像，见 publish-image.sh
#    --registry <host/ns>  容器库地址与命名空间（配合 --image）
#    --tag <tag>           镜像版本标签（配合 --image，默认 1.0.0）
#    -y, --yes          非交互
#
#  两种形态的区别（别混用）：
#    源码形态（默认）  镜像在本机构建；前端 dist 是 bind mount 进 nginx 的，
#                      所以**必须**先 build 前端，且目标机要有源码目录。
#    容器库形态(--image)  api 与 web 两个镜像自带全部内容（含 dist 与 nginx.conf），
#                      目标机只需要一个编排文件和一个 .env，**不需要任何源码**。
#    两者共用同一个 compose 项目名与数据卷，切换前先 down。
#
#  为什么脚本要自己构建前端：
#    deploy/docker-compose.yml 里的 nginx 是把 ../admin-web/dist **bind mount**
#    进去的（前端是纯静态产物，没必要打进镜像）。也就是说 dist 不存在时，
#    nginx 容器照样起来、但访问控制台是 404/空白 —— 这是本项目最常见的一次性坑。
#    这里用 node 官方镜像来构建，好处是**宿主机不需要装 Node.js**：
#    只要有 Docker，一条命令就能把整条链路拉起来。
#    （--image 形态没有这个坑：dist 已经在镜像里。）
# =============================================================================

set -euo pipefail

REPO_SLUG="dragonlin-ai/llmbridge"
DEFAULT_REF="main"
NODE_IMAGE="node:22-alpine"

DEPLOY_DIR="./llmbridge"
REF="$DEFAULT_REF"
HTTP_PORT="80"
PG_PASSWORD=""
SKIP_FRONTEND="false"
ASSUME_YES="false"
ACTION="deploy"
USE_IMAGE="false"
REGISTRY="registry.cn-hangzhou.aliyuncs.com/winyeahs"
IMAGE_TAG="1.0.0"

COMPOSE_FILE="deploy/docker-compose.yml"

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

usage() {
    # 打印文件头部的注释块。用 shell 内建而非 awk —— 有些环境确实没有 awk
    # （本项目的开发机 Git Bash 就是，awk/head/wc 全缺），那样 `--help` 会是空白。
    # 管道执行（curl | bash）时 $0 不是路径、读不到脚本自身，退化为一行提示。
    if [ ! -f "$0" ]; then
        echo "llmbridge Docker Compose 一键部署脚本。完整用法见 README.md 或仓库内 deploy/docker-deploy.sh 头部注释。"
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

# ---- 子命令（第一个位置参数）----
LOG_SERVICE=""
if [ $# -gt 0 ]; then
    case "$1" in
        deploy|status|logs|down|purge|upgrade) ACTION="$1"; shift ;;
        help|-h|--help) usage ;;
        --*) ;;                       # 以 - 开头的是选项，落到下面解析
        *)   die "未知子命令：$1" ;;
    esac
fi

# logs 允许再跟一个服务名（如 `logs api`）。必须在选项解析**之前**摘出来，
# 否则它会被当成未知参数而报错。
if [ "$ACTION" = "logs" ] && [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
    LOG_SERVICE="$1"; shift
fi

while [ $# -gt 0 ]; do
    case "$1" in
        --dir)          DEPLOY_DIR="${2:?--dir 需要参数}"; shift 2 ;;
        --ref)          REF="${2:?--ref 需要参数}"; shift 2 ;;
        --port)         HTTP_PORT="${2:?--port 需要参数}"; shift 2 ;;
        --pg-password)  PG_PASSWORD="${2:?--pg-password 需要参数}"; shift 2 ;;
        --image)        USE_IMAGE="true"; shift ;;
        --registry)     REGISTRY="${2:?--registry 需要参数}"; shift 2 ;;
        --tag)          IMAGE_TAG="${2:?--tag 需要参数}"; shift 2 ;;
        --skip-frontend) SKIP_FRONTEND="true"; shift ;;
        -y|--yes)       ASSUME_YES="true"; shift ;;
        -h|--help)      usage ;;
        *)              die "未知参数：$1（用 --help 查看用法）" ;;
    esac
done

REGISTRY="${REGISTRY%/}"
# 环境变量也能覆盖，方便 CI 里统一配置。
REGISTRY="${LLMBRIDGE_REGISTRY:-$REGISTRY}"
IMAGE_TAG="${LLMBRIDGE_TAG:-$IMAGE_TAG}"

if [ "$USE_IMAGE" = "true" ]; then
    COMPOSE_FILE="deploy/docker-compose.image.yml"
    # 容器库形态下"源码版本"指的是镜像标签，不是 git ref。
    if [ "$SKIP_FRONTEND" = "true" ]; then
        warn "--image 形态不需要 --skip-frontend（镜像里已含前端），该选项被忽略。"
        SKIP_FRONTEND="false"
    fi
fi

# =============================================================================
#  环境检查
# =============================================================================

DC=""   # docker compose 调用形式，检测后填充

check_docker() {
    command -v docker >/dev/null 2>&1 || die "未找到 docker。请先安装 Docker Engine 或 Docker Desktop。"
    docker info >/dev/null 2>&1 || die "Docker 守护进程未运行（docker info 失败）。请先启动 Docker。"

    if docker compose version >/dev/null 2>&1; then
        DC="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        DC="docker-compose"
        warn "检测到旧版 docker-compose（v1）。建议升级到 Docker Compose v2。"
    else
        die "未找到 Docker Compose。请安装 docker compose 插件（v2）。"
    fi
    info "容器运行时：$(docker --version)"
    info "编排工具：$DC（$($DC version --short 2>/dev/null || echo '版本未知')）"
}

# =============================================================================
#  源码
# =============================================================================

fetch_url() {
    # 只负责"把 url 落到 dest"，tar 解包等后续处理由调用方做。
    local url="$1" dest="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fSL --retry 3 --connect-timeout 20 -o "$dest" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --tries=3 -O "$dest" "$url"
    else
        die "需要 curl 或 wget 来下载文件。"
    fi
}

resolve_source() {
    # allow_fetch=false 时**不允许联网下载**：用于 logs/down/status 这类运维子命令。
    # 否则在「部署目录已被删掉」的情况下执行 down，脚本会莫名其妙开始下载源码。
    local allow_fetch="${1:-true}"

    # 脚本在 <repo>/deploy/ 下 → 用当前仓库，不下载。
    # 管道执行（curl | bash）时 $0 不是文件路径，dirname 会得到 "."，
    # 会把「用户碰巧站在某个含 app/ 的目录下」误判成本仓库 —— 先确认脚本自身是真实文件。
    if [ -f "$0" ]; then
        local self_dir here parent
        # 不用 dirname —— 最小化/异常的 bash 环境里可能没有它。纯参数展开即可。
        case "$0" in
            */*) self_dir="${0%/*}" ;;
            *)   self_dir="." ;;
        esac
        here="$(cd "$self_dir" && pwd)"
        parent="$(cd "$here/.." && pwd)"
        if [ -f "$parent/pyproject.toml" ] && [ -f "$parent/deploy/docker-compose.yml" ]; then
            SRC_DIR="$parent"
            info "使用当前仓库源码：$SRC_DIR"
            return 0
        fi
    fi

    # 部署目录里已经是仓库 → 复用（升级场景）。
    if [ -f "$DEPLOY_DIR/deploy/docker-compose.yml" ]; then
        SRC_DIR="$(cd "$DEPLOY_DIR" && pwd)"
        if [ "$ACTION" = "upgrade" ] && [ -d "$SRC_DIR/.git" ]; then
            info "拉取最新代码..."
            ( cd "$SRC_DIR" && git pull --ff-only ) || warn "git pull 失败，继续使用当前代码。"
        fi
        info "复用既有部署目录：$SRC_DIR"
        return 0
    fi

    [ "$allow_fetch" = "true" ] || \
        die "未找到部署目录（$DEPLOY_DIR）。请先执行部署：bash $0"

    local url tmp
    mkdir -p "$DEPLOY_DIR"
    DEPLOY_DIR="$(cd "$DEPLOY_DIR" && pwd)"
    tmp="$(mktemp -d)"
    url="https://github.com/${REPO_SLUG}/archive/refs/heads/${REF}.tar.gz"
    case "$REF" in
        v*|*.*.*) url="https://github.com/${REPO_SLUG}/archive/refs/tags/${REF}.tar.gz" ;;
    esac

    info "下载源码：$url"
    fetch_url "$url" "$tmp/src.tar.gz" || die "下载失败。"
    tar -xzf "$tmp/src.tar.gz" -C "$tmp"
    local inner
    inner="$(find "$tmp" -maxdepth 1 -type d -name 'llmbridge-*' | head -n 1)"
    [ -n "$inner" ] || die "解包后目录结构异常。"
    # 复制内容（含隐藏文件）而不是移动外层目录，让部署目录名保持用户指定值。
    ( cd "$inner" && tar -cf - . ) | ( cd "$DEPLOY_DIR" && tar -xf - )
    SRC_DIR="$DEPLOY_DIR"
    rm -rf "$tmp"
    ok "源码就绪：$SRC_DIR（ref=$REF）"
}

# -----------------------------------------------------------------------------
#  容器库形态：不下载源码，只取一个编排文件
# -----------------------------------------------------------------------------
#
# 为什么只要一个文件：api 与 web 两个镜像里已经装好了后端代码、前端 dist 与
# nginx.conf，目标机剩下的可变部分只有「编排文件 + .env」。
# 编排文件里 env_file 写的是 ../.env，与下载位置（<部署目录>/deploy/）配套，
# 所以这个相对路径不需要额外调整。

resolve_image_source() {
    local allow_fetch="${1:-true}"
    local rel="deploy/docker-compose.image.yml"

    # 脚本在仓库内 → 用仓库里那份，保证与当前代码同步。
    if [ -f "$0" ]; then
        local self_dir here parent
        case "$0" in
            */*) self_dir="${0%/*}" ;;
            *)   self_dir="." ;;
        esac
        here="$(cd "$self_dir" && pwd)"
        parent="$(cd "$here/.." && pwd)"
        if [ -f "$parent/$rel" ]; then
            SRC_DIR="$parent"
            info "使用当前仓库内的编排文件：$SRC_DIR/$rel"
            return 0
        fi
    fi

    # 部署目录里已有 → 复用。--image 形态刻意不 git pull：
    # 这一形态的"版本"由镜像标签决定，拉代码只会拉回与本机镜像无关的源码。
    if [ -f "$DEPLOY_DIR/$rel" ]; then
        SRC_DIR="$(cd "$DEPLOY_DIR" && pwd)"
        info "复用既有部署目录：$SRC_DIR"
        return 0
    fi

    [ "$allow_fetch" = "true" ] || \
        die "未找到编排文件（$DEPLOY_DIR/$rel）。请先执行部署：bash $0 --image"

    local url="https://raw.githubusercontent.com/${REPO_SLUG}/${REF}/${rel}"
    mkdir -p "$DEPLOY_DIR/deploy"
    DEPLOY_DIR="$(cd "$DEPLOY_DIR" && pwd)"
    info "下载编排文件：$url"
    fetch_url "$url" "$DEPLOY_DIR/$rel" || die "下载失败。可手动下载该文件放到 $DEPLOY_DIR/deploy/ 后重试。"
    SRC_DIR="$DEPLOY_DIR"
    ok "编排文件就绪：$SRC_DIR/$rel"
}
# 按形态分派。所有子命令都走这里，避免某个子命令漏判 --image ——
# 那会在一个「没有源码的部署目录」里去读 pyproject.toml，报出与真实原因无关的错。
resolve_any() {
    local allow_fetch="${1:-true}"
    if [ "$USE_IMAGE" = "true" ]; then
        resolve_image_source "$allow_fetch"
    else
        resolve_source "$allow_fetch"
    fi
}


# =============================================================================
#  配置
# =============================================================================

env_has_key() {
    local envfile="$1" key="$2"
    [ -f "$envfile" ] || return 1
    # 不用 grep —— 最小化环境里可能没有（详见脚本头的说明）。
    case "$(cat "$envfile")" in
        *"$key="*) return 0 ;;
        *) return 1 ;;
    esac
}

set_env_kv() {
    # 幂等写入：键不存在则追加，存在则就地改值。
    # 容器库形态下 LLMBRIDGE_REGISTRY / LLMBRIDGE_TAG 必须以命令行为准，
    # 否则「先跑过源码形态的 .env」会把后来的 --tag 静默吃掉。
    local envfile="$1" key="$2" val="$3"
    if env_has_key "$envfile" "$key"; then
        if sed -i "s|^${key}=.*|${key}=${val}|" "$envfile" 2>/dev/null; then
            return 0
        fi
        warn "sed 不可用，未能更新 $key=$val（请手动修改 $envfile）"
        return 0
    fi
    printf '%s=%s\n' "$key" "$val" >> "$envfile"
}

sync_image_env() {
    # 只在容器库形态下调用。
    local envfile="$1"
    set_env_kv "$envfile" LLMBRIDGE_REGISTRY "$REGISTRY"
    set_env_kv "$envfile" LLMBRIDGE_TAG "$IMAGE_TAG"
    ok "镜像来源已写入 .env：$REGISTRY / tag=$IMAGE_TAG"
}

gen_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 32 | tr -d '\n'
    else
        docker run --rm "$NODE_IMAGE" node -e \
            'process.stdout.write(require("crypto").randomBytes(32).toString("base64"))'
    fi
}

write_env() {
    local envfile="$SRC_DIR/.env"
    if [ -f "$envfile" ]; then
        info "保留既有 .env（不覆盖：其中的 ENCRYPTION_MASTER_KEY 一旦改变，已存厂商密钥将无法解密）"
        if [ "$USE_IMAGE" = "true" ]; then
            sync_image_env "$envfile"
        fi
        return 0
    fi
    [ -n "$PG_PASSWORD" ] || PG_PASSWORD="$(gen_secret | tr -d '/+=' | cut -c1-24)"
    umask 077
    cat > "$envfile" <<EOF
# 由 deploy/docker-deploy.sh 于 $(date '+%Y-%m-%d %H:%M:%S') 生成
# 含明文密钥，权限 600，请勿提交 git。

# Docker Compose 形态下由 compose 覆盖成容器内网地址，这里写值只为让本机直连也能用。
DATABASE_URL=postgresql+psycopg://llmbridge:${PG_PASSWORD}@127.0.0.1:5432/llmbridge

# compose 用：db 容器与 api 容器共享这个密码
POSTGRES_PASSWORD=${PG_PASSWORD}
# 控制台对外端口（nginx 映射）
HTTP_PORT=${HTTP_PORT}

AUTO_BOOTSTRAP=true
# 容器内以服务名互访：compose 网络内的 redis 服务
REDIS_URL=redis://redis:6379/0

ALLOW_LOCAL_BASE_URL=false
JWT_SECRET=$(gen_secret)
JWT_EXPIRE_SECONDS=86400
ENCRYPTION_MASTER_KEY=$(gen_secret)

JUDGE_PROVIDER=mock
JEV_API_KEY=
JEV_BASE_URL=https://api.typesafe.ai/v1/systemone
DECIDER_TIMEOUT_MS=3000
ROUTE_CONFIDENCE_THRESHOLD_T2=0.5

# 首次安装模型池为空，请在控制台「模型池」页添加模型后，把其 id 填到这里。
DEFAULT_MODEL_ID=1
REQUEST_TIMEOUT_MS=30000
ROUTE_CACHE_TTL=3600

LOG_BATCH_SIZE=50
LOG_FLUSH_SECONDS=1.0
ENABLE_TOOL_EXECUTION=false
TOOL_RESULT_MAX_CHARS=8000
EOF
    if [ "$USE_IMAGE" = "true" ]; then
        sync_image_env "$envfile"
    fi
    chmod 600 "$envfile"
    ok "已生成 $envfile（密钥为随机值）"
}

# =============================================================================
#  前端构建
# =============================================================================

build_frontend() {
    local dist="$SRC_DIR/admin-web/dist"
    if [ "$USE_IMAGE" = "true" ]; then
        # 容器库形态下前端 dist 已经在 llmbridge-web 镜像里，本机不需要构建。
        info "容器库形态：跳过前端构建（dist 已随 web 镜像发布）"
        return 0
    fi
    if [ "$SKIP_FRONTEND" = "true" ]; then
        [ -d "$dist" ] || die "指定了 --skip-frontend 但 $dist 不存在。"
        info "跳过前端构建（--skip-frontend）"
        return 0
    fi

    step "构建控制台前端"
    [ -f "$SRC_DIR/admin-web/package.json" ] || die "未找到 admin-web/package.json。"
    info "用 $NODE_IMAGE 在容器内构建（宿主机无需安装 Node.js）"
    # node_modules 挂命名卷：避免把大量文件写进宿主机（Linux 上还会留下 root 属主文件），
    # 同时让第二次构建复用依赖缓存。
    docker run --rm \
        -v "$SRC_DIR/admin-web:/app" \
        -v "llmbridge-nm:/app/node_modules" \
        -w /app \
        "$NODE_IMAGE" \
        sh -c 'npm ci --no-audit --no-fund && npm run build' \
        || die "前端构建失败（常见原因：npm 源不可达）。可改用 --skip-frontend 自备 dist。"
    [ -f "$dist/index.html" ] || die "构建结束但未找到 $dist/index.html。"
    ok "前端产物就绪：$dist"
}

# =============================================================================
#  启停
# =============================================================================

compose() {
    # COMPOSE_FILE 由 --image 决定（deploy/docker-compose.yml 或 .image.yml）。
    # cd 到 SRC_DIR 是必要的：compose 从这里读 .env 做变量插值，
    # 而编排文件里的 env_file 正是相对路径 ../.env。
    ( cd "$SRC_DIR" && $DC -f "$COMPOSE_FILE" "$@" )
}

do_deploy() {
    step "环境检查"
    check_docker
    if [ "$USE_IMAGE" = "true" ]; then
        step "准备编排文件"
    else
        step "准备源码"
    fi
    resolve_any true
    step "准备配置"
    write_env
    build_frontend

    if [ "$USE_IMAGE" = "true" ]; then
        step "拉取镜像并启动服务"
        info "镜像来源：$REGISTRY（tag=$IMAGE_TAG）"
        info "容器库不可达或标签不存在时，先执行 deploy/publish-image.sh 发布镜像。"
        compose pull || die "拉取镜像失败。请确认容器库可访问、且 $IMAGE_TAG 已发布。"
        compose up -d || die "启动失败。查看日志：bash $0 logs"
    else
        step "构建并启动服务"
        info "首次执行需要构建后端镜像并拉取 postgres/redis/nginx 镜像，约 2~5 分钟。"
        compose up -d --build || die "启动失败。查看日志：bash $0 logs"
    fi

    step "等待服务就绪"
    if command -v curl >/dev/null 2>&1; then
        local i=1 url="http://127.0.0.1:${HTTP_PORT}/health"
        while [ "$i" -le 60 ]; do
            if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
                ok "服务已就绪（第 ${i} 次探测）"
                break
            fi
            sleep 2
            i=$((i + 1))
        done
    else
        warn "未找到 curl，跳过自动探活。请手动访问 http://127.0.0.1:${HTTP_PORT}/health"
    fi

    compose ps

    local form_note="源码形态（本机构建）"
    if [ "$USE_IMAGE" = "true" ]; then
        form_note="容器库形态（${REGISTRY} / tag=${IMAGE_TAG}）"
    fi

    cat <<EOF

${C_GREEN}${C_BOLD}部署完成${C_OFF}

  控制台       http://127.0.0.1:${HTTP_PORT}/admin
  默认账号     admin / admin123  ${C_RED}（首次登录后立即修改）${C_OFF}
  部署形态     ${form_note}
  部署目录     ${SRC_DIR}
  配置文件     ${SRC_DIR}/.env
  日志         bash $0 logs
  停止         bash $0 down

${C_YELLOW}模型池初始为空是有意设计${C_OFF}
  接入通道已预置 13 家厂商 / 24 条通道，填 API Key 即可接入；
  模型需在「模型池」页手动添加，再把其 id 填进 .env 的 DEFAULT_MODEL_ID 后重启 api 服务。

${C_YELLOW}生产必做${C_OFF}：前置反向代理 + HTTPS；.env 的 ALLOW_LOCAL_BASE_URL 保持 false；
  备份 ENCRYPTION_MASTER_KEY（丢失 = 已存厂商密钥不可恢复）。

EOF
}

do_status() {
    check_docker
    resolve_any false
    compose ps
    echo
    if ! command -v curl >/dev/null 2>&1; then
        warn "未找到 curl，跳过健康检查。"
        return 0
    fi
    if curl -fsS --max-time 3 "http://127.0.0.1:${HTTP_PORT}/health" 2>/dev/null; then
        echo
        ok "健康检查通过：http://127.0.0.1:${HTTP_PORT}"
    else
        warn "健康检查失败。可能端口不是 ${HTTP_PORT}（看 .env 的 HTTP_PORT），或服务未启动。"
    fi
}

do_purge() {
    check_docker
    resolve_any false
    warn "即将停止服务并删除数据卷（PostgreSQL 与 Redis 数据全部丢失）"
    if [ "$ASSUME_YES" != "true" ]; then
        printf '确认？不可恢复 [y/N] '
        read -r ans
        case "$ans" in y|Y|yes|YES) ;; *) info "已取消。"; exit 0 ;; esac
    fi
    compose down -v
    ok "服务与数据卷已删除（编排文件与 .env 保留在 $SRC_DIR）"
}

# =============================================================================

case "$ACTION" in
    deploy)  do_deploy ;;
    status)  do_status ;;
    logs)    check_docker; resolve_any false; compose logs -f ${LOG_SERVICE:+"$LOG_SERVICE"} ;;
    down)    check_docker; resolve_any false; compose down; ok "已停止（数据卷保留）" ;;
    purge)   do_purge ;;
    upgrade)
        check_docker
        resolve_any true
        if [ "$USE_IMAGE" = "true" ]; then
            # 容器库形态的「升级」= 拉新标签 + 重建容器，不碰代码。
            info "拉取 $REGISTRY 上的 tag=$IMAGE_TAG"
            compose pull || die "拉取镜像失败。确认该标签已发布（deploy/publish-image.sh）。"
            compose up -d
            ok "升级完成（tag=$IMAGE_TAG）"
        else
            build_frontend
            compose up -d --build
            ok "升级完成"
        fi
        ;;
esac
