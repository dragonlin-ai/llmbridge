# LLM 路由中转系统（llmbridge）

> 一个 **OpenAI 兼容的 LLM 网关 + 智能路由**：请求进来先由判定器判断任务类型，
> 再转发到「最合适且最便宜」的下游大模型，全程可观测、可降级、可对账。

<p>
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-0.110%2B-009688">
  <img alt="vue" src="https://img.shields.io/badge/Vue-3.4-42b883">
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-green">
</p>

**简体中文** | [English](README_EN.md)

---

## 这是什么 / 不是什么

**是**：一个站在你的应用与各大模型厂商之间的**转发与决策层**。业务侧只认一个 OpenAI 兼容端点，
由网关决定这次请求该走哪个模型、失败了怎么退、花了多少钱。

**不是**：不是一个 Agent 框架，也不替调用方执行工具。
`tools` 字段会原样转发给下游，上游返回的 `tool_calls` 也原样回给调用方
（标准 OpenAI 语义，见下方「工具调用边界」）。网关只做转发与路由，不做编排。

---

## 核心特性

| 能力 | 说明 |
|---|---|
| **三层路由** | `L1 规则短路 → L2 判定器（Jev）→ L3 兜底`，判定在首个 token 下发**之前**完成 |
| **双入口隔离** | `/v1`（对外，OpenAI 兼容，**绝不透出 5xx 裸栈**）与 `/admin`（对内，完整错误信息）永不合流 |
| **内置厂商目录** | 13 家厂商 / 24 条接入通道 / 55 个模型，**填一个 Key 即接入**，无需手工建模型 |
| **密钥安全** | 厂商 Key 用 AES-256-GCM 加密落库；对外接口无任何回显 |
| **可观测** | 每个响应带 `x-router-*` 元信息头；请求日志含命中层级、实际模型、token、成本 |
| **成本对账** | 按模型 / 按层 / 按日聚合，与概览页**同源口径**（统一排除试跑台诊断流量） |
| **评测看板** | 内置评测集，可并发跑 Mock / 真实判定器，输出准确率与混淆矩阵 |
| **降级 + 兜底** | 上游失败按优先级降级重试，全失败也不向外透 5xx；兜底率 100% |
| **启动即自动初始化** | 首次启动自动建表 + 建默认管理员 + 预置全部主流接入商，幂等可重跑 |
| **Zero 依赖 i18n** | 控制台中英双语，不引入 vue-i18n（自研 `t()` / `setLang()`） |

---

## 架构

```
                    ┌──────────────── /v1（对外 · OpenAI 兼容）────────────────┐
客户端 ────────────▶│  鉴权 → 限流 → 路由判定 → 转发 → 流式回传               │
                    └──────────────────────────┬──────────────────────────────┘
                                               │
        ┌──────────────────────────────────────▼──────────────────────────────────┐
        │                          路由层 Router Engine（仅此一份）                │
        │   L1 规则短路  ──命中──▶                                  ┌─ 命中 ─┐   │
        │   （关键词 / 长度 / 正则）                                 │        │   │
        │   L2 判定器 Jev ──置信度 ≥ T2──▶  task_type + 候选打分 ────┤        │   │
        │   L3 兜底     ──置信度 < T2──▶  DEFAULT_MODEL_ID         ─┴─ 命中 ─┴─▶ │
        └──────────────────────────────────────┬──────────────────────────────────┘
                                               │  候选池唯一来源：load_routable_models()
                    ┌──────────────────────────▼──────────────────────────────┐
                    │  执行层 Adapter Pool（协议差异只在这里）                  │
                    │  OpenAICompatAdapter · 非流式 + SSE 流式                 │
                    └──────────────────────────┬──────────────────────────────┘
                                               │
                    ┌──────────────────────────▼──────────────────────────────┐
                    │  下游模型池：13 厂商 / 24 通道 / 55 模型                  │
                    │  api · package · batch · coding_plan · token_plan        │
                    └──────────────────────────┬──────────────────────────────┘
                                               │
                    ┌──────────────────────────▼──────────────────────────────┐
                    │  数据层：PostgreSQL（主） / SQLite（零依赖兜底）           │
                    │  request_log · provider · model · route_rule · sys_config │
                    └─────────────────────────────────────────────────────────┘

                    ┌──────────────── /admin（对内 · 控制台）──────────────────┐
                    │  厂商接入 · 模型 · 规则 · 日志 · 试跑台 · 评测 · 用量成本  │
                    └────────────────────────────────────────────────────────┘
```

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+（开发机 3.13）/ FastAPI / Uvicorn / SQLAlchemy 2.x（async） |
| 数据库 | PostgreSQL 14+（主，驱动 psycopg3）；SQLite（零依赖兜底，无需任何外部服务） |
| 缓存 / 限流 | Redis 7+（可选；缺失时自动降级，不影响功能） |
| 前端 | Vue 3.4 + Vite 5 + TypeScript 5.4 + Element Plus 2.6 + Pinia 2.1 + Vue Router 4 |
| 路由内核 | 自研三层判定（L1 规则 / L2 Jev 判定器 / L3 兜底），实现全局唯一一份 |
| 加密 | AES-256-GCM（厂商密钥）+ JWT（控制台会话） |
| Web 服务器 | Nginx（Docker Compose 形态内置；裸机形态由安装脚本生成站点配置） |
| 部署 | systemd（脚本安装）· Docker Compose · Apple container（macOS）· 源码 |

