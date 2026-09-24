#!/usr/bin/env bash
#
# =============================================================================
#  LLM 路由中转系统（llmbridge）· Docker Compose 一键部署脚本
# =============================================================================
#
#  用法（Sub2API 形态：脚本只生成配置，启停用标准 docker compose 命令）：
#    mkdir -p llmbridge && cd llmbridge
#    docker run --rm --entrypoint cat \
#      registry.cn-hangzhou.aliyuncs.com/winyeahs/llmbridge-api:1.0.0 \
#      /opt/llmbridge/deploy/docker-deploy.sh | bash -s --    # 只生成 ./docker-compose.yml + ./.env
#    docker compose up -d                                     # 启动（首次自动拉镜像）
#    docker compose logs -f api                               # 跟随后端日志
#
#    # 脚本连启动一起做完（生成配置 + 拉镜像 + 起容器 + 等健康检查 + 打印地址）：
#    docker run --rm --entrypoint cat \
#      registry.cn-hangzhou.aliyuncs.com/winyeahs/llmbridge-api:1.0.0 \
#      /opt/llmbridge/deploy/docker-deploy.sh | bash -s -- deploy
#
#    # 换镜像库（阿里云以外的第三方镜像库）：生成时追加
#    #   --registry <第三方镜像库host>/<命名空间>
#    # 私有库再给 REGISTRY_USER / REGISTRY_PASSWORD（deploy 拉取前自动 docker login）。
#
#    # 本地已有源码、想改代码后再构建（可选形态）：
#    bash deploy/docker-deploy.sh deploy --source
#
#  目标机最低要求（云端直拉形态）：
#    1) 装了 Docker（含 compose v2）；2) 能访问容器库（默认阿里云 ACR，可用 --registry 换任意第三方镜像库）。
#    就这两样 —— 不需要源码、不需要 Node、不需要 .env 模板、不需要登录容器库
#    （镜像仓库是公开的，匿名可拉）、除容器库外不访问任何外网（编排文件内嵌在本脚本里）。
#    默认只在当前目录生成编排文件与含随机密钥的 .env（不碰 Docker）；末尾加 deploy 才会
#    拉镜像、起容器、等健康检查、打印访问地址与账号。
#
#  为什么安装脚本要从容器库的镜像里取：
#    脚本本身也得先送到目标机，而 GitHub（raw.githubusercontent.com）在国内不可达 ——
#    `curl ... | bash` 在目标机上是**必然失败**的；容器库反而是目标机唯一一定能访问的
#    地址（否则业务镜像也拉不下来）。api 镜像里放了本脚本的一份
#    （/opt/llmbridge/deploy/docker-deploy.sh），而安装流程随后要拉的就是这套镜像，
#    所以取脚本这一步**不会多下载一个字节**。
#    ⚠️ `--entrypoint cat` 不能省：api 镜像默认入口会先做数据库初始化再起服务。
#    另有 8 MB 的纯安装器镜像 <registry>/llmbridge-deploy（更轻，但要求该仓库在容器库
#    里被设为公开，否则匿名拉取 401），以及 `bash deploy/docker-deploy.sh`（自家运维在
#    源码仓库里用）—— 三者跑的是同一个脚本、同一套编排，结果一致。
#
#  子命令：
#    (无) / prepare  **默认**：只在当前目录生成 ./docker-compose.yml + ./.env
#                    （含随机密钥），全程不碰 Docker —— 之后启停用标准 docker compose
#    deploy          一键全量：生成配置 + 拉镜像 + 起容器 + 等健康检查 + 打印地址
#    status          查看容器状态与健康检查
#    logs            跟随日志（可跟服务名：logs api）
#    down            停止并移除容器（保留数据卷）
#    upgrade         拉取最新镜像 + 重启（数据保留）
#    purge           停止并**删除数据卷**（不可恢复，二次确认）
#
#  选项：
#    --port <n>         控制台对外端口（默认 8081；prepare 时写进 ./.env）
#    --pg-password <p>  PostgreSQL 密码（默认随机 32 位）
#    --registry <host/ns>  容器库地址与命名空间（默认阿里云 ACR；可换任意第三方镜像库）
#    --tag <tag>           镜像版本标签（默认 1.0.0）
#    --dir <path>       部署目录（**仅源码形态**默认 ./llmbridge；镜像形态显式传了才用，
#                       默认就落当前目录；prepare 模式下传了会被忽略并提示）
#    --ref <ref>        源码版本：分支 / tag（默认 main；镜像形态下无意义）
#    --skip-frontend    跳过前端构建（仅源码形态、你已有 admin-web/dist 时使用）
#    --source           本地源码构建形态（配合 deploy）：不拉镜像，改用当前源码本地构建。
#                       只有「你有源码、要改了代码再构建」时才用；默认是云端直拉。
#    -y, --yes          非交互
#
#  环境变量：
#    LLMBRIDGE_REGISTRY / LLMBRIDGE_TAG   同 --registry / --tag（--image 形态）
#    REGISTRY_USER / REGISTRY_PASSWORD    私有容器库的凭据：设了就在 pull 前自动
#                                         docker login（--password-stdin）。凭据只经环境变量，
#                                         不写进 .env、不落盘、不进日志。
#
#  两种形态的区别（别混用）：
#    云端直拉形态（默认，即 --image）  镜像从容器库拉取，api 与 web 自带全部内容（含 dist 与 nginx.conf），
#                      目标机只需要一个编排文件和一个 .env，**不需要任何源码、不需要本地构建**。
#    源码形态（加 --source 开启）  镜像在本机构建；前端 dist 是 bind mount 进 nginx 的，
#                      所以**必须**先 build 前端，且目标机要么持有源码、要么能访问 GitHub。
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

