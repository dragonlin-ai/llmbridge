# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 方式二默认改为「云端直拉镜像」：不需要源码、不需要本地构建

- **默认形态翻转**：`docker-deploy.sh` 的 `USE_IMAGE` 由 `false` 改为 `true`，于是**默认就是云端直拉**
  （等同旧的 `--image`）：目标机只要有 Docker + Compose v2、并能访问容器库，一条
  `docker run ... | bash -s --` 就把 api + PostgreSQL + Redis + Nginx 四个容器拉起来 ——
  **不需要下载源码、不需要本地构建、不需要 Node.js**，且**一个 GitHub 请求都没有**（脚本与镜像都从容器库取）。
- **新增 `--source` 开关**：只有「本地已有源码、要改代码后再构建」时才显式加它，回落到本地源码构建
  形态（下载源码 → 构建前端 → `compose up -d --build`）。`--image` 保留但已可省略（它现在就是默认行为），
  老命令照旧可用，已在运行的实例不受影响。
- **可换任意第三方镜像库**：`--registry <host>/<命名空间>`（或 `LLMBRIDGE_REGISTRY` 环境变量）不再绑死
  阿里云 ACR；私有库仍可配 `REGISTRY_USER` / `REGISTRY_PASSWORD`，脚本在 `pull` 前自动
  `docker login`（`--password-stdin`，凭据不落盘、不进日志）。
- **文档口径统一（README 走极简）**：README（中英）「方式二」只留**一条 `docker run` 装完**的简明说明
  （前置条件 → 命令 → 访问 → 常用命令 → 换镜像库一行 → 详见部署文档），**不再展开两种形态的长篇讲解**；
  源码构建由「方式四」承接，细节全在 `01-部署文档.md` §3.6 与 `05-安装打包说明.md` §6.1.1
  （示例命令已去掉 `--image`）。
- **范围**：部署脚本默认值 + 文档层，**未动任何接口、表结构或判定口径**。

### 修掉控制台反复 403 的最后一块：构建产物权限（DAC）被 umask 077 弄成 600/700

- **根因（元凶）**：`write_env` 在「新建 .env」分支里把进程 `umask` 设成 `077` 后**全程未复位**。之后 `build_frontend` 用 vite 构建 `admin-web/dist` 时，文件被建成 `600`、目录被建成 `700`（`drwx------`，属主 `llmbridge`）。nginx 的 worker 以独立用户（RHEL 上是 `nginx`）运行，既进不去 `dist/`（无 `o+x`）也读不到文件（无 `o+r`）→ 控制台 403 Forbidden。上一轮的 SELinux 修复是必要条件但非充分条件，权限这块才是反复 403 的真凶；且重跑 `install.sh` 时 `build_frontend` 发现 `dist/index.html` 已存在会**跳过构建、也跳过修复**，所以怎么重跑都不好。
- **修法**：
  ① `write_env` 写完 `.env` 后立刻 `umask 022` 复位，杜绝再泄漏；
  ② 新增 `_fix_frontend_perms`：无条件把 `admin-web` 树 `chmod -R u+rwX,go+rX`（文件 644 / 目录 755），并给安装根与 `admin-web` 目录补 `o+x`（仅供 nginx 搜索穿过，不开放 `o+r`）；该函数在 `_frontend_finalize` 与 `ensure_nginx`（探活前）都调用，覆盖「重跑跳过构建」的情形；
  ③ SELinux 标整条路径（`nginx_fix_selinux`，上轮已加）保留——SELinux 管「上下文」、DAC 权限管「读/搜」，两者任一缺失都 403，现在都补齐。
  ④ 纯部署层，未动接口/表结构/判定口径。
- **服务器应急（已装实例不必重跑脚本）**：
  `sudo chmod -R u+rwX,go+rX /opt/llmbridge/admin-web && sudo chmod o+x /opt/llmbridge /opt/llmbridge/admin-web && sudo nginx -t && sudo systemctl reload nginx`

- **根因一（真 403）**：`nginx_fix_selinux` 原先只把 `…/admin-web/dist` 标 `httpd_sys_content_t`，漏了它的父目录 `admin-web` 与安装根 `/opt/llmbridge`。SELinux Enforcing 下，nginx 要读到 `dist/index.html` 必须能「穿过」`/opt/llmbridge → admin-web → dist` 每一层；父目录没标，traverse 被拦，直接 403 Forbidden（配置本身正确）。
- **根因二（掩盖故障）**：上一轮的探活被改成「任意 HTTP 应答即算就绪」，于是 403 也被当成成功，摘要误报「控制台已就绪」，把真故障藏起来了。
- **修法**：
  ① `nginx_fix_selinux` 标的范围扩展到整条路径：`chcon -t … $INSTALL_DIR`（安装根可搜索）+ `chcon -R -t … $INSTALL_DIR/admin-web`（含 dist）；并补 `semanage fcontext` + `restorecon` 持久化（只覆盖前端路径与安装根，不碰后端/.venv/.env），避免系统 relabel 后失效；
  ② `nginx_http_probe` 收紧为「根路径必须返回 HTTP 200 才算就绪」；非 200 时按状态码写入 `NGINX_FAIL_REASON`（403→指明 SELinux/权限拦读、502→后端未起、404→缺 index.html），不再把错误页当成功；
  ③ 纯部署层，未动接口/表结构/判定口径。