---

## ⚠️ 部署前必读

1. **默认口令 `admin / admin123` 必须在首次登录后立即修改。**
2. **`ENCRYPTION_MASTER_KEY` 必须备份。** 厂商 API Key 用它加密落库，
   一旦丢失，所有已录入的密钥**永久无法解密**（只能逐个重新填）。该值严禁提交 git。
3. **生产环境必须启用 HTTPS**，并保持 `.env` 的 `ALLOW_LOCAL_BASE_URL=false`
   （该开关允许厂商 `base_url` 指向 `http://` 与私网地址，是 SSRF 风险面，仅开发机可开）。
4. **模型池初始是空的，这是有意设计。** 首次安装只预置接入商（13 家 / 24 条通道），
   不预置模型 —— 你能用哪些 Model ID、什么价，取决于你的账号，网关不替你猜。
   必须先在「模型池」页添加至少一个模型，并给通道填 Key，路由候选池才非空。
5. **订阅类通道的单价是「参照值」**，按套餐额度折算，**不是真实边际成本**；
   条款限制（如「仅限编程工具交互式使用」）随通道原文落库并在控制台警示。
6. **请只接入你有权使用的上游服务**，并自行确认符合各厂商服务条款与适用法律。

---

## 部署

四种方式，按你的环境挑一种：

| 方式 | 适用场景 | 前置依赖 | 一句话 |
|---|---|---|---|
| **方式一 · 脚本安装**（推荐） | Linux 服务器生产部署 | Linux + Python 3.11+（可选 Node.js 20+） | 一条 `curl` 装完 |
| **方式二 · Docker Compose**（推荐） | 任意平台生产部署、想省去环境折腾 | Docker + Compose v2 | 一条 `curl` 起全栈 |
| └ 形态 A · 源码构建 | 目标机有源码、要改代码 | 同上 | `up -d --build` |
| └ 形态 B · 容器库镜像 | **目标机不需要任何源码**，适合交付给客户 | 同上，且能访问容器库 | `--image` |
| **方式三 · Apple container** | Apple Silicon Mac 本地开发 / 试用 | macOS 26+ + `container` 1.1.0+ | 三个子命令 |
| **方式四 · 源码编译** | 二次开发、离线交付、定制 | Python 3.11+ / Node.js 20+ | 见下文 |

> 完整步骤与验收记录另见 [`docs/阶段五-部署与交付/05-安装打包说明.md`](docs/阶段五-部署与交付/05-安装打包说明.md)。

---

### 方式一：脚本安装（推荐）

面向 **Linux 裸机**（systemd）。脚本自动完成：拉取源码 → 建运行用户 → 建虚拟环境 →
装依赖 → 生成 `.env`（随机密钥）→ 初始化数据 → 构建控制台前端 → 生成 Nginx 站点配置 →
注册并启动 systemd 服务。

#### 前置条件

- Linux（systemd 发行版；无 systemd 会提示改用 `--no-service`）
- Python **3.11+**（脚本会检测；不满足时给出各发行版的安装命令）
- **Node.js 20+**（用于构建控制台前端；缺失时脚本会明确告警并给出补装办法）
- Nginx（启用控制台用；脚本会生成站点配置，安装命令也在结束提示里给出）

#### 安装

```bash
curl -sSL https://raw.githubusercontent.com/dragonlin-ai/llmbridge/main/deploy/install.sh | sudo bash
```

已 clone 仓库时，直接用本地源码（不联网下载）：

```bash
sudo bash deploy/install.sh
```

常用选项：

