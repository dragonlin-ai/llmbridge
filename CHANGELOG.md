# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