# 本脚本用到数组与 $'...'，必须是 bash。被 sh/dash 执行时 `set -o pipefail` 会先报
# "Illegal option"，那句报错离真实原因很远，所以在这里先给一句人话。
if [ -z "${BASH_VERSION:-}" ]; then
    echo "[失败] 本脚本需要 bash 执行（用到数组），不能用 sh/dash。" >&2
    echo "       请用：bash docker-deploy.sh" >&2
    exit 1
fi

set -euo pipefail

REPO_SLUG="dragonlin-ai/llmbridge"
DEFAULT_REF="main"
NODE_IMAGE="node:22-alpine"

DEPLOY_DIR="./llmbridge"
DIR_GIVEN="false"
REF="$DEFAULT_REF"
HTTP_PORT="8081"
PORT_GIVEN="false"
PG_PASSWORD=""
SKIP_FRONTEND="false"
ASSUME_YES="false"
ACTION="prepare"
USE_IMAGE="true"
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
    # `docker run ... | bash -s -- --help` 这种管道执行时 $0 不是路径、读不到脚本自身，
    # 于是退化为提示 —— 想把完整用法打出来，先把脚本落盘（见下面的提示命令）。
    if [ ! -f "$0" ]; then
        echo "llmbridge Docker Compose 一键部署脚本。"
        printf '完整用法：docker run --rm %s/llmbridge-deploy:%s > docker-deploy.sh && bash docker-deploy.sh --help\n' \
            "$REGISTRY" "$IMAGE_TAG"
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

# 把「怎么再次调用本脚本」算成一个字符串，供文案里复用。
#   在磁盘上跑（仓库内 / 手工落盘）→ `bash <路径> <子命令>`
#   管道里跑（docker run ... | bash -s --）→ 用同一条 docker run 管道再调一次
#     （安装器镜像这时已经在本机了，不需要联网）
# 不这样区分的话，管道形态下会打出 `bash bash logs` 这种没法照做的提示。
self_cmd() {
    if [ -f "$0" ]; then
        printf 'bash %s' "$0"
    else
        # 管道形态：用「同一条 docker run 管道」再调一次（api 镜像这时已在本机，不必联网）。
        # 与脚本头部推荐的那一条保持一致（安装脚本的载体是 api 镜像，见头部说明）。
        printf 'docker run --rm --entrypoint cat %s/llmbridge-api:%s /opt/llmbridge/deploy/docker-deploy.sh | bash -s --' \
            "$REGISTRY" "$IMAGE_TAG"
    fi
}

# ---- 子命令（第一个位置参数）----
LOG_SERVICE=""
if [ $# -gt 0 ]; then
    case "$1" in
        prepare|deploy|status|logs|down|purge|upgrade) ACTION="$1"; shift ;;
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
        --dir)          DEPLOY_DIR="${2:?--dir 需要参数}"; DIR_GIVEN="true"; shift 2 ;;
        --ref)          REF="${2:?--ref 需要参数}"; shift 2 ;;
        --port)         HTTP_PORT="${2:?--port 需要参数}"; PORT_GIVEN="true"; shift 2 ;;
        --pg-password)  PG_PASSWORD="${2:?--pg-password 需要参数}"; shift 2 ;;
        --image)        USE_IMAGE="true"; shift ;;
        --source)       USE_IMAGE="false"; shift ;;
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
# registry 主机名 = 第一段，用于登录检测（`registry.cn-hangzhou.aliyuncs.com/winyeahs` → 前半段）。
REGISTRY_HOST="${REGISTRY%%/*}"