### 修掉「一键安装」收尾没做完 Nginx：反引号误执行 + 探活误判 + RHEL SELinux 兜底

- **根因一（确定性 bug）**：`print_summary` 的「启用控制台」提示里，在**未加引号**的 heredoc 中用反引号包着 `` `_` ``（指 nginx 的占位 server_name），bash 把它当成**命令替换**去执行 `_` 命令，安装末尾必报 `main: 行 N: _: 未找到命令`，并让那句话里的 server_name 丢失。
- **根因二（探活误判）**：`nginx_http_probe` 原先用 `curl -fsS`（带 `-f`），nginx 哪怕只是返回 403（SELinux 上下文偶发）/ 502（后端刚起还没热）就被判失败，导致 `NGINX_READY` 始终为 `false`、控制台永远显示「尚未就绪」，与「一键装完就能打开」相悖；且只在 nginx 监听的瞬间探测一次，nginx 刚 reload 完端口尚未 bind 也白判。
- **根因三（RHEL 最小化安装）**：`nginx_fix_selinux` 在 SELinux Enforcing 下要把非标准端口（8081）登记进 `http_port_t`，但最小化安装常缺 `semanage`（来自 `policycoreutils-python-utils`），缺了就只告警、nginx 在 8081 上绑不上、起不来，却无人兜底。
- **修法**：
  ① 把提示里的 `` `_` `` 换成中文引号「_」，消除命令替换（其余反引号都在 `#` 注释里，无害）；
  ② 重写 `nginx_http_probe`：去掉 `-f`，改为「HTTP 任意应答即算生效」+ 最多 12 次（约 12s）重试 + 退化到纯 TCP 连通性（`port_open`，不依赖 curl/wget，也不受 HTTP 状态码影响）；只要 nginx 在 `NGINX_PORT` 上真正监听就视为站点已生效；
  ③ 新增 `NGINX_FAIL_REASON`：每次 `ensure_nginx` 提前返回都把卡住的**具体那一步**（缺 nginx/写配置失败/`nginx -t` 未过/启动失败/探活失败）记下来，并打印进摘要的「启用控制台」小节，用户只贴尾部也能看到原因；
  ④ `nginx_fix_selinux` 在 Enforcing 且 `semanage` 缺失时，自动 `dnf/yum/apt-get` 补装 `policycoreutils-python-utils`（Debian 系为 `policycoreutils`）后再登记端口。
- **范围**：纯部署脚本层，**未动任何接口、表结构或判定口径**。

### 控制台对外默认端口 80 → 8081

- **变更**：后台管理端（控制台）的对外入口端口默认值由 `80` 改为 `8081`。
  - `deploy/install.sh`：`NGINX_PORT` 默认 `80` → `8081`；写入 `.env` 的 `HTTP_PORT` 同步 `80` → `8081`。
  - `deploy/docker-deploy.sh`：`HTTP_PORT` 默认 `80` → `8081`；两个 compose（`docker-compose.yml` / `docker-compose.image.yml`）的 `${HTTP_PORT:-80}` → `${HTTP_PORT:-8081}`。
  - 仍可用 `--nginx-port <n>`（裸机）/ `--port <n>`（容器）显式换端口；非 80 端口时 `print_summary` 自动在地址后补 `:<port>` 后缀。
  - SELinux 端口登记逻辑不变：8081 落进「非标准端口」分支，RHEL/CentOS 上安装会自动 `semanage port -a -t http_port_t -p tcp 8081`，避免 nginx 绑定被拦。
- **文档同步**：README（中英）、`05-安装打包说明.md` 的「默认 80」控制台端口表述全部改为 `8081`（含变量表与端口一致性核对）。`docs/README.md` 的 V1.6.2~V1.6.6 历史变更记录保持原样（那是当时事实）。
- **注意**：本改动只改**默认值**，不影响已在运行的实例。已装在 80 的机器要迁移到 8081，二选一：
  ① 重新跑 `sudo bash /opt/llmbridge/deploy/install.sh --nginx-port 8081`（会重新渲染站点配置并处理 SELinux/防火墙）；
  ② 手工把 `/etc/nginx/conf.d/llmbridge.conf` 的 `listen 80;` 改成 `listen 8081;`，`nginx -t && systemctl reload nginx`，并在防火墙/安全组放行 8081。
