"""内置厂商目录：13 家国内主流厂商，以及它们在库中的**全部接入通道**。

设计目的
--------
让接入成本从「查文档 + 填 base_url + 建模型 + 查价格 + 打能力标签」降为**只填一个 API Key**。
本目录是纯静态数据，不含任何密钥；密钥由使用者在控制台录入，加密入库。

一家厂商 ≠ 一条接入通道
------------------------
同一家厂商常常同时卖几种互不相通的东西，各有各的密钥、端点、计费与限流，
**密钥彼此不通用**（拿 A 的 Key 打 B 的端点会 401）。本目录把每种都建成独立通道：

| access_kind | 含义 | 密钥来源 | 计费 | 能否参与路由 |
|---|---|---|---|---|
| `api` | 按量 API | 开放平台通用 Key | 按 token 后付费 | ✅ |
| `package` | 预付费资源包 | **与 api 同一个 Key** | 先充值后抵扣 | ✅ |
| `batch` | 批处理 | **与 api 同一个 Key** | 按批优惠价 | ✅ |
| `coding_plan` | 编程订阅套餐 | 订阅专属 Key | 包月积分 / 请求次数 | ✅ |
| `token_plan` | 通用 Token 订阅套餐 | 订阅专属 Key | 包月 Token / Credits | ✅ |

⚠️ 为什么 `package` / `batch` **不单独建通道行**：
它们不改变端点、不改变密钥、不改变协议，只是同一条按量 API 的**结算方式**。
若为它们各建一行，使用者会在「同一个 Key 该填哪一行」上困惑，是纯噪音。
它们的差别已经体现在通道的 `note` 里（如「低谷时段约 5 折」）。

⚠️ 订阅类通道（`coding_plan` / `token_plan`）**参与路由，但必须知情**
--------------------------------------------------------------
本项目早期版本把订阅类通道排除在候选池之外。改为纳入后，风险从「被系统挡住」
变成「使用者自己承担责任」，所以官方条款原文被逐条落到 `terms_warning`，
写进库里的 `provider.terms_note`，并在控制台用警示条呈现。

各厂商官方口径高度一致，均明确限定这类套餐**只能在官方支持的编程 / 智能体工具中
交互式使用，不得作为应用后端**：

- 阿里云百炼：「Token Plan、Coding Plan 和隨用隨付的 API Key 與 Base URL 完全隔離，必須配套使用」
- 智谱 GLM：「套餐额度仅限在官方支持的编码工具和产品环境中使用；在自建应用、网站、机器人、
  SaaS 产品或其他场景中需要直接调用标准 API，不能使用套餐额度」
- 月之暗面 Kimi：「如需在自己的产品中调用大模型能力……请访问 Kimi 开放平台」；
  「篡改客户端标识（User-Agent）将被视为违规，可能导致会员权益暂停」
- 火山方舟：「在非 AI 工具中使用方舟 Coding Plan / Agent Plan 权益对应的 Base URL 和 API Key
  有可能被识别为滥用/违规，会导致订阅停用或账号封禁」
- 腾讯云：「禁止用于应用程序后端：不能作为生产环境后端服务的主调用通道」
- 百度千帆：「仅限在兼容的 AI 编程和智能体工具中交互式使用，不可用于自动化脚本或应用后端」

一个对外提供 `/v1` 接口的网关，从上游看正是「应用后端」。**接入即代表接受该风险。**

⚠️ 单价口径（重要，请勿当成实时报价）
--------------------------------------
`input_price` / `output_price` 单位为 **元 / 百万 token**，语义是「**该通道下每百万 token 的成本参照值**」，
仅供 L3 成本因子横向比较，**不是实时报价**。三种取法按优先级：

1. **等效单价**：套餐公布了「套餐价 + 套餐 Token 额度」时，直接相除
   （如腾讯云通用 Token Plan Max：599 元 ÷ 6.5 亿 token ≈ 0.92 元/百万）。
   官方声明「不区分模型倍率、输入输出统一抵扣」的套餐，其下所有模型共用这个等效单价。
2. **按量标准价**：套餐未公布 Token 额度的，取该模型的按量标准单价作为参照
   （订阅套餐内的边际成本实际为 0，但**绝不能填 0**——填 0 会让该通道在 L3 成本因子上
   拿满分、从而长期霸占路由，把流量静默导向条款受限的通道）。
3. **两者都拿不到 → 不收录该模型**，改在通道 `note` 里列出名称。
   宁可让通道暂时没有模型（填 Key 后在模型页手工添加），也不编造数字。

已知会失真的情形，启用前请务必按官网核对：
- **时间漂移**：国内大模型价格调整频繁，本目录写入后可能已变。
- **平台差异**：同一模型在厂商直销与聚合平台（如硅基流动）价差可达 2~4 倍；本目录取厂商直销口径。
- **计费口径差异**：部分厂商只公布「命中缓存 / 未命中」两档输入价，本目录统一取**未命中**价。

数据可信度
----------
`api` 通道的 base_url / 密钥入口 / 模型单价均取自厂商官方文档。
订阅类通道的 base_url、专属 Key 前缀、支持模型同样取自官方文档
（阿里云帮助中心、智谱 docs.bigmodel.cn、Kimi Code Docs、火山引擎文档中心、
百度智能云文档、腾讯云文档、MiniMax API Docs、阶跃星辰开放平台、小米 MiMo 开放平台
platform.xiaomimimo.com 与 mimo.mi.com/docs）。
未能从官方渠道确认的，一律留空并在 `note` 说明，不做转述式填写。
"""

from dataclasses import dataclass, field

CATALOG_VERSION = "2026-09"
"""目录数据的整理时间；价格与模型代号的时效基准。"""

PRICE_DISCLAIMER = (
    f"参考价（{CATALOG_VERSION} 整理，元/百万 token），仅供路由成本因子排序；"
    "大模型价格调整频繁，启用前请以厂商官网为准。"
)

ACCESS_KINDS: dict[str, str] = {
    "api": "按量 API",
    "package": "资源包",
    "batch": "批处理",
    "coding_plan": "编程订阅套餐",
    "token_plan": "Token 订阅套餐",
}

PROTOCOLS: dict[str, str] = {
    "openai": "OpenAI 兼容",
    "anthropic": "Anthropic 兼容",
}

ROUTABLE_ACCESS_KINDS = frozenset({"api", "package", "batch", "coding_plan", "token_plan"})
"""可参与路由的接入形态 —— 目前是**全部形态**。

订阅类套餐（`coding_plan` / `token_plan`）纳入路由是产品决策：
使用者有权使用自己付费的额度。代价是必须知情（见各通道 `terms_warning`）。

保留这个集合（而不是删掉判断）有两个原因：
1. 未来若出现「本系统明确不该接」的新形态，闸门还在；
2. `is_channel_supported()` 是「配置解决不了的不可路由原因」的唯一来源，
   删掉它会让 `routable_blockers()` 失去语义。
"""

SUPPORTED_PROTOCOLS = frozenset({"openai"})
"""已实现适配器的协议。厂商同时提供 Anthropic 端点时，本目录一律取 **OpenAI 兼容**端点
写在 `base_url`（因为只有 `adapters/openai_compat.py` 一个实现），
Anthropic 端点记在通道 `note` 里备查。"""