if [ "$USE_IMAGE" = "true" ]; then
    COMPOSE_FILE="deploy/docker-compose.image.yml"
    # 容器库形态下"源码版本"指的是镜像标签，不是 git ref。
    if [ "$SKIP_FRONTEND" = "true" ]; then
        warn "--image 形态不需要 --skip-frontend（镜像里已含前端），该选项被忽略。"
        SKIP_FRONTEND="false"
    fi
fi

# ---- 形态自检：运维子命令不必每次手写 --image ----
# 部署目录里**只有** docker-compose.image.yml（没有源码形态的 docker-compose.yml）时，
# 自动按容器库形态处理。理由：`status` / `logs` / `down` / `upgrade` 这些子命令一旦漏了
# --image，脚本会去源码形态找 pyproject.toml，报出「未找到部署目录」—— 而目录明明在，
# 真实原因只是漏了一个开关。实测踩到过（管道形态下尤其容易漏）。
if [ "$USE_IMAGE" != "true" ] \
   && [ ! -f "$DEPLOY_DIR/deploy/docker-compose.yml" ] \
   && [ -f "$DEPLOY_DIR/deploy/docker-compose.image.yml" ]; then
    USE_IMAGE="true"
    COMPOSE_FILE="deploy/docker-compose.image.yml"
    info "检测到 $DEPLOY_DIR 是容器库形态部署（无源码编排），自动按 --image 处理。"
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

registry_logged_in() {
    local cfg="${DOCKER_CONFIG:-$HOME/.docker}/config.json"
    [ -f "$cfg" ] || return 1
    # 不用 grep —— 最小化环境里可能没有（见脚本头说明）。纯 shell 匹配即可。
    case "$(cat "$cfg")" in
        *"$REGISTRY_HOST"*) return 0 ;;
        *) return 1 ;;
    esac
}