- **范围**：纯部署/文档层，**未动任何接口、表结构或判定口径**。

### 修掉前端构建在服务器上必挂：调用日志页面被 .gitignore 误吞 + Node 探测兜底

- **根因**：`.gitignore` 里有一条裸 `logs/`（本意是忽略仓库根目录的运行时日志），
  **却顺带把源码目录 `admin-web/src/views/logs/`（调用日志页面）整个排除出版本库**。
  凡是以 git 为源的部署（git clone / 同步）都缺这个文件，前端 `vue-tsc` 阶段直接报
  `Cannot find module '../views/logs/index.vue'` 而构建失败 —— 现象与根因相隔极远。
- **修法**：把 `logs/` 收紧为 `/logs/`（只忽略仓库根目录的日志目录），`admin-web/src/views/logs/`
  恢复入库；根目录运行时日志的忽略意图不受影响。已补 `git check-ignore` 复核：该文件不再被忽略、
  根 `/logs` 仍被忽略。
- **连带修掉 Node 探测的冗余下载**：`detect_node` 原先只靠 `command -v node/npm`，在受限的
  `sudo` `secure_path` 下常探不到已装好的 Node（如系统已装 nodejs-22 却判定「低于 20」，
  又去下载一份冗余的官方包、白耗时间）。现改为探测失败时**回退到常见绝对路径**
  （`/usr/bin/node` 等、并优先取同目录的 npm），命中后**把该目录前置进 `PATH`**，
  让 npm 子进程（vue-tsc/vite）也锁定同一份 node。
- **文档同步**：`.gitignore` 注释写明「绝不可写裸 `logs/`」的教训；本轮变更**行为层
  （部署脚本 + 忽略规则）**，未动任何接口、表结构或判定口径。

### 一键安装补上最后一环：Node.js 也自动装，并修掉提示里的坏命令

- **`install.sh` 新增「自动装 Node.js」全流程**（`ensure_node`）：缺 Node 或版本 < 20 时
  ① 先试发行版仓库（最快、走本地源；Alpine 只能走这条）→ ② 版本不够则下载**官方预编译包**，
  先 `nodejs.org`、**不通自动换 `npmmirror` 镜像**，解压到 `/usr/local/lib/nodejs` 并软链到
  `/usr/local/bin`。**已存在的同名实体文件绝不覆盖**（覆盖等于悄悄改掉机器上其它工具依赖的 node）。
  装完把新目录**前置进 `PATH`**：npm 的 shebang 是 `#!/usr/bin/env node`，旧 node 仍排在前面时
  npm 会拿旧 node 去跑新 npm，报的却是一堆语法错 —— 现象与成因相隔极远。
- **npm 源自动回退**：`npm ci` 首次失败时用 `registry.npmmirror.com` 重试一次并说明已切换，
  用户不必先去查「npm 怎么换源」。
- **修掉一条照抄必挂的命令**：补构建提示原先用 `$0` 拼命令，而 `curl … | sudo bash` 执行时
  `$0` 就是字符串 `bash`，于是打印出 **`sudo bash bash --frontend-only`**。改用 `self_cmd()`，
  优先指向 `<安装目录>/deploy/install.sh`；`need_root`、`--purge`、`--nginx-port` 三处同类
  提示一并修正。
- **修掉一处「自相矛盾的输出」**：站点探活通过但前端未构建时，摘要仍会打印「控制台已就绪」
  并给出地址 —— 用户按提示打开只会看到空白页，反而更怀疑是系统坏了。现已分岔为
  「控制台前端未构建 —— 站点已通，但页面暂时空白」并给出补构建命令；
  顶部地址栏的措辞也跟着改写（原先统一写「见下方『启用控制台』」，但前端也未构建时
  下方根本没有那一节，用户翻遍输出也找不到）。
- **新增选项**：`--no-node-install` / `--node-version <v>` / `--node-mirror <url>` /
  `--npm-registry <url>`；`--frontend-only` 现在一次补齐 Node.js + 前端 + Nginx。
- **顺手补掉一个静默失败**：`ln -s` 在部分环境会**静默**产出 0 字节空文件（退出码仍是 0），
  原先只看退出码等于把「软链没建起来」完全咽掉。改为 `ln` 之后**再验链接可执行**，失败即告警
  （但继续 —— 构建走绝对路径，不依赖软链）。
- **文档同步**：README（中英）前置条件与常用选项重写（Node.js / Nginx 均标「无需预装」），
  `05-安装打包说明.md` 补「Node.js 不漏」「提示语里的命令必须自包含」「不谎报就绪」三条约束、
  常见问题表新增一行，验证边界如实写入本轮 **37 项函数级自测**（A/B 两段独立进程）。