@dataclass(frozen=True)
class CatalogModel:
    """目录内的一个模型条目。"""

    model_name: str
    """调用上游时传的 model 字段（必须与厂商 API 完全一致）。"""

    display_name: str
    capabilities: tuple[str, ...]
    input_price: float
    output_price: float
    context_window: int
    priority: int = 100
    """越小越优先：既作降级顺序，也作 L3 打分的同分 tie-break。

    订阅类通道的同名模型刻意给**更大的数值**（更靠后），
    使「按量 API」在同价时优先被选中——合规风险更低的通道先走。"""

    price_note: str = ""
    """价格口径补充（如「输入输出合并计价」「峰谷定价」「套餐等效单价」）。"""


@dataclass(frozen=True)
class CatalogChannel:
    """一条接入通道 = provider 表的一行。"""

    access_kind: str
    protocol: str
    base_url: str
    key_url: str
    """该通道**专属**的密钥申请入口。与同厂商其它通道通常不是同一个页面。"""

    note: str = ""
    """接入注意事项（写入 provider.remark，控制台可见）。"""

    terms_warning: str = ""
    """厂商官方条款警示原文（写入 provider.terms_note）。
    订阅类通道必填——它是「纳入路由」这个决策的知情依据。"""

    unroutable_reason: str = ""
    """不可参与路由的原因。仅当 access_kind / protocol 本身不被支持时填写，
    用于在界面上把「为什么不参与路由」说到点上，而不是让使用者自己猜。

    ⚠️ **V1.6 起目录内已无此类通道**：五种形态（含 `coding_plan` / `token_plan`）
    全部纳入 `ROUTABLE_ACCESS_KINDS`，协议一律取 OpenAI 兼容端点，故本字段当前**全部为空**。
    保留它是为了「未来若接入了本系统明确不该路由的形态」，归因链路依然单向成立。
    订阅类的合规风险改由 `terms_warning` / `terms_note` 承载——**是告知，不是排除**。
    """

    models: tuple[CatalogModel, ...] = field(default_factory=tuple)
    """该通道下的模型清单。
    订阅类通道若官方未公布 Token 额度（无法算等效单价）且模型无按量标准价，
    则**留空**并在 `note` 说明——不编造价格（见模块 docstring 的单价口径第 3 条）。"""


@dataclass(frozen=True)
class CatalogProvider:
    """目录内的一家厂商，含其全部接入通道。"""

    name: str
    """厂商显示名，如「月之暗面 Kimi」。通道名会在其后拼接入形态。"""

    vendor: str
    """厂商标识（分组键），控制台按它把多条通道聚成一张厂商卡片。"""

    blurb: str = ""
    """厂商级说明，展示在厂商卡片头部。"""

    channels: tuple[CatalogChannel, ...] = field(default_factory=tuple)


def channel_name(provider_name: str, ch: CatalogChannel) -> str:
    """通道在库中的显示名：厂商名 + 接入形态。

    ⚠️ **第一个参数是厂商名字符串，不是 `CatalogProvider` 对象。**
    传错不会报错——f-string 会把整个 dataclass 的 `repr` 拼进通道名，生成一条
    "`CatalogProvider(name='阿里云百炼', vendor=…) · 按量 API`" 这种**看起来像数据、
    实则污染库内记录**的名字，且因为后续匹配按名字走，会导致每次预置都匹配不上。
    这类「全程不报错的空转」正是本项目反复踩到的坑（参见 D-25 / D-29 / D-30），
    故此处在入口显式拦一道，宁可 fail fast。
    """
    if not isinstance(provider_name, str):
        raise TypeError(
            f"channel_name() 第一个参数应为厂商名 str，"
            f"收到 {type(provider_name).__name__}；请传 catalog_provider.name"
        )
    label = ACCESS_KINDS.get(ch.access_kind, ch.access_kind)
    return f"{provider_name} · {label}"[:64]


def build_remark(ch: CatalogChannel) -> str:
    """把密钥申请地址与注意事项拼成 provider.remark（控制台单字段展示，255 上限）。"""
    parts = [f"密钥申请：{ch.key_url}"]
    if ch.note:
        parts.append(ch.note)
    return "；".join(parts)[:255]


def build_terms_note(ch: CatalogChannel) -> str | None:
    """条款警示写入 provider.terms_note（TEXT，不限长——条款原文常超 255 字符）。"""
    return ch.terms_warning or None


def is_channel_routable(ch: CatalogChannel) -> bool:
    """目录侧的通道可路由判定。与 services/provider_access.py 的判定保持一致。"""
    return ch.access_kind in ROUTABLE_ACCESS_KINDS and ch.protocol in SUPPORTED_PROTOCOLS


# ---------------------------------------------------------------------------
# 订阅类通道的口径常量（避免同一句话在十几处各写一遍、逐渐走样）
# ---------------------------------------------------------------------------

_TERMS_BACKEND_FORBIDDEN = (
    "【官方条款警示】本套餐仅限在厂商官方支持的编程 / 智能体工具中**交互式**使用，"
    "不得作为应用后端、自动化脚本或批量任务的主调用通道；违规可能导致套餐停用或 Key 封禁。"
    "本网关对外提供 /v1 接口，从上游看属于应用后端——接入前请自行评估合规风险。"
)

_TERMS_KEY_ISOLATED = (
    "订阅专属 Key 与按量 API Key **完全隔离、必须配套使用**："
    "用错 Key 或端点会返回 401/403，或静默走按量计费产生意外账单。"
)


