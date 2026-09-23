#!/usr/bin/env bash
#
# =============================================================================
#  LLM 路由中转系统（llmbridge）· 一键安装脚本 —— Linux
# =============================================================================
#
#  用法：
#    # 远程（无需先克隆仓库）
#    curl -sSL https://raw.githubusercontent.com/dragonlin-ai/llmbridge/main/deploy/install.sh | sudo bash
#
#    # 仓库内（已 clone 时，直接用本地源码，不联网下载）
#    sudo bash deploy/install.sh
#
#  选项：
#    --ref <ref>        安装版本：分支名 / tag / commit（默认 main）
#    --dir <path>       安装目录（默认 /opt/llmbridge）
#    --host <addr>      监听地址（默认 127.0.0.1；对外暴露请配合反向代理）
#    --port <n>         监听端口（默认 8000）
#    --user <name>      运行用户（默认 llmbridge）
#    --postgres <url>   直接指定 PostgreSQL 连接串；不指定则用 SQLite（开箱即用）
#    --with-models      预置厂商目录时一并灌入参考模型（默认只铺接入通道）
#    --skip-frontend    不构建控制台前端（仅后端；界面需自行备好 admin-web/dist）
#    --frontend-only    只构建控制台前端后退出（补装 Node.js 后可单独跑这一步）
#    --nginx-port <n>   Nginx 对外端口（默认 80，仅用于生成站点配置）
#    --no-service       只铺代码与虚拟环境，不安装/启动 systemd 服务
#    --uninstall        卸载（保留数据目录）
#    --purge            卸载并**删除**安装目录与数据（不可恢复，二次确认）
#    -y, --yes          非交互（跳过确认）
#    -h, --help         显示帮助
#
#  幂等性：重复执行 = 升级。代码更新到指定 ref，**不动 .env、不动数据库、
#          不动已录入的厂商密钥**（密钥用 ENCRYPTION_MASTER_KEY 加密落库，
#          新生成的 .env 一旦覆盖旧值，已存密钥就全部解不开了 —— 所以只增不改）。
#
#  两件容易被忽略、但缺了就等于没装好的事：
#
#  1) 必须构建控制台前端。后端只提供 /v1 与 /admin 两套**接口**，不托管静态文件；
#     控制台是一个独立的 Vue SPA，其构建产物（admin-web/dist）需要 web 服务器托管。
#     本脚本会在有 Node.js(>=20) 时自动构建；没有则明确告警并给出补装办法 ——
#     绝不静默跳过，否则现象是「服务正常、浏览器打开一片空白」，极难归因。
#
#  2) 必须有一个 web 服务器把 dist 托起来并把 /v1、/admin 反代到后端。
#     本脚本会生成一份可直接使用的 Nginx 站点配置（省略了手工写 SSE 相关配置的坑），
#     启用命令见安装结束时的输出。Docker Compose 形态里这个角色由 nginx 容器担任。
#
#  为什么默认用 SQLite：
#    一键安装的第一要义是「装完就能打开界面」。默认模板里的 PostgreSQL 连接串
#    在没装 PG 的机器上会让服务起得来、但一访问数据就 500，用户会以为是坏包。
#    所以这里探测本机 5432 端口：通了就用 PG，不通就退 SQLite 并明确提示如何切换。
# =============================================================================

set -euo pipefail

# ---- 常量 ----
REPO_SLUG="dragonlin-ai/llmbridge"
DEFAULT_REF="main"
DEFAULT_DIR="/opt/llmbridge"
DEFAULT_HOST="127.0.0.1"
DEFAULT_PORT="8000"
DEFAULT_USER="llmbridge"
SERVICE_NAME="llmbridge"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
PY_MIN_MINOR=11   # 需要 Python >= 3.11（pyproject.toml 的 requires-python）

# ---- 运行参数（可被命令行/环境变量覆盖）----
REF="${LLMBRIDGE_REF:-$DEFAULT_REF}"
INSTALL_DIR="${LLMBRIDGE_DIR:-$DEFAULT_DIR}"
SVC_HOST="${LLMBRIDGE_HOST:-$DEFAULT_HOST}"
SVC_PORT="${LLMBRIDGE_PORT:-$DEFAULT_PORT}"
RUN_USER="${LLMBRIDGE_USER:-$DEFAULT_USER}"
PG_URL=""
WITH_MODELS="false"
NO_SERVICE="false"
ASSUME_YES="false"
SKIP_FRONTEND="false"
FRONTEND_ONLY="false"
NGINX_PORT="80"
FRONTEND_OK="false"          # 由 build_frontend 置位，供结束摘要判断怎么提示
NGINX_CONF_READY="false"     # 由 write_nginx_conf 置位
ACTION="install"