ensure_registry_login() {
    # 只在容器库形态下需要。公开库什么都不用做；私有库靠环境变量里的凭据登录。
    # 凭据**只经环境变量**，不写进 .env、不落盘、不进日志。
    [ "$USE_IMAGE" = "true" ] || return 0
    if [ -z "${REGISTRY_USER:-}" ] || [ -z "${REGISTRY_PASSWORD:-}" ]; then
        # 没给凭据就交给 docker 自己：公开库能直接拉；私有库会在 pull 时以 401 报错，
        # 那时下面的提示会告诉用户怎么办（比起静默失败，不如让 docker 的原生报错出现）。
        return 0
    fi
    if registry_logged_in; then
        info "检测到已登录 $REGISTRY_HOST"
        return 0
    fi
    info "使用环境变量中的凭据登录 $REGISTRY_HOST（用户名：$REGISTRY_USER）"
    printf '%s' "$REGISTRY_PASSWORD" | docker login "$REGISTRY_HOST" \
        --username "$REGISTRY_USER" --password-stdin >/dev/null \
        || die "登录 $REGISTRY_HOST 失败。请核对 REGISTRY_USER / REGISTRY_PASSWORD，或先手动 docker login。"
    ok "已登录 $REGISTRY_HOST"
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
        die "未找到部署目录（$DEPLOY_DIR）。请先执行部署：$(self_cmd)"

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
#  容器库形态：只落一个编排文件 + 一个 .env，**不联网下载任何东西**
# -----------------------------------------------------------------------------
#
# 为什么只要一个文件：api 与 web 两个镜像里已经装好了后端代码、前端 dist 与
# nginx.conf，目标机剩下的可变部分只有「编排文件 + .env」。
# 编排文件里 env_file 写的是 ../.env，与放置位置（<部署目录>/deploy/）配套。
#
# 为什么编排改为**内嵌**进本脚本（原来是 curl 下载 raw.githubusercontent.com）：
#   国内网络下 raw.githubusercontent.com 基本不可达 —— 那条下载路径在目标机上
#   必然超时失败；而这个脚本本身也只能靠 scp/微信/U 盘进目标机（GitHub 同样拉不动）。
#   内嵌之后目标机只需要这一个文件：`bash docker-deploy.sh --image` 全程除容器库
#   外不访问任何外网。
#
# ⚠️ 内嵌副本与 deploy/docker-compose.image.yml 内容等价，是「两份」。改其一
#    必须同步另一；在仓库内执行时会自动比对，不一致就告警（见 resolve_image_source）。

IMAGE_COMPOSE_REL="deploy/docker-compose.image.yml"

write_image_compose() {
    # 内嵌副本写到 $1。分隔符带引号 → 内容里的 ${...} 一律不展开。
    local dest="$1"
    mkdir -p "${dest%/*}"
    cat > "$dest" <<'LLMBRIDGE_COMPOSE_EOF'
# LLM 路由中转系统 · Docker Compose 编排（容器库拉取形态）
#
# 与 deploy/docker-compose.yml 的区别，只有一句话：
#   **这份文件不含任何 `build:` 段，全部镜像从容器库拉取，目标机不需要源码。**
#
# 目标机推荐用法（Sub2API 形态：脚本只生成配置，启停用标准 docker compose）：
#   mkdir -p llmbridge && cd llmbridge
#   docker run --rm --entrypoint cat \
#     registry.cn-hangzhou.aliyuncs.com/winyeahs/llmbridge-api:1.0.0 \
#     /opt/llmbridge/deploy/docker-deploy.sh | bash -s --    # 只生成 ./docker-compose.yml + ./.env
#   docker compose up -d                                     # 启动（首次自动拉镜像）
#   docker compose logs -f api                               # 跟随后端日志
#   # 连启动一起做完（生成配置 + 拉镜像 + 起容器 + 等健康检查）：命令末尾加 deploy
#   # 需要换端口：   ... | bash -s -- --port 8080
#
# 本文件是**唯一真源**：可读、可 diff，也可留在仓库根直接使用 ——
#   docker compose --env-file ./.env -f deploy/docker-compose.image.yml up -d
#   ⚠️ `--env-file ./.env` 不能省：compose 的**变量插值**只读「编排文件所在目录」的
#      `.env`（即 deploy/.env），必须显式指到根下那一份，否则报
#      `required variable POSTGRES_PASSWORD is missing a value`。
#   而脚本生成的**根目录副本 ./docker-compose.yml** 已把 env_file 改写为同目录的 ./.env，
#   两条路径都落在同一份文件上，所以标准 `docker compose up -d` 不需要 --env-file。
#
# ⚠️ docker-deploy.sh 里**内嵌了一份等价内容**，供「手上只有那一个脚本文件」的
#    目标机离线使用（国内网络下 raw.githubusercontent.com 不可达，原来那条
#    下载编排的路径在目标机上必然失败）。改动本文件必须同步内嵌副本 ——
#    在仓库内执行 `bash deploy/docker-deploy.sh deploy` 时会自动比对并告警。
#
# 只有 4 个服务，没有源码目录、没有 bind mount、没有前端构建步骤：
#   api  ← llmbridge-api:<tag>   后端
#   web  ← llmbridge-web:<tag>   nginx + 已内置的 dist 与 nginx.conf
#   db   ← postgres:16-alpine
#   redis← redis:7-alpine
#
# ⚠️ 镜像仓库必须是**公开**的，目标机才不用 docker login（公开库匿名可拉）。
#    私有库请在目标机先 `docker login <host>`，或给脚本传 REGISTRY_USER /
#    REGISTRY_PASSWORD 环境变量（脚本会在 pull 前自动登录，凭据只经环境变量、不落盘）。
# ⚠️ 升级前先确认目标 tag 存在：`docker manifest inspect <image>`
# ⚠️ 与 docker-compose.yml 共用 project name，因此**共用同一套数据卷**；
#    两种形态互相切换时先 `down` 再 `up`，否则会留下上一种形态的孤儿容器。

name: llmbridge

services:
  api:
    # 没有 build 段。想本地改代码就回到 docker-compose.yml。
    image: ${LLMBRIDGE_REGISTRY:-registry.cn-hangzhou.aliyuncs.com/winyeahs}/llmbridge-api:${LLMBRIDGE_TAG:-1.0.0}
    restart: unless-stopped
    env_file:
      - ../.env
    environment:
      # compose 内网用服务名 `db` 互访；这里覆盖 .env 里的 127.0.0.1。
      # 驱动固定 psycopg3 —— 写成 asyncpg 会因为依赖未安装而启动即失败。
      DATABASE_URL: postgresql+psycopg://llmbridge:${POSTGRES_PASSWORD:?POSTGRES_PASSWORD 未设置}@db:5432/llmbridge
      LLMBRIDGE_REPO_ROOT: /app
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "/usr/local/bin/healthcheck.py"]
      interval: 30s
      timeout: 5s
      start_period: 25s
      retries: 3
    networks: [llmbridge]

  web:
    image: ${LLMBRIDGE_REGISTRY:-registry.cn-hangzhou.aliyuncs.com/winyeahs}/llmbridge-web:${LLMBRIDGE_TAG:-1.0.0}
    restart: unless-stopped
    ports:
      - "${HTTP_PORT:-8081}:80"
    depends_on:
      api:
        condition: service_started
    networks: [llmbridge]
    # 前端产物与 nginx.conf 都在镜像里，所以这里**不需要任何 volumes**。
    # 想临时改反代规则（例如加 HTTPS、调 client_max_body_size），挂一份覆盖即可：
    # volumes:
    #   - ../deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    #   - ../deploy/certs:/etc/nginx/certs:ro

  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: llmbridge
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD 未设置}
      POSTGRES_DB: llmbridge
      # 中文环境常踩：容器默认 C locale，中文排序/比较会不合预期。
      POSTGRES_INITDB_ARGS: --encoding=UTF8 --locale=C
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U llmbridge -d llmbridge"]
      interval: 10s
      timeout: 5s
      retries: 10
    networks: [llmbridge]

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 10
    networks: [llmbridge]

