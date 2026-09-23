-- ============================================================================
-- LLM 路由中转系统 · 数据库设计（DDL + 索引 + 种子数据）
-- ----------------------------------------------------------------------------
-- 项目   : llmbridge（OPD 阶段二交付物，署名 SDA）
-- 版本   : V1.6    创建日期 : 2026-09-21   （V1.6：2026-09-22 订阅类套餐纳入路由 + provider.terms_note）
-- 基线   : docs/README.md 3.5 节「数据库表（固定，共 8 张）」
--
-- 方言兼容策略：
--   本文件使用 SQLite 与 PostgreSQL 均可执行的通用写法：
--   · 类型仅用 INTEGER / VARCHAR / TEXT / REAL / DATETIME / BOOLEAN
--   · 不使用 PostgreSQL 独有的 SERIAL / JSONB / 部分索引 / 表分区
--   · BOOLEAN 在 SQLite 中以 INTEGER 0/1 存储，SQLAlchemy 按方言自动转换
--   · 主键统一 INTEGER PRIMARY KEY AUTOINCREMENT（PG 下自动映射为序列语义，
--     SQLAlchemy 建表时以 Integer autoincrement=True 处理，两者行为一致）
--
-- 迁移状态（2026-09-22）：**已完成**。开发与生产统一使用 PostgreSQL 17，
--   异步驱动 psycopg3（postgresql+psycopg://）；表结构由 app/db/tables/ 的 SQLAlchemy
--   元数据 create_all 建立，历史数据由 scripts/migrate_sqlite_to_pg.py 全量迁移
--   （8 表，逐表行数校验一致）。本文件保留为「设计基线」，实际 DDL 以 ORM 元数据为准。
--   ⚠️ Windows 下须用 SelectorEventLoop 启动，否则 psycopg 首次查询即失败
--   （--loop app.core.eventloop:selector_loop_factory）。详见
--   docs/阶段三-开发与实现/03-端到端联调验证记录.md §七。
--
-- 生产迁移 PostgreSQL 时的后续差异点（在 alembic 迁移中补齐，勿改本文件）：
--   1. router_output_json / probabilities_json / condition_json 改为 JSONB，
--      并建 GIN 索引（支持按 confidence、task_type 内部字段查询）
--   2. created_at 改为 timestamptz
--   3. request_log 按 created_at 做月度分区（表名不变，主表转继承/分区表）
--   4. 大文本字段 input_text 截断阈值由应用层保证（2000 字符）
--
-- 外键删除策略（V1.1 补充，缺陷 D-12 整改）：
--   引用 model(id) 的 5 处外键按语义分两类，禁止一刀切：
--   · 配置类引用 —— route_rule.target_model_id / eval_case.expected_model_id
--     → ON DELETE RESTRICT：删模型会让规则或评测用例悬空，必须先解除引用或改为「禁用」
--   · 历史类引用 —— request_log.final_model_id / decision_sample.chosen_model_id /
--     decision_sample.actual_model_id
--     → ON DELETE SET NULL：日志与样本是既成事实，应保留记录、仅解绑模型引用
--   注：应用层 app/api/admin/models.py 已实现同语义（先统计再解绑，最后删除）。
--   注（D-19 整改）：解绑会抹掉「这条日志当时调用的是谁」，故 request_log 增列
--     final_model_key 存 model_name 快照；日志的模型归属从此不随配置变更消失。
--       SQLite 现库修改外键须重建表，故当前库由应用层显式置 NULL 保证；
--       DDL 级约束用于 PostgreSQL 侧兜底。SQLite 需 PRAGMA foreign_keys=ON 才生效
--       （app/db/session.py 连接事件已开启）。
--
-- 执行方式（当前主库为 PostgreSQL）：
--   PG（默认）: psql "postgresql://<用户>@<主机>:5432/llmbridge" -f 05-数据库设计.sql
--   或用 ORM 建表（推荐，保证与代码一致）: python -m app.seed
--   SQLite（仅兼容性参考，已非开发主库）: sqlite3 llmbridge.db < 05-数据库设计.sql
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 表 1/8 : provider  厂商接入通道（一条记录 = 一条接入通道，不是一家厂商）
-- ----------------------------------------------------------------------------
CREATE TABLE provider (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                VARCHAR(64)  NOT NULL,                    -- 通道显示名，如「月之暗面 Kimi · 按量 API」
    vendor              VARCHAR(64)  NULL,                        -- 厂商标识（分组键），如 moonshot；同厂商各通道共用
    access_kind         VARCHAR(32)  NOT NULL DEFAULT 'api',      -- 接入形态：api/package/token_plan/coding_plan/batch
    protocol            VARCHAR(32)  NOT NULL DEFAULT 'openai',   -- 上游协议：openai/anthropic
    base_url            VARCHAR(255) NOT NULL,                    -- 接入点地址，须过 SSRF 白名单校验
    api_key_encrypted   TEXT         NOT NULL,                    -- AES-256-GCM 密文（明文永不落库、永不回显）
    remark              VARCHAR(255) NULL,                        -- 备注：密钥申请入口 + 接入注意事项（内置目录写入）
    terms_note          TEXT         NULL,                        -- 厂商官方条款警示（订阅类通道通常有值）
    enabled             BOOLEAN      NOT NULL DEFAULT 1,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_provider_access_kind CHECK (access_kind IN ('api','package','token_plan','coding_plan','batch')),
    CONSTRAINT ck_provider_protocol    CHECK (protocol IN ('openai','anthropic'))
);
CREATE UNIQUE INDEX ux_provider_name ON provider(name);
CREATE INDEX ix_provider_vendor ON provider(vendor);