# ---- 输出工具（颜色在非 TTY 时自动关闭，避免污染管道）----
if [ -t 1 ]; then
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
    C_BLUE=$'\033[36m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
    C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_BOLD=""; C_OFF=""
fi

info()  { printf '%s[信息]%s %s\n' "$C_BLUE"   "$C_OFF" "$*"; }
ok()    { printf '%s[完成]%s %s\n' "$C_GREEN"  "$C_OFF" "$*"; }
warn()  { printf '%s[警告]%s %s\n' "$C_YELLOW" "$C_OFF" "$*" >&2; }
die()   { printf '%s[失败]%s %s\n' "$C_RED"    "$C_OFF" "$*" >&2; exit 1; }
step()  { printf '\n%s==> %s%s\n' "$C_BOLD" "$*" "$C_OFF"; }

usage() {
    # 打印文件头部的注释块（跳过 shebang，遇到首个非注释行即停）。不用固定行号 —— 头部一改就失效。
    #
    # 刻意用 shell 内建实现而不是 awk：awk 虽属 POSIX 必备，但确实存在没有它的环境
    # （本项目的开发机 Git Bash 就是，awk/head/wc 全部缺失），那样 `--help` 会输出空白。
    # 同理，管道执行（curl | bash）时 $0 不是路径、读不到脚本自身，退化为一行提示。
    if [ ! -f "$0" ]; then
        echo "llmbridge 一键安装脚本（Linux）。完整用法见 README.md 或仓库内 deploy/install.sh 头部注释。"
        exit 0
    fi
    local lineno=0 line
    while IFS= read -r line || [ -n "$line" ]; do
        lineno=$((lineno + 1))
        [ "$lineno" -eq 1 ] && continue        # 跳过 shebang
        case "$line" in
            "# "*) printf '%s\n' "${line#"# "}" ;;
            "#"*)  printf '%s\n' "${line#"#"}" ;;
            *)     break ;;                    # 首个非注释行 → 停止
        esac
    done < "$0"
    exit 0
}

# ---- 参数解析 ----
# 先把原始参数存下来：need_root 里要回显「该用什么命令重跑」，
# 但函数内的 $* 指的是**函数的**参数（空），不是脚本的 —— 直接用会漏掉用户传的选项。
ORIG_ARGS="$*"
while [ $# -gt 0 ]; do
    case "$1" in
        --ref)        REF="${2:?--ref 需要参数}"; shift 2 ;;
        --dir)        INSTALL_DIR="${2:?--dir 需要参数}"; shift 2 ;;
        --host)       SVC_HOST="${2:?--host 需要参数}"; shift 2 ;;
        --port)       SVC_PORT="${2:?--port 需要参数}"; shift 2 ;;
        --user)       RUN_USER="${2:?--user 需要参数}"; shift 2 ;;
        --postgres)   PG_URL="${2:?--postgres 需要参数}"; shift 2 ;;
        --with-models) WITH_MODELS="true"; shift ;;
        --skip-frontend) SKIP_FRONTEND="true"; shift ;;
        --frontend-only) FRONTEND_ONLY="true"; shift ;;
        --nginx-port) NGINX_PORT="${2:?--nginx-port 需要参数}"; shift 2 ;;
        --no-service) NO_SERVICE="true"; shift ;;
        --uninstall)  ACTION="uninstall"; shift ;;
        --purge)      ACTION="uninstall"; PURGE="true"; shift ;;
        -y|--yes)     ASSUME_YES="true"; shift ;;
        -h|--help)    usage ;;
        *)            die "未知参数：$1（用 --help 查看用法）" ;;
    esac
done
PURGE="${PURGE:-false}"

# sed 以 # 作分隔符、& 在替换串中有特殊含义 —— 安装目录含这两个字符会让模板替换出错，
# 与其生成一份坏配置，不如在入口就拦下。
case "$INSTALL_DIR" in
    *'#'*|*'&'*) die "安装目录不能包含 # 或 & 字符（会破坏模板替换）。请换一个路径。" ;;
esac

# =============================================================================
#  前置检查
# =============================================================================

