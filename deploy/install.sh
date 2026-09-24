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
#    --frontend-only    只构建控制台前端后退出（会顺带把 Node.js / Nginx 一并补齐）
#    --nginx-port <n>   Nginx 对外端口（默认 80）
#    --no-nginx         不自动安装 / 配置系统 Nginx（改用你已有的 web 服务器）
#    --no-node-install  不自动安装 Node.js（只用机器上已有的）
#    --node-version <v> 指定要安装的 Node.js 版本（如 v22.14.0）
#    --node-mirror <u>  只用指定的 Node.js 下载镜像（默认先试官方、再试国内镜像）
#    --npm-registry <u> npm 源（默认官方源，失败会自动用国内镜像重试一次）
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
#     本脚本**把这件事也一次做到底**：没装 Node.js（或版本 < 20）就自动装 ——
#     先试发行版仓库，版本不够则下载官方预编译包（先官方源、不通再走国内镜像），
#     装进 /usr/local/lib/nodejs 并软链到 /usr/local/bin，不动系统包管理的既有文件。
#     任一环节失败都会明确告警并给出补装办法，绝不静默跳过 ——
#     否则现象是「服务正常、浏览器打开一片空白」，极难归因。
#
#  2) 必须有一个 web 服务器把 dist 托起来并把 /v1、/admin 反代到后端。
#     本脚本**把这件事一次做到底**：没装 Nginx 就自动装（apt/dnf/yum/zypper/apk），
#     装好即写入站点配置、处理「发行版自带默认站点抢 80」、放行 SELinux 与防火墙，
#     最后直接打印控制台地址 —— 装完不需要你再手工敲任何命令。
#     Docker Compose 形态里这个角色由 nginx 容器担任。
#     若你有自己的 web 服务器、或不愿让脚本改动系统 Nginx，加 --no-nginx 跳过这一步。
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
NODE_MIN_MAJOR=20 # 前端构建需要 Node.js >= 20
# 要下载的 Node.js 版本：按顺序尝试，前一个 404 就退到下一个 ——
# 单一硬编码版本一旦从官方归档下线（Node 每个大版本都会被清），整条自动安装链就断了。
NODE_CANDIDATES="v22.14.0 v22.12.0 v20.18.0"
# 预编译包与软链的落点，可用环境变量覆盖（便于测试与「不动 /usr/local」的部署）。
NODE_INSTALL_ROOT="${LLMBRIDGE_NODE_ROOT:-/usr/local/lib/nodejs}"
NODE_LINK_DIR="${LLMBRIDGE_NODE_BIN_DIR:-/usr/local/bin}"

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
NO_NGINX="false"             # --no-nginx：不自动装/配 Nginx
NO_NODE_INSTALL="false"      # --no-node-install：不自动装 Node.js
NODE_VERSION_ARG=""          # --node-version
NODE_MIRROR=""               # --node-mirror：非空则只用这个镜像
NPM_REGISTRY=""              # --npm-registry：非空则固定用这个源
FRONTEND_OK="false"          # 由 build_frontend 置位，供结束摘要判断怎么提示
NGINX_CONF_READY="false"     # 由 write_nginx_conf 置位
NGINX_READY="false"          # 由 ensure_nginx 置位：站点真的对外可用了
NGINX_URL=""                 # 控制台访问地址（只有装成功才有值）
NODE_VER=""                  # detect_node 命中后填
NODE_HOME=""                 # 自动安装的 Node.js 根目录（仅自动装时有值）
NODE_BIN=""                  # node 可执行文件绝对路径
NPM_BIN=""                   # npm 可执行文件绝对路径
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
        --no-nginx)   NO_NGINX="true"; shift ;;
        --no-node-install) NO_NODE_INSTALL="true"; shift ;;
        --node-version) NODE_VERSION_ARG="${2:?--node-version 需要参数}"; shift 2 ;;
        --node-mirror)  NODE_MIRROR="${2:?--node-mirror 需要参数}"; shift 2 ;;
        --npm-registry) NPM_REGISTRY="${2:?--npm-registry 需要参数}"; shift 2 ;;
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
    [ "$(id -u)" -eq 0 ] || die "需要 root 权限。请用：$(self_cmd) $ORIG_ARGS"
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
    local cand node_bin npm_bin ver major
    # 1) 常规场景：PATH 里就有 node / npm（含 sudo 正常 secure_path 覆盖 /usr/bin 的情况）。
    node_bin="$(command -v node 2>/dev/null || true)"
    npm_bin="$(command -v npm 2>/dev/null || true)"
    # 2) 兜底：某些发行版的 sudo secure_path 会砍掉 node 所在目录，PATH 里找不到，
    #    但 node 其实是装好的（典型如系统已装 nodejs-22 却探测失败、又去下载冗余的官方包）。
    #    这里直接探常见绝对路径；npm 优先取与 node 同目录的那份，避免版本错配。
    if [ -z "$node_bin" ] || [ -z "$npm_bin" ]; then
        for cand in /usr/bin/node /usr/local/bin/node /opt/node/bin/node \
                    /usr/local/node/bin/node "$NODE_INSTALL_ROOT"/*/bin/node; do
            [ -x "$cand" ] || continue
            node_bin="$cand"
            if [ -x "$(dirname "$cand")/npm" ]; then
                npm_bin="$(dirname "$cand")/npm"
            fi
            break
        done
    fi
    [ -n "$node_bin" ] || return 1
    [ -n "$npm_bin" ] || npm_bin="$(command -v npm 2>/dev/null || true)"
    [ -n "$npm_bin" ] || return 1

    ver="$($node_bin -v 2>/dev/null | sed 's/^v//')"
    major="${ver%%.*}"
    # 非数字（版本串异常）时 -ge 会报语法错，整个 test 的 stderr 丢掉即可。
    [ -n "$major" ] && [ "$major" -ge "$NODE_MIN_MAJOR" ] 2>/dev/null || return 1
    NODE_BIN="$node_bin"
    NPM_BIN="$npm_bin"
    NODE_VER="$ver"
    # 把命中 node 的目录前置进 PATH：npm 子进程（vue-tsc/vite）的 shebang 是
    # `#!/usr/bin/env node`，若本会话 PATH 里没有这个 node（正是探测失败的根因），
    # 子进程会找不到 node 或错配版本。前置后整条链路都锁定同一份 node。
    case ":$PATH:" in
        *":$(dirname "$NODE_BIN"):"*) ;;
        *) export PATH="$(dirname "$NODE_BIN"):$PATH" ;;
    esac
    return 0
}

download_tool() {
    if command -v curl >/dev/null 2>&1; then
        echo curl
    elif command -v wget >/dev/null 2>&1; then
        echo wget
    else
        return 1
    fi
}

do_download() {
    local url="$1" out="$2" tool
    tool="$(download_tool)" || return 1
    if [ "$tool" = "curl" ]; then
        curl -fsSL --connect-timeout 15 --max-time 900 -o "$out" "$url"
    else
        wget -q --timeout=60 -O "$out" "$url"
    fi
}

node_tarball_arch() {
    case "$(uname -m)" in
        x86_64|amd64)  echo "linux-x64" ;;
        aarch64|arm64) echo "linux-arm64" ;;
        armv7l|armv7)  echo "linux-armv7l" ;;
        *)             echo "" ;;
    esac
}

install_node_pkg() {
    if command -v apt-get >/dev/null 2>&1; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs npm
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y nodejs npm
    elif command -v yum >/dev/null 2>&1; then
        yum install -y nodejs npm
    elif command -v zypper >/dev/null 2>&1; then
        zypper --non-interactive install -y nodejs npm
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache nodejs npm
    else
        return 1
    fi
}

node_link_bins() {
    local dir="$1" b
    for b in node npm npx; do
        [ -x "$dir/bin/$b" ] || continue
        # 已存在同名**实体文件**（包管理器装的、或前人手工放的）时绝不覆盖：
        # 覆盖它等于悄悄改掉机器上其它工具依赖的 node，风险远大于收益。
        if [ -e "$NODE_LINK_DIR/$b" ] && [ ! -L "$NODE_LINK_DIR/$b" ]; then
            info "$NODE_LINK_DIR/$b 已存在且非软链，保持不动（本次构建用绝对路径调用）"
            continue
        fi
        # 注意 ln -s 的失败可能是**静默**的（部分文件系统/容器不允许建符号链接，
        # 某些兼容层还会产出一个 0 字节的空文件并返回 0）。所以不能只看退出码，
        # 还要验一下链接真的可执行；失败也不致命 —— 下面会 export PATH，
        # 构建走的是绝对路径，不依赖这个软链。
        if ! ln -sf "$dir/bin/$b" "$NODE_LINK_DIR/$b" 2>/dev/null || [ ! -x "$NODE_LINK_DIR/$b" ]; then
            warn "$NODE_LINK_DIR/$b 未生效（本机可能不允许创建符号链接）—— 本次构建用绝对路径调用，不受影响"
        fi
    done
}

install_node_tarball() {
    local arch ver base bases url tmpdir dest try_list
    arch="$(node_tarball_arch)"
    if [ -z "$arch" ]; then
        warn "未识别的 CPU 架构 $(uname -m)，无法使用官方预编译包。"
        return 1
    fi
    if ! download_tool >/dev/null; then
        warn "本机既没有 curl 也没有 wget，无法下载 Node.js。"
        return 1
    fi

    if [ -n "$NODE_VERSION_ARG" ]; then
        try_list="$NODE_VERSION_ARG"
    else
        try_list="${NODE_CANDIDATES:-}"
    fi
    [ -n "$try_list" ] || return 1

    for ver in $try_list; do
        if [ -n "$NODE_MIRROR" ]; then
            bases="$NODE_MIRROR"
        else
            # 官方源优先；连不上再走国内镜像（与 npm 侧同一套思路）。
            bases="https://nodejs.org/dist https://npmmirror.com/mirrors/node"
        fi
        for base in $bases; do
            base="${base%/}"
            url="${base}/${ver}/node-${ver}-${arch}.tar.gz"
            tmpdir="$(mktemp -d)"
            info "下载 Node.js ${ver}（来源 ${base}）…"
            if ! do_download "$url" "$tmpdir/node.tar.gz"; then
                warn "下载失败：$url"
                rm -rf "$tmpdir"
                continue
            fi
            dest="${NODE_INSTALL_ROOT}/node-${ver}-${arch}"
            if ! { mkdir -p "$dest" && tar -xzf "$tmpdir/node.tar.gz" -C "$dest" --strip-components=1; }; then
                warn "解压失败：$tmpdir/node.tar.gz"
                rm -rf "$tmpdir" "$dest"
                continue
            fi
            rm -rf "$tmpdir"
            node_link_bins "$dest"
            NODE_HOME="$dest"
            # 本次进程内让 node/npm 先被解析到新装的那份：npm 的 shebang 是
            # `#!/usr/bin/env node`，若 PATH 里旧 node 仍排在前面，npm ci 会拿**旧版本**
            # 的 node 去跑新 npm，报的是一堆语法错 —— 现象与成因相隔极远，极难归因。
            export PATH="$dest/bin:$PATH"
            NODE_BIN="$dest/bin/node"
            NPM_BIN="$dest/bin/npm"
            ok "Node.js ${ver} 已就位：$dest"
            return 0
        done
    done
    return 1
}

ensure_node() {
    if detect_node; then
        info "已检测到 Node.js v${NODE_VER}（${NODE_BIN}）"
        return 0
    fi
    if [ "$NO_NODE_INSTALL" = "true" ]; then
        warn "已指定 --no-node-install：跳过 Node.js 自动安装。"
        return 1
    fi

    step "安装 Node.js（构建控制台前端所需，>= ${NODE_MIN_MAJOR}）"

    # 1) 先试发行版仓库：最快、走本地镜像源，Alpine 也只有这条路。
    #    代价是版本常常偏旧（Ubuntu 20.04 是 v10、CentOS 7 是 v10），装完必须再验版本。
    if install_node_pkg 2>/dev/null; then
        if detect_node; then
            ok "已通过系统包管理器安装 Node.js v${NODE_VER}"
            return 0
        fi
        info "发行版仓库提供的 Node.js 低于 ${NODE_MIN_MAJOR}，改用官方预编译包。"
    fi

    # 2) 官方预编译二进制：不依赖发行版仓库的版本，也不碰系统包管理的既有文件。
    if install_node_tarball && detect_node; then
        return 0
    fi

    return 1
}

# 通过管道执行（curl … | sudo bash）时 $0 是 "bash"，拿它拼出的补构建命令会变成
# `sudo bash bash --frontend-only` —— 用户照抄必然失败，还会以为脚本坏了。
# 安装目录里的副本路径确定且必然存在，优先用它拼命令。
self_cmd() {
    if [ -f "$INSTALL_DIR/deploy/install.sh" ]; then
        printf 'sudo bash %s/deploy/install.sh' "$INSTALL_DIR"
    elif [ -f "$0" ]; then
        printf 'sudo bash %s' "$0"
    else
        printf 'sudo bash %s/deploy/install.sh' "$INSTALL_DIR"
    fi
}

_frontend_finalize() {
    local dist="$INSTALL_DIR/admin-web/dist"
    if [ -f "$dist/index.html" ]; then
        # frontend-only 场景下运行用户未必还在，chown 失败不该让整个脚本挂掉。
        if id -u "$RUN_USER" >/dev/null 2>&1; then
            chown -R "$RUN_USER:$RUN_USER" "$INSTALL_DIR/admin-web" 2>/dev/null || true
        fi
        FRONTEND_OK="true"
        ok "前端产物就绪：$dist"
        return 0
    fi
    warn "构建命令返回成功，但未找到 $dist/index.html —— 请核对 admin-web/vite.config.ts 的 outDir。"
    return 1
}

_npm_build() {
    local registry="${1:-}" extra=""
    if [ -n "$registry" ]; then
        extra="--registry=$registry"
    fi
    ( cd "$INSTALL_DIR/admin-web" && \
      "$NPM_BIN" ci --no-audit --no-fund $extra && \
      "$NPM_BIN" run build )
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

    # 要构建就必须有 Node.js —— 缺了自动装，装不上才告警。
    # 「装完发现界面打不开、还要再敲一条命令」正是本脚本要消灭的现象。
    if ! ensure_node; then
        cat >&2 <<EOF

${C_YELLOW}[警告] 未能准备可用的 Node.js >= ${NODE_MIN_MAJOR}，跳过控制台前端构建。${C_OFF}

  后端与 /v1、/admin 接口**不受影响**，但浏览器打开控制台会是空白页。
  补上这一步：

  a) 装好 Node.js 后重跑（会自动构建前端，并把 Nginx 一并配好）：
       $(self_cmd) --frontend-only
     Node.js 获取：https://nodejs.org/ （或用 nvm、发行版包管理器）

  b) 在任何有 Node.js 的机器上构建后拷过来：
       cd admin-web && npm ci && npm run build
       scp -r admin-web/dist 用户@本机:${INSTALL_DIR}/admin-web/

EOF
        return 0
    fi

    step "构建控制台前端"
    info "Node.js v${NODE_VER}；执行 npm ci && npm run build（首次约 1~3 分钟）"
    if _npm_build "$NPM_REGISTRY"; then
        _frontend_finalize || true
    elif [ -z "$NPM_REGISTRY" ] && _npm_build "https://registry.npmmirror.com"; then
        # 国内机器直连 registry.npmjs.org 常是几十 KB/s 或直接超时。
        # 自动换镜像重试一次，用户不必先去查「npm 怎么换源」。
        info "已改用国内镜像源 registry.npmmirror.com 完成构建（可用 --npm-registry 固定源）"
        _frontend_finalize || true
    else
        warn "前端构建失败（常见原因：npm 源不可达）。后端不受影响。"
        warn "可指定镜像源重跑：$(self_cmd) --frontend-only --npm-registry https://registry.npmmirror.com"
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
#  Nginx：自动装 + 置配置 + 放行（「一键装完就能打开界面」的关键一步）
# =============================================================================

pick_nginx_conf_dir() {
    # 站点配置目录各发行版不同：Debian / RHEL 系是 conf.d，Alpine 是 http.d。
    # 以「目录存在」为准即可 —— 装出来的包一定已在主配置里 include 了它。
    local d
    for d in /etc/nginx/conf.d /etc/nginx/http.d; do
        if [ -d "$d" ]; then
            printf '%s' "$d"
            return 0
        fi
    done
    printf '/etc/nginx/conf.d'
}

install_nginx_pkg() {
    info "未检测到 Nginx，自动安装 ..."
    if command -v apt-get >/dev/null 2>&1; then
        DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 || true
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y nginx
    elif command -v yum >/dev/null 2>&1; then
        yum install -y nginx
    elif command -v zypper >/dev/null 2>&1; then
        zypper --non-interactive install nginx
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache nginx
    else
        return 1
    fi
}

nginx_disable_default_sites() {
    # 发行版自带的默认站点占着 `<端口> default_server`，而本站点的 server_name 是 `_`
    # （不匹配任何真实 Host），抢不到「默认」位 —— 现象是 `nginx -t` 通过、访问 IP 却是
    # 欢迎页、反代完全没走。这一步是「装完就能用」的必要条件。
    local f
    # Debian/Ubuntu：sites-enabled/default 只是指向 sites-available/default 的软链，
    # 移走安全且可逆（改名 .disabled-by-llmbridge 保留）。
    for f in /etc/nginx/sites-enabled/default /etc/nginx/conf.d/default.conf; do
        if [ -e "$f" ] && ! grep -q 'llmbridge' "$f" 2>/dev/null; then
            if mv -f "$f" "$f.disabled-by-llmbridge" 2>/dev/null; then
                info "已移走发行版默认站点：$f（否则它会抢走默认 server）"
            fi
        fi
    done
    # RHEL 系：默认 server 块直接写在 nginx.conf 里，移不走，只能摘掉 default_server 标记。
    # 摘掉后 conf.d 的 include 位于该块之前，本站点自然成为默认 server。幂等，改前留备份。
    if [ -f /etc/nginx/nginx.conf ] && grep -q 'default_server' /etc/nginx/nginx.conf 2>/dev/null; then
        cp -a /etc/nginx/nginx.conf /etc/nginx/nginx.conf.llmbridge.bak 2>/dev/null || true
        sed -i -E 's#^([[:space:]]*listen[[:space:]]+[0-9a-fA-F.:\[\]]+[[:space:]]+)default_server;#\1;#' \
            /etc/nginx/nginx.conf 2>/dev/null || true
        info "已摘掉 nginx.conf 中默认 server 的 default_server 标记（备份 nginx.conf.llmbridge.bak）"
    fi
}

nginx_fix_selinux() {
    command -v getenforce >/dev/null 2>&1 || return 0
    if [ "$(getenforce 2>/dev/null || echo Disabled)" != "Enforcing" ]; then
        return 0
    fi
    info "SELinux 处于 Enforcing，放行 Nginx 所需权限 ..."
    # 反代到 127.0.0.1 需要这条，否则请求一律 502（配置看着完全正常，极难归因）。
    if ! setsebool -P httpd_can_network_connect 1 2>/dev/null; then
        warn "setsebool 失败：反代后端可能 502。请手工执行：setsebool -P httpd_can_network_connect 1"
    fi
    # 非标准端口：SELinux 默认不允许 nginx 绑定，需登记进 http_port_t。
    case "$NGINX_PORT" in
        80|443|8080) ;;
        *)
            if command -v semanage >/dev/null 2>&1; then
                semanage port -a -t http_port_t -p tcp "$NGINX_PORT" 2>/dev/null || \
                    semanage port -m -t http_port_t -p tcp "$NGINX_PORT" 2>/dev/null || true
            else
                warn "端口 $NGINX_PORT 可能被 SELinux 拦下（需 semanage port -a -t http_port_t -p tcp $NGINX_PORT）"
            fi
            ;;
    esac
    # 静态产物在 $INSTALL_DIR（非标准 web 目录），默认上下文不许 httpd 读 → 403。
    if [ -d "$INSTALL_DIR/admin-web/dist" ] && command -v chcon >/dev/null 2>&1; then
        chcon -R -t httpd_sys_content_t "$INSTALL_DIR/admin-web/dist" 2>/dev/null || true
    fi
}

nginx_open_firewall() {
    local port="$1"
    if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
        firewall-cmd --permanent --add-port="${port}/tcp" >/dev/null 2>&1 || true
        if firewall-cmd --reload >/dev/null 2>&1; then
            ok "防火墙已放行 ${port}/tcp（firewalld）"
        fi
    elif command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
        if ufw allow "${port}/tcp" >/dev/null 2>&1; then
            ok "防火墙已放行 ${port}/tcp（ufw）"
        fi
    else
        info "未检测到启用中的 firewalld / ufw —— 若为云服务器，请在控制台安全组放行 ${port} 端口"
    fi
}

nginx_start_or_reload() {
    if command -v systemctl >/dev/null 2>&1; then
        systemctl enable nginx >/dev/null 2>&1 || true
        if ! systemctl reload nginx >/dev/null 2>&1; then
            systemctl restart nginx >/dev/null 2>&1 || true
        fi
        if ! systemctl is-active nginx >/dev/null 2>&1; then
            warn "Nginx 未能启动。排查：journalctl -u nginx -n 50"
            return 1
        fi
    elif command -v rc-service >/dev/null 2>&1; then
        # Alpine
        rc-update add nginx default >/dev/null 2>&1 || true
        rc-service nginx restart >/dev/null 2>&1 || true
    else
        nginx -s reload >/dev/null 2>&1 || nginx >/dev/null 2>&1 || true
    fi
    return 0
}

nginx_http_probe() {
    # 探活必须显式绕开系统代理：Linux 上常设了 http_proxy，
    # 会把对 127.0.0.1 的请求送出去，得到假的失败。
    local url="http://127.0.0.1:${NGINX_PORT}/"
    if command -v curl >/dev/null 2>&1; then
        curl -fsS --noproxy '*' -o /dev/null "$url" 2>/dev/null
    elif command -v wget >/dev/null 2>&1; then
        wget -q --no-proxy -O /dev/null "$url" 2>/dev/null
    else
        port_open "$NGINX_PORT"
    fi
}

detect_lan_ip() {
    # 给用户一个「照着敲就能打开」的地址。hostname -I 在多数发行版可用；
    # 取第一个非回环地址，取不到就退 127.0.0.1（至少说明服务在本机是活的）。
    local ips ip
    ips="$(hostname -I 2>/dev/null || true)"
    for ip in $ips; do
        case "$ip" in
            127.*|::1|fe80:*|"") continue ;;
        esac
        printf '%s' "$ip"
        return 0
    done
    printf '127.0.0.1'
}

ensure_nginx() {
    NGINX_READY="false"
    NGINX_URL=""
    [ "$NGINX_CONF_READY" = "true" ] || return 0

    if [ "$NO_NGINX" = "true" ]; then
        info "已跳过 Nginx 配置（--no-nginx）：站点配置在 $INSTALL_DIR/deploy/nginx-llmbridge.conf"
        return 0
    fi

    # 1) 装
    if ! command -v nginx >/dev/null 2>&1; then
        if install_nginx_pkg && command -v nginx >/dev/null 2>&1; then
            ok "Nginx 已安装：$(nginx -v 2>&1)"
        else
            warn "自动安装 Nginx 失败（包管理器不可用或软件源不可达）。"
            warn "手工安装后重跑本脚本即可补齐：sudo dnf install -y nginx   # 或 apt-get install -y nginx"
            return 0
        fi
    else
        info "已检测到 Nginx：$(nginx -v 2>&1)"
    fi

    # 2) 写站点配置（先试 install -D，它自带 mkdir -p；失败退化为 mkdir + cp）
    local conf_dir
    conf_dir="$(pick_nginx_conf_dir)"
    if ! install -D -m 644 "$INSTALL_DIR/deploy/nginx-llmbridge.conf" "$conf_dir/llmbridge.conf" 2>/dev/null; then
        if mkdir -p "$conf_dir" && cp -f "$INSTALL_DIR/deploy/nginx-llmbridge.conf" "$conf_dir/llmbridge.conf"; then
            :
        else
            warn "写入 $conf_dir/llmbridge.conf 失败，跳过 Nginx 配置。"
            return 0
        fi
    fi
    ok "站点配置已就位：$conf_dir/llmbridge.conf"

    # 3) 让本站点拿到「默认 server」的位置
    nginx_disable_default_sites

    # 4) 语法门禁 —— 不通过就不 reload，避免把机器上其它站点一起搞挂
    if ! nginx -t >/dev/null 2>&1; then
        warn "nginx -t 未通过，站点配置未启用。报错如下："
        nginx -t
        warn "常见原因：端口 $NGINX_PORT 已被其它服务占用。可换端口重跑：$(self_cmd) --nginx-port 8080"
        return 0
    fi
    ok "Nginx 配置语法检查通过"

    # 5) SELinux / 防火墙 / 启动
    nginx_fix_selinux
    nginx_open_firewall "$NGINX_PORT"
    if ! nginx_start_or_reload; then
        return 0
    fi
    ok "Nginx 已启动并加载站点配置"

    # 6) 探活：通了才对外宣称「地址可用」
    if nginx_http_probe; then
        local psfx=""
        [ "$NGINX_PORT" = "80" ] || psfx=":${NGINX_PORT}"
        NGINX_READY="true"
        NGINX_URL="http://$(detect_lan_ip)${psfx}/"
    else
        warn "Nginx 已启动，但探活 http://127.0.0.1:${NGINX_PORT}/ 未成功 —— 请确认后端服务在跑。"
    fi
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
        info "如需彻底删除：$(self_cmd) --purge -y"
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

    # 控制台地址放在最顶上：用户的诉求就是「装完直接给一个能打开的地址」。
    # 只有探活成功（NGINX_READY）才写地址 —— 否则宁可明说「还没就绪」，
    # 也不要甩一个打不开的 URL 让人反复试。
    # 措辞必须和**下方真正会打印的那个小节**对上：早先统一写「见下方『启用控制台』」，
    # 但「前端也未构建」时下方根本没有这一节（走的是另一个分支），用户翻遍输出也找不到。
    local console_line
    if [ "$NGINX_READY" = "true" ] && [ "$FRONTEND_OK" = "true" ]; then
        console_line="  ${C_GREEN}${C_BOLD}控制台地址  ${NGINX_URL}${C_OFF}   ← 浏览器打开即后台管理界面"
    elif [ "$NGINX_READY" = "true" ]; then
        console_line="  控制台地址  ${NGINX_URL}   （前端还没构建，页面暂时空白 —— 见下方红字）"
    elif [ "$FRONTEND_OK" = "true" ]; then
        console_line="  控制台地址  尚未就绪（缺 Web 服务器 —— 见下方「启用控制台」）"
    else
        console_line="  控制台地址  尚未就绪（缺前端构建 —— 见下方红字）"
    fi

    cat <<EOF

${C_GREEN}${C_BOLD}安装完成${C_OFF}

${console_line}
  默认账号    ${C_BOLD}admin / admin123${C_OFF}（首次登录后请立即修改密码）

  服务管理   systemctl {status|restart|stop} ${SERVICE_NAME}
  查看日志   journalctl -u ${SERVICE_NAME} -f
  配置文件   ${INSTALL_DIR}/.env
  代码目录   ${INSTALL_DIR}
  运行用户   ${RUN_USER}
  CLI 工具   ${INSTALL_DIR}/.venv/bin/{llmbridge-serve,llmbridge-seed,llmbridge-catalog}
  后端接口   http://127.0.0.1:${SVC_PORT}/health   （/v1 与 /admin 都在这个端口上）

EOF

    if [ "$NGINX_READY" = "true" ]; then
        if [ "$FRONTEND_OK" = "true" ]; then
            # 已装好：不再让用户动手，只给「想改配置时怎么办」的可选信息。
            cat <<EOF
${C_BOLD}控制台已就绪${C_OFF}

  浏览器打开 ${C_BOLD}${NGINX_URL}${C_OFF} 即进入后台管理界面（默认账号 admin / admin123）。
  站点配置   $(pick_nginx_conf_dir)/llmbridge.conf
  改完之后   sudo nginx -t && sudo systemctl reload nginx

EOF
        else
            # 站点通了、前端却没构建：若还打印「控制台已就绪」就是自相矛盾 ——
            # 用户按提示打开地址只会看到空白页，反而更怀疑是系统坏了。
            cat <<EOF
${C_YELLOW}${C_BOLD}控制台前端未构建 —— 站点已通，但页面暂时空白${C_OFF}

  浏览器打开 ${NGINX_URL} 会是空白页（/v1、/admin 接口本身是好的）。
  一条命令补齐（会自动装 Node.js 并构建前端）：
    $(self_cmd) --frontend-only

EOF
        fi
    elif [ "$FRONTEND_OK" = "true" ] && [ "$NGINX_CONF_READY" = "true" ]; then
        # 兜底：只有自动装 Nginx 没成功时才会走到这里。
        # 提示语必须按「本机有没有 nginx」分岔：
        # 没装时 /etc/nginx/conf.d 根本不存在，照抄 cp 会得到
        # 「cp: 无法创建普通文件 '/etc/nginx/conf.d/llmbridge.conf': 没有那个文件或目录」——
        # 这句报错说的是目标目录缺失（源缺失时报的是「无法获取 … 的状态」），
        # 但字面上像是在怪站点配置，用户极易误判成配置文件有问题。
        # `install -D` 会自带 mkdir -p，把这个失败模式直接消掉。
        if command -v nginx >/dev/null 2>&1; then
            cat <<EOF
${C_BOLD}启用控制台（还差两步）${C_OFF}

  后端在 127.0.0.1:${SVC_PORT} 监听、前端产物也已就绪，只差把站点配置挂进 Nginx。
  站点配置已替你生成（含 SSE 四件套，不必手写）：

    sudo install -D -m 644 ${INSTALL_DIR}/deploy/nginx-llmbridge.conf /etc/nginx/conf.d/llmbridge.conf
    sudo nginx -t && sudo systemctl reload nginx

  提示：reload 成功但访问 IP 仍是 Nginx 欢迎页，是系统自带的默认站点占着 80 的
  default_server（Debian/Ubuntu 在 /etc/nginx/sites-enabled/default；RHEL 系在
  nginx.conf 里的 default_server 块）—— 本站点的 server_name 是 `_`，抢不到默认位。
  移走那份默认站点再 reload 即可，与本项目 /v1 的配置无关。

  之后打开控制台：${C_BOLD}http://<服务器IP>${port_suffix}/${C_OFF}

EOF
        else
            cat <<EOF
${C_BOLD}启用控制台（还差三步 —— 本机还没有 Nginx）${C_OFF}

  后端在 127.0.0.1:${SVC_PORT} 监听、前端产物也已就绪，但控制台是独立的 Vue SPA，
  需要一个 web 服务器托管它的构建产物、并把 /v1/ 与 /admin/ 反代过去。先装 Nginx：

    sudo dnf install -y nginx       # RHEL / CentOS / Fedora
    sudo apt-get install -y nginx   # Debian / Ubuntu
    sudo systemctl enable --now nginx

  站点配置已替你生成（含 SSE 四件套，不必手写）。装完 Nginx 再执行：

    sudo install -D -m 644 ${INSTALL_DIR}/deploy/nginx-llmbridge.conf /etc/nginx/conf.d/llmbridge.conf
    sudo nginx -t && sudo systemctl reload nginx

  RHEL / CentOS 上装完仍打不开，通常是这两处没放行（与配置无关）：
    sudo setsebool -P httpd_can_network_connect 1      # SELinux：不放行则反代一律 502
    sudo firewall-cmd --permanent --add-service=http && sudo firewall-cmd --reload

  提示：reload 成功但访问 IP 仍是 Nginx 欢迎页，是系统自带的默认站点占着 80 的
  default_server（Debian/Ubuntu 在 /etc/nginx/sites-enabled/default；RHEL 系在
  nginx.conf 里的 default_server 块）—— 移走那份默认站点再 reload 即可。

  之后打开控制台：${C_BOLD}http://<服务器IP>${port_suffix}/${C_OFF}

EOF
        fi
    elif [ "$FRONTEND_OK" = "true" ]; then
        cat <<EOF
${C_BOLD}控制台前端已就绪${C_OFF}

  产物在 ${INSTALL_DIR}/admin-web/dist，请用你现有的 web 服务器托管它，
  并把 /v1/、/admin/、/health 反代到 http://127.0.0.1:${SVC_PORT}。
  （未找到 deploy/nginx-standalone.conf 模板，故没有自动生成站点配置。）

EOF
    else
        cat <<EOF
${C_RED}${C_BOLD}控制台前端未构建 —— 浏览器暂时打不开界面（后端接口正常）${C_OFF}

  一条命令补齐（会自动装 Node.js、构建前端，并把 Nginx 也一并配好）：
    $(self_cmd) --frontend-only

  只做这一步，不动 .env、数据库与已录入的密钥。
  Node.js 也可自行安装（需 >= ${NODE_MIN_MAJOR}）：https://nodejs.org/

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
        # 走这条路的用户多半就是上次卡在「前端没构建 / Nginx 没配好」的人 —— 顺手补齐，
        # 并把控制台地址打出来，而不是静默退出让人以为没干活。
        ensure_nginx
        print_summary
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

    # 放在服务之后：Nginx 反代的目标必须已经起来，否则探活必然失败。
    step "配置 Nginx（自动安装 + 站点配置 + 放行端口）"
    ensure_nginx

    print_summary
}

main