# 与 docker-compose.yml 同名，用于跨形态复用数据（见文件头说明）。
volumes:
  pgdata: {}
  redisdata: {}

networks:
  llmbridge:
    driver: bridge
LLMBRIDGE_COMPOSE_EOF
}

# 仓库内执行时比对内嵌副本与真源，防止两边漂移（这是「两份内容」的唯一代价，
# 所以用一个明示告警把它变成可见问题，而不是等目标机上出现诡异差异）。
compare_embedded_compose() {
    local repo_file="$1" tmp
    tmp="$(mktemp)"
    write_image_compose "$tmp"
    if [ "$(cat "$tmp")" = "$(cat "$repo_file")" ]; then
        rm -f "$tmp" 2>/dev/null || true
        return 0
    fi
    rm -f "$tmp" 2>/dev/null || true
    warn "内嵌编排与 $repo_file 内容不一致！请同步 deploy/docker-compose.image.yml 与 deploy/docker-deploy.sh 的内嵌副本。"
}

# 根形态副本：把内嵌编排里的 `env_file: ../.env` 改写成 `env_file: .env` 后写到 $1。
# 为什么必须改这一行（Sub2API 形态的命门）：
#   `docker compose up -d`（不带 -f / --env-file）要求编排就叫 ./docker-compose.yml 落在
#   当前目录；compose 的**变量插值**自动读当前目录的 .env（这条没问题），但 `env_file:`
#   指令是**相对编排文件**解析的 —— 编排挪到根目录后，../.env 会指到上一层，容器起来
#   就没有环境变量。改写成 .env 后两条路径都落在同一份 ./.env，用户用最普通的
#   `docker compose up -d` 即可，不再需要 --env-file。
write_root_compose() {
    local dest="$1" tmp line content=""
    tmp="$(mktemp)"
    write_image_compose "$tmp"
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            "      - ../.env") line="      - .env" ;;
        esac
        content="${content}${line}"$'\n'
    done < "$tmp"
    rm -f "$tmp" 2>/dev/null || true

    if [ -f "$dest" ]; then
        # 内容判据：只有含 llmbridge-api 的才是本项目的编排，否则拒绝覆盖（防误伤）。
        case "$(cat "$dest")" in
            *llmbridge-api*) ;;
            *) die "$dest 已存在且不是本项目的编排，拒绝覆盖。请 mkdir -p llmbridge && cd llmbridge 后重跑。" ;;
        esac
        if [ "$(cat "$dest")" = "$(printf '%s' "$content")" ]; then
            info "$dest 已是最新（幂等重跑），未改动。"
            return 0
        fi
        warn "$dest 与默认编排不一致（可能被手工改过），将被覆盖。"
    fi
    printf '%s' "$content" > "$dest"

    # 写后自检：改写必须真的发生，否则容器会因读不到 ../.env 而起不来。
    case "$(cat "$dest")" in
        *"      - ../.env"*) die "生成 $dest 失败：env_file 仍是 ../.env（内嵌编排可能已变更，请检查本脚本）。" ;;
        *"      - .env"*) ;;
        *) die "生成 $dest 失败：未找到 env_file 行（内嵌编排可能已变更，请检查本脚本）。" ;;
    esac
    ok "已写入编排文件：$dest（env_file 指向同目录 ./.env）"
}