need_root() {
    [ "$(id -u)" -eq 0 ] || die "需要 root 权限。请用：sudo bash $0 $ORIG_ARGS"
}

detect_python() {
    # 依次找 python3.13 / 3.12 / 3.11 / python3，取第一个满足 >= 3.11 的。
    # 刻意不自动 apt install python3.12：各发行版仓库版本差异大，
    # 猜错会装上 3.10 反而更糟。找不到就明确告诉用户装哪个包。
    local cand ver major minor
    for cand in python3.13 python3.12 python3.11 python3; do
        command -v "$cand" >/dev/null 2>&1 || continue
        ver="$("$cand" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "0.0")"
        major="${ver%%.*}"; minor="${ver##*.}"
        if [ "$major" -eq 3 ] && [ "$minor" -ge "$PY_MIN_MINOR" ]; then
            PY_BIN="$(command -v "$cand")"
            PY_VER="$ver"
            return 0
        fi
    done
    cat >&2 <<EOF

[失败] 未找到 Python >= 3.${PY_MIN_MINOR}。请先安装，例如：

  Debian / Ubuntu : sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
  RHEL / CentOS   : sudo dnf install -y python3 python3-pip
  Fedora          : sudo dnf install -y python3 python3-pip
  openSUSE        : sudo zypper install -y python3 python3-pip
  Alpine          : sudo apk add --no-cache python3 py3-pip python3-dev

装完重跑本脚本即可。
EOF
    exit 1
}

check_os() {
    [ "$(uname -s)" = "Linux" ] || die "本脚本仅支持 Linux。macOS 请用 deploy/apple-container.sh，Windows 请用 deploy/windows/start-backend.ps1。"
    if ! command -v systemctl >/dev/null 2>&1 && [ "$NO_SERVICE" != "true" ]; then
        warn "未检测到 systemctl —— 将自动改用 --no-service 模式（只装代码，不注册服务）。"
        NO_SERVICE="true"
    fi
}

check_prereqs() {
    # curl 或 wget 至少有一个（远程模式要下载源码）；tar 解包；python3-venv。
    if [ -z "${LOCAL_SRC:-}" ]; then
        if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
            die "需要 curl 或 wget 之一用于下载源码。"
        fi
    fi
    command -v tar >/dev/null 2>&1 || die "需要 tar。"
    # venv 模块在部分发行版是独立包，缺失时给明确指引而不是让 python -m venv 报晦涩错误。
    if ! "$PY_BIN" -c 'import venv' >/dev/null 2>&1; then
        die "Python 缺少 venv 模块。Debian/Ubuntu 请执行：sudo apt-get install -y python3-venv"
    fi
}

# =============================================================================
#  源码获取
# =============================================================================