-- ============================================================================
-- provider 表语义演进说明
-- ============================================================================
--
-- 【V1.2】新增 remark 列 —— 内置厂商目录特性引入
--   hint 列为后加列，历史库由 scripts/migrate_add_provider_remark.py 幂等补齐
--   （ALTER TABLE provider ADD COLUMN remark VARCHAR(255)，重复执行自动 skip）。
--   该列仅承载「展示用文案」，不参与任何路由判定，故可空、无默认值、不加索引。
--
--   ⚠️ model.capabilities 必须为 JSON 数组字符串（json.dumps 写入）。psycopg 不做方言转换，
--      直接写入 Python list 会被适配成 PG 数组字面量 {a,b}，下游 json.loads 必崩（缺陷 D-26）。
--
-- 【V1.5】新增 vendor / access_kind / protocol 三列 —— 一家厂商多条接入通道
--   历史库由 scripts/migrate_add_provider_channels.py 幂等补齐。
--
--   为什么需要：同一家厂商往往同时卖几种互不相通的东西，密钥、端点、计费、限流全都不同，
--   **密钥彼此不通用**（拿按量 API 的 Key 打订阅端点会 401）。典型三形态：
--     · api          按量 API        —— 开放平台，按 token 后付费
--     · coding_plan  编程订阅套餐    —— 订阅页专属 Key + 专属端点，包月积分/次数限流
--     · package      资源包          —— 与 api 同 Key 同端点，只是预付费抵扣
--     · batch        批处理          —— 与 api 同 Key 同端点，按批优惠价
--   所以「一条 provider 记录」的正确语义是**一条接入通道**；同厂商的多条靠 vendor 聚合，
--   控制台按该字段聚成一张厂商卡片展示。
--
--   ⚠️ package / batch 刻意**不单独建行**：它们不改变端点、密钥与协议，只是同一条按量 API 的
--      结算方式。各建一行只会让使用者困惑「同一个 Key 该填哪一行」。其价差写在 model.price_note。
--
--   ⚠️ 可路由判定（services/provider_access.py）三道闸门，顺序不可反： 【V1.6 已变更，见下】
--        ① access_kind ∈ ROUTABLE_ACCESS_KINDS（api/package/batch）
--        ② protocol ∈ SUPPORTED_PROTOCOLS（当前仅 openai，Anthropic 适配器未实现）
--        ③ 密钥可解密且非空白
--      前两道**配置解决不了**，故在错误归因里排在密钥之前（否则使用者会反复填 Key 却始终不生效）。
--      coding_plan 通道照常登记、照常可填 Key，但默认不进候选池：厂商条款限定其仅限官方
--      编程工具使用（Kimi 官方明确「篡改客户端标识视为违规，可暂停会员权益」），
--      且订阅制无 token 单价，硬填 0 会让它在 L3 成本因子上拿满分、长期霸占路由。
--
--   内置厂商目录（app/data/provider_catalog.py，CATALOG_VERSION=2026-09）现预置
--   12 家国内主流厂商 / 15 条通道 / 27 个模型，由 scripts/seed_provider_catalog.py 幂等写入：
--   · 新通道 / 新模型一律 enabled=False，api_key_encrypted 写占位密文 ENC_PLACEHOLDER_<name>
--   · 占位密文**非法**，故 has_usable_key() 解密必抛 ValueError → 自动判为「未接入」，
--     无需额外 is_configured 字段即可表达三态（已接入 / 待配置密钥 / 已停用）
--   · 使用者只需在控制台填入真实 Key，后端在首次录入密钥时自动启用该**可路由**通道与其目录模型；
--     不参与路由的通道只记密钥、不自动启用，并回报 skipped_reason
--
-- 【V1.6】新增 terms_note 列 + 订阅类套餐纳入路由 —— 推翻 V1.5 的「登记但不路由」
--   历史库由 scripts/migrate_add_provider_channels.py 幂等补齐（同一次运行同时补 column 与重建 CHECK）。
--
--   ① 新增第 5 种接入形态 token_plan（通用 Token 订阅套餐），与 coding_plan 并列：
--        · api          按量 API        —— 开放平台，按 token 后付费
--        · package      资源包          —— 与 api 同 Key 同端点，只是预付费抵扣（不单独建行）
--        · batch        批处理          —— 与 api 同 Key 同端点（不单独建行）
--        · coding_plan  编程订阅套餐    —— 订阅页专属 Key + 专属端点，包月积分/次数
--        · token_plan   通用 Token 订阅 —— 订阅页专属 Key + 专属端点，包月 Token 额度
--      ROUTABLE_ACCESS_KINDS 由此扩为**全部五种**。该集合刻意保留而非删掉判断：
--      未来若出现本系统明确不该接的新形态，闸门仍在原处，无需重新引入。
--
--   ② 为什么新增 terms_note 独立成列而不复用 remark：
--      remark 是 VARCHAR(255)，而厂商条款原文通常远超 255 字符，截断会丢失约束语义
--      （例如「不得作为应用后端」这一句被截掉，警示就失去意义）。故改 TEXT 且独立成列。
--
--   ③ 合规风险由「被系统挡住」改为「如实告知、使用者自担」：
--      订阅类通道的厂商条款普遍限定「仅限厂商官方支持的编程 / 智能体工具**交互式**使用，
--      不得作为应用后端 / 自动化脚本 / 批量任务的主调用通道」。本网关对外提供 /v1 接口，
--      从上游看属于应用后端，天然落在这条限制内。系统的处置是**不隐瞒**：
--        · 条款原文落 provider.terms_note（目录侧由 build_terms_note() 统一生成）
--        · 控制台厂商页给可展开的条款警示条 + is-info 徽章「单价为参照值」
--        · 首次填 Key 自动启用时，auto_enabled 响应一并回传 terms_note，前端用 alert 弹窗
--          （toast 会消失，而「启用了一条条款受限的通道」值得占用一次点击）
--        · 产品决策理由需在用户手册 / 发布说明中写明（记为 U-25）
--
--   ④ 订阅制无 token 单价 → 单价一律是**成本参照值**，绝不填 0：
--      填 0 会让它在 L3 成本因子上拿满分而长期霸占路由。三条优先级：
--        ① 套餐公布「套餐价 + Token 额度」→ 相除得等效单价
--           （例：腾讯云 Max 599 元 ÷ 6.5 亿 token ≈ 0.92 元/百万）
--        ② 未公布额度 → 取该模型按量标准价作参照
--        ③ 两者都拿不到 → **不收录该模型**，在通道 note 里列出名称（界面提示去模型池手工添加）
--      同名模型会在「按量 API」与「订阅通道」下重复出现，故订阅通道的同名模型刻意给
--      **更大的 priority 数值**，使合规风险更低的按量通道在同价时优先。
--
--   ⑤ 闸门 ① 覆盖全部五形态后**正常配置下恒为空**，但仍保留；措辞已改为
--      「接入方式「X」不在支持的接入形态内」。闸门 ②（协议）未取消：Anthropic 协议适配器
--      仍未实现（记为 U-23），各通道 base_url 一律取 OpenAI 兼容端点。
--
--   ⑥ 目录规模：12 家厂商 / 22 条通道 / 51 个模型，其中订阅类 10 条
--      （5 coding_plan + 5 token_plan），6 条暂无模型。有独立订阅套餐的 8 家；
--      确认无订阅套餐的 4 家（DeepSeek / 零一万物 / 百川 / 硅基流动）只有资源包。
--
--   ⚠️ 迁移脚本必须比对 CHECK 表达式的**字符串字面量集合**，不能只比约束名：
--      ck_provider_access_kind 名字没变但取值集合变了。只按名字判断会打印 skip 然后放行，
--      留下一个拒绝写入 token_plan 的旧约束，表现为「预置时 CheckViolation，而脚本说已最新」。