```bash
sudo bash deploy/install.sh --port 9000            # 后端改监听 9000
sudo bash deploy/install.sh --dir /srv/llmbridge   # 换安装目录（默认 /opt/llmbridge）
sudo bash deploy/install.sh --postgres "postgresql+psycopg://user:pass@127.0.0.1:5432/llmbridge"
sudo bash deploy/install.sh --nginx-port 8080      # 生成 :8080 的站点配置（默认 80）
sudo bash deploy/install.sh --with-models          # 额外灌入目录里的参考模型与参考单价
sudo bash deploy/install.sh --skip-frontend        # 不构建前端（自备 dist 时）
sudo bash deploy/install.sh --frontend-only        # 只补构建前端，其它一律不碰
sudo bash deploy/install.sh --no-service           # 只铺代码与虚拟环境，不注册 systemd
sudo bash deploy/install.sh --help
```

> 数据库默认策略：探测本机 `5432`。**通**则按 PostgreSQL 配置；**不通**则退到 SQLite
> （`<安装目录>/llmbridge.db`），保证「装完就能打开界面」。
> 生产建议显式用 `--postgres` 指定，或装好后改 `.env` 的 `DATABASE_URL` 再重启。

#### 安装后：启用控制台

后端只提供 `/v1` 与 `/admin` 两套**接口**，不托管前端静态文件；控制台是需要 web 服务器
托管的独立 SPA。安装脚本已把站点配置生成好了（含 SSE 必要的 `proxy_buffering off`）：

```bash
sudo cp /opt/llmbridge/deploy/nginx-llmbridge.conf /etc/nginx/conf.d/llmbridge.conf
sudo nginx -t && sudo systemctl reload nginx
```

然后浏览器打开 `http://<服务器IP>/`，默认账号 `admin / admin123`。

> 用 Caddy 或其它 web 服务器也可以，只需满足两点：静态托管 `<安装目录>/admin-web/dist`
> 并对未命中路径回落 `index.html`；把 `/v1/`、`/admin/`、`/health` 反代到 `127.0.0.1:<port>`。

#### 升级

重复执行同一条安装命令即可 —— **代码更新，`.env`、数据库、已录入的密钥一律不动**：

```bash
curl -sSL https://raw.githubusercontent.com/dragonlin-ai/llmbridge/main/deploy/install.sh | sudo bash
```

补构建前端（例如装完 Node.js 之后）：

```bash
sudo bash /opt/llmbridge/deploy/install.sh --frontend-only
```

#### 卸载

```bash
sudo bash /opt/llmbridge/deploy/install.sh --uninstall        # 停服务、移除单元，保留数据目录
sudo bash /opt/llmbridge/deploy/install.sh --purge -y         # 连同安装目录与数据一起删除
```

#### 常用命令

```bash
systemctl status llmbridge          # 状态
systemctl restart llmbridge         # 重启（改 .env 后必须重启才生效）
journalctl -u llmbridge -f          # 实时日志

/opt/llmbridge/.venv/bin/llmbridge-seed                 # 手工执行初始化（幂等）
/opt/llmbridge/.venv/bin/llmbridge-catalog --dry-run    # 查看厂商目录预置结果，不写库
```

---

### 方式二：Docker Compose（推荐）

一条命令拉起 **api + PostgreSQL + Redis + Nginx** 四个容器。前端构建在容器内完成，
**宿主机不需要装 Node.js**。

#### 前置条件

- Docker Engine 20.10+（或 Docker Desktop），且守护进程已运行
- Docker Compose **v2**（`docker compose` 子命令形式）

#### 快速开始（一键部署）

```bash
curl -sSL https://raw.githubusercontent.com/dragonlin-ai/llmbridge/main/deploy/docker-deploy.sh | bash
```

脚本会：下载源码到 `./llmbridge` → 生成 `.env`（随机 `JWT_SECRET` /
`ENCRYPTION_MASTER_KEY` / `POSTGRES_PASSWORD`）→ 用 `node:22-alpine` 容器构建前端 →
`docker compose up -d --build` → 轮询 `/health` 直到就绪 → 打印访问地址。

常用选项与子命令：

```bash
bash deploy/docker-deploy.sh --port 8080        # 控制台对外端口（默认 80）
bash deploy/docker-deploy.sh --dir /srv/llmbridge
bash deploy/docker-deploy.sh --skip-frontend    # 已有 admin-web/dist 时跳过构建
bash deploy/docker-deploy.sh status             # 容器状态 + 健康检查
bash deploy/docker-deploy.sh logs api           # 跟随某个服务日志
bash deploy/docker-deploy.sh upgrade            # 拉代码 + 重建镜像 + 重启（数据保留）
bash deploy/docker-deploy.sh down               # 停止（保留数据卷）
bash deploy/docker-deploy.sh purge              # 停止并**删除数据卷**（不可恢复）
```

#### 手动部署

