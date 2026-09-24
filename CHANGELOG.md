# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### README 顶部加自绘图标，新增「交流与社区」

- **新增矢量图标** `.github/images/llmbridge-logo.svg`（中英 README 顶部各引用一次，`width="120"`）：
  几何化表达主链路 —— **一次请求入站 → 判定菱形（决策发生在调用下游之前）→ 三个落点**，
  三个落点沿用界面既定的层级语义配色 **L1 绿 / L2 紫 / L3 红**。
  要点：图标**自带渐变圆角底**，故 GitHub 亮色与暗色主题下都可见；**纯路径绘制、不含任何 `<text>`**，
  不依赖对方机器字体，32px 或 512px 均不失真。
- **新增「交流与社区」章节**（`README.md` / `README_EN.md`）：微信交流二维码、Issues / Discussions 入口、
  商务联系邮箱（`93634776@qq.com`）。位置在「已知限制」之后、「许可证」之前。
- **修掉一条线上一直失效的目录锚点**：`## ⚠️ 部署前必读` 的真实锚点并不是 `#-部署前必读` ——
  github-slugger **不删变体选择符 U+FE0F**，真实锚点是「U+FE0F + `-部署前必读`」，`#` 后面第一个字符
  **肉眼看不见**，所以按常规写法永远对不上。已把两级标题的 `⚠️` 换成不带 U+FE0F 的 `🚨`
  （`## 🚨 部署前必读` / `## 🚨 Read before deploying`），锚点重新变成可预期的 `#-部署前必读`。
  本地复算脚本同时修正为**按 Unicode 大类筛字符**（保留 L/N/M，删 P/S/C），
  并以线上真实锚点回归 12/12 通过。
- **同步折叠目录**：中英各 **16 个锚点**（新增 `#-交流与社区` / `#-community`）。
  已用 GitHub 官方 GFM 渲染接口核验渲染结果，并**拉线上仓库页逐条对账真实锚点** —— 20/20 命中。
- **发布包修正**：`scripts/build_release.py` 白名单加入 `.github/images`，
  否则发布包内的 README 图标与二维码会全部断链。
- **口径说明**：仍是**文档层变更**，未动任何接口、表结构或判定口径。

### README 把「决策内核 Jev」提到台前（中英双语）

- **新增专章「决策内核：Jev」**（`README.md` / `README_EN.md`，位置在「这是什么 / 不是什么」之后、
  「核心特性」之前 —— 读者视线最先落到的地方）：讲清 Jev 是**非自回归决策模型**
  （不生成文本、输出类型化判定 + 校准概率、官方 70～500ms），并与「拿大模型当裁判」逐项对照
  （输出形态 / 延迟 / 置信度可信度 / 可解释性 / 出错方式），给出 Choice / Score / Noul 三原语，
  以及本项目的**真实请求体**（一次调用并行问 4 个原子问题）。
- **讲清「为什么不直接让 Jev 选 model_id」**：模型池增删不必改判定器、`task_type` 是稳定概念、
  权重可调且**改动可审计**；并附判定链结构图（一次调用 → 类型化判定 → 代码层映射 × 成本 / 延迟 / 健康度 → `model_id`）。
- **两条硬事实写在明面上**（原先只存在于阶段文档）：① Jev 官方 API **未对中国大陆开放**，
  境内直连涉及**用户输入出境**，本项目默认 `JUDGE_PROVIDER=mock`；② 厂商自报准确率约 **68%**，
  **低于本项目 85% 的验收线**，必须用自己的评测集实测。同一条已补进「已知限制」。
- **配置表补齐 3 个漏掉的判定器变量**（`JEV_API_KEY` / `JEV_BASE_URL` / `DECIDER_TIMEOUT_MS`）——
  原先表里只有 `JUDGE_PROVIDER` 与 `ROUTE_CONFIDENCE_THRESHOLD_T2`。
- **可读性**：顶部加 `decider` 徽章与**折叠目录**（中英各 15 个锚点；其中 `#-部署前必读` 一条
  在下方「README 顶部加自绘图标」一节修正 —— 它此前一直是失效链接）；
  核心特性表首行改为「决策内核 · Jev」并给 Jev 加交叉链接。
- **顶部版式居中**：标题 / 简介 / 徽章 / 语言切换四块用 `<div align="center">` 包住居中。
  实现要点：GitHub 的 HTML 块**在空行处结束**，所以 `<div>` 之后必须留一个空行，块内的
  Markdown（`#` 标题、`>` 引用块）才会被照常解析 —— 标题保持 Markdown 标题形态，**锚点不受影响**
  （换成裸 `<h1>` 反而会丢锚点）。已用 **GitHub 官方 GFM 渲染接口** `POST /markdown` 核对真实输出：
  `<div align="center" dir="auto">` / `<h1 dir="auto">` / `<blockquote>` 均正常，四块都在 `</div>` 之内。
- **口径说明**：README 是**对外介绍页**，本轮只改文字与版式，**未动任何接口、表结构或判定口径**。

### 一条命令安装：镜像与脚本都从阿里云容器库取，不再依赖 GitHub

