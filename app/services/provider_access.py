"""厂商可用性判定：一个模型能否真正被调用，取决于它的厂商「通道」是否可用且被支持。

闸门
----
一条 provider 记录 = 一条**接入通道**。一个模型要进入路由候选池，必须同时满足：

  1. **形态被支持**：`access_kind` 在 ROUTABLE_ACCESS_KINDS 内。
     目前该集合是**全部形态**（api / package / batch / coding_plan / token_plan）——
     订阅类套餐（Coding Plan、Token Plan）也已纳入路由，使用者有权使用自己付费的额度。
     代价是必须知情：这类套餐的厂商官方条款普遍限定「仅可在官方支持的工具中交互式使用，
     不得作为应用后端」，原文落在 `provider.terms_note`，控制台以警示条呈现。
  2. **协议被支持**：`protocol` 必须有已实现的适配器。现在只有 `openai`。
     登记一个没有适配器的协议，等于在候选池里放一批必然失败的模型。
     厂商若同时提供 OpenAI / Anthropic 双端点，目录一律取 OpenAI 端点。
  3. **密钥可用**：能解密且非空白。

为什么第 3 道（密钥）放在最后
------------------------------
目录预置的通道天然处于「形态可能不支持 + 密钥一定没配」的状态。
若先报「密钥未配置」，使用者会去填 Key；填完发现还是调不通——
这正是 D-28 那类「错误信息把人引向错误方向」的毛病。
所以**不可通过配置解决的问题要先报**，可配置解决的后报。

关于 `has_usable_key`（缺陷 D-25）
----------------------------------
候选池此前只按 `Model.enabled` 过滤，**不看厂商状态**。在只有零星手工录入厂商时，
这个问题不显形；一旦内置厂商目录把通道全部预置进库，库里就会长期存在
大批「模型已启用、但通道还没填密钥」的条目。若不做校验，路由会照常选中它们，
然后在调用阶段必然失败（解密密文失败 → 走降级 → 最终 502）——对外表现为
**随机 502 且日志里全是 fallback**。使用者的真实处境只是「还没填那个 Key」，
系统却像坏了一样。

所以「通道已接入」必须是一条**进入候选池的前置条件**，而不是调用失败后的补救。

订阅类套餐纳入路由后的额外注意事项
----------------------------------
订阅制**没有 token 单价**（包月额度 / Credits / 请求次数限流）。
因此它们的模型单价一律是「成本参照值」而非真实边际成本，
绝不能填 0——填 0 会在 L3 成本因子上拿满分，使条款受限的通道长期霸占路由。
订阅通道的同名模型也刻意给**更大的 priority 数值**，让按量 API 在同价时优先。
详见 `app/data/provider_catalog.py` 模块 docstring 的「单价口径」。
"""
from app.core.crypto import decrypt_api_key
from app.data.provider_catalog import (
    ACCESS_KINDS,
    PROTOCOLS,
    ROUTABLE_ACCESS_KINDS,
    SUPPORTED_PROTOCOLS,
)


def has_usable_key(encrypted: str | None) -> bool:
    """密钥是否真正可用：能解密且非空白。

    目录预置的厂商写的是占位符（`ENC_PLACEHOLDER_*`），解密必然抛 ValueError——
    这与「已录入真实密钥」在本函数中天然区分开，无需额外加标记字段。
    """
    if not encrypted:
        return False
    try:
        return bool(decrypt_api_key(encrypted).strip())
    except ValueError:
        return False


def access_kind_of(provider) -> str:
    """接入形态；老数据（迁移前录入）没有该字段时视为按量 API。"""
    return getattr(provider, "access_kind", None) or "api"


def protocol_of(provider) -> str:
    return getattr(provider, "protocol", None) or "openai"


def access_kind_label(provider) -> str:
    return ACCESS_KINDS.get(access_kind_of(provider), access_kind_of(provider))


def protocol_label(provider) -> str:
    return PROTOCOLS.get(protocol_of(provider), protocol_of(provider))


def is_channel_supported(provider) -> bool:
    """通道形态与协议是否被本系统支持。与密钥、启用状态无关。"""
    return (access_kind_of(provider) in ROUTABLE_ACCESS_KINDS
            and protocol_of(provider) in SUPPORTED_PROTOCOLS)


def is_provider_usable(provider) -> bool:
    """是否「已接入」：已启用 且 密钥可用。

    刻意**不含**形态/协议判断——界面上「已接入」指的是凭证配好了，
    与「能不能参与路由」是两件事，混在一起会让使用者看不懂状态。
    """
    if provider is None or not getattr(provider, "enabled", False):
        return False
    return has_usable_key(getattr(provider, "api_key_encrypted", None))


def is_provider_routable(provider) -> bool:
    """是否真正能进候选池：已接入 且 形态/协议被支持。"""
    return is_provider_usable(provider) and is_channel_supported(provider)


def routable_blockers(provider) -> list[str]:
    """列出「为什么这条通道不参与路由」，用于界面直接展示。

    空列表 = 形态与协议都没问题。返回的是**配置无法解决**的原因，
    所以与密钥是否配置无关——避免把使用者引向「去填个 Key 试试」。

    订阅类套餐已全部纳入 ROUTABLE_ACCESS_KINDS，所以正常情况下这里恒为空；
    它保留的意义是：一旦出现目录之外的新形态（或未来收紧了某个形态的支持），
    归因链路依然成立，不需要改动调用方。
    """
    out: list[str] = []
    kind = access_kind_of(provider)
    if kind not in ROUTABLE_ACCESS_KINDS:
        out.append(f"接入方式「{ACCESS_KINDS.get(kind, kind)}」不在支持的接入形态内")
    proto = protocol_of(provider)
    if proto not in SUPPORTED_PROTOCOLS:
        out.append(f"暂不支持 {PROTOCOLS.get(proto, proto)}协议（适配器未实现）")
    return out


def terms_note_of(provider) -> str | None:
    """厂商官方条款警示（订阅类通道通常有值）。无警示时返回 None。"""
    note = getattr(provider, "terms_note", None)
    return note.strip() if note and note.strip() else None


def is_subscription_channel(provider) -> bool:
    """是否订阅制通道（包月额度 / Credits / 请求次数限流，无 token 单价）。

    界面用它把「成本数字只是参照值」这件事说清楚，避免使用者把
    订阅通道的单价当成真实报价。
    """
    return access_kind_of(provider) in {"coding_plan", "token_plan"}


def provider_unavailable_reason(provider) -> str | None:
    """给出「不可用」的可读原因；可用时返回 None。用于把错误信息说到点上。

    顺序刻意是「先通道能力、再密钥、后启用」：
    形态/协议不支持是配置解决不了的，先说；密钥和启用才是可行动的。
    若反过来先报「已停用」，使用者会去找启用开关，而启用后依然调不通。
    """
    if provider is None:
        return "厂商不存在或已被删除"
    blockers = routable_blockers(provider)
    if blockers:
        return blockers[0]
    if not has_usable_key(provider.api_key_encrypted):
        return "厂商密钥未配置（请在「厂商接入」录入 API Key）"
    if not provider.enabled:
        return "厂商已停用"
    return None