```bash
# 1) 获取代码
git clone https://github.com/dragonlin-ai/llmbridge.git
cd llmbridge

# 2) 配置（生产必改三项）
cp .env.example .env
#   JWT_SECRET / ENCRYPTION_MASTER_KEY：随机生成
#     python -c "import secrets;print(secrets.token_urlsafe(32))"
#     openssl rand -base64 32
#   POSTGRES_PASSWORD：与 DATABASE_URL 里的密码保持一致
#   HTTP_PORT：控制台对外端口（默认 80）

# 3) 构建前端（nginx 挂载 admin-web/dist，不构建则控制台空白）
cd admin-web && npm ci && npm run build && cd ..

# 4) 起全栈
docker compose -f deploy/docker-compose.yml up -d --build
```

生成密钥：

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"   # JWT_SECRET
openssl rand -base64 32                                        # ENCRYPTION_MASTER_KEY
openssl rand -base64 24 | tr -d '/+='                          # POSTGRES_PASSWORD
```

> ⚠️ `.env` 里的 `DATABASE_URL` 写的 `127.0.0.1` 是给「本机直连」用的；
> compose 会用服务名 `db` 覆盖它，无需手动改。

#### 数据与迁移

PostgreSQL 与 Redis 数据存放在 Docker **命名卷**（`llmbridge_pgdata` / `llmbridge_redisdata`），
容器重建不丢数据。整机迁移：

```bash
# 源服务器
docker compose -f deploy/docker-compose.yml stop
docker run --rm -v llmbridge_pgdata:/data -v "$PWD":/backup alpine \
  tar czf /backup/pgdata.tar.gz -C /data .

# 新服务器：还原到同名卷后再 up
docker volume create llmbridge_pgdata
docker run --rm -v llmbridge_pgdata:/data -v "$PWD":/backup alpine \
  tar xzf /backup/pgdata.tar.gz -C /data
```

SQLite 形态（方式一默认、方式三默认）直接拷 `<数据目录>/llmbridge.db` 即可。

#### 访问

浏览器打开 `http://<服务器IP>:<HTTP_PORT>/`（`HTTP_PORT` 默认 80），
默认账号 `admin / admin123`。对外 API 也在同一入口下：`http://<IP>:<HTTP_PORT>/v1/chat/completions`。

#### 升级

```bash
git pull
cd admin-web && npm ci && npm run build && cd ..
docker compose -f deploy/docker-compose.yml up -d --build
```

> `--build` 是必需的：前端 `dist/` 是 bind mount 进 nginx 的，
> **改了前端必须重新 build，重启容器不会生效**。

#### 常用命令

```bash
docker compose -f deploy/docker-compose.yml ps               # 状态
docker compose -f deploy/docker-compose.yml logs -f api      # 后端日志
docker compose -f deploy/docker-compose.yml restart api      # 重启后端
docker compose -f deploy/docker-compose.yml down             # 停止（保留卷）
docker compose -f deploy/docker-compose.yml down -v          # 停止并删除数据（危险）
```

---

#### 形态 B：从容器库拉取（不需要源码）

上面「快速开始 / 手动部署 / 升级 / 常用命令」说的都是**形态 A（源码构建）**：
镜像在目标机构建，前端 `dist` 通过 bind mount 进 nginx，所以目标机必须持有源码目录。

**形态 B** 把前端也做成镜像，容器库里两个镜像即构成完整系统：

| 镜像 | 内容 |
|---|---|
| `llmbridge-api` | 后端（FastAPI + 路由引擎 + 迁移脚本） |
| `llmbridge-web` | nginx + 已内置的前端 `dist` 与 `nginx.conf` |

目标机只需要**一个编排文件 + 一份 `.env`** —— 没有源码、不装 Node.js、不构建任何东西。

##### 1) 发布镜像（发布侧，一次即可）

```bash
# 登录容器库（密码由 docker 自己读取，不经过任何脚本、不写入任何文件）
docker login --username=<你的账号> registry.cn-hangzhou.aliyuncs.com

# 构建并推送 api + web（默认 linux/amd64,linux/arm64 双架构）
bash deploy/publish-image.sh --tag 1.0.0

# 只交付 x86 服务器时显式指定单平台（跨架构走 QEMU 模拟，明显更慢）
bash deploy/publish-image.sh --tag 1.0.0 --platform linux/amd64

# 先看会执行什么命令、不真跑
bash deploy/publish-image.sh --tag 1.0.0 --dry-run
```

脚本同时打两个标签：`1.0.0` 与 `1.0.0-<git短sha>`。**前者可被后续推送覆盖，后者不可变** ——
出问题时能回到「当时那一版」（生产建议用不可变标签或 digest）。

默认推送到 `registry.cn-hangzhou.aliyuncs.com/winyeahs/`，用 `--registry` 换命名空间：

```bash
bash deploy/publish-image.sh --registry registry.cn-hangzhou.aliyuncs.com/<你的命名空间> --tag 1.0.0
```