- **安装脚本改为随镜像交付**：`deploy/Dockerfile` 把 `docker-deploy.sh` 与内嵌用的
  `docker-compose.image.yml` 装进 api 镜像的 `/opt/llmbridge/deploy/`，于是目标机
  一条命令即可安装，**全程不访问 GitHub**：

  ```bash
  docker run --rm --entrypoint cat \
    registry.cn-hangzhou.aliyuncs.com/winyeahs/llmbridge-api:1.0.0 \
    /opt/llmbridge/deploy/docker-deploy.sh | bash -s -- --image
  ```

  为什么必须这样做：安装脚本本身也得先送到目标机，而 `raw.githubusercontent.com`
  在国内不可达 —— `curl ... | bash` 在目标机上是**必然失败**的；容器库反而是目标机
  唯一一定能访问的地址（否则业务镜像也拉不下来）。选 api 镜像做载体是因为安装流程
  随后要拉的就是这套镜像，**取脚本不会多下载一个字节**（`--entrypoint cat` 不能省：
  默认入口会先做数据库初始化再起服务）。
- 另新增 `deploy/Dockerfile.deploy` → 第三个镜像 **`llmbridge-deploy`**（基于 alpine，
  约 8 MB，**不含业务代码**，只把脚本打印到 stdout）：想「只要脚本、不拉整套后端」时用它。
  ⚠️ 它要求该仓库在容器库里是**公开**的 —— 实测 ACR 上 `llmbridge-api` / `llmbridge-web`
  的匿名令牌带 `pull` 权限，而新建的 `llmbridge-deploy` 令牌 access 为空（401），
  需在控制台把仓库改为公开，否则先 `docker login`。因此**文档与脚本默认给 api 镜像那条**。
- `deploy/publish-image.sh` 支持第三个镜像（`--only` 增加 `deploy`），结束时直接打印
  安装命令。三个镜像**同标签发布**，避免「新脚本去装旧镜像」。
- **构建侧修复（国内必踩）**：`docker-container` 驱动的 BuildKit **不读宿主机的
  `daemon.json`**，宿主机能 `docker pull` 并不代表构建器能拉基础镜像。实测构建死在
  `failed to authorize: ... auth.docker.io/token ... Bad Gateway`。
  现在脚本会写 `~/.docker/buildx/llmbridge-buildkitd.toml` 给构建器指定 `docker.io`
  加速器，配置变化时自动重建构建器；可用 `LLMBRIDGE_REGISTRY_MIRRORS` 覆盖。
- **端到端实测暴露并修掉 5 个真问题**（都属于「装上了但用不了」，只看 `docker ps` 发现不了）：

  1. **`compose` 的变量插值读不到 `.env`**：compose 只在「项目目录」里找 `.env`，而项目目录
     默认是**编排文件所在目录**（`<SRC_DIR>/deploy`），`.env` 却写在 `<SRC_DIR>`。现象是
     `compose pull` 直接失败：`error while interpolating services.api.environment.DATABASE_URL:
     required variable POSTGRES_PASSWORD is missing a value` —— 容器一个都没起。
     → 显式传 `--env-file "$SRC_DIR/.env"`。注意编排里的 `env_file: ../.env` 是**另一条**路径
     （相对编排文件解析），只影响容器进程环境，救不了插值；缺 `.env` 时退回 `/dev/null`，
     保证 `down` / `status` 仍可用。
  2. **脚本打印的控制台地址一直是错的**：写的是 `http://<host>:<port>/admin`，但 `/admin` 是
     **后端接口前缀**（`/admin/auth/login` …），控制台 SPA 挂在**根路径** `/`。照提示打开只会
     看到 `{"detail":"Not Found"}`。→ 改为 `http://<host>:<port>/`，`apple-container.sh` 同改。
     实测：`/` → 200 且含 `<div id="app">`；`/admin/` → 404（正好证明两者不是一回事）。
  3. **运维子命令漏 `--image` 会报与真实原因无关的错**：管道形态下 `... | bash -s -- status`
     会退回源码形态，报「未找到部署目录」（目录明明在）。→ 加**形态自检**：部署目录里只有
     `docker-compose.image.yml` 时自动按容器库形态处理。
  4. **子命令用错端口**：`--port 8099` 装完，`status` 仍去探默认的 80，报「健康检查失败」，
     看起来像服务挂了。→ 新增 `sync_http_port_from_env()`，从 `.env` 读回 `HTTP_PORT`；
     用户显式传 `--port` 时以命令行为准并同步写回 `.env`。
  5. **docker.io 拉取偶发失败**：实测 `postgres:16-alpine` 报
     `short read: expected 9065 bytes but got 0: unexpected EOF`（国内加速器偶发）。
     → 拉取失败自动重试一次（拉取本身幂等，重试通常一次就过）。