-- ----------------------------------------------------------------------------
-- 表 2/8 : model  模型池（业务术语「下游大模型」；ORM 侧对应 db/tables/model.py）
-- ----------------------------------------------------------------------------
CREATE TABLE model (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id         INTEGER      NOT NULL,
    model_name          VARCHAR(128) NOT NULL,                    -- 厂商侧真实模型名，如 deepseek-chat
    display_name        VARCHAR(128) NOT NULL,                    -- 控制台显示名
    capabilities        TEXT         NOT NULL DEFAULT '[]',       -- 能力标签 JSON 数组，如 ["code_generation","long_context"]
    input_price         REAL         NOT NULL DEFAULT 0,          -- 输入单价  元/百万token
    output_price        REAL         NOT NULL DEFAULT 0,          -- 输出单价  元/百万token
    context_window      INTEGER      NOT NULL DEFAULT 8192,
    enabled             BOOLEAN      NOT NULL DEFAULT 1,
    priority            INTEGER      NOT NULL DEFAULT 100,        -- 数值越小越优先；降级顺序据此排列
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_model_provider FOREIGN KEY (provider_id) REFERENCES provider(id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX ux_model_provider_name ON model(provider_id, model_name);
CREATE INDEX ix_model_enabled_priority ON model(enabled, priority);

-- ----------------------------------------------------------------------------
-- 表 3/8 : route_rule  路由规则（L1 规则短路）
-- ----------------------------------------------------------------------------
CREATE TABLE route_rule (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                VARCHAR(128) NOT NULL,
    priority            INTEGER      NOT NULL DEFAULT 100,        -- 数值越小越优先；多条命中取最小值
    type                VARCHAR(32)  NOT NULL,                    -- keyword / regex / token_len / tenant_whitelist / session_pin
    condition_json      TEXT         NOT NULL,                    -- 条件定义，见接口设计说明书 §条件编辑器 Schema
    target_model_id     INTEGER      NOT NULL,
    enabled             BOOLEAN      NOT NULL DEFAULT 1,
    remark              VARCHAR(255) NULL,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_rule_model FOREIGN KEY (target_model_id) REFERENCES model(id),
    CONSTRAINT ck_rule_type CHECK (type IN ('keyword','regex','token_len','tenant_whitelist','session_pin'))
);
CREATE INDEX ix_rule_enabled_priority ON route_rule(enabled, priority);

-- ----------------------------------------------------------------------------
-- 表 4/8 : decision_sample  决策样本（V1.1 由 route_sample 重定义）
-- ----------------------------------------------------------------------------
CREATE TABLE decision_sample (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    input_text          TEXT         NOT NULL,
    task_type           VARCHAR(64)  NOT NULL,                    -- Jev Choice 判定类别
    probabilities_json  TEXT         NOT NULL DEFAULT '{}',       -- Jev 概率分布快照
    chosen_model_id     INTEGER      NULL,                        -- 映射表选出的模型
    actual_model_id     INTEGER      NULL,                        -- 最终实际调用（含降级）
    source              VARCHAR(32)  NOT NULL DEFAULT 'manual',   -- manual / log_mined / eval_backfill
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_sample_chosen FOREIGN KEY (chosen_model_id) REFERENCES model(id) ON DELETE SET NULL,
    CONSTRAINT fk_sample_actual FOREIGN KEY (actual_model_id) REFERENCES model(id) ON DELETE SET NULL
);
CREATE INDEX ix_sample_task_type ON decision_sample(task_type);

-- ----------------------------------------------------------------------------
-- 表 5/8 : prompt_template  判定提示词模板（BaseDecider 本地实现位使用）
-- ----------------------------------------------------------------------------
CREATE TABLE prompt_template (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    scene               VARCHAR(64)  NOT NULL,                    -- 使用场景，如 jev_task_type / local_fallback
    content             TEXT         NOT NULL,
    version             INTEGER      NOT NULL DEFAULT 1,
    is_active           BOOLEAN      NOT NULL DEFAULT 1,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX ux_template_scene_version ON prompt_template(scene, version);

-- ----------------------------------------------------------------------------
-- 表 6/8 : request_log  调用日志（全链路 Trace 落点；增长最快的表，重点索引）
-- ----------------------------------------------------------------------------
CREATE TABLE request_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id            VARCHAR(64)  NOT NULL,
    input_text          TEXT         NOT NULL,                    -- 应用层截断至 2000 字符
    router_output_json  TEXT         NOT NULL DEFAULT '{}',       -- 判定快照：task_type/probabilities/confidence/候选打分
    router_layer        VARCHAR(8)   NOT NULL,                    -- L1 / L2 / L3
    final_model_id      INTEGER      NULL,
    final_model_key     VARCHAR(128) NULL,                        -- 模型名快照（落库当时的 model_name）
                                                                  -- 外键会被 ON DELETE SET NULL 清空，快照保证「当时真实调用了谁」这一事实不丢失
    latency_ms          INTEGER      NOT NULL DEFAULT 0,          -- 端到端总耗时
    route_latency_ms    INTEGER      NOT NULL DEFAULT 0,          -- 路由判定额外耗时（≤800ms P95 的考核口径）
    prompt_tokens       INTEGER      NOT NULL DEFAULT 0,
    completion_tokens   INTEGER      NOT NULL DEFAULT 0,
    cost                REAL         NOT NULL DEFAULT 0,          -- 单次成本（元）
    status              VARCHAR(16)  NOT NULL DEFAULT 'success',  -- success / error
    fallback_reason     VARCHAR(128) NULL,                        -- LOW_CONFIDENCE / DECIDER_UNAVAILABLE / UPSTREAM_UNAVAILABLE:<model>
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_log_model FOREIGN KEY (final_model_id) REFERENCES model(id) ON DELETE SET NULL,
    CONSTRAINT ck_log_layer CHECK (router_layer IN ('L1','L2','L3'))
);
CREATE UNIQUE INDEX ux_log_trace ON request_log(trace_id);
CREATE INDEX ix_log_created ON request_log(created_at);
CREATE INDEX ix_log_model ON request_log(final_model_id);
CREATE INDEX ix_log_layer_status ON request_log(router_layer, status);

-- ----------------------------------------------------------------------------
-- 表 7/8 : eval_case  评测用例（验收硬指标「准确率 ≥85% / 50 条」的载体）
-- ----------------------------------------------------------------------------
CREATE TABLE eval_case (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    input_text          TEXT         NOT NULL,
    expected_task_type  VARCHAR(64)  NOT NULL,
    expected_model_id   INTEGER      NULL,
    remark              VARCHAR(255) NULL,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_eval_model FOREIGN KEY (expected_model_id) REFERENCES model(id)
);

-- ----------------------------------------------------------------------------
-- 表 8/8 : admin_user  控制台用户
-- ----------------------------------------------------------------------------
CREATE TABLE admin_user (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    username            VARCHAR(64)  NOT NULL,
    password_hash       VARCHAR(255) NOT NULL,                    -- bcrypt
    role                VARCHAR(16)  NOT NULL DEFAULT 'admin',    -- admin / readonly
    enabled             BOOLEAN      NOT NULL DEFAULT 1,
    last_login_at       DATETIME     NULL,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_user_role CHECK (role IN ('admin','readonly'))
);
CREATE UNIQUE INDEX ux_user_username ON admin_user(username);

-- ============================================================================
-- 种子数据（开发环境 · 最小可跑集）
-- 密钥说明：种子里的 api_key_encrypted 为占位密文，首次登录控制台后必须改录真实 Key；
--           admin 密码为 bcrypt(admin123)，生产部署后必须立即修改。
-- ----------------------------------------------------------------------------
-- 注（V1.2）：以下 2 厂商 / 4 模型仅用于「开发环境最小可跑」，非交付态数据。
--   交付态由内置厂商目录脚本预置 12 家主流厂商 + 各家全部接入通道（均 enabled=False 待填 Key）：
--     python scripts/migrate_add_provider_channels.py  # 幂等补 vendor/access_kind/protocol/terms_note + 重建 CHECK
--     python scripts/seed_provider_catalog.py          # 幂等写入目录（--dry-run 可预演）
--   本段 INSERT 一并补全 remark 列，保持与当前表结构一致（见 app/db/tables/__init__.py）。
--   ⚠️ 本段未显式写 vendor / access_kind / protocol / terms_note —— 走列默认值
--      （access_kind='api'、protocol='openai'、vendor=NULL、terms_note=NULL）。这是有意的：
--      这 4 行是历史联调数据，不属于内置目录，故不参与目录的 vendor 分组与订阅标识。
-- ============================================================================

INSERT INTO provider (id, name, base_url, api_key_encrypted, remark, enabled) VALUES
  (1, 'DeepSeek',   'https://api.deepseek.com/v1',   'ENC_PLACEHOLDER_DEEPSEEK',
     '密钥申请：https://platform.deepseek.com/api_keys', 1),
  (2, 'OpenAI',     'https://api.openai.com/v1',     'ENC_PLACEHOLDER_OPENAI',
     '密钥申请：https://platform.openai.com/api-keys', 1);

INSERT INTO model (id, provider_id, model_name, display_name, capabilities, input_price, output_price, context_window, enabled, priority) VALUES
  (1, 1, 'deepseek-chat',    'DeepSeek Chat',   '["general","code_generation"]',          2.0,  8.0,  65536, 1, 10),
  (2, 1, 'deepseek-coder',   'DeepSeek Coder',  '["code_generation"]',                    2.0,  8.0,  65536, 1, 10),
  (3, 2, 'gpt-4o-mini',      'GPT-4o mini',     '["general","translation","summarize"]',  1.25, 5.0,  128000, 1, 20),
  (4, 2, 'gpt-4o',           'GPT-4o',          '["general","complex_reasoning","long_context"]', 20.0, 80.0, 128000, 1, 30);

INSERT INTO route_rule (id, name, priority, type, condition_json, target_model_id, enabled, remark) VALUES
  (1, '代码任务直达 Coder', 10, 'keyword',
     '{"all":[{"field":"text","op":"contains","value":"def "},{"field":"text","op":"contains","value":"debug"}]}',
     2, 1, 'L1 示例：文本同时含 def 与 debug 时短路到 deepseek-coder'),
  (2, '翻译任务走 mini',   20, 'keyword',
     '{"all":[{"field":"text","op":"contains","value":"翻译"}]}',
     3, 1, 'L1 示例：含「翻译」关键词短路到 gpt-4o-mini');

INSERT INTO admin_user (id, username, password_hash, role, enabled) VALUES
  (1, 'admin', '$2b$12$C6UzMDM.H6dfI/f/IKcEe.6rUdQlBpOtQK7H7Z5u1l5S8l1v0E1qG', 'admin', 1);

INSERT INTO eval_case (input_text, expected_task_type, expected_model_id, remark) VALUES
  ('帮我写一个 Python 函数，计算两个日期之间的工作日', 'code_generation', 2, '代码生成样本'),
  ('把下面这段话翻译成英文：今天天气很好',             'translation',     3, '翻译样本'),
  ('总结这篇文章的核心观点，控制在 200 字以内',         'summarize',       3, '摘要样本'),
  ('用通俗语言解释一下什么是量子纠缠',                 'general',         1, '通用问答样本');
