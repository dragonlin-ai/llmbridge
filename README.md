# LLM 路由中转系统（llmbridge）

> 一个 **OpenAI 兼容的 LLM 网关 + 智能路由**：请求进来先由判定器判断任务类型，
> 再转发到「最合适且最便宜」的下游大模型，全程可观测、可降级、可对账。

<p>
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-0.110%2B-009688">
  <img alt="vue" src="https://img.shields.io/badge/Vue-3.4-42b883">
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-green">
</p>

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

## 快速开始

### 前置

| 组件 | 版本 | 是否必需 |
|---|---|---|
| Python | **3.11+**（开发机验证于 3.13.14） | 必需 |
| PostgreSQL | 14+ | 生产必需；本机不装会**自动回退 SQLite** |
| Node.js | 20+（开发机验证于 22.18.0） | 仅控制台前端需要 |
| Redis | 7+ | 可选，缺失时缓存/限流自动降级 |

### 五步跑起来

```bash
# 1) 获取代码
git clone https://github.com/linwf/llmbridge_python.git
cd llmbridge_python

# 2) 建虚拟环境并安装（-e 可编辑安装，改代码免重装）
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"      # Windows
# source .venv/bin/activate && pip install -e ".[dev]"   # Linux / macOS

# 3) 配置环境变量
cp .env.example .env
# 生产必改三项：JWT_SECRET、ENCRYPTION_MASTER_KEY、DATABASE_URL 里的密码
#   JWT_SECRET:            python -c "import secrets;print(secrets.token_urlsafe(32))"
#   ENCRYPTION_MASTER_KEY: openssl rand -base64 32

# 4) 初始化数据库（两个命令都是幂等的，可重复执行）
llmbridge-seed                    # 建表 + 最小种子数据（厂商/模型/规则/管理员）
llmbridge-catalog                 # 灌入内置厂商目录（13 家 / 24 通道 / 55 模型）
# 只想看会做什么不写库：llmbridge-catalog --dry-run

# 5) 启动
llmbridge-serve --host 127.0.0.1 --port 8000
```

验证：

```bash
curl -f http://127.0.0.1:8000/health
# {"status":"ok"}

curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"用一句话解释什么是量子纠缠"}]}'
```

控制台前端：

```bash
cd admin-web
npm ci
npm run dev -- --host 127.0.0.1     # http://127.0.0.1:5173
```

默认账号 **`admin` / `admin123`** —— **首次登录后请立即改密**。

> **Windows + PostgreSQL 必读**：`uvicorn app.main:app` 直接启动会连不上数据库。
> uvicorn 默认的 loop 工厂返回 `ProactorEventLoop`，而 psycopg3 主动拒绝它 ——
> 症状是「服务起来了、`/health` 也是 200，但一访问数据库就 500」。
> 用 `llmbridge-serve` 即可，它内置了正确的 `SelectorEventLoop`；
> 若坚持用裸 uvicorn，必须带 `--loop app.core.eventloop:selector_loop_factory`。

---

## 命令行

| 命令 | 作用 |
|---|---|
| `llmbridge-serve [--host] [--port] [--workers] [--reload]` | 启动网关。内置 psycopg3 兼容的事件循环，跨平台都是这一条 |
| `llmbridge-seed` | 建表 + 写入最小可跑集。幂等；已有数据则跳过 |
| `llmbridge-catalog [--dry-run] [--overwrite] [--prune-orphans] [--report PATH]` | 预置内置厂商目录。幂等，三级匹配认领旧行、不动已录密钥 |

源码内的运维脚本：

```bash
python scripts/seed_provider_catalog.py --dry-run   # 同上，更细的选项
python scripts/migrate_sqlite_to_pg.py              # SQLite → PostgreSQL 数据搬迁
python scripts/migrate_add_provider_channels.py     # 历史库补通道字段
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

## 目录结构

```
llmbridge_python/
├── app/                      后端（FastAPI）
│   ├── api/v1/               对外入口：OpenAI 兼容 + SSE
│   ├── api/admin/            对内入口：控制台全部接口
│   ├── router_engine/        路由内核（L1/L2/L3 判定编排，全局唯一一份）
│   ├── deciders/             判定器实现（mock / Jev）
│   ├── adapters/             下游协议适配（差异只允许出现在这里）
│   ├── services/             密钥、计费、日志缓冲、配额缓存、库级配置、工具
│   ├── data/provider_catalog.py   内置厂商目录常量（只读）
│   ├── db/                   ORM 表定义与会话
│   ├── core/                 配置、加解密、安全、事件循环
│   └── cli.py                命令行入口
├── admin-web/                控制台前端（Vue 3 + Vite + Element Plus）
├── scripts/                  幂等运维脚本（预置目录 / 历史库迁移）
├── deploy/                   部署产物
│   ├── Dockerfile            后端镜像
│   ├── docker-compose.yml    编排（api / db / redis / nginx）
│   ├── nginx.conf            反向代理（SSE 关键配置）
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

## 部署

三种形态的完整步骤见 **[`docs/阶段五-部署与交付/05-安装打包说明.md`](docs/阶段五-部署与交付/05-安装打包说明.md)**。

```bash
# Docker Compose（生产推荐）
cp .env.example .env                 # 改 JWT_SECRET / ENCRYPTION_MASTER_KEY / POSTGRES_PASSWORD
cd admin-web && npm ci && npm run build && cd ..
docker compose -f deploy/docker-compose.yml up -d --build
```

```powershell
# Windows 本机
.\deploy\windows\start-backend.ps1              # 只起后端
.\deploy\windows\start-dev.ps1                  # 后端 + 控制台前端（开发）
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
- **`alembic/` 目录预留但未启用**：当前建表走 ORM `create_all`（`llmbridge-seed`），
  历史库升级走 `scripts/migrate_*.py`。
- 目录里厂商参考价来自官方公开页，**订阅类套餐的单价是按额度折算的参照值**，
  不是真实边际成本；条款限制（如「仅限编程工具交互式使用」）原文随通道落库并在控制台警示。

---

## 许可证

[Apache License 2.0](LICENSE)