- **文档里的手工命令补上 `--env-file`（两套形态原来都敲不通）**：同一次回归里顺手验了
  文档给出的「手工等价操作」，结论是**源码形态与容器库形态一样中招**。干净临时目录内实测
  （compose v5.5.1）：

  ```
  $ docker compose -f deploy/docker-compose.image.yml config --services
  error while interpolating ... required variable POSTGRES_PASSWORD is missing a value
  $ docker compose --env-file ./.env -f deploy/docker-compose.image.yml config --services
  db redis api web
  $ docker compose -f deploy/docker-compose.yml config --services
  error while interpolating ... required variable POSTGRES_PASSWORD is missing a value
  $ docker compose --env-file ./.env -f deploy/docker-compose.yml config --services
  db redis api nginx
  ```

  即 README / 部署文档 / 运维手册 / 安装打包说明里**所有** `docker compose -f deploy/...`
  命令都是「照抄必失败」，而源码形态这条**一直存在**、此前从未被发现（`docker-compose.yml`
  里的 `env_file: ../.env` 只管容器内环境变量，救不了 compose 自己的插值）。
  → **46 处**命令与编排注释统一补上 `--env-file ./.env`，并在 README（中英）、部署文档、
  运维手册、安装打包说明与两份编排文件头部写明原因。
- **核验镜像内容时的两个假结论来源（都实测踩过，已写进文档）**：
  ① `docker run` 的默认 pull policy 是 `missing` —— 本机若已缓存同名 `:1.0.0`，它会**直接用本地那份**
  而不去容器库取，于是 `cmp` 比的是**旧镜像**（新旧两份脚本的 md5 都是 `301947a0…`，一度被误判成
  「推上去的是旧脚本」）。**核验镜像内容前必须显式 `docker pull`。**
  ② buildkit 的**构建上下文快照在构建开始时就固定**，边构建边改仓库文件，打进镜像的仍是旧内容。
  所以「改完 → 重推 → 再 `cmp` 断言」的顺序不能省，不能凭「刚推过」推断。
- **Windows Git Bash 的路径改写**：`docker run --entrypoint cat <镜像> /opt/llmbridge/...` 里的 `/opt/...`
  会被 MSYS 改写成 `C:/Program Files/Git/opt/...`，报 `No such file or directory`，看着像镜像里没这个文件。
  前面加 `MSYS_NO_PATHCONV=1` 即可（Linux/macOS 无此层）。已记入 troubleshooting。
- **已知性能问题（本次未修）**：`publish-image.sh` 每次构建都会重下依赖（`RUN pip install` 层不命中缓存，
  实测 amd64 247 s、arm64 628 s；一次 `--only api` 约 11 分钟）。构建器本身是复用的
  （`prepare_builder` 只在加速器配置变化时才重建），怀疑是 buildkit 的缓存回收把该层挤掉了。
  后续可加 `--cache-to type=local` 把缓存落盘持久化。
- **新增两个「交付核验」脚本**，把上面这套核验方法固化下来，别人也能复现：
  `scripts/verify_registry.py`（走 Bearer 挑战查 `tags/list`，**不采信 `push` 退出码**；默认只查必须公开的
  api / web —— `llmbridge-deploy` 默认私有，401 属预期；只回显标签列表，从不打印令牌）与
  `scripts/verify_deploy.py`（装后**功能性**核验：控制台 SPA / `/health` / 真实登录 / 厂商目录已铺 /
  模型池留空 / 概览页不 500；内置 `ProxyHandler({})` 绕开本机代理）。
  实测：`verify_deploy.py --port 8099` → 7 项全过 `ALL_OK`（rc=0）；`verify_registry.py --tag 1.0.0` →
  api / web 的 3 个标签全命中。另有 `scripts/check_compose_sync.py`：不碰 Docker 独立比对
  「内嵌编排副本 vs 真源」（脚本自身的运行期比对需要真跑一次部署，CI 里用这个更省事）。
- **编排文件由「下载」改为「内嵌」**：`docker-deploy.sh` 内嵌 `docker-compose.image.yml`，
  目标机除容器库外不访问任何外网。脚本在仓库内运行时会自动比对两份内容，不一致即告警。
- `deploy/Dockerfile` 顺带把部署脚本放进 api 镜像（约几十 KB）作为兜底：
  `docker run --rm --entrypoint cat <api镜像> /opt/llmbridge/deploy/docker-deploy.sh | bash -s -- --image`。
- **脚本健壮性（让「自动跑通」更稳）**：`gen_secret` 增加 `/dev/urandom + base64` 兜底
  （不再依赖 `openssl`，也不再为生成密钥去拉 node 镜像）；探活在没有 `curl` 时改为进 api
  容器用 python 探（不再直接跳过）；被 `sh`/`dash` 执行时给出人话提示；正式输出里的子命令
  提示在管道形态下改写成同一条 `docker run`（原来会打印出没法照做的 `bash bash logs`）；
  探活 120 秒未通过时给出 `status` / `logs` 排查命令（原来只有一句「部署完成」）；
  控制台地址补上「从别的机器访问请换成本机 IP」的提示。
- **`REGISTRY_USER` / `REGISTRY_PASSWORD` 真正落地**：此前文档与编排注释都写了「脚本会自动
  登录」，但 `docker-deploy.sh` 里并没有这段实现。现在 `--image` 形态会在 `compose pull`
  前检测登录态并自动 `docker login --password-stdin`（凭据只经环境变量，不写 `.env`、
  不落盘、不进日志）。

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
