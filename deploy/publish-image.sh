#!/usr/bin/env bash
#
# =============================================================================
#  LLM 路由中转系统（llmbridge）· 镜像构建并推送到容器库
# =============================================================================
#
#  用法：
#    # 1) 先登录容器库（密码由 docker 自己读取，不经过本脚本、不进任何文件）
#    docker login --username=<你的账号> registry.cn-hangzhou.aliyuncs.com
#
#    # 2) 构建并推送 api + web 两个镜像
#    bash deploy/publish-image.sh --tag 1.0.0
#
#    # 3) 目标机部署（只要容器库能访问，就不需要源码）
#    bash deploy/docker-deploy.sh --image
#
#  选项：
#    --registry <host/ns>   容器库地址 + 命名空间
#                           （默认 registry.cn-hangzhou.aliyuncs.com/winyeahs）
#    --tag <tag>            版本标签（默认 1.0.0）
#    --platform <list>      目标平台（默认 linux/amd64,linux/arm64）
#    --only <api|web>       只出其中一个镜像（默认两个都出）
#    --load                 只构建到本机（仅单平台，不推送；用于本机验证）
#    --no-immutable         不附带 git 短 sha 的不可变标签（默认附带）
#    --dry-run              只打印将执行的命令，不真正构建
#    -y, --yes              非交互，跳过推送前确认
#
#  账号密码怎么给（脚本一律不落盘）：
#    已登录过    直接跑，脚本只做检测。
#    环境变量    自动登录：REGISTRY_USER=xxx REGISTRY_PASSWORD=yyy bash deploy/publish-image.sh
#    都没有      脚本会提示你手动执行 docker login（密码由 docker 提示输入）。
#    ⚠️ 不要把密码写进本文件或 .env —— 仓库里任何明文口令都等于公开。
#
#  为什么同时打两个标签：
#    `1.0.0` 这类浮动标签可以被后续推送覆盖，同一个标签指向的镜像会变，
#    出问题时无法回到「当时那一版」。所以额外推一个 `1.0.0-<git短sha>` 的
#    不可变标签，部署侧用哪个自己选（生产建议用不可变标签或 digest）。
#
#  多平台说明：
#    linux/arm64 在 x86 构建机上要靠 QEMU 模拟，明显慢于 amd64 ——
#    前端阶段要跑 npm ci 与 vue-tsc，跨架构下尤其慢。
#    只交付 x86 服务器就显式传 --platform linux/amd64。
# =============================================================================

set -euo pipefail