resolve_image_source() {
    # 入参保留是为了与源码形态共用调用签名；--image 已不依赖网络。
    local rel="$IMAGE_COMPOSE_REL"

    # step 0：当前目录就是 prepare 生成的根形态部署 → status/logs/down/upgrade/purge
    #   与 deploy 全部直接用它。判据用**内容**而非文件名：任何项目都可能有
    #   ./docker-compose.yml，只有含 llmbridge-api 的才是本项目的。
    if [ -f "./docker-compose.yml" ]; then
        case "$(cat ./docker-compose.yml)" in
            *llmbridge-api*)
                SRC_DIR="$(pwd)"
                COMPOSE_FILE="docker-compose.yml"
                info "使用当前目录的编排文件：$SRC_DIR/docker-compose.yml"
                return 0
                ;;
        esac
    fi

    # 脚本在仓库内 → 用仓库里那份（唯一真源），并比对防漂移。
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
            compare_embedded_compose "$SRC_DIR/$rel"
            return 0
        fi
    fi

    # 旧布局部署目录里已有 → 复用（向后兼容：上一版脚本把编排落在
    # <dir>/deploy/docker-compose.image.yml）。--image 形态刻意不 git pull：
    # 这一形态的"版本"由镜像标签决定，拉代码只会拉回与本机镜像无关的源码。
    if [ -f "$DEPLOY_DIR/$rel" ]; then
        SRC_DIR="$(cd "$DEPLOY_DIR" && pwd)"
        info "复用既有编排文件：$SRC_DIR/$rel"
        return 0
    fi

    # 都没有 → 落**根形态**副本：默认就在当前目录（Sub2API 布局），
    # 只有显式传了 --dir 才 mkdir 到指定目录。目标机（只有本脚本一个文件）走的就是这条路。
    if [ "$DIR_GIVEN" = "true" ]; then
        mkdir -p "$DEPLOY_DIR"
        DEPLOY_DIR="$(cd "$DEPLOY_DIR" && pwd)"
        SRC_DIR="$DEPLOY_DIR"
    else
        SRC_DIR="$(pwd)"
    fi
    COMPOSE_FILE="docker-compose.yml"
    write_root_compose "$SRC_DIR/docker-compose.yml"
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

env_get() {
    # 从 .env 读一个键的值（纯 shell，仍不依赖 grep）。
    local envfile="$1" key="$2" line
    [ -f "$envfile" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            "$key="*) printf '%s' "${line#"$key="}" ; return 0 ;;
        esac
    done < "$envfile"
}

sync_http_port_from_env() {
    # 运维子命令（status 等）必须用**部署时写进 .env 的端口**，不能用命令行默认值。
    # 不同步的话：`--port 8099` 装完，`status` 会去探 80 端口并报「健康检查失败」，
    # 让人以为服务挂了（实测踩到）。只有用户显式传了 --port 才以命令行为准。
    if [ "$PORT_GIVEN" = "true" ]; then
        return 0
    fi
    local v
    v="$(env_get "$SRC_DIR/.env" HTTP_PORT)"
    if [ -n "$v" ]; then
        HTTP_PORT="$v"
    fi
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
    # 三种来源依次尝试，**不依赖 openssl** —— 最小化的服务器/精简系统上经常没有它，
    # 而它恰恰是「目标机自动跑通」最容易被卡住的一步（旧版本直接去拉 node 镜像）。
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 32 | tr -d '\n'
    elif command -v dd >/dev/null 2>&1 && command -v base64 >/dev/null 2>&1 && [ -r /dev/urandom ]; then
        # 用 dd 而不是 head：head 在极简环境里可能缺失（本项目开发机的 Git Bash 就是）。
        dd if=/dev/urandom bs=32 count=1 2>/dev/null | base64 | tr -d '\n'
    else
        # 最后兜底才用容器：它要拉 node 镜像，在国内网络下可能是慢甚至失败的一步，
        # 所以只在前两条都不成立时才走这里（例如在 macOS/Windows 上跑且无 openssl）。
        docker run --rm "$NODE_IMAGE" node -e \
            'process.stdout.write(require("crypto").randomBytes(32).toString("base64"))'
    fi
}

write_env() {
    local envfile="$SRC_DIR/.env"
    if [ -f "$envfile" ]; then
        info "保留既有 .env（不覆盖：其中的 ENCRYPTION_MASTER_KEY 一旦改变，已存厂商密钥将无法解密）"
        # 端口例外：用户显式传了 --port 就应当生效，否则 compose 映射的还是旧端口，
        # 而探活按新端口去探 —— 报「健康检查失败」，现象与真实原因差得很远。
        if [ "$PORT_GIVEN" = "true" ]; then
            set_env_kv "$envfile" HTTP_PORT "$HTTP_PORT"
            info "已按 --port 更新 .env：HTTP_PORT=$HTTP_PORT"
        fi
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
    # cd 到 SRC_DIR 是让相对路径与手册一致，但**光 cd 不够**：
    #   compose 做变量插值（${POSTGRES_PASSWORD:?...} 之类）时只读「项目目录」下的 .env，
    #   而项目目录默认是**编排文件所在目录**（<SRC_DIR>/deploy），不是 SRC_DIR。
    #   不显式指定就必然报
    #     error while interpolating services.api.environment.DATABASE_URL:
    #     required variable POSTGRES_PASSWORD is missing a value
    #   这条实测踩到过：容器都还没起，pull 就失败了。
    # 注意：编排里的 `env_file: ../.env` 是另一条路径（相对编排文件解析），只影响容器
    #   进程的环境变量，救不了插值 —— 两件事都要成立，所以两边都指向同一个文件。
    # 文件被手工删掉时退回 /dev/null，保证 `down` / `status` 这类运维子命令仍可用。
    local envf="$SRC_DIR/.env"
    [ -f "$envf" ] || envf=/dev/null
    ( cd "$SRC_DIR" && $DC --env-file "$envf" -f "$COMPOSE_FILE" "$@" )
}

