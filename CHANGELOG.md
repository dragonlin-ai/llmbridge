# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 首次运行引导：装完打开界面即可用

- 新增 `app/services/bootstrap.py`，服务启动时自动完成四步（全部幂等，失败只记 ERROR
  不阻塞启动）：建表 → 默认管理员 → 内置评测样本 → **预置厂商接入目录**。
  此前要手工跑 `llmbridge-seed` + `llmbridge-catalog` 两步，漏掉第二步打开控制台就是
  「一家厂商都没有」。实测：只跑旧的 seed 时库里只有 2 个开发用厂商，13 家主流接入商一个都不出现。
- **`llmbridge-catalog` 不再依赖源码 `scripts/` 目录**：预置逻辑搬进
  `app/data/catalog_seed.py`，wheel 安装后同样可用（此前纯 wheel 安装会以 exit 2 退出）。
  `scripts/seed_provider_catalog.py` 保留为薄壳 CLI，附加 `--with-models`。
- **模型池默认留空**：预置只铺「接入通道」，模型需在「模型池」页按自己账号实际可用的
  Model ID 手工添加。目录参考模型（含官方参考单价）可用 `llmbridge-catalog --with-models`
  显式灌入。理由：模型 ID 与计费口径因账号而异，预置一份「参考目录」会让人误以为已配置。
- 新增配置项 `AUTO_BOOTSTRAP`（默认 `true`）。生产由 DBA 管库时可置 `false`，
  改由运维显式跑 `llmbridge-seed`（与自动引导同源，行为一致）。
- `llmbridge-seed` 语义变更：不再写入**与目录冲突的开发用假数据**
  （2 家厂商 / 4 个示例模型 / 2 条示例路由规则）。示例模型名（`deepseek-chat` / `gpt-4o`）
  已不在当前目录中，且与目录里的 DeepSeek 通道重复；`RouteRule.target_model_id` 是
  非空外键，模型池留空时示例规则也写不进去。评测样本保留（模型真值留空，看板已支持）。
- `deploy/entrypoint.sh` 简化为单次 `llmbridge-seed`（不再单独调 catalog）。
- 实测：全新空库零初始化直接起服务 → 24 条通道 / 13 家厂商 / 0 模型 / 1 管理员 / 4 评测样本；
  登录 200、概览页不 500、评测看板正常返回。

### 一键部署脚本：四种部署方式

- 新增 **`deploy/install.sh`（方式一：Linux 脚本安装，推荐）**：一条 `curl` 完成拉源码 →
  建运行用户 → venv + 依赖 → 生成 `.env`（随机密钥）→ 首次引导 → 构建控制台前端 →
  生成 Nginx 站点配置 → 注册 systemd 服务。幂等（重跑 = 升级），**绝不覆盖既有 `.env`**
  —— `ENCRYPTION_MASTER_KEY` 一变，已存厂商密钥就全部解不开。
  数据库默认策略：探测本机 `5432`，通即 PostgreSQL、不通即 SQLite，保证装完就能打开界面。
- 新增 **`deploy/docker-deploy.sh`（方式二：Docker Compose，推荐）**：用 `node:22-alpine`
  容器构建前端，**宿主机无需安装 Node.js**；子命令 `status / logs / down / purge / upgrade`。
  `logs`、`down` 等运维子命令刻意不允许联网下载（部署目录被删时不会莫名开始拉源码）。
- 新增 **`deploy/apple-container.sh`（方式三：macOS Apple container）**：面向 Apple Silicon +
  macOS 26 的本地开发形态，默认单容器 + SQLite。Apple container 没有 compose 那样的依赖编排
  与健康检查等待，硬管 PG + Redis + 应用三层就得自写启动轮询，脆弱难排障 —— 完整形态仍走方式二。
- 新增 **`deploy/nginx-standalone.conf`**：裸机形态的站点配置模板（三个占位符由 `install.sh`
  替换），与 compose 用的 `nginx.conf` 同源，同样包含 SSE 必需的四件套。
- **补上一个此前会「装完打不开界面」的缺口**：后端不托管前端静态文件，控制台是需要 web 服务器
  托管的独立 SPA。此前 `05-安装打包说明.md` §6.2 只用一句「前端交给 nginx」带过，既没给可用配置，
  也没点明「不构建 `dist` 就是白屏」。现在脚本会自动构建并生成站点配置；构建不了（无 Node.js）时
  明确告警并给出 `--frontend-only` 补装命令，**不静默跳过**。

### 容器库镜像交付：目标机不再需要源码