# 不用 dirname —— 最小化/异常的 bash 环境里可能没有它（本项目开发机的
# Git Bash 就缺 dirname/head/awk，docker-deploy.sh 里有同款说明）。
case "$0" in
    */*) SELF_DIR="${0%/*}" ;;
    *)   SELF_DIR="." ;;
esac
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"

# 用产物做判据而不是看目录存不存在：管道执行（curl | bash）时 $0 不是路径，
# SELF_DIR 会退化成 "."，此时 cd 到上一级很可能是个无关目录却「看起来正常」。
if [ ! -f "$REPO_ROOT/pyproject.toml" ] || [ ! -f "$REPO_ROOT/deploy/Dockerfile" ]; then
    echo "[失败] 未定位到仓库根目录（当前推断为 $REPO_ROOT）。请用 bash deploy/publish-image.sh 在仓库内执行，本脚本不支持管道执行。" >&2
    exit 1
fi

REGISTRY="${LLMBRIDGE_REGISTRY:-registry.cn-hangzhou.aliyuncs.com/winyeahs}"
TAG="${LLMBRIDGE_TAG:-1.0.0}"
PLATFORMS="${LLMBRIDGE_PLATFORMS:-linux/amd64,linux/arm64}"
ONLY=""
IMMUTABLE="true"
DRY_RUN="false"
ASSUME_YES="false"
USE_LOAD="false"

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
    # 打印文件头注释块。用 shell 内建逐行读取，不依赖 awk/head —— 本项目的
    # 开发机 Git Bash 就缺这些（详见 docker-deploy.sh 里的同款说明）。
    if [ ! -f "$0" ]; then
        echo "llmbridge 镜像发布脚本。完整用法见仓库内 deploy/publish-image.sh 头部注释。"
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

while [ $# -gt 0 ]; do
    case "$1" in
        --registry)     REGISTRY="${2:?--registry 需要参数}"; shift 2 ;;
        --tag)          TAG="${2:?--tag 需要参数}"; shift 2 ;;
        --platform)     PLATFORMS="${2:?--platform 需要参数}"; shift 2 ;;
        --only)         ONLY="${2:?--only 需要参数}"; shift 2 ;;
        --load)         USE_LOAD="true"; shift ;;
        --no-immutable) IMMUTABLE="false"; shift ;;
        --dry-run)      DRY_RUN="true"; shift ;;
        -y|--yes)       ASSUME_YES="true"; shift ;;
        -h|--help)      usage ;;
        *)              die "未知参数：$1（用 --help 查看用法）" ;;
    esac
done

case "$ONLY" in
    ""|api|web) ;;
    *) die "--only 只接受 api 或 web，收到：$ONLY" ;;
esac

# 去掉可能被写进来的尾部斜杠，避免拼出 //（部分 registry 会因此 401）。
REGISTRY="${REGISTRY%/}"
# registry 主机名 = 第一段（用于登录检测）
REGISTRY_HOST="${REGISTRY%%/*}"

if [ "$USE_LOAD" = "true" ]; then
    case "$PLATFORMS" in
        *,*) die "--load 只支持单平台。多平台镜像必须直接推送到容器库（去掉 --load 与 --platform 里的逗号）。" ;;
    esac
fi

# =============================================================================
#  环境检查
# =============================================================================

check_docker() {
    command -v docker >/dev/null 2>&1 || die "未找到 docker。请先安装 Docker Engine 或 Docker Desktop。"
    if [ "$DRY_RUN" = "true" ]; then
        # dry-run 不执行任何 docker 命令，没必要要求守护进程在跑 ——
        # 否则「在没开 Docker 的机器上看一眼会推什么」这件正事都做不了。
        info "容器运行时：$(docker --version)"
        info "dry-run：跳过守护进程与 buildx 检查"
        return 0
    fi
    docker info >/dev/null 2>&1 || die "Docker 守护进程未运行（docker info 失败）。请先启动 Docker。"
    docker buildx version >/dev/null 2>&1 || die "未找到 docker buildx。请升级 Docker（20.10+ 自带 buildx）。"
    info "容器运行时：$(docker --version)"
    info "构建器：$PLATFORMS"
}

check_login() {
    # --load 不推送、--dry-run 不执行，都不需要凭据。
    if [ "$USE_LOAD" = "true" ] || [ "$DRY_RUN" = "true" ]; then
        return 0
    fi

    # 已配置凭据则直接过（不做网络探测：首次推送时远端本来就没有该镜像，
    # 探测结果无法区分「没登录」和「镜像不存在」，反而误导）。
    if docker_logged_in; then
        info "检测到已登录 $REGISTRY_HOST"
        return 0
    fi

    if [ -n "${REGISTRY_USER:-}" ] && [ -n "${REGISTRY_PASSWORD:-}" ]; then
        info "使用环境变量中的凭据登录 $REGISTRY_HOST（用户名：$REGISTRY_USER）"
        printf '%s' "$REGISTRY_PASSWORD" | docker login "$REGISTRY_HOST" \
            --username "$REGISTRY_USER" --password-stdin >/dev/null \
            || die "登录失败。请核对账号/密码，或改为手动执行 docker login。"
        ok "已登录 $REGISTRY_HOST"
        return 0
    fi

    cat >&2 <<EOF
${C_YELLOW}未检测到 $REGISTRY_HOST 的登录凭据${C_OFF}

请先登录（密码由 docker 自己读取，不经过本脚本、不写入任何文件）：

  docker login --username=<你的账号> $REGISTRY_HOST

或改用环境变量（适合 CI，注意别让它留在 shell 历史里）：

  REGISTRY_USER=<账号> REGISTRY_PASSWORD=<密码> bash deploy/publish-image.sh

${C_YELLOW}别把密码写进本脚本或 .env${C_OFF} —— 仓库里的明文口令等于公开。
推送前请顺手确认一遍：git status 里不应出现任何含口令的改动。

EOF
    exit 1
}

docker_logged_in() {
    local cfg="${DOCKER_CONFIG:-$HOME/.docker}/config.json"
    [ -f "$cfg" ] || return 1
    # 不用 grep/fgrep —— 最小化环境里可能没有；纯 shell 匹配即可。
    case "$(cat "$cfg")" in
        *"$REGISTRY_HOST"*) return 0 ;;
        *) return 1 ;;
    esac
}

# =============================================================================
#  标签
# =============================================================================

GIT_SHA=""
resolve_git_sha() {
    command -v git >/dev/null 2>&1 || return 0
    ( cd "$REPO_ROOT" && git rev-parse --short=8 HEAD 2>/dev/null ) || return 0
}

API_IMAGE="$REGISTRY/llmbridge-api"
WEB_IMAGE="$REGISTRY/llmbridge-web"

IMMUTABLE_TAG=""
if [ "$IMMUTABLE" = "true" ]; then
    GIT_SHA="$(resolve_git_sha)"
    if [ -n "$GIT_SHA" ]; then
        IMMUTABLE_TAG="${TAG}-${GIT_SHA}"
    else
        warn "取不到 git 短 sha（不在仓库内或未安装 git），跳过不可变标签。"
    fi
fi

# 下面两段是给确认提示与结束提示复用的，避免在 heredoc 里塞命令替换
# （命令替换的失败会污染退出码，也让 --dry-run 之外的输出难以预判）。
BUILT_LIST=""
if [ "$ONLY" != "web" ]; then BUILT_LIST="${API_IMAGE}:${TAG}"; fi
if [ "$ONLY" != "api" ]; then BUILT_LIST="${BUILT_LIST}${BUILT_LIST:+ / }${WEB_IMAGE}:${TAG}"; fi

IMMUTABLE_NOTE=""
if [ -n "$IMMUTABLE_TAG" ]; then
    IMMUTABLE_NOTE="  不可变标签  ${IMMUTABLE_TAG}（两个镜像均附加）"
fi

# =============================================================================
#  构建
# =============================================================================

BUILDER="llmbridge-builder"

prepare_builder() {
    if [ "$DRY_RUN" = "true" ]; then
        return 0
    fi
    if docker buildx inspect "$BUILDER" >/dev/null 2>&1; then
        docker buildx use "$BUILDER" >/dev/null
        info "复用构建器：$BUILDER"
    else
        docker buildx create --name "$BUILDER" --use >/dev/null || die "创建 buildx 构建器失败。"
        info "已创建构建器：$BUILDER"
    fi
    docker buildx inspect --bootstrap >/dev/null 2>&1 || true
}

run() {
    if [ "$DRY_RUN" = "true" ]; then
        printf '%s[dry-run]%s' "$C_YELLOW" "$C_OFF"
        printf ' %q' "$@"
        printf '\n'
        return 0
    fi
    "$@"
}

build_one() {
    local name="$1" image="$2" dockerfile="$3"
    local -a args=(docker buildx build
        --platform "$PLATFORMS"
        --file "$dockerfile"
        --tag "${image}:${TAG}"
    )
    if [ -n "$IMMUTABLE_TAG" ]; then
        args+=(--tag "${image}:${IMMUTABLE_TAG}")
    fi
    # 关掉 provenance/SBOM attestation：否则 manifest list 里会多出
    # `unknown/unknown` 平台条目，部分 registry 与旧版 docker pull 会因此失败。
    args+=(--provenance=false --sbom=false)
    if [ "$USE_LOAD" = "true" ]; then
        args+=(--load)
    else
        args+=(--push)
    fi
    args+=("$REPO_ROOT")

    step "构建 $name 镜像：${image}:${TAG}"
    if [ -n "$IMMUTABLE_TAG" ]; then
        info "同时打不可变标签：${image}:${IMMUTABLE_TAG}"
    fi
    run "${args[@]}" || die "$name 镜像构建/推送失败。"
}

confirm() {
    if [ "$ASSUME_YES" = "true" ]; then
        return 0
    fi
    cat <<EOF

${C_BOLD}即将构建并推送${C_OFF}
  容器库    $REGISTRY
  版本标签  $TAG
$IMMUTABLE_NOTE
  平台      $PLATFORMS
  镜像      $BUILT_LIST

EOF
    printf '继续？[y/N] '
    read -r ans
    case "$ans" in y|Y|yes|YES) ;; *) info "已取消。"; exit 0 ;; esac
}

show_digest() {
    if [ "$USE_LOAD" = "true" ] || [ "$DRY_RUN" = "true" ]; then
        return 0
    fi
    local img
    for img in "$API_IMAGE" "$WEB_IMAGE"; do
        if [ "$ONLY" = "api" ] && [ "$img" = "$WEB_IMAGE" ]; then
            continue
        fi
        if [ "$ONLY" = "web" ] && [ "$img" = "$API_IMAGE" ]; then
            continue
        fi
        info "远端摘要 ${img}:${TAG}"
        docker buildx imagetools inspect "${img}:${TAG}" 2>/dev/null || \
            warn "读取 ${img}:${TAG} 摘要失败，可稍后手动确认。"
    done
}

# =============================================================================

check_docker
check_login

if [ "$DRY_RUN" != "true" ] && [ -n "$PLATFORMS" ] && [ "$USE_LOAD" != "true" ]; then
    case "$PLATFORMS" in
        *arm64*|*aarch64*)
            case "$(uname -m 2>/dev/null || echo unknown)" in
                aarch64|arm64) ;;
                *) warn "跨架构构建依赖 QEMU 模拟，会明显变慢。若报 'exec format error'，执行：docker run --privileged --rm tonistiigi/binfmt --install all" ;;
            esac
            ;;
    esac
fi

confirm
prepare_builder

if [ "$ONLY" != "web" ]; then
    build_one "后端" "$API_IMAGE" "$REPO_ROOT/deploy/Dockerfile"
fi
if [ "$ONLY" != "api" ]; then
    build_one "前端" "$WEB_IMAGE" "$REPO_ROOT/deploy/Dockerfile.web"
fi

if [ "$USE_LOAD" = "true" ]; then
    ok "已构建到本机（未推送）：$BUILT_LIST"
    info "本机验证镜像内容（确认产物真在镜像里，而不是挂载进来的）："
    info "  docker run --rm --entrypoint ls ${WEB_IMAGE}:${TAG} -l /usr/share/nginx/html"
    info "  docker run --rm --entrypoint ls ${API_IMAGE}:${TAG} -l /app"
else
    show_digest
    DONE_TITLE="推送完成"
    if [ "$DRY_RUN" = "true" ]; then
        DONE_TITLE="dry-run 结束（以上命令均未真正执行）"
    fi
    cat <<EOF

${C_GREEN}${C_BOLD}${DONE_TITLE}${C_OFF}
  镜像        $BUILT_LIST
$IMMUTABLE_NOTE

${C_BOLD}目标机部署（不需要源码）${C_OFF}
  bash deploy/docker-deploy.sh --image --tag ${TAG}
  # 或在 .env 里写 LLMBRIDGE_REGISTRY / LLMBRIDGE_TAG 后：
  #   docker compose -f deploy/docker-compose.image.yml up -d

${C_YELLOW}生产建议${C_OFF}：用不可变标签或 digest 锁版本，别让浮动标签在半夜被覆盖。

EOF
fi