compose_pull() {
    # 拉取是幂等的，失败就再试一次。国内镜像加速器**偶发** short read / unexpected EOF
    # （实测：redis 成功、postgres 报 `short read: expected 9065 bytes but got 0`），
    # 直接 die 会让「一条命令装完」在最后一公里失败，而重试通常一次就过。
    if compose pull; then
        return 0
    fi
    warn "镜像拉取失败，10 秒后重试一次（国内加速器偶发 short read / EOF）..."
    sleep 10
    compose pull
}

probe_once() {
    # 探活优先用本机 curl —— 它测的是「用户真正要访问的那条路」：
    # 宿主机 → 映射端口 → nginx → api。
    if command -v curl >/dev/null 2>&1; then
        curl -fsS --max-time 3 "http://127.0.0.1:${HTTP_PORT}/health" >/dev/null 2>&1
        return $?
    fi
    # 目标机没有 curl（最小化发行版常见）时退一步：进 api 容器用 python 打自己的 /health。
    # 好处是**不依赖服务名**，两种编排形态（服务名叫 api/web 或 api/nginx）都通用。
    # 这一条只能证明后端起来了，不能证明 nginx 映射通了 —— 所以只在没有 curl 时才用。
    compose exec -T api python -c \
        "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)" \
        >/dev/null 2>&1
}

# 默认动作（Sub2API 形态）：只在当前目录生成编排 + .env，**全程不碰 Docker**。
# 之后的启停交给最标准的 `docker compose up -d` / `docker compose logs -f api`。
do_prepare() {
    step "生成部署配置（prepare：不碰 Docker）"

    if [ "$USE_IMAGE" = "false" ]; then
        die "prepare 只支持镜像形态（默认）。源码构建请用：$(self_cmd) deploy --source"
    fi
    if [ "$DIR_GIVEN" = "true" ]; then
        warn "--dir 在 prepare 模式下被忽略：配置就生成在当前目录（$(pwd)）。"
    fi
    # cwd 已有编排文件时：本项目的幂等保留；别人的拒绝覆盖。
    if [ -f "./docker-compose.yml" ]; then
        case "$(cat ./docker-compose.yml)" in
            *llmbridge-api*) info "检测到本项目已生成的 ./docker-compose.yml（幂等重跑）。" ;;
            *) die "当前目录已有不是本项目的 ./docker-compose.yml，拒绝覆盖。请 mkdir -p llmbridge && cd llmbridge 后重跑。" ;;
        esac
    fi
    # 在源码仓库根上跑：只提醒不拦（自家运维可能就是想就地生成）。
    if [ -f "./pyproject.toml" ] && [ -f "./deploy/docker-compose.yml" ]; then
        warn "当前目录是 llmbridge 源码仓库根：建议在空目录生成配置（mkdir -p ../llmbridge-deploy && cd ../llmbridge-deploy），避免与源码混放。"
    fi
    # 上一层已有旧布局/--dir 布局的部署，而当前目录还没有 .env：
    # 直接再生成一份 .env 会分叉出一套全新的空数据库（连的是新密码/新卷），
    # 现场表现为「装完发现以前的数据全没了」—— 必须拦。
    if [ ! -f "./.env" ] && { [ -f "./llmbridge/deploy/docker-compose.image.yml" ] || [ -f "./llmbridge/docker-compose.yml" ]; }; then
        die "检测到 ./llmbridge/ 下已有本项目的部署，而当前目录没有 .env —— 在这里再生成会分叉出一套全新的空数据库。请二选一：cd llmbridge 后重跑本脚本（沿用既有 .env），或先 mv ./llmbridge <备份名> 再部署。"
    fi

    SRC_DIR="$(pwd)"
    COMPOSE_FILE="docker-compose.yml"
    write_root_compose "./docker-compose.yml"
    write_env
    # 端口以刚生成/既有的 .env 为准（用户没显式传 --port 时），摘要里才打得对。
    sync_http_port_from_env

    # 下面这段会进 unquoted heredoc：**一个反引号都不能有**（会被命令替换执行）。
    cat <<EOF