> ⚠️ 不要把容器库密码写进脚本、`.env` 或提交进仓库 —— 仓库里的明文口令等于公开。
> CI 场景用 `REGISTRY_USER` / `REGISTRY_PASSWORD` 环境变量交给脚本（内部走
> `docker login --password-stdin`），或改用容器库签发的临时凭证。

##### 2) 部署（目标机，只需要 Docker）

```bash
# 在仓库内
bash deploy/docker-deploy.sh --image --tag 1.0.0

# 或者完全不要源码：脚本自己取编排文件
curl -sSL https://raw.githubusercontent.com/dragonlin-ai/llmbridge/main/deploy/docker-deploy.sh \
  | bash -s -- --image --tag 1.0.0
```

脚本会：取 `docker-compose.image.yml` → 生成 `.env`（随机密钥）→ `compose pull` →
`compose up -d` → 轮询 `/health`。部署目录里最终只有两样东西：编排文件与 `.env`。

手工等价操作：

```bash
docker compose -f deploy/docker-compose.image.yml pull
docker compose -f deploy/docker-compose.image.yml up -d
```

升级与回滚（数据卷不受影响）：

```bash
docker compose -f deploy/docker-compose.image.yml pull
docker compose -f deploy/docker-compose.image.yml up -d      # 升到 .env 里写的 tag

# 回滚：把 .env 的 LLMBRIDGE_TAG 改回上一版（或不可变标签），重跑上面两行
```

##### 3) 形态 A ↔ 形态 B 切换

两种编排共用 compose 项目名 `llmbridge`，因此**共用同一套数据卷**
（`llmbridge_pgdata` / `llmbridge_redisdata`）—— 换形态不丢数据。
但服务名不同（A 是 `nginx`，B 是 `web`），切换前必须先停：

```bash
docker compose -f deploy/docker-compose.yml down       # 从 A 切到 B 之前
docker compose -f deploy/docker-compose.image.yml up -d
```

重建时若看到 `orphan containers` 警告，通常就是漏了这一步。

##### 4) 常见问题

- **`pull` 报 manifest 不存在**：确认该 tag 已发布（发布脚本结束时会打印 digest，
  也可用 `docker manifest inspect <镜像>:<tag>` 核对），并确认目标机架构在镜像支持列表里。
- **控制台 404 / 空白**：形态 B 的 `dist` 在 `llmbridge-web` 镜像里，没有「忘了构建前端」
  这一说；若仍空白，先看 `web` 容器是否真的起来了。
- **`exec format error`**：镜像架构与本机不符（如 arm64 镜像跑在 x86）。
  重新发布时带上目标平台，或让 `publish-image.sh` 同时产出 amd64 与 arm64。

---

### 方式三：Apple container（macOS）

Apple Silicon Mac 在 macOS 26 上可用 Apple 原生 `container`（1.1.0+）跑起完整网关。
本方式定位是**本地开发与人工运维**，生产部署请用方式一或方式二。

#### 前置条件