locate_local_source() {
    # 脚本位于 <repo>/deploy/install.sh 时，说明用户在仓库里跑 —— 直接用本地源码，
    # 不联网、不下载，也避免「明明改了代码却装出旧版」。
    #
    # 通过 `curl ... | sudo bash` 执行时 $0 不是文件路径（通常是 "bash"），
    # 此时 dirname 会得到 "."、pwd 得到用户的当前目录 —— 不去拦的话会把「用户碰巧
    # 站在某个含 app/ 的目录下」误判成本地仓库。所以先确认脚本自身是个真实文件。
    [ -f "$0" ] || return 0
    local self_dir here parent
    # 不用 dirname —— 最小化/异常的 bash 环境里可能没有它
    # （本项目开发机的 Git Bash 就报 dirname: command not found）。纯参数展开即可。
    case "$0" in
        */*) self_dir="${0%/*}" ;;
        *)   self_dir="." ;;
    esac
    here="$(cd "$self_dir" && pwd)"
    parent="$(cd "$here/.." && pwd)"
    if [ -f "$parent/pyproject.toml" ] && [ -d "$parent/app" ]; then
        LOCAL_SRC="$parent"
    fi
}

fetch_source() {
    local url tmp
    if [ -n "${LOCAL_SRC:-}" ]; then
        info "使用本地源码：$LOCAL_SRC"
        SRC_DIR="$LOCAL_SRC"
        return 0
    fi

    tmp="$(mktemp -d)"
    url="https://github.com/${REPO_SLUG}/archive/refs/heads/${REF}.tar.gz"
    # tag / commit 走另一条路径（heads/ 只接受分支名）
    case "$REF" in
        v*|*.*.*) url="https://github.com/${REPO_SLUG}/archive/refs/tags/${REF}.tar.gz" ;;
    esac

    info "下载源码：$url"
    if command -v curl >/dev/null 2>&1; then
        curl -fSL --retry 3 --connect-timeout 20 -o "$tmp/src.tar.gz" "$url" \
            || die "下载失败。可指定镜像：export LLMBRIDGE_REF=<分支或tag> 后重试，或手动 git clone 后在仓库内执行本脚本。"
    else
        wget -q --tries=3 --timeout=20 -O "$tmp/src.tar.gz" "$url" \
            || die "下载失败。请检查网络，或手动 git clone 后在仓库内执行本脚本。"
    fi

    tar -xzf "$tmp/src.tar.gz" -C "$tmp" || die "解包失败，下载文件可能不完整。"
    SRC_DIR="$(find "$tmp" -maxdepth 1 -type d -name 'llmbridge-*' | head -n 1)"
    [ -n "$SRC_DIR" ] && [ -f "$SRC_DIR/pyproject.toml" ] || die "解包后未找到 pyproject.toml，源码包结构异常。"
    ok "源码就绪（ref=$REF）"
}

# =============================================================================
#  用户与目录
# =============================================================================

ensure_user() {
    if id "$RUN_USER" >/dev/null 2>&1; then
        info "运行用户已存在：$RUN_USER"
    else
        info "创建系统用户：$RUN_USER"
        useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$RUN_USER" 2>/dev/null \
            || useradd -r -d "$INSTALL_DIR" -s /sbin/nologin "$RUN_USER" \
            || die "创建用户 $RUN_USER 失败。"
    fi
}

sync_code() {
    mkdir -p "$INSTALL_DIR"
    if [ -d "$INSTALL_DIR/app" ]; then
        info "检测到既有安装，执行升级（保留 .env 与数据）"
    fi
    # 用户在安装目录里就地跑本脚本时（sudo bash /opt/llmbridge/deploy/install.sh），
    # 源与目标是同一目录 —— 用 tar 管道读写自己会读到边读边变的目录树，必须跳过。
    if [ "$SRC_DIR" = "$INSTALL_DIR" ]; then
        info "源码已在安装目录内，跳过拷贝"
    else
        # 用 tar 管道同步而非 rsync：rsync 未必预装，tar 几乎必然存在。
        # --exclude .env 是关键 —— 绝不覆盖既有配置（否则已存厂商密钥全部无法解密）。
        ( cd "$SRC_DIR" && tar \
            --exclude='./.venv' --exclude='./.git' --exclude='./node_modules' \
            --exclude='./.env' --exclude='./*.db' --exclude='./*.db-wal' --exclude='./*.db-shm' \
            --exclude='./admin-web/node_modules' --exclude='./admin-web/dist' \
            -cf - . ) | ( cd "$INSTALL_DIR" && tar -xf - )
    fi
    chown -R "$RUN_USER:$RUN_USER" "$INSTALL_DIR"
    ok "代码已同步到 $INSTALL_DIR"
}

# =============================================================================
#  虚拟环境与依赖
# =============================================================================

setup_venv() {
    local venv="$INSTALL_DIR/.venv"
    if [ ! -x "$venv/bin/python" ]; then
        info "创建虚拟环境：$venv"
        "$PY_BIN" -m venv "$venv" || die "创建虚拟环境失败。"
    else
        info "复用既有虚拟环境：$venv"
    fi
    info "安装依赖（首次约 1~2 分钟）..."
    "$venv/bin/python" -m pip install --quiet --upgrade pip
    ( cd "$INSTALL_DIR" && "$venv/bin/python" -m pip install --quiet -e . ) \
        || die "依赖安装失败。请检查网络（pip 源可用性）。"
    chown -R "$RUN_USER:$RUN_USER" "$venv"
    ok "依赖安装完成（Python $PY_VER）"
}

# =============================================================================
#  配置
# =============================================================================

gen_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 32 | tr -d '\n'
    else
        "$INSTALL_DIR/.venv/bin/python" -c 'import secrets;print(secrets.token_urlsafe(32))'
    fi
}

port_open() {
    # 纯 bash 的 TCP 探测，不依赖 nc/nmap（它们未必预装）。
    # /dev/tcp 是 bash 内建特性，Alpine 用 ash 时不可用 —— 那种情况返回「未开」。
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3<&- && return 0
    return 1
}

write_env() {
    local envfile="$INSTALL_DIR/.env"
    if [ -f "$envfile" ]; then
        # 既有 .env：只补缺失的关键项，不改已有值。
        info "保留既有 .env（仅补空缺项，绝不覆盖已有密钥）"
        grep -q '^JWT_SECRET=' "$envfile" || {
            printf '\nJWT_SECRET=%s\n' "$(gen_secret)" >> "$envfile"
            warn "已为既有 .env 补生成 JWT_SECRET（旧会话将失效）"
        }
        grep -q '^ENCRYPTION_MASTER_KEY=' "$envfile" || die "既有 .env 缺少 ENCRYPTION_MASTER_KEY。请手动补上后再运行，否则已存厂商密钥无法解密。"
        chown "$RUN_USER:$RUN_USER" "$envfile" && chmod 600 "$envfile"
        return 0
    fi

    local jwt enc db_url
    jwt="$(gen_secret)"
    enc="$(gen_secret)"

    if [ -n "$PG_URL" ]; then
        db_url="$PG_URL"
        info "数据库：使用指定的 PostgreSQL"
    elif port_open 5432; then
        db_url="postgresql+psycopg://llmbridge:llmbridge@127.0.0.1:5432/llmbridge"
        warn "检测到本机 5432 端口在监听，已按 PostgreSQL 配置连接串。"
        warn "若尚未创建库和账号，请先建：CREATE USER llmbridge PASSWORD '...'; CREATE DATABASE llmbridge OWNER llmbridge;"
        warn "并务必修改 .env 里的密码（文件：$envfile）。"
    else
        db_url="sqlite:///${INSTALL_DIR}/llmbridge.db"
        info "数据库：SQLite（本机未检测到 PostgreSQL，开箱即用）"
        warn "生产环境建议改用 PostgreSQL：编辑 $envfile 的 DATABASE_URL 后 systemctl restart $SERVICE_NAME"
    fi

    umask 077
    cat > "$envfile" <<EOF
# ============================================================
# 由 deploy/install.sh 于 $(date '+%Y-%m-%d %H:%M:%S') 生成
# 本文件含明文密钥，权限已设为 600，严禁提交 git
# ============================================================

# ---- 数据库 ----
# 支持 sqlite:///<绝对路径> 或 postgresql+psycopg://user:pass@host:5432/db
# 注意：不要写 postgresql+asyncpg://（asyncpg 不在依赖里，会在建连时才失败）
DATABASE_URL=${db_url}
POSTGRES_PASSWORD=
HTTP_PORT=80

# ---- 首次运行引导 ----
# 启动时自动建表 + 建默认管理员(admin/admin123) + 预置厂商接入目录，三步幂等。
AUTO_BOOTSTRAP=true

# ---- Redis（可选；留空则缓存/限流自动降级，不影响功能）----
REDIS_URL=

# ---- 安全 ----
# SSRF 白名单：是否允许厂商 base_url 用 http:// 及 localhost/私网地址。
# 生产【必须】false；仅当需要连本机/内网自建网关时才置 true。
ALLOW_LOCAL_BASE_URL=false
JWT_SECRET=${jwt}
JWT_EXPIRE_SECONDS=86400
# 厂商 API Key 的 AES-256-GCM 主密钥。
# 【高危】丢失 = 所有已存厂商密钥无法解密，必须自行备份并妥善保管。
ENCRYPTION_MASTER_KEY=${enc}

# ---- 判定器 ----
# mock = 内置无依赖判定（默认，离线可用）；jev = TypeSafe AI 官方 API
JUDGE_PROVIDER=mock
JEV_API_KEY=
JEV_BASE_URL=https://api.typesafe.ai/v1/systemone
DECIDER_TIMEOUT_MS=3000
ROUTE_CONFIDENCE_THRESHOLD_T2=0.5

# ---- 路由 ----
# 全部候选失败时的最终兜底模型 id。
# 【必改】首次安装模型池是空的，请先在控制台「模型池」页添加模型，再把它的 id 填到这里。
DEFAULT_MODEL_ID=1
REQUEST_TIMEOUT_MS=30000
ROUTE_CACHE_TTL=3600

# ---- 日志 ----
LOG_BATCH_SIZE=50
LOG_FLUSH_SECONDS=1.0

# ---- 工具调用 ----
# 默认关 = 纯透传：tools 原样转发，工具由调用方执行（标准 OpenAI 语义）。
ENABLE_TOOL_EXECUTION=false
TOOL_RESULT_MAX_CHARS=8000
EOF
    chown "$RUN_USER:$RUN_USER" "$envfile"
    chmod 600 "$envfile"
    ok "已生成 $envfile（密钥为随机值，权限 600）"
}

# =============================================================================
#  控制台前端与 Web 服务器配置
# =============================================================================

detect_node() {
    command -v node >/dev/null 2>&1 || return 1
    command -v npm  >/dev/null 2>&1 || return 1
    NODE_VER="$(node -v 2>/dev/null | sed 's/^v//')"
    local major="${NODE_VER%%.*}"
    # 非数字（版本串异常）时 -ge 会报语法错，整个 test 的 stderr 丢掉即可。
    [ -n "$major" ] && [ "$major" -ge 20 ] 2>/dev/null
}

build_frontend() {
    local dist="$INSTALL_DIR/admin-web/dist"

    if [ -f "$dist/index.html" ]; then
        info "控制台前端产物已存在，跳过构建：$dist"
        FRONTEND_OK="true"
        return 0
    fi
    if [ "$SKIP_FRONTEND" = "true" ]; then
        warn "已指定 --skip-frontend：不构建控制台前端。接口不受影响，但浏览器打不开界面。"
        return 0
    fi

    if ! detect_node; then
        cat >&2 <<EOF

${C_YELLOW}[警告] 未找到 Node.js >= 20，跳过控制台前端构建。${C_OFF}

  后端与 /v1、/admin 接口**不受影响**，但浏览器打开控制台会是空白页。
  补上这一步的两种办法：

  a) 装好 Node.js 后只补构建（不会动其它任何东西）：
       sudo bash $0 --frontend-only
     Node.js 获取：https://nodejs.org/ （或用 nvm、发行版包管理器）

  b) 在任何有 Node.js 的机器上构建后拷过来：
       cd admin-web && npm ci && npm run build
       scp -r admin-web/dist 用户@本机:${INSTALL_DIR}/admin-web/

EOF
        return 0
    fi

    step "构建控制台前端"
    info "Node.js v${NODE_VER}；执行 npm ci && npm run build（首次约 1~3 分钟）"
    if ( cd "$INSTALL_DIR/admin-web" && npm ci --no-audit --no-fund && npm run build ); then
        if [ -f "$dist/index.html" ]; then
            # frontend-only 场景下运行用户未必还在，chown 失败不该让整个脚本挂掉。
            chown -R "$RUN_USER:$RUN_USER" "$INSTALL_DIR/admin-web" 2>/dev/null || true
            FRONTEND_OK="true"
            ok "前端产物就绪：$dist"
        else
            warn "构建命令返回成功，但未找到 $dist/index.html —— 请核对 admin-web/vite.config.ts 的 outDir。"
        fi
    else
        warn "前端构建失败（常见原因：npm 源不可达）。后端不受影响，可稍后重跑 --frontend-only。"
    fi
}

write_nginx_conf() {
    local tpl="$INSTALL_DIR/deploy/nginx-standalone.conf"
    local out_conf="$INSTALL_DIR/deploy/nginx-llmbridge.conf"
    NGINX_CONF_READY="false"
    [ -f "$tpl" ] || return 0

    sed -e "s#__API_PORT__#${SVC_PORT}#g" \
        -e "s#__LISTEN_PORT__#${NGINX_PORT}#g" \
        -e "s#__DIST_DIR__#${INSTALL_DIR}/admin-web/dist#g" \
        "$tpl" > "$out_conf"
    NGINX_CONF_READY="true"
    ok "已生成 Nginx 站点配置：$out_conf"
}

# =============================================================================
#  引导（建表 / 管理员 / 厂商目录）
# =============================================================================

run_bootstrap() {
    info "执行首次引导（建表 + 默认管理员 + 评测样本 + 厂商接入目录）..."
    local args=""
    [ "$WITH_MODELS" = "true" ] && args="--with-models"
    # 用运行用户执行，确保生成的文件属主正确（否则后续 systemd 起不来）。
    if su -s /bin/sh "$RUN_USER" -c "cd '$INSTALL_DIR' && ./.venv/bin/llmbridge-seed" 2>&1; then
        ok "引导完成"
    else
        warn "引导失败（不阻断安装）。服务启动时会自动重试同一套引导；"
        warn "若界面里看不到厂商，请查看日志：journalctl -u $SERVICE_NAME -n 100"
    fi
    if [ "$WITH_MODELS" = "true" ]; then
        su -s /bin/sh "$RUN_USER" -c "cd '$INSTALL_DIR' && ./.venv/bin/llmbridge-catalog $args" || \
            warn "参考模型预置失败（不影响接入通道）。"
    fi
}

# =============================================================================
#  systemd 服务
# =============================================================================

install_service() {
    local unit_src="$INSTALL_DIR/deploy/linux/llmbridge.service"
    [ -f "$unit_src" ] || die "未找到 systemd 模板：$unit_src"

    # 从模板生成，而不是另写一份 —— 保证「文档/模板/实际单元」单一真源。
    # 替换的是路径与端口，其余安全加固项（ProtectSystem 等）原样保留。
    sed -e "s#/opt/llmbridge#${INSTALL_DIR}#g" \
        -e "s#^User=llmbridge#User=${RUN_USER}#" \
        -e "s#^Group=llmbridge#Group=${RUN_USER}#" \
        -e "s#--host 127.0.0.1#--host ${SVC_HOST}#" \
        -e "s#--port 8000#--port ${SVC_PORT}#" \
        "$unit_src" > "$UNIT_PATH"
    chmod 644 "$UNIT_PATH"

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
    systemctl restart "$SERVICE_NAME"
    ok "systemd 服务已启动：$SERVICE_NAME"
}

health_check() {
    local url="http://127.0.0.1:${SVC_PORT}/health" i
    info "探活：$url"
    i=1
    while [ "$i" -le 30 ]; do
        if command -v curl >/dev/null 2>&1; then
            curl -fsS --max-time 3 "$url" >/dev/null 2>&1 && { ok "服务已就绪（第 ${i} 次探测）"; return 0; }
        else
            "$INSTALL_DIR/.venv/bin/python" - "$SVC_PORT" <<'PY' >/dev/null 2>&1 && { ok "服务已就绪（第 ${i} 次探测）"; return 0; }
import sys, urllib.request
urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
    f"http://127.0.0.1:{sys.argv[1]}/health", timeout=3).read()
PY
        fi
        sleep 1
        i=$((i + 1))
    done
    warn "探活超时（30 秒）。服务可能仍在启动，请检查日志："
    warn "  journalctl -u $SERVICE_NAME -n 80 --no-pager"
    return 1
}

# =============================================================================
#  卸载
# =============================================================================

do_uninstall() {
    info "卸载 $SERVICE_NAME"
    if systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then
        systemctl stop "$SERVICE_NAME" 2>/dev/null || true
        systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    fi
    [ -f "$UNIT_PATH" ] && rm -f "$UNIT_PATH" && systemctl daemon-reload
    ok "服务已停止并移除（单元的 daemon-reload 已完成）"

    if [ "$PURGE" = "true" ]; then
        warn "即将删除安装目录：$INSTALL_DIR"
        if [ "$ASSUME_YES" != "true" ]; then
            printf '确认删除？数据不可恢复 [y/N] '
            read -r ans
            case "$ans" in y|Y|yes|YES) ;; *) info "已取消删除，目录保留。"; exit 0 ;; esac
        fi
        rm -rf "$INSTALL_DIR"
        ok "已删除 $INSTALL_DIR"
    else
        info "安装目录已保留：$INSTALL_DIR"
        info "如需彻底删除：sudo bash $0 --purge -y"
    fi
    info "运行用户 $RUN_USER 未删除（如需：userdel $RUN_USER）"
}

# =============================================================================
#  主流程
# =============================================================================

print_summary() {
    # 80 端口不带后缀，其它端口要显式写出来，否则用户照抄地址会打不开。
    local port_suffix=""
    [ "$NGINX_PORT" = "80" ] || port_suffix=":${NGINX_PORT}"

    cat <<EOF

${C_GREEN}${C_BOLD}安装完成${C_OFF}

  服务管理   systemctl {status|restart|stop} ${SERVICE_NAME}
  查看日志   journalctl -u ${SERVICE_NAME} -f
  配置文件   ${INSTALL_DIR}/.env
  代码目录   ${INSTALL_DIR}
  运行用户   ${RUN_USER}
  CLI 工具   ${INSTALL_DIR}/.venv/bin/{llmbridge-serve,llmbridge-seed,llmbridge-catalog}
  后端接口   http://127.0.0.1:${SVC_PORT}/health   （/v1 与 /admin 都在这个端口上）

EOF

    if [ "$FRONTEND_OK" = "true" ] && [ "$NGINX_CONF_READY" = "true" ]; then
        cat <<EOF
${C_BOLD}启用控制台（还差两步）${C_OFF}

  后端在 127.0.0.1:${SVC_PORT} 监听、前端产物也已就绪，但还需要一个 web 服务器
  把两者串起来。站点配置已替你生成（含 SSE 相关配置，不必手写）：

    sudo cp ${INSTALL_DIR}/deploy/nginx-llmbridge.conf /etc/nginx/conf.d/llmbridge.conf
    sudo nginx -t && sudo systemctl reload nginx

  若尚未安装 Nginx：
    sudo apt-get install -y nginx     # Debian / Ubuntu
    sudo dnf install -y nginx         # RHEL / Fedora

  之后打开控制台：${C_BOLD}http://<服务器IP>${port_suffix}/${C_OFF}

EOF
    elif [ "$FRONTEND_OK" = "true" ]; then
        cat <<EOF
${C_BOLD}控制台前端已就绪${C_OFF}

  产物在 ${INSTALL_DIR}/admin-web/dist，请用你现有的 web 服务器托管它，
  并把 /v1/、/admin/、/health 反代到 http://127.0.0.1:${SVC_PORT}。
  （未找到 deploy/nginx-standalone.conf 模板，故没有自动生成站点配置。）

EOF
    else
        cat <<EOF
${C_RED}${C_BOLD}控制台前端未构建 —— 浏览器暂时打不开界面（接口正常）${C_OFF}

  补构建（装好 Node.js >= 20 后执行，只做这一步、不影响其它任何内容）：
    sudo bash $0 --frontend-only

EOF
    fi

    cat <<EOF
${C_YELLOW}${C_BOLD}三步就绪指南${C_OFF}

  1. 打开控制台（默认账号 ${C_BOLD}admin / admin123${C_OFF}），${C_RED}立即修改密码${C_OFF}。
  2. 「厂商接入」页预置了 13 家主流厂商 / 24 条接入通道 —— 全部是「未接入」状态，
     填一个你已有的 API Key 即可接通（密钥以 AES-256-GCM 加密落库）。
  3. 「模型池」页添加至少一个模型（模型池初始为空是有意设计：能用哪些模型、
     什么价取决于你的账号，网关不替你猜），并把它的 id 填进 .env 的 DEFAULT_MODEL_ID。

${C_YELLOW}生产环境必做${C_OFF}
  · 修改 .env 里的数据库密码（若用 PostgreSQL）
  · 备份 ENCRYPTION_MASTER_KEY —— 丢失后已存厂商密钥不可恢复
  · 启用 HTTPS（上面生成的站点配置里有现成的 443 段，取消注释即可）
  · 保持 .env 的 ALLOW_LOCAL_BASE_URL=false
  · 完整清单见 ${INSTALL_DIR}/docs/阶段五-部署与交付/04-运维手册.md

EOF
}

main() {
    step "环境检查"
    check_os
    locate_local_source
    if [ "$ACTION" = "uninstall" ]; then
        need_root
        do_uninstall
        exit 0
    fi
    need_root

    # --frontend-only：只补构建控制台前端，不碰虚拟环境、配置、服务与数据。
    if [ "$FRONTEND_ONLY" = "true" ]; then
        [ -d "$INSTALL_DIR/admin-web" ] || \
            die "未找到 $INSTALL_DIR/admin-web —— 请先完整安装一次，或用 --dir 指定正确的安装目录。"
        build_frontend
        write_nginx_conf
        exit 0
    fi

    detect_python
    check_prereqs
    info "Python：$PY_BIN（$PY_VER）"

    step "获取源码"
    fetch_source

    step "安装到 $INSTALL_DIR"
    ensure_user
    sync_code

    step "创建虚拟环境并安装依赖"
    setup_venv

    step "生成配置"
    write_env

    step "初始化数据"
    run_bootstrap

    # 前端与站点配置放在引导之后：后端已可用，即使这两步失败也不影响接口。
    build_frontend
    write_nginx_conf

    if [ "$NO_SERVICE" = "true" ]; then
        ok "已跳过 systemd 注册（--no-service）"
        cat <<EOF

手动启动：
  cd ${INSTALL_DIR}
  sudo -u ${RUN_USER} ./.venv/bin/llmbridge-serve --host ${SVC_HOST} --port ${SVC_PORT}

EOF
        exit 0
    fi

    step "注册并启动服务"
    install_service
    health_check || true
    print_summary
}

main