_CATALOG: tuple[CatalogProvider, ...] = (
    # ---------------------------------------------------------------- 1. DeepSeek
    CatalogProvider(
        name="DeepSeek", vendor="deepseek",
        blurb="只有按量 API，无官方订阅套餐（官方另有「批量推理」通道，走同一个 Key）。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://api.deepseek.com/v1",
                key_url="https://platform.deepseek.com/api_keys",
                note="峰谷定价：低谷时段约 5 折；输入命中缓存可低至 0.2 元/百万 token。"
                     "官方另有「批量推理」通道，走同一个 Key 与端点，价格约五折"
                     "（属结算方式差异，故不单列通道）。未查到官方订阅套餐。",
                models=(
                    CatalogModel(
                        model_name="deepseek-v4-pro", display_name="DeepSeek V4 Pro",
                        capabilities=("general", "code_generation", "complex_reasoning", "long_context"),
                        input_price=3.0, output_price=6.0, context_window=131072, priority=20,
                        price_note="取平峰未命中缓存价；低谷时段约 5 折",
                    ),
                    CatalogModel(
                        model_name="deepseek-v4-flash", display_name="DeepSeek V4 Flash",
                        capabilities=("general", "code_generation", "summarize"),
                        input_price=1.0, output_price=2.0, context_window=131072, priority=40,
                        price_note="高并发轻量版；不同渠道对 Flash 报价差异较大（0.3~1.0）",
                    ),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- 2. 阿里云百炼（通义千问）
    CatalogProvider(
        name="阿里云百炼", vendor="aliyun-bailian",
        blurb="三套**完全隔离**的体系：按量 API（sk-）、Coding Plan（sk-ws-）、"
              "Token Plan（sk-sp-）。Key 与 Base URL 必须成对使用，混用会 401/403 或静默走按量计费。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                key_url="https://bailian.console.aliyun.com/",
                note="需先在百炼控制台开通「OpenAI 兼容模式」并创建 API-KEY（sk- 前缀）。"
                     "百炼支持购买预付费额度包 / 「AI 通用型节省计划」抵扣，与按量共用同一个 Key"
                     "（属结算方式差异，故不单列通道）。Anthropic 端点为 /apps/anthropic。",
                models=(
                    CatalogModel(
                        model_name="qwen3.8-max", display_name="通义千问 Qwen3.8 Max",
                        capabilities=("general", "complex_reasoning", "long_context", "translation"),
                        input_price=4.0, output_price=12.0, context_window=131072, priority=30,
                    ),
                    CatalogModel(
                        model_name="qwen3.8-flash", display_name="通义千问 Qwen3.8 Flash",
                        capabilities=("general", "summarize", "translation", "long_context"),
                        input_price=0.8, output_price=2.7, context_window=1000000, priority=45,
                        price_note="官方口径：输入 0.8 / 输出 2.7，命中缓存 0.1 元/百万 token；"
                                   "原生 100 万上下文",
                    ),
                    CatalogModel(
                        model_name="qwen-plus", display_name="通义千问 Qwen Plus",
                        capabilities=("general", "summarize", "translation"),
                        input_price=0.8, output_price=2.0, context_window=131072, priority=60,
                    ),
                    CatalogModel(
                        model_name="qwen-long", display_name="通义千问 Qwen Long",
                        capabilities=("long_context", "summarize"),
                        input_price=0.5, output_price=2.0, context_window=1000000, priority=70,
                        price_note="超长上下文专用",
                    ),
                    CatalogModel(
                        model_name="qwen-turbo", display_name="通义千问 Qwen Turbo",
                        capabilities=("general", "summarize", "translation"),
                        input_price=0.3, output_price=0.6, context_window=131072, priority=80,
                    ),
                ),
            ),
            CatalogChannel(
                access_kind="coding_plan", protocol="openai",
                base_url="https://coding.dashscope.aliyuncs.com/v1",
                key_url="https://bailian.console.aliyun.com/",
                note="Coding Plan 专属 Key（sk-ws- 前缀）+ 该专属端点；在百炼控制台「订阅」页获取。"
                     "Anthropic 兼容端点为 https://coding.dashscope.aliyuncs.com/apps/anthropic。"
                     "⚠️ 官方未公开 Coding Plan 的完整模型清单，本目录**不猜**："
                     "填 Key 后在「模型池」页按控制台确认的 Model ID 手工添加即可。"
                     "注意部分模型名需改写（如 glm-5 写作 glm-5-0、kimi-k2.5 写作 kimi-k2-5）。",
                terms_warning=_TERMS_BACKEND_FORBIDDEN + " " + _TERMS_KEY_ISOLATED,
            ),
            CatalogChannel(
                access_kind="token_plan", protocol="openai",
                base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
                key_url="https://www.aliyun.com/benefit/scene/tokenplan",
                note="Token Plan 专属 Key（sk-sp- 前缀）+ 该专属端点；在百炼控制台"
                     "「我的订阅 → Token Plan」页获取。"
                     "Anthropic 兼容端点为 https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic。"
                     "个人版 Lite/Standard/Pro 为 5 小时 + 7 天双层限流；团队版按坐席分配 Credits。"
                     "官方列表还含 qwen3.7-max / qwen3.7-plus / qwen3.6-plus / qwen3.6-flash / "
                     "deepseek-v4.1-flash / deepseek-v3.2 / kimi-k2.5 / kimi-k2.7-code / glm-5.1 / glm-5，"
                     "因未查到可靠按量单价而未收录。",
                terms_warning=_TERMS_BACKEND_FORBIDDEN + " " + _TERMS_KEY_ISOLATED,
                models=(
                    CatalogModel(
                        model_name="qwen3.8-max", display_name="通义千问 Qwen3.8 Max（Token Plan）",
                        capabilities=("general", "complex_reasoning", "long_context", "translation"),
                        input_price=4.0, output_price=12.0, context_window=131072, priority=310,
                        price_note="订阅套餐内按 Credits 抵扣；此为该模型按量标准价，仅作成本参照",
                    ),
                    CatalogModel(
                        model_name="qwen3.8-flash", display_name="通义千问 Qwen3.8 Flash（Token Plan）",
                        capabilities=("general", "summarize", "translation", "long_context"),
                        input_price=0.8, output_price=2.7, context_window=1000000, priority=320,
                        price_note="按量标准价参照（官方口径 0.8 / 2.7）",
                    ),
                    CatalogModel(
                        model_name="deepseek-v4-pro", display_name="DeepSeek V4 Pro（百炼 Token Plan）",
                        capabilities=("general", "code_generation", "complex_reasoning", "long_context"),
                        input_price=3.0, output_price=6.0, context_window=131072, priority=330,
                        price_note="按量标准价参照",
                    ),
                    CatalogModel(
                        model_name="deepseek-v4-flash", display_name="DeepSeek V4 Flash（百炼 Token Plan）",
                        capabilities=("general", "code_generation", "summarize"),
                        input_price=1.0, output_price=2.0, context_window=131072, priority=340,
                        price_note="按量标准价参照",
                    ),
                    CatalogModel(
                        model_name="glm-5.2", display_name="智谱 GLM-5.2（百炼 Token Plan）",
                        capabilities=("general", "long_context", "summarize"),
                        input_price=4.0, output_price=16.0, context_window=1048576, priority=350,
                        price_note="按量标准价参照",
                    ),
                    CatalogModel(
                        model_name="kimi-k2.6", display_name="Kimi K2.6（百炼 Token Plan）",
                        capabilities=("general", "summarize", "translation"),
                        input_price=6.5, output_price=27.0, context_window=262144, priority=360,
                        price_note="按量标准价参照",
                    ),
                    CatalogModel(
                        model_name="MiniMax-M2.5", display_name="MiniMax M2.5（百炼 Token Plan）",
                        capabilities=("general", "complex_reasoning", "long_context"),
                        input_price=2.1, output_price=8.4, context_window=524288, priority=370,
                        price_note="按量标准价参照（官方长期五折活动，请以控制台为准）",
                    ),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- 3. 智谱 GLM
    CatalogProvider(
        name="智谱 GLM", vendor="zhipu",
        blurb="两套体系：开放平台按量 API，与 GLM Coding Plan 订阅套餐。"
              "Coding Key 与开放平台 Key 互不通用。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://open.bigmodel.cn/api/paas/v4",
                key_url="https://open.bigmodel.cn/usercenter/apikeys",
                note="注意：base_url 路径为 /api/paas/v4，末尾**不带** /v1（自动补 /v1 的客户端会 404）。"
                     "Batch 批处理走同一个 Key，对支持的文本模型约五折（属结算方式差异，故不单列通道）。",
                models=(
                    CatalogModel(
                        model_name="glm-5.3", display_name="智谱 GLM-5.3",
                        capabilities=("general", "code_generation", "complex_reasoning", "long_context"),
                        input_price=3.5, output_price=11.0, context_window=1048576, priority=30,
                        price_note="MIT 协议代理，可私有化部署",
                    ),
                    CatalogModel(
                        model_name="glm-5.2", display_name="智谱 GLM-5.2",
                        capabilities=("general", "long_context", "summarize"),
                        input_price=4.0, output_price=16.0, context_window=1048576, priority=40,
                    ),
                ),
            ),
            CatalogChannel(
                access_kind="coding_plan", protocol="openai",
                base_url="https://open.bigmodel.cn/api/coding/paas/v4",
                key_url="https://www.bigmodel.cn/glm-coding",
                note="GLM Coding Plan 专属 Key；OpenAI 兼容端点为"
                     " https://open.bigmodel.cn/api/coding/paas/v4 。"
                     "官方同时提供 Anthropic 端点 https://open.bigmodel.cn/api/anthropic"
                     "（Claude Code / Goose 用），以及 OpenAI Response 端点 https://open.bigmodel.cn/api/v1。"
                     "⚠️ 端点配错会在扣费时报「1113 余额不足」——那是套餐额度没生效、走了账号余额。"
                     "套餐设 5 小时 + 每周双层积分限额，耗尽后等下一周期，不会消耗资源包/余额。"
                     "Lite 5 小时 2000 / 周 10000 积分，Pro 12000 / 60000，Max 28000 / 140000。",
                terms_warning=_TERMS_BACKEND_FORBIDDEN + " 官方原文：「套餐额度仅限在官方支持的编码工具"
                              "和产品环境中使用；在自建应用、网站、机器人、SaaS 产品或其他场景中需要"
                              "直接调用标准 API，不能使用套餐额度。」另注：套餐不接受与他人共享。",
                models=(
                    CatalogModel(
                        model_name="glm-5.2", display_name="智谱 GLM-5.2（Coding Plan）",
                        capabilities=("general", "code_generation", "long_context", "summarize"),
                        input_price=4.0, output_price=16.0, context_window=1048576, priority=310,
                        price_note="订阅套餐内按积分抵扣；此为该模型按量标准价，仅作成本参照。"
                                   "官方建议配置为 glm-5.2[1m] 以启用长上下文",
                    ),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- 4. 月之暗面 Kimi
    CatalogProvider(
        name="月之暗面 Kimi", vendor="moonshot",
        blurb="两套体系：开放平台按量 API（api.moonshot.cn），与 Kimi Code 会员套餐"
              "（api.kimi.com/coding）。Code 专属 Key 打到开放平台端点会 401。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://api.moonshot.cn/v1",
                key_url="https://platform.moonshot.cn/console/api-keys",
                note="K3 输出价较高（100 元/百万 token），建议只用于长程代码与复杂推理，勿作默认兜底。",
                models=(
                    CatalogModel(
                        model_name="kimi-k3", display_name="Kimi K3",
                        capabilities=("general", "complex_reasoning", "long_context"),
                        input_price=20.0, output_price=100.0, context_window=1048576, priority=20,
                        price_note="输入取未命中缓存价；命中缓存 2 元/百万 token",
                    ),
                    CatalogModel(
                        model_name="kimi-k2.7-code", display_name="Kimi K2.7 Code",
                        capabilities=("code_generation", "general"),
                        input_price=6.5, output_price=27.0, context_window=262144, priority=40,
                        price_note="输入取未命中缓存价；命中缓存 1.3 元/百万 token",
                    ),
                    CatalogModel(
                        model_name="kimi-k2.6", display_name="Kimi K2.6",
                        capabilities=("general", "summarize", "translation"),
                        input_price=6.5, output_price=27.0, context_window=262144, priority=50,
                    ),
                ),
            ),
            CatalogChannel(
                access_kind="coding_plan", protocol="openai",
                base_url="https://api.kimi.com/coding/v1",
                key_url="https://www.kimi.com/code",
                note="Kimi Code 会员专属 Key（在 kimi.com/code 控制台创建，最多 5 个、仅显示一次）。"
                     "OpenAI 兼容端点为 /coding/v1；Anthropic 兼容端点为 https://api.kimi.com/coding/ 。"
                     "并发上限 30；档位 Moderato / Allegretto / Allegro / Vivace 按周刷新额度。"
                     "模型 ID 为 kimi-for-coding（K2.8 Preview，全档可用）与"
                     " kimi-for-coding-highspeed（K2.7 Code HighSpeed，需 Allegretto 及以上；"
                     "写错会**静默回退**到标准版而不报错）。"
                     "⚠️ 官方未公布这两个 ID 的按量单价，且套餐按请求次数而非 Token 限流，"
                     "无法折算等效单价，故本目录**不收录模型**——填 Key 后在「模型池」页手工添加。",
                terms_warning="【官方条款警示】Kimi 官方原文：「使用时请保持工具的真实身份标识，"
                              "篡改客户端标识（User-Agent）将被视为违规，可能导致会员权益暂停」；"
                              "并明确「如需在自己的产品中调用大模型能力……请访问 Kimi 开放平台」。"
                              "会员权益专为编程场景设计，作为对外网关后端属违规使用。",
            ),
        ),
    ),
    # ---------------------------------------------------------------- 5. 火山方舟（豆包）
    CatalogProvider(
        name="火山方舟（豆包）", vendor="volcengine",
        blurb="一个 Key 可调多家模型；另有 Coding Plan 订阅套餐（模型由控制台统一切换）"
              "与 token 资源包。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                key_url="https://console.volcengine.com/ark",
                note="方舟部分模型需先创建「推理接入点」，此时 model 字段要填接入点 ID（ep-xxxx）"
                     "而非模型名；请在控制台确认后再启用。"
                     "官方提供 token 资源包（预付费）与按量后付费两种结算，资源包与按量共用同一个 Key"
                     "（属结算方式差异，故不单列通道）。",
                models=(
                    CatalogModel(
                        model_name="doubao-seed-2-0-pro", display_name="豆包 Seed 2.0 Pro",
                        capabilities=("general", "complex_reasoning", "translation"),
                        input_price=3.2, output_price=16.0, context_window=262144, priority=30,
                    ),
                    CatalogModel(
                        model_name="doubao-seed-2-0-lite", display_name="豆包 Seed 2.0 Lite",
                        capabilities=("general", "summarize", "translation"),
                        input_price=0.6, output_price=3.6, context_window=131072, priority=60,
                    ),
                    CatalogModel(
                        model_name="doubao-seed-2-0-mini", display_name="豆包 Seed 2.0 Mini",
                        capabilities=("general", "summarize"),
                        input_price=0.43, output_price=4.03, context_window=131072, priority=70,
                    ),
                ),
            ),
            CatalogChannel(
                access_kind="coding_plan", protocol="openai",
                base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
                key_url="https://www.volcengine.com/activity/codingplan",
                note="Coding Plan 专属 Key；OpenAI 兼容端点为 /api/coding/v3，"
                     "Anthropic 兼容端点为 /api/coding（Claude Code 用）。"
                     "⚠️ 官方特别提示：**不要**用标准端点 /api/v3 —— 请求不会消耗套餐额度，"
                     "反而会按量额外计费。"
                     "档位 Lite（每 5 小时约 1200 次、每月约 18000 次）与 Pro（Lite 的 5 倍）。"
                     "模型支持两种配置方式：填具体 Model Name 实时切换，或填 ark-code-latest "
                     "由控制台统一切换（后者更稳妥，接入点 ID 仍在控制台管理）。"
                     "官方套餐页还列出 Doubao-Seed-2.1-turbo、kimi-k2.5、gpt-oss-120b、MiniMax-M3 等，"
                     "因未查到可靠按量单价而未收录。",
                terms_warning="【官方条款警示】火山引擎官方原文：「在非 AI 工具中使用方舟 Coding Plan / "
                              "Agent Plan 权益对应的 Base URL 和 API Key 有可能被识别为滥用/违规，"
                              "会导致订阅停用或账号封禁。」"
                              "另：套餐额度仅在支持的 Coding 工具中生效，不能用于 API 调用。",
                models=(
                    CatalogModel(
                        model_name="ark-code-latest", display_name="方舟 Coding Plan Auto",
                        capabilities=("general", "code_generation", "complex_reasoning", "long_context"),
                        input_price=3.0, output_price=6.0, context_window=1048576, priority=310,
                        price_note="由控制台统一切换实际模型；此价取套餐内 deepseek-v4-pro 的按量标准价"
                                   "作成本参照（官方声明套餐按请求次数限流，无 Token 单价）",
                    ),
                    CatalogModel(
                        model_name="deepseek-v4-pro", display_name="DeepSeek V4 Pro（方舟 Coding Plan）",
                        capabilities=("general", "code_generation", "complex_reasoning", "long_context"),
                        input_price=3.0, output_price=6.0, context_window=1048576, priority=330,
                        price_note="官方套餐支持 1M 上下文；按量标准价参照",
                    ),
                    CatalogModel(
                        model_name="deepseek-v4-flash", display_name="DeepSeek V4 Flash（方舟 Coding Plan）",
                        capabilities=("general", "code_generation", "summarize"),
                        input_price=1.0, output_price=2.0, context_window=1048576, priority=340,
                        price_note="按量标准价参照",
                    ),
                    CatalogModel(
                        model_name="glm-5.3", display_name="智谱 GLM-5.3（方舟 Coding Plan）",
                        capabilities=("general", "code_generation", "complex_reasoning", "long_context"),
                        input_price=3.5, output_price=11.0, context_window=1048576, priority=350,
                        price_note="按量标准价参照",
                    ),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- 6. 百度千帆（文心）
    CatalogProvider(
        name="百度千帆（文心）", vendor="baidu-qianfan",
        blurb="使用新版千帆 v2 端点，Bearer 直传鉴权。"
              "另有 Token Plan 个人版 / 企业版订阅，专属 Key 与后付费体系完全隔离。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://qianfan.baidubce.com/v2",
                key_url="https://console.bce.baidu.com/iam/#/iam/apikey/list",
                note="使用新版千帆 v2 端点；密钥在百度云 IAM 的 API Key 页面创建（Bearer 直传，无需 access_token 换取）。"
                     "另支持 Tokens 资源包（先消耗资源包余量、用完自动切按量）与 TPM/RPM 配额预付费"
                     "（属结算方式差异，故不单列通道）。",
                models=(
                    CatalogModel(
                        model_name="ernie-4.5", display_name="文心 ERNIE 4.5",
                        capabilities=("general", "complex_reasoning", "translation"),
                        input_price=8.0, output_price=24.0, context_window=131072, priority=40,
                        price_note="官方口径；ernie-5.0 尚未查到稳定公开价，故未收录",
                    ),
                ),
            ),
            CatalogChannel(
                access_kind="token_plan", protocol="openai",
                base_url="https://qianfan.baidubce.com/v2/tokenplan/personal",
                key_url="https://console.bce.baidu.com/qianfan/resource/token-plan",
                note="Token Plan 个人版专属 Key + 专属端点（与千帆常规服务不同）。"
                     "企业版端点为 https://qianfan.baidubce.com/v2/tokenplan/team 。"
                     "Anthropic 兼容端点：个人版 /anthropic/tokenplan/personal，企业版 /anthropic/tokenplan/team 。"
                     "个人版四档 Mini 1000 万 / Lite 4200 万 / Pro 2.3 亿 / Max 7 亿 Token，"
                     "按通用 Token 统一抵扣（不区分模型倍率、不区分输入输出与缓存命中），"
                     "并已取消原 Coding Plan 的三层滑动窗口限流。"
                     "⚠️ 官方未公开套餐价格，无法折算等效单价，故本目录**不收录模型**；"
                     "官方列表含 ernie-5.1 / glm-5.2 / glm-5.1 / kimi-k2.6 / deepseek-v4-pro / "
                     "deepseek-v4-flash，填 Key 后可在「模型池」页手工添加。",
                terms_warning=_TERMS_BACKEND_FORBIDDEN + " 官方原文：「使用范围：仅限在兼容的 AI 编程和"
                              "智能体工具中交互式使用，不可用于自动化脚本或应用后端。违规使用可能导致"
                              "订阅暂停或 API Key 封禁。」",
            ),
        ),
    ),
    # ---------------------------------------------------------------- 7. 腾讯混元
    CatalogProvider(
        name="腾讯混元", vendor="tencent-hunyuan",
        blurb="按量 API 走 hunyuan.cloud.tencent.com；订阅类走 lkeap.cloud.tencent.com，"
              "分 Coding Plan 与 Token Plan（通用版 / Hy 版）两条线。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://api.hunyuan.cloud.tencent.com/v1",
                key_url="https://console.cloud.tencent.com/hunyuan/api-key",
                note="混元已提供 OpenAI 兼容接口，可直接用 Bearer 鉴权。"
                     "注意：混元生文接口默认并发限制 5，限额由主子账号共享。",
                models=(
                    CatalogModel(
                        model_name="hunyuan-a13b", display_name="混元 Hunyuan-A13B",
                        capabilities=("general", "summarize", "translation"),
                        input_price=0.5, output_price=2.0, context_window=131072, priority=60,
                        price_note="腾讯云刊例价",
                    ),
                    CatalogModel(
                        model_name="hunyuan-hy3", display_name="混元 Hy3",
                        capabilities=("general", "code_generation", "complex_reasoning"),
                        input_price=1.0, output_price=4.0, context_window=262144, priority=30,
                        price_note="官方发布口径：输入 1 元、输出 4 元、命中缓存 0.25 元；"
                                   "模型 ID 请以控制台为准",
                    ),
                ),
            ),
            CatalogChannel(
                access_kind="coding_plan", protocol="openai",
                base_url="https://api.lkeap.cloud.tencent.com/coding/v3",
                key_url="https://buy.cloud.tencent.com/hunyuan",
                note="Coding Plan 专属 Key（在 TokenHub 控制台的 API Key 管理页获取）；"
                     "OpenAI 兼容端点为 /coding/v3，Anthropic 兼容端点为 /coding/anthropic。"
                     "套餐由 CodeBuddy 等工具使用；官方口径：额度用完即停，**不会自动转按量计费**。"
                     "⚠️ 官方未公布套餐内模型的 Token 单价，故本目录**不收录模型**；"
                     "常见 Model ID 有 tc-code-latest（Auto）、glm-5、kimi-k2.5、minimax-m2.5 等，"
                     "填 Key 后可在「模型池」页手工添加。",
                terms_warning="【官方条款警示】腾讯云官方原文：「禁止用于应用程序后端：不能作为生产环境"
                              "后端服务的主调用通道」；「禁止用于自动化脚本：定时任务、定时跑批、"
                              "CI/CD 流水线内的批量调用」；「禁止非交互式批量调用：离线评测、"
                              "批量数据生成等」。仅限交互式 AI 工具使用。",
            ),
            CatalogChannel(
                access_kind="token_plan", protocol="openai",
                base_url="https://api.lkeap.cloud.tencent.com/plan/v3",
                key_url="https://cloud.tencent.com/document/product/1823/130060",
                note="通用 Token Plan 专属 Key + 专属端点；"
                     "Anthropic 兼容端点为 /plan/anthropic。"
                     "四档：Lite 3500 万 Token / 39 元，Standard 1 亿 / 99 元，"
                     "Pro 3.2 亿 / 299 元，Max 6.5 亿 / 599 元（另有更便宜的 Hy 版）。"
                     "官方声明按通用 Token 统一抵扣、输入输出不区分，因此本通道所有模型"
                     "共用 Max 档折算的等效单价 599 ÷ 6.5 亿 ≈ 0.92 元/百万 token。"
                     "企业版支持自定义月预算（1000~20000 元，步长 1000 元）与多 Key 配额分配。",
                terms_warning="【官方条款警示】腾讯云官方原文：「禁止用于应用程序后端：不能作为生产环境"
                              "后端服务的主调用通道」；「禁止用于自动化脚本：定时任务、定时跑批、"
                              "CI/CD 流水线内的批量调用」。套餐用完即停、不会自动转按量计费。",
                models=(
                    CatalogModel(
                        model_name="tc-code-latest", display_name="腾讯云 Token Plan Auto",
                        capabilities=("general", "code_generation", "complex_reasoning", "long_context"),
                        input_price=0.92, output_price=0.92, context_window=262144, priority=310,
                        price_note="Auto 智能路由，模型由系统自动匹配；价取 Max 档等效单价",
                    ),
                    CatalogModel(
                        model_name="hunyuan-2.0-instruct", display_name="腾讯混元 HY 2.0 Instruct",
                        capabilities=("general", "summarize", "translation"),
                        input_price=0.92, output_price=0.92, context_window=262144, priority=360,
                        price_note="套餐等效单价（通用 Token 统一抵扣，输入输出同价）",
                    ),
                    CatalogModel(
                        model_name="hunyuan-2.0-thinking", display_name="腾讯混元 HY 2.0 Think",
                        capabilities=("general", "complex_reasoning"),
                        input_price=0.92, output_price=0.92, context_window=262144, priority=370,
                        price_note="套餐等效单价（通用 Token 统一抵扣，输入输出同价）",
                    ),
                    CatalogModel(
                        model_name="glm-5", display_name="智谱 GLM-5（腾讯云 Token Plan）",
                        capabilities=("general", "long_context", "summarize"),
                        input_price=0.92, output_price=0.92, context_window=262144, priority=380,
                        price_note="套餐等效单价（一套订阅横跨多家厂商模型，额度共享）",
                    ),
                    CatalogModel(
                        model_name="glm-5.1", display_name="智谱 GLM-5.1（腾讯云 Token Plan）",
                        capabilities=("general", "long_context", "summarize"),
                        input_price=0.92, output_price=0.92, context_window=262144, priority=390,
                        price_note="套餐等效单价（一套订阅横跨多家厂商模型，额度共享）",
                    ),
                    CatalogModel(
                        model_name="kimi-k2.5", display_name="Kimi K2.5（腾讯云 Token Plan）",
                        capabilities=("general", "long_context", "summarize"),
                        input_price=0.92, output_price=0.92, context_window=262144, priority=400,
                        price_note="套餐等效单价（一套订阅横跨多家厂商模型，额度共享）",
                    ),
                    CatalogModel(
                        model_name="minimax-m2.5", display_name="MiniMax M2.5（腾讯云 Token Plan）",
                        capabilities=("general", "complex_reasoning", "long_context"),
                        input_price=0.92, output_price=0.92, context_window=524288, priority=410,
                        price_note="套餐等效单价（一套订阅横跨多家厂商模型，额度共享）",
                    ),
                    CatalogModel(
                        model_name="minimax-m2.7", display_name="MiniMax M2.7（腾讯云 Token Plan）",
                        capabilities=("general", "complex_reasoning", "long_context"),
                        input_price=0.92, output_price=0.92, context_window=524288, priority=420,
                        price_note="套餐等效单价（一套订阅横跨多家厂商模型，额度共享）",
                    ),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- 8. MiniMax
    CatalogProvider(
        name="MiniMax", vendor="minimax",
        blurb="base_url 为 api.minimaxi.com（旧域名已迁移）。"
              "按量 Key（sk-api-）与订阅 Key（sk-cp-）不通用。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://api.minimaxi.com/v1",
                key_url="https://platform.minimaxi.com/user-center/basic-information/interface-key",
                note="base_url 为 api.minimaxi.com（旧域名为 api.minimax.chat，已迁移）。"
                     "Anthropic 兼容端点为 https://api.minimaxi.com/anthropic 。"
                     "国际站域名是 api.minimax.io，与国内站 Key 不互通。",
                models=(
                    CatalogModel(
                        model_name="MiniMax-M2.5", display_name="MiniMax M2.5",
                        capabilities=("general", "complex_reasoning", "long_context"),
                        input_price=2.1, output_price=8.4, context_window=524288, priority=40,
                        price_note="该价位为平台侧快照，官方长期五折活动，请以控制台为准",
                    ),
                ),
            ),
            CatalogChannel(
                access_kind="token_plan", protocol="openai",
                base_url="https://api.minimaxi.com/v1",
                key_url="https://platform.minimaxi.com/subscribe/token-plan",
                note="Token Plan 订阅 Key（sk-cp- 前缀）走的是**与按量相同的端点** /v1，"
                     "由 Key 前缀区分计费方式——这与其它厂商「专属端点」的做法不同，"
                     "所以两个通道 base_url 相同，靠 Key 区分。"
                     "官方推荐 Anthropic 端点 https://api.minimaxi.com/anthropic 。"
                     "档位 Plus ¥49/月（6 亿 token）、Max ¥119/月（18 亿 token）、"
                     "Ultra ¥469/月（55 亿 token）；文本 / 图像 / 语音共享同一额度池。",
                terms_warning="【官方条款警示】Token Plan 订阅 Key 与按量 API Key **不通用**"
                              "（前者 sk-cp-、后者 sk-api-），用错会鉴权失败或走错计费。"
                              "套餐面向个人交互式开发与编码 Agent 场景（官方并发建议 3~7 个 Agent），"
                              "作为对外网关后端不在官方支持范围内。",
                models=(
                    CatalogModel(
                        model_name="MiniMax-M2.5", display_name="MiniMax M2.5（Token Plan）",
                        capabilities=("general", "complex_reasoning", "long_context"),
                        input_price=0.082, output_price=0.082, context_window=524288, priority=310,
                        price_note="套餐等效单价：Plus ¥49 ÷ 6 亿 token ≈ 0.082 元/百万"
                                   "（文本/图像/语音共享额度，输入输出统一抵扣）",
                    ),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- 9. 零一万物
    CatalogProvider(
        name="零一万物", vendor="lingyiwanwu",
        blurb="平台仅列出少量在售模型，其余 Yi 系列已下线；未查到官方订阅套餐。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://api.lingyiwanwu.com/v1",
                key_url="https://platform.lingyiwanwu.com/apikeys",
                note="该平台仅列出少量在售模型，其余 Yi 系列已下线，请勿沿用旧文档的模型名。"
                     "未查到官方订阅套餐或资源包。",
                models=(
                    CatalogModel(
                        model_name="yi-lightning", display_name="零一万物 Yi Lightning",
                        capabilities=("general", "summarize", "translation"),
                        input_price=0.99, output_price=0.99, context_window=16384, priority=70,
                        price_note="输入输出合并计价（部分场景按 0.99 元/百万 token 统一计费）",
                    ),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- 10. 阶跃星辰
    CatalogProvider(
        name="阶跃星辰", vendor="stepfun",
        blurb="Flash 系列定位轻量 Agent 工作流；另有 Step Plan 订阅套餐"
              "（国外站 api.stepfun.ai，国内站 api.stepfun.com）。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://api.stepfun.com/v1",
                key_url="https://platform.stepfun.com/interface-key",
                note="Flash 系列定位轻量 Agent 工作流，响应快、单价低。"
                     "Anthropic 兼容端点见官方文档。",
                models=(
                    CatalogModel(
                        model_name="step-3.7-flash", display_name="阶跃 Step 3.7 Flash",
                        capabilities=("general", "code_generation", "summarize"),
                        input_price=1.35, output_price=8.1, context_window=262144, priority=50,
                        price_note="输入取未命中缓存价；命中缓存 0.27 元/百万 token",
                    ),
                    CatalogModel(
                        model_name="step-3.5-flash", display_name="阶跃 Step 3.5 Flash",
                        capabilities=("general", "summarize"),
                        input_price=0.7, output_price=2.1, context_window=262144, priority=70,
                        price_note="输入取未命中缓存价；命中缓存 0.14 元/百万 token",
                    ),
                ),
            ),
            CatalogChannel(
                access_kind="token_plan", protocol="openai",
                base_url="https://api.stepfun.com/step_plan/v1",
                key_url="https://platform.stepfun.com/docs/zh/stepplan/quick-start",
                note="Step Plan 订阅专属端点（国内站）。"
                     "OpenAI 兼容为 /step_plan/v1，Anthropic 兼容为 /step_plan 。"
                     "国际站对应 https://api.stepfun.ai/step_plan/v1 。"
                     "⚠️ 不要把完整的 /v1/messages 请求路径粘进 Base URL。"
                     "档位 Flash Mini / Plus / Pro / Max，按套餐月 Credit 额度计，"
                     "与账号余额是**两套体系**（套餐额度不扣余额）。"
                     "官方未公布各档 Token 额度，故模型单价取按量标准价作参照。",
                terms_warning=_TERMS_BACKEND_FORBIDDEN + " 官方口径：Step Plan 是「面向受支持的模型与"
                              "工具集成的订阅接入计划」，账号余额与套餐额度相互独立。",
                models=(
                    CatalogModel(
                        model_name="step-3.7-flash", display_name="阶跃 Step 3.7 Flash（Step Plan）",
                        capabilities=("general", "code_generation", "summarize"),
                        input_price=1.35, output_price=8.1, context_window=262144, priority=310,
                        price_note="官方推荐的套餐验证模型；按量标准价参照",
                    ),
                    CatalogModel(
                        model_name="step-3.5-flash", display_name="阶跃 Step 3.5 Flash（Step Plan）",
                        capabilities=("general", "summarize"),
                        input_price=0.7, output_price=2.1, context_window=262144, priority=320,
                        price_note="按量标准价参照",
                    ),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- 11. 百川智能
    CatalogProvider(
        name="百川智能", vendor="baichuan",
        blurb="采用输入输出合并计价的单一价格；未查到官方订阅套餐。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://api.baichuan-ai.com/v1",
                key_url="https://platform.baichuan-ai.com/console/apikey",
                note="采用输入输出合并计价的单一价格；模型名区分大小写（如 Baichuan4-Turbo）。"
                     "未查到官方订阅套餐或资源包。",
                models=(
                    CatalogModel(
                        model_name="Baichuan4-Turbo", display_name="百川 Baichuan4 Turbo",
                        capabilities=("general", "code_generation", "summarize"),
                        input_price=15.0, output_price=15.0, context_window=32768, priority=60,
                        price_note="输入输出合并计价",
                    ),
                    CatalogModel(
                        model_name="Baichuan4-Air", display_name="百川 Baichuan4 Air",
                        capabilities=("general", "summarize", "translation"),
                        input_price=0.98, output_price=0.98, context_window=32768, priority=80,
                        price_note="输入输出合并计价",
                    ),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- 12. 硅基流动
    CatalogProvider(
        name="硅基流动", vendor="siliconflow",
        blurb="聚合平台：一个 Key 可用多家开源模型；只有资源包，无订阅套餐。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://api.siliconflow.cn/v1",
                key_url="https://cloud.siliconflow.cn/account/ak",
                note="聚合平台：一个 Key 可用多家开源模型。模型名必须带组织前缀"
                     "（如 deepseek-ai/DeepSeek-V4-Flash），漏写前缀会 404。"
                     "平台提供 Token 资源包（在「余额充值 → 资源包」兑换，全额抵扣缓存命中/输入/输出 token）"
                     "与会员赠量，与按量共用同一个 Key（属结算方式差异，故不单列通道）；"
                     "未查到官方订阅套餐。",
                models=(
                    CatalogModel(
                        model_name="deepseek-ai/DeepSeek-V4-Flash", display_name="硅基流动 DeepSeek V4 Flash",
                        capabilities=("general", "code_generation", "summarize"),
                        input_price=1.0, output_price=2.0, context_window=1048576, priority=40,
                    ),
                    CatalogModel(
                        model_name="zai-org/GLM-5.2", display_name="硅基流动 GLM-5.2",
                        capabilities=("general", "code_generation", "long_context"),
                        input_price=8.0, output_price=28.0, context_window=1048576, priority=40,
                    ),
                    CatalogModel(
                        model_name="moonshotai/Kimi-K2.7-Code", display_name="硅基流动 Kimi K2.7 Code",
                        capabilities=("code_generation", "general"),
                        input_price=6.5, output_price=27.0, context_window=262144, priority=50,
                    ),
                    CatalogModel(
                        model_name="Qwen/Qwen3.6-35B-A3B", display_name="硅基流动 Qwen3.6 35B A3B",
                        capabilities=("general", "summarize", "translation"),
                        input_price=1.8, output_price=10.8, context_window=262144, priority=60,
                    ),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- 13. 小米 MiMo
    CatalogProvider(
        name="小米 MiMo", vendor="xiaomi-mimo",
        blurb="两条互不相通的通道：按量 API（sk- 前缀，api.xiaomimimo.com）与 "
              "Token Plan 订阅（tp- 前缀，token-plan-cn.xiaomimimo.com），Key 与端点必须配套。"
              "旗舰 mimo-v2.6-pro 原生全模态、标称 100 万上下文，命中缓存输入低至 0.025 元/百万 token。",
        channels=(
            CatalogChannel(
                access_kind="api", protocol="openai",
                base_url="https://api.xiaomimimo.com/v1",
                key_url="https://platform.xiaomimimo.com/#/console/api-keys",
                note="鉴权头两种都接受：官方 Python/Anthropic SDK 走 `Authorization: Bearer sk-xxxxx`，"
                     "curl 示例走 `api-key: sk-xxxxx` —— 本网关适配器发前者，可直接用。"
                     "Anthropic 兼容端点为 https://api.xiaomimimo.com/anthropic（本目录只取 OpenAI 兼容端点）。"
                     "批量推理另有**专属端点** https://batch-api-cn.xiaomimimo.com/v1（同一 sk- Key、"
                     "约为实时价 5 折）—— 端点与同步接口不同，但批量接口通常为异步提交/轮询语义，"
                     "与本网关的同步 /chat/completions 调用不一定兼容，故**未单列通道**，"
                     "启用前请先确认该端点是否接受同步调用。"
                     "思考模式下模型在返回 tool_calls 的同时返回 reasoning_content，"
                     "官方建议后续请求保留历史 reasoning_content 以获得最佳表现。"
                     "官方称 MiMo-V2.6-Pro-UltraSpeed 定价为 Pro 的 10 倍，但未查到公开单价，"
                     "故不收录；填 Key 后可在「模型池」页手工添加。"
                     "夜间（北京时间 00:00-08:00）消耗按 0.8 倍计。",
                models=(
                    CatalogModel(
                        model_name="mimo-v2.6-pro", display_name="小米 MiMo V2.6 Pro",
                        capabilities=("general", "code_generation", "complex_reasoning", "long_context"),
                        input_price=3.0, output_price=6.0, context_window=1048576, priority=25,
                        price_note="官方口径（2026-09 发布，与 V2.5 系列同价）：未命中缓存输入 3 元、"
                                   "输出 6 元、命中缓存输入 0.025 元/百万 token；原生全模态，"
                                   "标称 100 万上下文（本目录记 1048576）",
                    ),
                    CatalogModel(
                        model_name="mimo-v2.6-flash", display_name="小米 MiMo V2.6 Flash",
                        capabilities=("general", "summarize", "translation", "long_context"),
                        input_price=1.0, output_price=2.0, context_window=1048576, priority=42,
                        price_note="官方口径：未命中缓存输入 1 元、输出 2 元、"
                                   "命中缓存输入 0.02 元/百万 token",
                    ),
                ),
            ),
            CatalogChannel(
                access_kind="token_plan", protocol="openai",
                base_url="https://token-plan-cn.xiaomimimo.com/v1",
                key_url="https://platform.xiaomimimo.com/#/token-plan",
                note="Token Plan 专属 Key（个人版 tp-xxxxx / 团队版 ttp-xxxxx）+ 专属端点。"
                     "订阅与取 Key 均在控制台：https://platform.xiaomimimo.com/#/console/plan-manage 。"
                     "多集群端点可换：新加坡 token-plan-sgp.xiaomimimo.com、"
                     "欧洲 token-plan-ams.xiaomimimo.com（Anthropic 兼容端点把 /v1 换成 /anthropic）。"
                     "个人版四档（月度）：Lite 39 元/41 亿 Credits、Standard 99 元/110 亿、"
                     "Pro 329 元/380 亿、Max 659 元/820 亿；年度套餐额度约为月度的 12 倍。"
                     "额度按 Credits 折算，官方语言模型口径（每 token 消耗 Credits）："
                     "mimo-v2.6-pro 输入命中缓存 2.5 / 未命中 300 / 输出 600；"
                     "mimo-v2.6-flash 2 / 100 / 200。"
                     "另有 ASR（30M Credits/小时音频）与 TTS 系列（限时免费、不消耗额度）——"
                     "非 Chat Completions 语义，本目录不收录。"
                     "⚠️ mimo-v2.5-pro 与 mimo-v2.5 官方公告将于 2026-10-21 下线，故未收录。"
                     "夜间（北京时间 00:00-08:00）消耗按 0.8 倍计。",
                terms_warning="【官方条款警示】小米官方原文：「Token Plan 套餐额度仅可在编程工具"
                              "（如 OpenClaw、OpenCode 等）中使用，禁止以 API 调用的形式用于自动化脚本、"
                              "自定义应用程序后端等明显非 Coding 场景的请求行为」；"
                              "「若使用套餐对应的 API Key 进行超出许可范围的调用，将被视为违规或滥用行为，"
                              "平台有权对相关订阅采取暂停服务、封禁 API Key 等处理措施」。"
                              "另须注意：套餐额度耗尽即停服，**不会自动转按量计费**；"
                              "订阅一经购买不支持退款，未用完额度亦不退费。",
                models=(
                    CatalogModel(
                        model_name="mimo-v2.6-pro", display_name="小米 MiMo V2.6 Pro（Token Plan）",
                        capabilities=("general", "code_generation", "complex_reasoning", "long_context"),
                        input_price=2.41, output_price=4.82, context_window=1048576, priority=310,
                        price_note="Max 档等效单价：659 元 ÷ 820 亿 Credits ⇒ 1 Credit ≈ 8.04e-9 元；"
                                   "未命中输入 300 Credits/token ⇒ 2.41 元/百万 token，"
                                   "输出 600 Credits/token ⇒ 4.82 元/百万 token。"
                                   "**非官方报价**，仅作 L3 成本因子参照",
                    ),
                    CatalogModel(
                        model_name="mimo-v2.6-flash", display_name="小米 MiMo V2.6 Flash（Token Plan）",
                        capabilities=("general", "summarize", "translation", "long_context"),
                        input_price=0.80, output_price=1.61, context_window=1048576, priority=320,
                        price_note="Max 档等效单价：未命中输入 100 Credits/token ⇒ 0.80 元/百万 token，"
                                   "输出 200 Credits/token ⇒ 1.61 元/百万 token。"
                                   "**非官方报价**，仅作 L3 成本因子参照",
                    ),
                ),
            ),
        ),
    ),
)

CATALOG: tuple[CatalogProvider, ...] = _CATALOG
"""对外暴露的厂商目录。"""


def catalog_provider_count() -> int:
    return len(CATALOG)


def catalog_channel_count() -> int:
    return sum(len(p.channels) for p in CATALOG)


def catalog_model_count() -> int:
    return sum(len(c.models) for p in CATALOG for c in p.channels)


def catalog_subscription_channel_count() -> int:
    """订阅类通道数（coding_plan + token_plan），用于文档与验证脚本口径统一。"""
    return sum(1 for p in CATALOG for c in p.channels
               if c.access_kind in ("coding_plan", "token_plan"))


def find_catalog_provider(name: str) -> CatalogProvider | None:
    """按厂商名查目录（精确匹配，大小写无关）。"""
    target = name.strip().lower()
    for p in CATALOG:
        if p.name.strip().lower() == target:
            return p
    return None