- **口径说明**：**行为层变更（安装脚本）**，未动任何接口、表结构或判定口径。

### 裸机安装真正做到「一键」：自动装 Nginx，装完直接给控制台地址

- **`install.sh` 新增「自动装并配置 Nginx」全流程**（`ensure_nginx`）：没装就用系统包管理器自动装
  （`apt` / `dnf` / `yum` / `zypper` / `apk`）；随后渲染并写入站点配置、
  **移走发行版自带默认站点**、按需 `setsebool -P httpd_can_network_connect 1` 与放行防火墙端口、
  `nginx -t` 门禁 + reload，**探活成功才对外宣称地址可用**。
- **安装结束直接打印控制台地址**：`控制台地址  http://<服务器IP>/` 放在摘要最顶部
  （IP 取 `hostname -I` 的第一个非回环地址），下面紧跟默认账号 `admin / admin123`。
  只有探活通过才写地址 —— 宁可明说「尚未就绪」，也不甩一个打不开的 URL 让人反复试。
- **两个高发坑改为脚本内解决，不再交给用户**：
  ① 没装 Nginx 时 `/etc/nginx/conf.d` 根本不存在，照抄 `cp` 只会得到
  `cp: 无法创建普通文件 '…': 没有那个文件或目录` —— 这句报错说的是**目标目录**缺失，
  字面上却像在怪站点配置，极易被带偏方向；
  ② 发行版自带默认站点占着 80 的 `default_server`，本站点 `server_name` 是 `_`（不匹配任何真实
  Host），抢不到「默认」位 → 访问到的是欢迎页、反代完全没走。现在分别由
  「自动安装」与「自动移走默认站点」处理。
- **新增 `--no-nginx`**：改用自己的 web 服务器时跳过这一步。
  `--frontend-only` 也顺带补齐 Nginx 并打印地址（走这条路的多半正是上次卡在这里的人）。
- **失败不阻断**：装不上 Nginx、`nginx -t` 不通过、启动失败都只告警并返回 0，不连累已装好的后端；
  兜底提示里保留手工步骤与 `--nginx-port <n>` 换端口的办法。
- **文档同步**：README（中英）的「前置条件 / 常用选项 / 安装后打开控制台」段重写，
  `05-安装打包说明.md` 补「Nginx 不漏」约束、手工段标注为「方式一可跳过」、
  常见问题表分组，并在验证边界里如实写入本轮新增的**函数级自测**范围。
- **口径说明**：**行为层变更（安装脚本）**，未动任何接口、表结构或判定口径。

### 修掉裸机部署里两个「照抄命令必然失败」的坑

- **`install.sh` 结束提示改为按「本机有没有 Nginx」分岔**：原先无条件打印
  `sudo cp <安装目录>/deploy/nginx-llmbridge.conf /etc/nginx/conf.d/llmbridge.conf`，
  而在**没装 Nginx** 的机器上 `/etc/nginx/conf.d` 根本不存在，照抄会得到
  `cp: 无法创建普通文件 '/etc/nginx/conf.d/llmbridge.conf': 没有那个文件或目录` ——
  这句报错说的是**目标目录缺失**（源文件缺失时报的是「无法获取 … 的状态」），
  字面上却像是在怪站点配置，极易误判成「配置文件坏了」。现在：已装 → 直接给两步；
  未装 → 先给装 Nginx 的命令，再给站点配置两步，并附 RHEL / CentOS 的 SELinux 与防火墙放行。
- **落盘命令本身也换了**：`cp` → `install -D -m 644`（`install -D` 自带 `mkdir -p`），
  把「目标目录不存在」这个失败模式从根上消掉。
- **补上第二个高发坑**：站点配好、`nginx -t` 与 `systemctl reload nginx` 都成功，
  访问 IP 却是 **Nginx 欢迎页** —— 系统自带的默认站点占着 80 端口的 `default_server`，
  而本站点 `server_name` 是 `_`（不匹配任何真实 Host），抢不到「默认」位，请求被默认站点接走。
  提示里给出 Debian / Ubuntu（删 `/etc/nginx/sites-enabled/default`）与
  RHEL 系（注释 `nginx.conf` 里的 `default_server` 块）两种处理。**与 `/v1` 的 SSE 配置无关**。
- **文档同步**：`docs/阶段五-部署与交付/05-安装打包说明.md` 的手工装配段补「前提是本机已装 Nginx」
  的说明，常见问题表新增 3 行（`conf.d` 目录缺失报错 / 欢迎页抢 80 / SELinux 502）。
- **口径说明**：**安装脚本提示层 + 文档层变更**，未动任何接口、表结构或判定口径。

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