- Apple Silicon Mac + macOS 26 或更高
- Apple `container` 1.1.0+：`brew install container`
  （或从 [apple/container releases](https://github.com/apple/container/releases) 下载）
- 首次使用先执行一次 `container system start`（脚本也会自动尝试拉起）

#### 快速开始

```bash
git clone https://github.com/dragonlin-ai/llmbridge.git
cd llmbridge

./deploy/apple-container.sh init      # 检查环境 + 生成密钥 + 构建镜像
./deploy/apple-container.sh up        # 启动容器并等待 /health 就绪
./deploy/apple-container.sh status    # 查看容器、镜像与健康状态
```

之后打开 `http://127.0.0.1:8000/`，默认账号 `admin / admin123`。

默认形态是**单容器 + SQLite**，数据落在宿主机 `./llmbridge-data/`（可删除容器而不丢数据）。
之所以不做「PostgreSQL + Redis + 应用」多容器编排：Apple container 是逐容器手工编排的
（没有 compose 那样的依赖顺序与健康检查等待），让它管三层服务就得自己写启动时序轮询，
脆弱且难排障 —— 需要完整形态时请用方式二。

#### 常用命令

```bash
./deploy/apple-container.sh logs              # 跟随日志
./deploy/apple-container.sh shell             # 进容器
./deploy/apple-container.sh restart
./deploy/apple-container.sh upgrade           # 拉代码 + 重建镜像 + 重启（数据保留）
./deploy/apple-container.sh down              # 停并删除容器（保留数据目录）
./deploy/apple-container.sh purge             # 连数据目录一起删（不可恢复）
```

可调环境变量：

```bash
LLMBRIDGE_PORT=9000 ./deploy/apple-container.sh up    # 宿主机端口
LLMBRIDGE_BIND=0.0.0.0 ./deploy/apple-container.sh up # 对外暴露（请自备反代与 HTTPS）
LLMBRIDGE_DATA_DIR=/path ./deploy/apple-container.sh up
```

#### 切换 PostgreSQL

先起一个 PG 容器（或用远程 PG），再把连接串写进配置文件并重启：

```bash
vim ./llmbridge-data/.env      # 改 DATABASE_URL=postgresql+psycopg://user:pass@host:5432/llmbridge
./deploy/apple-container.sh restart
```

> 注意：不要写 `postgresql+asyncpg://` —— asyncpg 不在依赖里，会在真正建连时才报错。

---

### 方式四：源码编译

适合二次开发、定制，或需要产出离线发行包的场景。

#### 前置条件

| 组件 | 版本 |
|---|---|
| Python | **3.11+** |
| Node.js | 20+（仅控制台前端需要） |
| PostgreSQL | 14+（不装则自动回退 SQLite） |
| Redis | 7+（可选） |

#### 源码运行

```bash
# 1) 获取代码
git clone https://github.com/dragonlin-ai/llmbridge.git
cd llmbridge

# 2) 建虚拟环境并可编辑安装（改代码免重装）
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"      # Windows
# source .venv/bin/activate && pip install -e ".[dev]"   # Linux / macOS

# 3) 配置
cp .env.example .env
# 生产必改：JWT_SECRET、ENCRYPTION_MASTER_KEY、DATABASE_URL 里的密码

# 4) 启动（首次启动自动建表 / 默认管理员 / 预置接入商，幂等）
llmbridge-serve --host 127.0.0.1 --port 8000
```

验证后端：

```bash
curl -f http://127.0.0.1:8000/health
# {"status":"ok"}

curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"用一句话解释什么是量子纠缠"}]}'
```

构建并运行控制台：

```bash
cd admin-web
npm ci
npm run dev -- --host 127.0.0.1     # 开发模式，热更新：http://127.0.0.1:5173
npm run build                       # 生产产物：admin-web/dist
```

> **Windows + PostgreSQL 必读**：`uvicorn app.main:app` 直接启动会连不上数据库。
> uvicorn 默认的 loop 工厂返回 `ProactorEventLoop`，而 psycopg3 主动拒绝它 ——
> 症状是「服务起来了、`/health` 也是 200，但一访问数据库就 500」。
> 用 `llmbridge-serve` 即可，它内置了正确的 `SelectorEventLoop`；
> 若坚持用裸 uvicorn，必须带 `--loop app.core.eventloop:selector_loop_factory`。

#### 开发模式

```bash
# 后端（热重载）
llmbridge-serve --host 127.0.0.1 --port 8000 --reload

# 控制台（热重载，vite 代理 /admin 与 /v1 到 8000）
cd admin-web && npm run dev -- --host 127.0.0.1

# 测试
pytest
```

Windows 本机也可用现成脚本：

```powershell
.\deploy\windows\start-backend.ps1     # 只起后端
.\deploy\windows\start-dev.ps1         # 后端 + 控制台前端
```

#### 构建分发包

```bash
python -m build                        # 标准 wheel / sdist → dist/
python scripts/build_release.py        # 项目自带：组装可离线交付的 zip
```

`build_release.py` 产出 `release/llmbridge-<版本>-<日期>.zip`，内含后端代码、
数据库脚本、部署编排、前端静态产物，以及 `BUILD-INFO.txt` 与 `SHA256SUMS.txt`
（完整性清单）。常用选项：

```bash
python scripts/build_release.py --skip-frontend    # 前端已构建，跳过 npm
python scripts/build_release.py --no-archive       # 只组装目录，不压 zip
```

---

## 配置

全部配置走环境变量，模板见 [`.env.example`](.env.example)。最关键的几项：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./llmbridge.db` | PostgreSQL 用 `postgresql+psycopg://…`（**勿写 asyncpg**）；生产必改 |
| `POSTGRES_PASSWORD` | `change-me` | 仅 Docker Compose 形态使用（注入 db 与 api 容器） |
| `HTTP_PORT` | `80` | 仅 Docker Compose 形态：控制台对外端口 |
| `AUTO_BOOTSTRAP` | `true` | 启动时自动建表 / 建管理员 / 预置接入商，幂等。生产由 DBA 管库时可设 `false` |
| `JWT_SECRET` | `dev-only-change-me` | **生产必改**。控制台会话签名密钥 |
| `ENCRYPTION_MASTER_KEY` | `dev-only-change-me…` | **生产必改**。厂商 Key 的 AES-256-GCM 主密钥，**丢失不可恢复** |
| `ALLOW_LOCAL_BASE_URL` | `false` | 是否允许厂商 `base_url` 用 `http://` 与私网地址。**生产必须 false** |
| `REDIS_URL` | 空 | 留空则不启用缓存 / 限流（自动降级） |
| `JUDGE_PROVIDER` | `mock` | `mock` = 内置无依赖判定；`jev` = TypeSafe AI 官方 API |
| `ROUTE_CONFIDENCE_THRESHOLD_T2` | `0.5` | L2 置信度阈值，低于此值走 L3 兜底 |
| `DEFAULT_MODEL_ID` | `1` | 全部候选失败时的最终兜底模型 id。**必须指向模型池里真实存在的 id** |
| `ENABLE_TOOL_EXECUTION` | `false` | 见「工具调用边界」 |
| `REQUEST_TIMEOUT_MS` | `30000` | 上游调用超时 |

---

## 命令行

| 命令 | 作用 |
|---|---|
| `llmbridge-serve [--host] [--port] [--workers] [--reload]` | 启动网关。内置 psycopg3 兼容的事件循环，跨平台都是这一条。**启动时自动完成首次引导**（建表 / 默认管理员 / 内置评测样本 / 厂商接入目录），全部幂等 |
| `llmbridge-seed [--force]` | 手工执行同一套引导。幂等；已就绪时全部跳过。生产用 `AUTO_BOOTSTRAP=false` 关掉自动引导后，由运维显式跑这一条 |
| `llmbridge-catalog [--with-models] [--dry-run] [--overwrite] [--keep-names] [--prune-orphans] [--report PATH]` | 预置厂商接入目录。幂等，三级匹配认领旧行、不动已录密钥。默认**只铺接入通道** |

源码内的运维脚本：

```bash
python scripts/seed_provider_catalog.py --dry-run   # 同上（薄壳，逻辑在 app/data/catalog_seed.py）
python scripts/migrate_sqlite_to_pg.py              # SQLite → PostgreSQL 数据搬迁
python scripts/migrate_add_provider_channels.py     # 历史库补通道字段
python scripts/build_release.py                     # 打离线发行包
```

---

## 接口一览

对外（`/v1`，OpenAI 兼容）：

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/v1/chat/completions` | 唯一对外端点。`model` 传 `auto` 走智能路由，传具体模型名则短路直达 |

对内（`/admin`，需 JWT）共 24 条路径 / 35 个操作，覆盖：

```
/admin/auth/login                  /admin/providers[/{id}][/test]
/admin/models[/{id}][/references]  /admin/rules[/{id}][/priorities]
/admin/logs[/{trace_id}]           /admin/samples
/admin/api-keys[/{id}]             /admin/options
/admin/stats/overview              /admin/usage/report
/admin/route/preview               /admin/eval/report
/admin/decider/settings[/test]
```

**响应元信息头**（`x-router-*`，恒返回前 4 项）：

| 头 | 恒返回 | 说明 |
|---|---|---|
| `x-router-trace-id` | ✅ | 调用链唯一标识，与日志页、库内 `request_log` 对应 |
| `x-router-layer` | ✅ | 命中层级 `L1` / `L2` / `L3` |
| `x-router-model` | ✅ | **实际服务**的模型名（与决策值区分，降级后以后者为准） |
| `x-router-confidence` | ✅ | 置信度；L1 恒 `1.0`，L3 按兜底口径 |
| `x-router-task-type` | 仅 L2 | 任务类型；L1 短路与「显式指定模型」都不经判定器 |
| `x-router-tools` | 仅执行过工具 | 工具执行轮数（`ENABLE_TOOL_EXECUTION=true` 时） |

---

## 工具调用边界

网关**默认纯透传**（`ENABLE_TOOL_EXECUTION=false`）：

- 请求里的 `tools` / `tool_choice` 原样转发给下游；
- 上游返回的正文与原生 `tool_calls`、SSE 字节**一个字节都不改写**；
- 工具由**调用方**执行 —— 这是标准 OpenAI 语义，也是推荐用法。

若把 `ENABLE_TOOL_EXECUTION` 置 `true`，网关会自己执行白名单内的 `WebFetch`
（含 SSRF 拦截，私网/环回/链路本地地址一律拒绝）并续写多轮。
**仅适用于调用方完全没有工具循环的场景** —— 打开后网关会吞掉中间轮并改写正文，
使得「模型只说了一句话」与「工具没执行」在现象上无法区分。

---

## 项目结构

```
llmbridge/
├── app/                      后端（FastAPI）
│   ├── api/v1/               对外入口：OpenAI 兼容 + SSE
│   ├── api/admin/            对内入口：控制台全部接口
│   ├── router_engine/        路由内核（L1/L2/L3 判定编排，全局唯一一份）
│   ├── deciders/             判定器实现（mock / Jev）
│   ├── adapters/             下游协议适配（差异只允许出现在这里）
│   ├── services/             密钥、计费、日志缓冲、配额缓存、库级配置、工具、启动引导
│   ├── data/provider_catalog.py   内置厂商目录常量（只读）
│   ├── data/catalog_seed.py       厂商目录预置实现（包内，命令行与启动引导共用）
│   ├── db/                   ORM 表定义与会话
│   ├── core/                 配置、加解密、安全、事件循环
│   └── cli.py                命令行入口
├── admin-web/                控制台前端（Vue 3 + Vite + Element Plus）
├── scripts/                  幂等运维脚本（预置目录 / 历史库迁移 / 发行打包）
├── deploy/                   部署产物
│   ├── install.sh            ★ 方式一：Linux 一键安装（systemd）
│   ├── docker-deploy.sh      ★ 方式二：Docker Compose 一键部署（源码形态 / `--image` 容器库形态）
│   ├── publish-image.sh      ★ 容器库形态的发布侧：构建并推送 api + web 两个镜像
│   ├── apple-container.sh    ★ 方式三：macOS Apple container
│   ├── Dockerfile            后端镜像
│   ├── Dockerfile.web        前端镜像（nginx + 内置 dist 与 nginx.conf）
│   ├── docker-compose.yml    编排（api / db / redis / nginx）· 源码形态
│   ├── docker-compose.image.yml  编排（api / db / redis / web）· 容器库形态，无 build 段
│   ├── nginx.conf            Compose 形态的反向代理（SSE 关键配置；web 镜像内置此文件）
│   ├── nginx-standalone.conf 裸机形态的站点配置模板
│   ├── entrypoint.sh         容器入口：先初始化再启动
│   ├── healthcheck.py        探活（仅标准库）
│   ├── linux/                systemd 单元
│   └── windows/              本机启动脚本
├── docs/                     全阶段交付文档（需求 → 设计 → 开发 → 测试 → 部署）
├── tests/                    自动化测试
├── .env.example              环境变量模板
├── MANIFEST.in               sdist 内容清单
└── pyproject.toml            构建配置与依赖
```

---

## 文档索引

| 文档 | 内容 |
|---|---|
| [`docs/README.md`](docs/README.md) | **项目总纲**（当前基线），架构、接口、约定、验收一次性看全 |
| [`docs/阶段一-需求与规划/`](docs/阶段一-需求与规划/) | 需求规格、UI 设计、项目计划、验收标准、风险清单 |
| [`docs/阶段二-设计与架构/`](docs/阶段二-设计与架构/) | 架构设计、接口设计、数据库设计、安全方案 |
| [`docs/阶段三-开发与实现/`](docs/阶段三-开发与实现/) | 技术实现、代码审查、端到端联调验证记录 |
| [`docs/阶段四-测试与验证/`](docs/阶段四-测试与验证/) | 测试计划、用例、缺陷报告、质量评估 |
| [`docs/阶段五-部署与交付/`](docs/阶段五-部署与交付/) | **安装打包说明**、部署文档、用户手册、运维手册 |

---

## 已知限制

- **流式请求的 token 用量依赖上游**：若客户端未传 `stream_options.include_usage`，
  部分厂商不回 `usage`，该条日志的 token / 成本会记 0 —— 是「缺数据」，不是「零消耗」。
- **纯 HTTP 抓取拿不到 JS 渲染站点正文**（仅 `ENABLE_TOOL_EXECUTION=true` 时相关）。
- **模型池默认是空的**：首次安装只预置接入商，不预置模型（各账号可用模型与计费口径不同）。
  必须先在「模型池」页添加至少一个模型、并给通道填 Key，路由候选池才非空；
  否则 `/v1` 请求会走兜底路径并如实报错，控制台概览也会是 0。
  `.env` 的 `DEFAULT_MODEL_ID` 要指向**真实存在**的模型 id。
- **`alembic/` 目录预留但未启用**：当前建表走 ORM `create_all`（服务启动引导 / `llmbridge-seed`），
  历史库升级走 `scripts/migrate_*.py`。
- **方式三（Apple container）未在真机端到端验证**：脚本按 Apple `container` CLI 编写并做了
  shell 静态检查，但开发机为 Windows，无法执行 macOS 特有路径。首次使用请留意脚本输出。
- 目录里厂商参考价来自官方公开页，**订阅类套餐的单价是按额度折算的参照值**，
  不是真实边际成本；条款限制（如「仅限编程工具交互式使用」）原文随通道落库并在控制台警示。

---

## 许可证

[Apache License 2.0](LICENSE)