${C_GREEN}${C_BOLD}配置已生成${C_OFF}（当前目录：${SRC_DIR}）

  ./docker-compose.yml   编排文件（api / web / db / redis 共 4 个服务）
  ./.env                 随机密钥与端口（权限 600，请勿提交 git）
  控制台端口             ${HTTP_PORT}

下一步用标准 docker compose 启停（无需再调本脚本）：
  docker compose up -d           # 启动（首次自动拉取镜像）
  docker compose logs -f api     # 跟随后端日志
  docker compose ps              # 查看容器状态
  docker compose down            # 停止（数据卷保留）

  控制台       http://127.0.0.1:${HTTP_PORT}/
  默认账号     admin / admin123  ${C_RED}（首次登录后立即修改）${C_OFF}

  改端口/换镜像版本：编辑 ./.env 的 HTTP_PORT 或 LLMBRIDGE_TAG，再 docker compose up -d
  想让脚本连启动一起做完：命令末尾加 deploy，即 $(self_cmd) deploy

EOF
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
    # 端口以 .env 为准（用户没显式传 --port 时），否则探活会去探默认的 80。
    sync_http_port_from_env
    build_frontend

    if [ "$USE_IMAGE" = "true" ]; then
        step "拉取镜像并启动服务"
        info "镜像来源：$REGISTRY（tag=$IMAGE_TAG）"
        info "容器库不可达或标签不存在时，先执行 deploy/publish-image.sh 发布镜像。"
        ensure_registry_login
        compose_pull || die "拉取镜像失败。请确认容器库可访问、且 $IMAGE_TAG 已发布；若是私有仓库，请先 docker login 或设置 REGISTRY_USER / REGISTRY_PASSWORD。"
        compose up -d || die "启动失败。查看日志：$(self_cmd) logs"
    else
        step "构建并启动服务"
        info "首次执行需要构建后端镜像并拉取 postgres/redis/nginx 镜像，约 2~5 分钟。"
        compose up -d --build || die "启动失败。查看日志：$(self_cmd) logs"
    fi

    step "等待服务就绪"
    local i=1 ready="false"
    while [ "$i" -le 60 ]; do
        if probe_once; then
            ok "服务已就绪（第 ${i} 次探测）"
            ready="true"
            break
        fi
        sleep 2
        i=$((i + 1))
    done
    if [ "$ready" != "true" ]; then
        # 不静默放过：没探通时要把「怎么看」直接给出来，否则目标机上只剩一句
        # 「装完了但打不开」，现场无从下手。
        warn "等待约 120 秒仍未通过健康检查。可能原因：镜像还在拉、db 尚未就绪、端口被占用。"
        warn "排查：$(self_cmd) status    /    $(self_cmd) logs api"
    fi

    compose ps

    local form_note="源码形态（本机构建）"
    if [ "$USE_IMAGE" = "true" ]; then
        form_note="容器库形态（${REGISTRY} / tag=${IMAGE_TAG}）"
    fi

    # 预先算好「再次调用本脚本」的写法：管道形态下不是 `bash xxx`（见 self_cmd 的说明）。
    local self_hint
    self_hint="$(self_cmd)"

    cat <<EOF

${C_GREEN}${C_BOLD}部署完成${C_OFF}

  控制台       http://127.0.0.1:${HTTP_PORT}/
               （从别的机器访问就把 127.0.0.1 换成这台机器的 IP/域名）
  默认账号     admin / admin123  ${C_RED}（首次登录后立即修改）${C_OFF}
  部署形态     ${form_note}
  部署目录     ${SRC_DIR}
  配置文件     ${SRC_DIR}/.env
  日志         ${self_hint} logs
  状态         ${self_hint} status
  停止         ${self_hint} down

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
    sync_http_port_from_env
    compose ps
    echo
    # probe_once 自带「没有 curl 就进容器探」的兜底，所以这里不再单独判断 curl。
    if probe_once; then
        ok "健康检查通过：http://127.0.0.1:${HTTP_PORT}/health"
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
    prepare) do_prepare ;;
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
            ensure_registry_login
            compose_pull || die "拉取镜像失败。确认该标签已发布（deploy/publish-image.sh）。"
            compose up -d
            ok "升级完成（tag=$IMAGE_TAG）"
        else
            build_frontend
            compose up -d --build
            ok "升级完成"
        fi
        ;;
esac
