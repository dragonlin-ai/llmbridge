<!-- 顶部（图标 / 标题 / 简介 / 徽章 / 语言切换）居中：GitHub 的 HTML 块在空行处结束，
     因此 <div> 内部的 Markdown 仍会被正常解析，标题锚点不受影响。 -->
<div align="center">

<img src=".github/images/llmbridge-logo.svg" alt="llmbridge" width="120" height="120">

# LLM 路由中转系统（llmbridge）

> 一个 **OpenAI 兼容的 LLM 网关 + 智能路由**：请求进来先由 **Jev 决策模型**判定任务类型与复杂度，
> 再转发到「最合适且最便宜」的下游大模型 —— 判定发生在首个 token 之前，全程可观测、可降级、可对账。

<p>
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-0.110%2B-009688">
  <img alt="vue" src="https://img.shields.io/badge/Vue-3.4-42b883">
  <img alt="decider" src="https://img.shields.io/badge/decider-Jev%20%C2%B7%20TypeSafe%20AI-7c3aed">
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-green">
</p>

**简体中文** | [English](README_EN.md)

</div>

<details>
<summary><b>目录</b></summary>

- [这是什么 / 不是什么](#这是什么--不是什么)
- [**决策内核：Jev**](#决策内核jev)
- [核心特性](#核心特性)
- [架构](#架构)
- [技术栈](#技术栈)
- [部署前必读](#-部署前必读)
- [部署](#部署)
- [配置](#配置)
- [命令行](#命令行)
- [接口一览](#接口一览)
- [工具调用边界](#工具调用边界)
- [项目结构](#项目结构)
- [文档索引](#文档索引)
- [已知限制](#已知限制)
- [交流与社区](#-交流与社区)
- [许可证](#许可证)

</details>

---

## 这是什么 / 不是什么

**是**：一个站在你的应用与各大模型厂商之间的**转发与决策层**。业务侧只认一个 OpenAI 兼容端点，
由网关决定这次请求该走哪个模型、失败了怎么退、花了多少钱。

**不是**：不是一个 Agent 框架，也不替调用方执行工具。
`tools` 字段会原样转发给下游，上游返回的 `tool_calls` 也原样回给调用方
（标准 OpenAI 语义，见下方「工具调用边界」）。网关只做转发与路由，不做编排。

---

## 决策内核：Jev

> **「这次该用哪个模型」不是靠关键词表拍脑袋，也不是让一个大模型写段 JSON 再解析 ——
> 而是交给一个专门做判定的决策模型：Jev。**
> 判定结果不是文本，是**带校准概率的类型化值**。这是本项目与同类网关最大的区别。

### 一、Jev 是什么

**Jev** 是 [TypeSafe AI](https://typesafe.ai)（旧金山；创始人 Diogo Almeida，前 OpenAI，
参与过 ChatGPT / RLHF 相关工作）于 **2026-09-15** 发布的 **System One** 决策模型。
它与「生成式大模型」是**互补**关系，而不是一个更小号的替代品：

| | 常见做法：拿大模型当裁判 | **Jev（本项目所用）** |
|---|---|---|
| 工作方式 | 自回归逐 token 生成，再解析 JSON | **非自回归**：一次前向直接给出判定，**不生成任何文本** |
| 输出 | 一段文字 + 需要二次校验/重试的 JSON | **类型化判定**（选项必然落在给定枚举内）+ **校准过的概率** |
| 延迟 | 秒级（前沿模型 3～329s 量级） | 官方 **70～500ms**；本项目实测单次 **0.4～1.2s**（含跨网往返） |
| 置信度可信度 | 编出来的，只能当噪声 | **经 RLCD 训练校准**：说 0.9 就真有约 90% 兑现 → **阈值才真正可用** |
| 可解释性 | 会附一段自然语言理由 | **不写理由**（这是换来速度与成本所付的代价） |
| 出错方式 | 可能吐出枚举外的值或格式坏掉 | 类型层面不可能出错，但**选项本身仍可能选错** |

计费口径：输入 **$0.042 / 百万 token**，**输出 token 免费**。

### 二、三种原语（一次请求可并行混问，延迟几乎不增加）

| 原语 | 回答什么 | 返回什么 | 本项目用它判定 |
|---|---|---|---|
| **Choice** | 从固定选项里选一个 | `choice` + `probabilities` + `confidence` | `task_type` —— 6 类任务之一 |
| **Score** | 按 rubric 打分 | `score` + `probabilities` | `complexity` —— 简单 / 中等 / 复杂 |
| **Noul** | 是 / 否 | `noul`（0～1 概率） | `has_code`、`is_sensitive` |

### 三、本项目怎么用它

**一次调用、并行问 4 个原子问题**（下为 `app/deciders/jev_decider.py` 发出的真实请求体）：

```jsonc
POST https://api.typesafe.ai/v1/systemone        // Authorization: Bearer $JEV_API_KEY
{
  "state": "<用户输入，截断至 1000 字符>",        // 判定输入最小化：不带历史、不带 system
  "model": "jev-latest",
  "questions": {
    "task_type":    { "type": "choice", "criteria": { /* general / code_generation / translation
                                                        / summarize / complex_reasoning / long_context */ } },
    "complexity":   { "type": "score",  "criteria": ["简单", "中等", "复杂"] },
    "has_code":     { "type": "noul" },
    "is_sensitive": { "type": "noul" }
  }
}
```

拿到 `task_type` + 置信度 + 复杂度 + 两个特征标记之后，**具体调哪个模型由代码层的映射表
结合成本 / 延迟 / 健康度权重决定**，而不是让 Jev 直接挑模型 id。这样做有三个理由：

1. 模型池怎么增删，都不必改动判定器；
2. `task_type` 是稳定概念，`model_id` 不是；
3. 权重与阈值随时可调，且**改动可审计**（改代码，而不是改一段没人看得懂的提示词）。

整条判定链的形状：

```
用户输入
   │
   ├─▶ Jev：一次调用，并行问 4 个原子问题
   │     task_type(Choice) · complexity(Score) · has_code(Noul) · is_sensitive(Noul)
   │     └─▶ 类型化判定 + 校准概率（不生成文本，也不给理由）
   │
   └─▶ 代码层：task_type → 能力标签映射 × 成本 / 延迟 / 健康度权重
         └─▶ 具体 model_id（可审计、可回放、可灰度调整）
```

### 四、为什么这个设计值得关注

1. **判定在首个 token 之前完成** —— 不牺牲首字延迟，也不需要「先答应、再改口」式的重试。
2. **置信度终于可以当阈值用**：低于 `ROUTE_CONFIDENCE_THRESHOLD_T2` 即走 L3 兜底；
   每个响应都带 `x-router-*` 元信息头，`request_log` 落库命中层级与 `fallback_reason`。
3. **失败必留痕**：Jev 不可达 / key 失效 / 返回枚举外值时，一律写 `fallback_reason=DECIDER_*` 并打 warning
   —— **绝不伪装成「置信度低」**（否则「判定器挂了」与「判定不准」在外部无法区分，排查代价极高）。
4. **判定器可插拔**：路由层只依赖 `BaseDecider`，内置 `mock`（零依赖、离线可用，**默认**）与 `jev` 两个实现，
   走同一组契约测试；控制台可在两者间切换，无需改代码。
5. **概率分布可复盘**：Jev 不给理由，但落库的 `probabilities` 比「编出来的理由」更可信；
   评测看板可并发跑真实判定器，直接给出准确率与混淆矩阵。

### 五、接入方式与现状（如实说）

| 项 | 值 |
|---|---|
| 模型 id | `jev-latest`（2026-09-21 实测回传 `jev-1.13.0`） |
| 端点 | `POST https://api.typesafe.ai/v1/systemone`，Bearer 鉴权 |
| 控制台配置 | 「判定器」页 5 项：`JUDGE_PROVIDER` / `JEV_API_KEY` / `JEV_BASE_URL` / `DECIDER_TIMEOUT_MS`（3000ms）/ `ROUTE_CONFIDENCE_THRESHOLD_T2`（0.5）。**库内配置优先于 `.env`，保存即生效** |
| 连通性自检 | 页面「测试」按钮直接复用真实的 `health_check()` 探活，**不是 mock 自嗨** |
| 密钥存放 | AES-256-GCM 加密落库，接口不回显明文 |

> **⚠️ 两点请务必知情**
>
> 1. **Jev 官方 API 目前未对中国大陆开放**（2026-09-20 报道），且 `api.typesafe.ai` 是境外服务 ——
>    从境内直连意味着**用户输入出境**的合规问题。本项目默认 `JUDGE_PROVIDER=mock`；
>    境内生产环境请保持 mock，或按 `BaseDecider` 接口换自建的本地判定模型。
> 2. **准确率请用自己的评测集实测**：厂商自报约 68%（自设基准、无独立验证），
>    低于本项目 85% 的验收线。控制台评测看板可直接跑出准确率与混淆矩阵 —— **不要假定，去测**。

---

## 核心特性

| 能力 | 说明 |
|---|---|
| **决策内核 · Jev** | 判定由 **Jev（TypeSafe AI System One）** 完成：非自回归、不生成文本、输出**校准概率**，官方 70～500ms → 详见 [决策内核：Jev](#决策内核jev) |
| **三层路由** | `L1 规则短路 → L2 判定器（[Jev](#决策内核jev)）→ L3 兜底`，判定在首个 token 下发**之前**完成 |
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
| Web 服务器 | Nginx（Docker Compose 形态内置；裸机形态由安装脚本**自动安装并配置**） |
| 部署 | systemd（脚本安装）· Docker Compose（云端直拉 / 本地源码构建）· Apple container（macOS）· 源码 |

---

## 🚨 部署前必读

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
| **方式一 · 脚本安装**（推荐） | Linux 服务器生产部署 | Linux + Python 3.11+ | 一条 `curl` 装完 |
| **方式二 · Docker Compose**（推荐） | 任意平台生产部署、交付给客户、省去环境折腾 | Docker + Compose v2，能访问容器库 | **一条 `docker run` 云端直拉镜像装完（默认不需要源码 / 不需要本地构建）** |
| └ 形态 A · 本地源码构建（可选） | 你持有源码、要改代码后再构建 | 同上，且能访问 GitHub | `bash deploy/docker-deploy.sh --source` |
| **方式三 · Apple container** | Apple Silicon Mac 本地开发 / 试用 | macOS 26+ + `container` 1.1.0+ | 三个子命令 |
| **方式四 · 源码编译** | 二次开发、离线交付、定制 | Python 3.11+ / Node.js 20+ | 见下文 |

> 完整步骤与验收记录另见 [`docs/阶段五-部署与交付/05-安装打包说明.md`](docs/阶段五-部署与交付/05-安装打包说明.md)。

---

### 方式一：脚本安装（推荐）

面向 **Linux 裸机**（systemd）。脚本自动完成：拉取源码 → 建运行用户 → 建虚拟环境 →
装依赖 → 生成 `.env`（随机密钥）→ 初始化数据 → **自动安装 Node.js 并构建控制台前端** →
注册并启动 systemd 服务 → **自动安装并配置 Nginx**（写站点配置、放行 SELinux 与防火墙）→
**打印控制台地址**。

也就是说：**装完就能用，不需要你再手工敲任何命令** —— 结束时直接给出
`控制台地址  http://<服务器IP>/`，浏览器打开即是后台管理界面。

#### 前置条件

- Linux（systemd 发行版；无 systemd 会提示改用 `--no-service`）
- Python **3.11+**（脚本会检测；不满足时给出各发行版的安装命令）
- Node.js —— **无需预装**：脚本先试发行版仓库，版本不够就下载官方预编译包
  （先官方源、不通再走国内镜像），装进 `/usr/local/lib/nodejs` 并软链到 `/usr/local/bin`，
  **不动系统包管理已有的文件**。要自己管 Node 就用 `--no-node-install`
- Nginx —— **无需预装**：脚本会用系统包管理器自动装好并配置
  （`apt` / `dnf` / `yum` / `zypper` / `apk`）。若你想用自己的 web 服务器，加 `--no-nginx` 跳过

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
sudo bash deploy/install.sh --nginx-port 8080      # 控制台对外端口（默认 8081）
sudo bash deploy/install.sh --no-nginx             # 不自动装/配 Nginx（改用你已有的 web 服务器）
sudo bash deploy/install.sh --no-node-install      # 不自动装 Node.js（用机器上已有的）
sudo bash deploy/install.sh --node-version v22.14.0  # 指定要装的 Node.js 版本
sudo bash deploy/install.sh --npm-registry https://registry.npmmirror.com  # 固定 npm 源
sudo bash deploy/install.sh --with-models          # 额外灌入目录里的参考模型与参考单价
sudo bash deploy/install.sh --skip-frontend        # 不构建前端（自备 dist 时）
sudo bash deploy/install.sh --frontend-only        # 只补前端构建（顺带把 Node.js / Nginx 补齐）
sudo bash deploy/install.sh --no-service           # 只铺代码与虚拟环境，不注册 systemd
sudo bash deploy/install.sh --help
```

> 数据库默认策略：探测本机 `5432`。**通**则按 PostgreSQL 配置；**不通**则退到 SQLite
> （`<安装目录>/llmbridge.db`），保证「装完就能打开界面」。
> 生产建议显式用 `--postgres` 指定，或装好后改 `.env` 的 `DATABASE_URL` 再重启。

#### 安装后：打开控制台

后端只提供 `/v1` 与 `/admin` 两套**接口**，不托管前端静态文件；控制台是需要 web 服务器
托管的独立 SPA。**这些步骤脚本已经替你做完**，结束时直接打印地址：

```text
安装完成

  控制台地址  http://<服务器IP>/   ← 浏览器打开即后台管理界面
  默认账号    admin / admin123（首次登录后请立即修改密码）
```

配置 Nginx 时脚本顺带处理了三件最容易卡住的事，无需你手工做：

- **没装 Nginx** → 自动用系统包管理器安装；
- **发行版自带默认站点占着 80 的 `default_server`** → 自动移走让位，
  否则访问到的是 Nginx 欢迎页、反代完全没走；
- **SELinux / 防火墙拦截** → 自动 `setsebool -P httpd_can_network_connect 1` 并放行端口
  （RHEL / CentOS 上不做这一步就是一律 502）。

> 若服务器在**云厂商安全组**后面，仍需在云控制台放行该端口 —— 这一步在机器内做不到。
>
> 用 Caddy 等其它 web 服务器（或加 `--no-nginx` 跳过自动配置）时，只需满足两点：
> 静态托管 `<安装目录>/admin-web/dist` 并对未命中路径回落 `index.html`；
> 把 `/v1/`、`/admin/`、`/health` 反代到 `127.0.0.1:<port>`。
> 站点配置模板见 `deploy/nginx-standalone.conf`（`__API_PORT__` / `__LISTEN_PORT__` / `__DIST_DIR__`）。

#### 升级

重复执行同一条安装命令即可 —— **代码更新，`.env`、数据库、已录入的密钥一律不动**：

```bash
curl -sSL https://raw.githubusercontent.com/dragonlin-ai/llmbridge/main/deploy/install.sh | sudo bash
```

若上次卡在「前端没构建 / Nginx 没配好」，这条命令会把两件事一次补齐（不动其它任何东西）：

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

默认就是**云端直拉镜像**：不需要源码、不需要本地构建、不需要 Node.js ——
目标机只要有 **Docker + Compose v2**、并能访问容器库（默认阿里云 ACR，可换任意第三方镜像库），
一条命令即可拉起 **api + PostgreSQL + Redis + Nginx** 四个容器。
（如果你本地**已有源码**、想改了代码再构建，加 `--source` 走「形态 A · 本地源码构建」，见文末。）

#### 前置条件

- Docker Engine 20.10+（或 Docker Desktop），且守护进程已运行
- Docker Compose **v2**（`docker compose` 子命令形式）
- 能访问容器库（默认 `registry.cn-hangzhou.aliyuncs.com/winyeahs`；可用 `--registry` 换成任意第三方镜像库）

#### 快速开始（云端直拉，推荐）

```bash
docker run --rm --entrypoint cat \
  registry.cn-hangzhou.aliyuncs.com/winyeahs/llmbridge-api:1.0.0 \
  /opt/llmbridge/deploy/docker-deploy.sh | bash -s --
```

就这一句。它会自动完成：落编排文件 → 生成 `.env`（随机 `JWT_SECRET` /
`ENCRYPTION_MASTER_KEY` / `POSTGRES_PASSWORD`）→ `compose pull` → `compose up -d` →
轮询 `/health` 直到就绪 → 打印控制台地址与默认账号。

等价于显式加 `--image` —— `--image` 现在就是默认行为，可省略。
`--entrypoint cat` 不能省：api 镜像默认入口会先做数据库初始化再起服务；脚本取出来交给
**目标机本地的 bash** 执行，镜子里不跑任何部署动作。

> **这条命令一个 GitHub 请求都没有**：脚本与镜像都从容器库取，所以它也是国内目标机的首选路径。

常用变体（先把那条管道记成一个变量，后续子命令都能复用）：

```bash
LB='docker run --rm --entrypoint cat registry.cn-hangzhou.aliyuncs.com/winyeahs/llmbridge-api:1.0.0 /opt/llmbridge/deploy/docker-deploy.sh'

$LB | bash -s -- --port 8080            # 换控制台端口（默认 8081）
$LB | bash -s -- --dir /srv/llmbridge   # 换部署目录
$LB | bash -s -- --tag 1.0.0-<git短sha> # 锁不可变版本（建议生产用）
$LB | bash -s -- status                 # 状态 + 健康检查（api 镜像已在本机，不再联网）
$LB | bash -s -- logs api               # 跟随某个服务日志
$LB | bash -s -- down                   # 停止（保留数据卷）
$LB > docker-deploy.sh                  # 只落盘，先审阅再跑
```

> 子命令请在**同一个目录**下执行（默认部署目录是 `./llmbridge`，与 `docker compose` 同理）。
> 只想先看看脚本：`$LB > docker-deploy.sh`，然后 `bash docker-deploy.sh --help`。

**换镜像库（阿里云以外的第三方镜像库）**：用 `--registry <host>/<命名空间>` 指定，脚本会按该地址拼
`llmbridge-api` / `llmbridge-web` 两个镜像并拉取：

```bash
docker run --rm --entrypoint cat \
  <第三方镜像库host>/<命名空间>/llmbridge-api:1.0.0 \
  /opt/llmbridge/deploy/docker-deploy.sh | bash -s -- --registry <第三方镜像库host>/<命名空间>
```

私有容器库：任一写法都可以传 `REGISTRY_USER` / `REGISTRY_PASSWORD` 环境变量，
脚本会在 `pull` 前自动 `docker login`（走 `--password-stdin`，凭据不落盘）：

```bash
REGISTRY_USER=<账号> REGISTRY_PASSWORD=<密码> bash docker-deploy.sh --registry <host>/<命名空间>
```

**更轻的写法**（可选）：另有一个 8 MB 的纯安装器镜像 `llmbridge-deploy`，只打印脚本。
但它要求**该仓库在容器库里是公开的** —— 阿里云 ACR 新建仓库默认私有，匿名令牌不带
pull 权限、直接 401。在控制台「容器镜像服务 → 命名空间 → 仓库 → 修改」里设为公开后：

```bash
docker run --rm registry.cn-hangzhou.aliyuncs.com/winyeahs/llmbridge-deploy:1.0.0 \
  | bash -s --
```

（不想动这个设置就忽略上面这段，用 api 镜像那条即可 —— 两者拿到的是**同一份脚本**。）

##### 发布镜像（发布侧，一次即可）

```bash
# 登录容器库（密码由 docker 自己读取，不经过任何脚本、不写入任何文件）
docker login --username=<你的账号> registry.cn-hangzhou.aliyuncs.com

# 构建并推送 api + web + deploy（默认 linux/amd64,linux/arm64 双架构）
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

#### 镜像里有什么

容器库里三个镜像即构成完整交付，目标机不需要任何源码与本机构建：

| 镜像 | 内容 |
|---|---|
| `llmbridge-api` | 后端（FastAPI + 路由引擎 + 迁移脚本）+ **安装脚本**（`/opt/llmbridge/deploy/`） |
| `llmbridge-web` | nginx + 已内置的前端 `dist` 与 `nginx.conf` |
| `llmbridge-deploy` | **安装器**：不含业务代码，只有那一个安装脚本（约 8 MB，可选） |

> **为什么安装脚本要放进镜像**：脚本本身也得先送到目标机，而 GitHub
> （`raw.githubusercontent.com`）在国内不可达 —— `curl ... | bash` 这条路在
> 国内目标机上是**必然失败**的。容器库反而是目标机唯一一定能访问的地址
> （否则业务镜像也拉不下来），所以脚本随 api 镜像交付；而安装流程随后要拉的
> 就是这套镜像，**取脚本这一步不会多下载一个字节**。

#### 部署目录与手工等价操作

部署目录里最终只有两样东西：编排文件与 `.env`：

```text
llmbridge/
├── .env
└── deploy/docker-compose.image.yml
```

手工等价操作（在部署目录根下执行）：

```bash
docker compose --env-file ./.env -f deploy/docker-compose.image.yml pull
docker compose --env-file ./.env -f deploy/docker-compose.image.yml up -d
```

> `--env-file ./.env` 同样不能省：`.env` 在部署目录根下，而编排文件在 `deploy/` 里，
> 默认只会去找 `deploy/.env`。（脚本自己也是这么调的，所以一条命令那条路不受影响。）

#### 访问

浏览器打开 `http://<服务器IP>:<HTTP_PORT>/`（`HTTP_PORT` 默认 8081），
默认账号 `admin / admin123`。对外 API 也在同一入口下：`http://<IP>:<HTTP_PORT>/v1/chat/completions`。

#### 升级与回滚

升级：把 `.env` 里的 `LLMBRIDGE_TAG` 改到新版本（建议写成不可变标签 `1.0.0-<git短sha>`），再拉取 + 起栈：

```bash
sed -i 's/^LLMBRIDGE_TAG=.*/LLMBRIDGE_TAG=1.0.1/' .env
docker compose --env-file ./.env -f deploy/docker-compose.image.yml pull
docker compose --env-file ./.env -f deploy/docker-compose.image.yml up -d
```

回滚：把 `LLMBRIDGE_TAG` 改回上一版的不可变标签，重跑上面两行。数据卷不动，无需动数据库。

#### 数据与迁移

PostgreSQL 与 Redis 数据存放在 Docker **命名卷**（`llmbridge_pgdata` / `llmbridge_redisdata`），
容器重建不丢数据。整机迁移：

```bash
# 源服务器
docker compose --env-file ./.env -f deploy/docker-compose.image.yml stop
docker run --rm -v llmbridge_pgdata:/data -v "$PWD":/backup alpine \
  tar czf /backup/pgdata.tar.gz -C /data .

# 新服务器：还原到同名卷后再 up
docker volume create llmbridge_pgdata
docker run --rm -v llmbridge_pgdata:/data -v "$PWD":/backup alpine \
  tar xzf /backup/pgdata.tar.gz -C /data
```

SQLite 形态（方式一默认、方式三默认）直接拷 `<数据目录>/llmbridge.db` 即可。

#### 常见问题

- **`pull` 报 manifest 不存在**：确认该 tag 已发布（发布脚本结束时会打印 digest，
  也可用 `docker manifest inspect <镜像>:<tag>` 核对），并确认目标机架构在镜像支持列表里。
- **控制台 404 / 空白**：`dist` 在 `llmbridge-web` 镜像里，没有「忘了构建前端」这一说；
  若仍空白，先看 `web` 容器是否真的起来了。
- **`exec format error`**：镜像架构与本机不符（如 arm64 镜像跑在 x86）。
  重新发布时带上目标平台，或让 `publish-image.sh` 同时产出 amd64 与 arm64。

#### 形态 A：本地源码构建（可选）

如果你本地**已有源码**、想改了代码再构建（而不是从容器库拉取现成镜像），
加 `--source` 走这一形态。**镜像在目标机构建**，前端 `dist` 通过 bind mount 进 nginx，
所以目标机要么持有源码目录、要么能访问 GitHub（脚本会下载源码）。

前置条件：与云端直拉相同（Docker + Compose v2）；若本机没有源码，还需能访问 `github.com`。

快速开始（仓库内、用当前源码）：

```bash
bash deploy/docker-deploy.sh --source
```

或从任意机器下载源码再本地构建：

```bash
curl -sSL https://raw.githubusercontent.com/dragonlin-ai/llmbridge/main/deploy/docker-deploy.sh | bash -s -- --source
```

脚本会：下载源码到 `./llmbridge` → 生成 `.env`（随机 `JWT_SECRET` /
`ENCRYPTION_MASTER_KEY` / `POSTGRES_PASSWORD`）→ 用 `node:22-alpine` 容器构建前端 →
`docker compose up -d --build` → 轮询 `/health` 直到就绪 → 打印访问地址。

> ⚠️ 上面这条要能访问 `github.com`（下载脚本与源码）。**国内网络、目标机不想碰 GitHub 时，
> 直接走上面的「云端直拉」** —— 那条路一个 GitHub 请求都没有。

常用选项与子命令（形态 A）：

```bash
bash deploy/docker-deploy.sh --source --port 8080        # 控制台对外端口（默认 8081）
bash deploy/docker-deploy.sh --source --dir /srv/llmbridge
bash deploy/docker-deploy.sh --source --skip-frontend    # 已有 admin-web/dist 时跳过构建
bash deploy/docker-deploy.sh --source status             # 容器状态 + 健康检查
bash deploy/docker-deploy.sh --source logs api           # 跟随某个服务日志
bash deploy/docker-deploy.sh --source upgrade            # 拉代码 + 重建镜像 + 重启（数据保留）
bash deploy/docker-deploy.sh --source down               # 停止（保留数据卷）
bash deploy/docker-deploy.sh --source purge              # 停止并**删除数据卷**（不可恢复）
```

手动部署（形态 A）：

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
#   HTTP_PORT：控制台对外端口（默认 8081）

# 3) 构建前端（nginx 挂载 admin-web/dist，不构建则控制台空白）
cd admin-web && npm ci && npm run build && cd ..

# 4) 起全栈
docker compose --env-file ./.env -f deploy/docker-compose.yml up -d --build
```

> ⚠️ **`--env-file ./.env` 不能省**。一旦用 `-f` 把编排文件指到 `deploy/` 子目录，
> compose 就只去**编排文件所在目录**找 `.env`（即 `deploy/.env`）来做**变量插值**，
> 仓库根的 `.env` 对它不可见 —— 直接报
> `required variable POSTGRES_PASSWORD is missing a value`。
> 注意 `docker-compose.yml` 里的 `env_file: ../.env` 只管**容器内**的环境变量，
> 管不到 compose 自己的插值。**下文所有 `docker compose -f deploy/...` 命令同理。**

生成密钥：

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"   # JWT_SECRET
openssl rand -base64 32                                        # ENCRYPTION_MASTER_KEY
openssl rand -base64 24 | tr -d '/+='                          # POSTGRES_PASSWORD
```

> ⚠️ `.env` 里的 `DATABASE_URL` 写的 `127.0.0.1` 是给「本机直连」用的；
> compose 会用服务名 `db` 覆盖它，无需手动改。

升级（形态 A）：

```bash
git pull
cd admin-web && npm ci && npm run build && cd ..
docker compose --env-file ./.env -f deploy/docker-compose.yml up -d --build
```

> `--build` 是必需的：前端 `dist/` 是 bind mount 进 nginx 的，
> **改了前端必须重新 build，重启容器不会生效**。

常用命令（形态 A）：

```bash
docker compose --env-file ./.env -f deploy/docker-compose.yml ps               # 状态
docker compose --env-file ./.env -f deploy/docker-compose.yml logs -f api      # 后端日志
docker compose --env-file ./.env -f deploy/docker-compose.yml restart api      # 重启后端
docker compose --env-file ./.env -f deploy/docker-compose.yml down             # 停止（保留卷）
docker compose --env-file ./.env -f deploy/docker-compose.yml down -v          # 停止并删除数据（危险）
```

#### 形态 A ↔ 云端直拉 切换

两种编排共用 compose 项目名 `llmbridge`，因此**共用同一套数据卷**
（`llmbridge_pgdata` / `llmbridge_redisdata`）—— 换形态不丢数据。
但服务名不同（A 是 `nginx`，云端直拉是 `web`），切换前必须先停：

```bash
docker compose --env-file ./.env -f deploy/docker-compose.yml down       # 从 A 切到云端直拉之前
docker compose --env-file ./.env -f deploy/docker-compose.image.yml up -d
```

重建时若看到 `orphan containers` 警告，通常就是漏了这一步。

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
| Node.js | 20+（仅控制台前端需要；脚本安装形态会自动装） |
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
| `HTTP_PORT` | `8081` | 仅 Docker Compose 形态：控制台对外端口 |
| `AUTO_BOOTSTRAP` | `true` | 启动时自动建表 / 建管理员 / 预置接入商，幂等。生产由 DBA 管库时可设 `false` |
| `JWT_SECRET` | `dev-only-change-me` | **生产必改**。控制台会话签名密钥 |
| `ENCRYPTION_MASTER_KEY` | `dev-only-change-me…` | **生产必改**。厂商 Key 的 AES-256-GCM 主密钥，**丢失不可恢复** |
| `ALLOW_LOCAL_BASE_URL` | `false` | 是否允许厂商 `base_url` 用 `http://` 与私网地址。**生产必须 false** |
| `REDIS_URL` | 空 | 留空则不启用缓存 / 限流（自动降级） |
| `JUDGE_PROVIDER` | `mock` | 判定器选择：`mock` = 内置无依赖判定（离线可用）；`jev` = **Jev 决策模型**（TypeSafe AI 官方 API）。详见 [决策内核：Jev](#决策内核jev) |
| `JEV_API_KEY` | 空 | Jev 的 API Key。`judge_provider=jev` 时必填；为空会静默退回 mock（看板会提示不一致） |
| `JEV_BASE_URL` | `https://api.typesafe.ai/v1/systemone` | Jev 端点。**⚠️ 境外服务，境内直连涉及用户输入出境** |
| `DECIDER_TIMEOUT_MS` | `3000` | 判定器独立超时。实测单次 0.4～1.2s，3000ms 够用 |
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
python scripts/verify_registry.py --tag 1.0.0        # 核验容器库上真有这个标签（不采信 push 退出码）
python scripts/verify_deploy.py --port 8099          # 装完做**功能性**核验（控制台/登录/读库/引导）
python scripts/check_compose_sync.py                 # 校验内嵌编排副本与真源一致（发布前自查）
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
├── scripts/                  幂等运维脚本（预置目录 / 历史库迁移 / 发行打包 / 交付核验）
├── deploy/                   部署产物
│   ├── install.sh            ★ 方式一：Linux 一键安装（systemd）
│   ├── docker-deploy.sh      ★ 方式二：Docker Compose 一键部署（默认云端直拉；`--source` 走本地源码构建）
│   ├── publish-image.sh      ★ 容器库形态的发布侧：构建并推送 api + web + deploy 三个镜像
│   ├── apple-container.sh    ★ 方式三：macOS Apple container
│   ├── Dockerfile            后端镜像
│   ├── Dockerfile.web        前端镜像（nginx + 内置 dist 与 nginx.conf）
│   ├── Dockerfile.deploy     安装器镜像（只打印 docker-deploy.sh，约 8 MB）
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

- **Jev 官方 API 目前未对中国大陆开放**，且 `api.typesafe.ai` 为境外服务 —— 境内直连存在**用户输入出境**的
  合规问题。本项目默认 `JUDGE_PROVIDER=mock`；境内生产环境请保持 mock，或按 `BaseDecider` 接口换自建的
  本地判定模型（详见 [决策内核：Jev](#决策内核jev)）。另：厂商自报判定准确率约 68%，
  **低于本项目 85% 的验收线**，必须用自己的评测集实测 —— 评测看板可直接跑出准确率与混淆矩阵。
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

## 🤝 交流与社区

我们欢迎所有开发者和用户加入社区：提问、分享经验、贡献代码，或者只是聊聊你把它用在了什么场景。

<div align="center">
<img src=".github/images/微信交流.jpg" width="300" alt="微信交流">
<p align="center">扫码加微信交流</p>
</div>

**更多链接：**

- **报告问题与建议（Issues）：** 到 [GitHub Issues](https://github.com/dragonlin-ai/llmbridge/issues) 提交你发现的 Bug 或功能建议。
- **参与讨论（Discussions）：** 到 [GitHub Discussions](https://github.com/dragonlin-ai/llmbridge/discussions) 做更深入的技术探讨和想法交流。
- **联系我们（Contact）：** 如有商务合作或其他事宜，请发邮件至 `93634776@qq.com`。

---

## 许可证

[Apache License 2.0](LICENSE)