- 新增 **`deploy/Dockerfile.web`（前端镜像）**：多阶段构建，`node:22-alpine` 里跑
  `npm ci` + `vue-tsc -b && vite build`，产物 `dist` 与 `deploy/nginx.conf` 一起进
  `nginx:1.27-alpine`。**类型检查刻意不跳过** —— 镜像构建同样要过门禁。
- 新增 **`deploy/docker-compose.image.yml`（纯拉取编排）**：api / db / redis / web，
  **没有任何 `build:` 段**，零 volumes、零源码依赖。镜像名走 `LLMBRIDGE_REGISTRY` /
  `LLMBRIDGE_TAG` 插值，默认 `registry.cn-hangzhou.aliyuncs.com/winyeahs`。
- 新增 **`deploy/publish-image.sh`（发布侧）**：用 `buildx` 构建并推送 api + web 两个镜像。
  每个镜像打两个标签 —— 浮动 `1.0.0` 与**不可变** `1.0.0-<git短sha>`，后者用于生产锁版本
  与回滚（浮动标签会被后续推送静默覆盖）。固定带 `--provenance=false --sbom=false`，
  避免 manifest list 出现 `unknown/unknown` 条目导致部分容器库拒绝拉取。
  **凭据只走 `docker login` 或 `REGISTRY_USER`/`REGISTRY_PASSWORD` 环境变量，脚本内绝不落盘**；
  `--dry-run` 不依赖 Docker 守护进程，没开 Docker 也能先看清会推什么。
- **`deploy/docker-deploy.sh` 新增 `--image` 形态**：不下载源码、不构建前端，只取编排文件 +
  生成 `.env` + `compose pull` + `up -d`。部署目录最终只有两样东西：编排文件与 `.env`。
  `upgrade` 在该形态下是「拉新标签 + 重建容器」，不再 `git pull`。
- `.env.example` 新增 `LLMBRIDGE_REGISTRY` / `LLMBRIDGE_TAG`。
- `.dockerignore` 新增 `**/tsconfig.tsbuildinfo` 排除项：`vue-tsc -b` 会据此判定「已是最新」
  而跳过类型检查，宿主机残留一份就会让前端镜像的类型门禁**静默失效**（dist 照样产出，
  本地类型报错而镜像构建成功）。
- 两种形态共用 compose 项目名与数据卷，换形态不丢数据；但服务名不同（`nginx` ↔ `web`），
  切换前必须先 `down`，否则留下孤儿容器。
- **验证边界（如实标注）**：`bash -n` 四脚本 PASS；`publish-image.sh --dry-run` 实跑通过
  （仓库根定位、git 短 sha、双标签、四个路径参数均正确）；两个编排经
  `docker compose config --services/--images` 语义核验通过（镜像形态正确解析出带仓库前缀的
  `llmbridge-api` 与 `llmbridge-web`）；服务名 `api` 与 `nginx.conf` 的 `upstream` 一致性已交叉核对。
  **但镜像本身从未真正构建过** —— 本机 Docker 守护进程未启动（`dockerDesktopLinuxEngine`
  管道不存在），构建、推送、端到端起栈均未实测。首次发布的验证命令见
  `docs/阶段五-部署与交付/05-安装打包说明.md` §11。

### 中英双语 README

- `README.md` 重写为完整交付文档：语言切换、部署前必读、**四种部署方式**
  （脚本安装 / Docker Compose / Apple container / 源码编译，每种含前置条件 → 步骤 → 升级 → 常用命令）、
  技术栈、配置、命令行、接口一览、工具调用边界、项目结构、已知限制。
- 新增 `README_EN.md`，与中文版结构一一对应；`scripts/build_release.py` 的白名单已同步
  （否则打出的发行包里会缺英文 README）。

### 验证边界（如实标注）

- 三个 shell 脚本：`bash -n` 通过 + shellcheck（v0.10.0，`-S warning`）**零告警**；
  过程中修掉 3 处真实问题（`need_root` 用函数内 `$*` 回显会丢用户选项、两个未使用变量）。
- 另做：模板占位符 ↔ sed 替换交叉核验、四个部署文件端口一致性、依赖文件存在性、
  中英 README 引用完整性核验（44 项全部命中）。
- **未做**：真实 Linux / macOS 机器上的端到端执行（开发机为 Windows，本机 Docker 守护进程未启动）。

## [1.0.0] - 2026-09

首个公开版本。核心是「**OpenAI 兼容网关 + 智能路由**」：请求先进判定器判断任务类型，
再转发到最合适的下游模型，全链路可观测、可降级、可对账。

### 路由内核

- 三层决策链 `L1 规则短路 → L2 判定器 → L3 兜底`，判定在首个 token 下发**之前**完成，
  流式请求不会中途换模型。
- L1 支持关键词 / 文本长度 / 正则三类条件，规则按优先级短路。
- L2 判定器可插拔：内置 `mock`（零依赖、离线可用）与 `Jev`（TypeSafe 决策模型）两种实现，
  判定器不可达时自动降级并在看板显性提示。
- 候选池唯一来源 `load_routable_models()`，两个入口共用；过滤项与总数满足
  `routable + disabled_models + blocked_by_provider + excluded_channel == total`。

### 双入口

- `/v1`（对外，OpenAI 兼容）：**绝不透出 5xx 裸栈**，上游失败内部按优先级降级重试，
  全失败也返回结构化错误；兜底率 100%。
- `/admin`（对内，控制台）：保留完整错误详情，便于排障。
- 两个入口永不合流，策略相反。

### 厂商接入

- 内置目录 **13 家厂商 / 24 条接入通道 / 55 个模型**，覆盖五种接入形态
  `api / package / batch / coding_plan / token_plan`，**填一个 Key 即接入**。
- 「一家厂商多条通道」：`vendor` 聚合、`name` 为通道名，一条通道对应库中一行。
- 厂商 Key 使用 **AES-256-GCM** 加密落库，对外接口无任何回显。
- 状态三分为 `has_key / enabled / routable`，避免把「没填 Key」误读成「不可用」。
- 订阅类套餐通道（`coding_plan` / `token_plan`）同样参与路由；官方条款限制
  （如「仅限编程工具交互式使用、禁止用作应用后端」）原文随通道落库并在控制台警示。
  订阅套餐单价一律标注为**参照值**，绝不填 0。

### 可观测与对账

- 每个响应带 `x-router-*` 元信息头（trace-id / layer / model / confidence 恒返回，
  task-type 仅 L2 命中时返回）。
- 请求日志记录命中层级、实际服务模型、降级原因、token 与成本；流式请求从 SSE 末尾解析用量。
- 用量与成本支持按模型 / 按层 / 按日聚合，与概览页**同源口径**：
  统一排除试跑台诊断流量（`trace_id NOT LIKE 'preview-%'`），
  否则同一份数据会出现两个不同成本数字。
- 评测看板：内置评测集，并发跑判定器，输出准确率、概率分布与混淆矩阵。

### 控制台前端

- Vue 3 + Vite + Element Plus，Teal 主题，支持暗色模式与中英双语。
- **零依赖 i18n**：自研 `t()` / `setLang()` / `capLabel()` / `taskLabel()`，不引入 vue-i18n。
- 图表全部用 CSS 原生实现（进度条 + 渐变），不引入图表库。
- 页面：概览 / 试跑台 / 厂商接入 / 模型管理 / 路由规则 / 请求日志 / 决策样本 /
  评测看板 / 用量与成本 / 密钥指引 / 判定器设置。

### 部署与工程

- 命令行入口 `llmbridge-serve` / `llmbridge-seed` / `llmbridge-catalog`。
  `llmbridge-serve` 内置 psycopg3 所需的事件循环工厂 —— 规避了
  「Windows 上服务能起来、`/health` 也是 200，但一访问数据库就 500」这一高频故障。
- 部署产物齐备：Dockerfile、docker-compose（api / db / redis / nginx）、
  经 SSE 调优的 nginx.conf、systemd 单元、Windows 启动脚本。
- 一键打包脚本 `scripts/build_release.py`，产出带 `BUILD-INFO.txt` 与
  `SHA256SUMS.txt` 的可离线交付发布包。
- 初始化脚本全部幂等且支持 `--dry-run`；目录预置采用三级匹配认领历史行，
  不会把使用者已录入的密钥或校正过的价格覆盖掉。

### 已知限制

- 流式请求若客户端未传 `stream_options.include_usage`，部分厂商不回 `usage`，
  该条日志的 token / 成本记为 0 —— 是**缺数据**，不是零消耗。
- 纯 HTTP 抓取无法获取 JS 渲染站点的正文。
- 工具调用默认纯透传（标准 OpenAI 语义），网关不替调用方执行工具；
  `ENABLE_TOOL_EXECUTION=true` 可开启网关代执行，但会改写正文，仅适用于
  调用方完全没有工具循环的场景。
- `alembic/` 目录预留未启用：当前建表走 ORM `create_all`，
  历史库升级走 `scripts/migrate_*.py`。
