"""把内置厂商目录（`app/data/provider_catalog.py`）预置进库，使接入成本降为「填一个 API Key」。

为什么这段逻辑必须在**包内**（`app/`）而不是 `scripts/`
------------------------------------------------------
目录是交付态的一部分：**装完就要能在界面上看到全部主流接入商**。
原先它只存在于 `scripts/seed_provider_catalog.py`，而 `scripts/` 不进 wheel
（`MANIFEST.in` 只管 sdist），于是 `pip install .` 装完该脚本根本不存在，
控制台里一家厂商都没有、使用者不知道从哪儿接入。逻辑搬进包后，
无源码 checkout 的场景（wheel / 容器整包）同样可用。

调用方
------
- `app/services/bootstrap.py` —— **启动时自动**调用（默认 `with_models=False`）
- `app/cli.py` 的 `llmbridge-catalog`
- `scripts/seed_provider_catalog.py`（薄壳，仅做参数解析与报告落盘）

「一家厂商多条通道」
------------------
目录里每家厂商可含多条 channel（按量 API / 编程订阅套餐 / …），
每条 channel 在库里对应**一行 provider**，靠 `vendor` 聚成一组。因此本模块
遍历的是 (厂商, 通道) 二元组，而不是厂商。

默认只预置「接入通道」，不预置模型
--------------------------------
`with_models=False`（默认）时**只写 provider 行，不写 model 行** —— 模型池初始为空，
由使用者在「模型池」页按自己账号实际可用的 Model ID 手工添加。
原因：模型 ID、计费口径、可用范围因账号而异，预置一份「参考目录」反而会让人
误以为已配置；而接入商是客观存在、可枚举的，必须先摆出来。
需要连目录参考模型（含官方参考单价）一起灌入时，显式加 `--with-models`。

设计取舍（沿用脚本版，勿轻改）
------------------------------
1. **不动使用者已有的数据**。匹配到已存在的通道时，只补 `remark`（接入说明），
   绝不动 `api_key_encrypted`；已存在的模型默认整个跳过，避免把使用者校正过的价格覆盖回参考价。
   `overwrite=True` 是显式的例外通道。

2. **三级匹配，键从可靠到宽松**：
   ① 通道名精确匹配；② 同厂商 + 同接入形态（目录内该组合唯一时）；
   ③ base_url（**仅当它在目录内唯一**）。
   为什么需要第二级：目录改了端点后，旧行的名字与 base_url 都变了，前两级都认不出，
   会凭空多出一条重复通道，而旧行还留着**错的 protocol**（实测：旧智谱 Coding 行
   base_url 是 Anthropic 端点、protocol 却写着 openai —— 协议与端点矛盾，
   一旦启用就会拿 OpenAI 格式去请求 Anthropic 端点）。第二级认领它并就地修正端点与协议。
   为什么 base_url 要判唯一：MiniMax 的按量与 Token Plan **共用同一个端点**
   （官方靠 Key 前缀 sk-api- / sk-cp- 区分计费），不判唯一会把按量通道改名覆盖成订阅通道。
   另外厂商名是人工起的、容易有笔误或改名（库里就出现过「阿里云白炼」），
   只按名字匹配会凭空多出一家重复厂商；有回退匹配后同一家会被认出，
   避免出现「两个都填了 Key 却只有一半生效」。

3. **新通道 `enabled=False`**（新模型同样）：预置的是「目录」，不是「已接入」。
   密钥由使用者录入，填 Key 时后端自动启用该通道及其名录模型
   （见 api/admin/providers.py）。

   订阅类通道（`coding_plan` / `token_plan`）**同样参与路由**，因此也会被自动启用。
   代价是必须知情：厂商官方条款普遍限定这类套餐「仅可在官方支持的工具中交互式使用，
   不得作为应用后端」。条款原文随 `terms_warning` 写入 `provider.terms_note`——
   它与 `remark` 分开两列，是因为 `remark` 只有 255 字符，装不下条款原文。

4. **把迁移前的旧名字规范化**。上一版目录一个厂商只有一条通道，名字就是「DeepSeek」；
   现在同一家可能有多条，「DeepSeek」无法区分是哪条。按 base_url 命中后，
   若名字与目录不一致则规范化为「厂商 · 接入形态」
   （`keep_names=True` 可保留手工改名）。
   名字是本模块自己写进去的，不是使用者填的，所以这一步不算覆盖使用者数据。

5. **部分通道在目录里本就没有模型**。官方未公布 Token 额度（算不出等效单价）、
   且找不到按量标准价可折算的，一律不收录——宁可空着，也不填 0
   （填 0 会让它在 L3 成本因子上拿满分而霸占路由）。
   这类通道会在报告里标 `无模型`，提示填 Key 后在「模型池」页手工添加。

6. **不提交事务**。是否 commit / rollback 由调用方决定（`--dry-run` 靠 rollback 实现）。
"""
from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.provider_catalog import (
    ACCESS_KINDS,
    CATALOG,
    CATALOG_VERSION,
    build_remark,
    build_terms_note,
    channel_name,
    is_channel_routable,
)
from app.db.tables import Model, Provider

__all__ = ["seed_catalog", "catalog_stats", "placeholder_key"]


def placeholder_key(provider_name: str) -> str:
    """未配置密钥时的占位密文。

    刻意用**非法密文**：`services.provider_access.has_usable_key` 靠「能否解密」判断是否已配置，
    占位符必然解密失败，于是该通道自动被判为「未接入」而不进候选池。
    这样就不需要额外的 `is_configured` 标记字段，也就不存在标记与实际状态不一致的可能。
    """
    return f"ENC_PLACEHOLDER_{provider_name}"


def _norm(url: str) -> str:
    return url.rstrip("/").lower()


def catalog_stats() -> dict[str, int]:
    """目录规模（厂商 / 通道 / 模型），供报告与引导日志复用同一口径。"""
    return {
        "vendors": len(CATALOG),
        "channels": sum(len(cp.channels) for cp in CATALOG),
        "models": sum(len(c.models) for cp in CATALOG for c in cp.channels),
    }


async def seed_catalog(
    session: AsyncSession,
    *,
    with_models: bool = False,
    overwrite: bool = False,
    keep_names: bool = False,
    prune_orphans: bool = False,
) -> list[str]:
    """幂等预置接入通道；`with_models=True` 时连目录参考模型一起写。

    返回逐行报告（调用方决定打印 / 落盘）。**不提交事务**。
    """
    lines: list[str] = []
    stats = catalog_stats()
    n_channel_total, n_model_total = stats["channels"], stats["models"]
    lines.append("内置厂商目录预置报告")
    lines.append(f"目录版本 = {CATALOG_VERSION}    厂商 {stats['vendors']} 家 / "
                 f"通道 {n_channel_total} 条 / 目录内模型 {n_model_total} 个")
    lines.append(f"模式 = overwrite={overwrite}    with_models={with_models}")
    if not with_models:
        lines.append("预置范围 = **仅接入通道**（模型池留空，请在「模型池」页手工添加）")
    lines.append("")

    n_new = n_hit_name = n_hit_url = n_hit_kind = n_renamed = 0
    n_model_new = n_model_skip = n_model_upd = 0

    existing = (await session.execute(select(Provider))).scalars().all()
    by_name: dict[str, Provider] = {}
    by_url: dict[str, Provider] = {}
    for p in existing:
        by_name.setdefault(p.name.strip().lower(), p)
        by_url.setdefault(_norm(p.base_url), p)

    # 库内 (vendor, access_kind) 索引——只在库内该组合唯一时才可用于匹配，
    # 否则会认错（同一厂商可能有两条同类通道）。
    db_by_kind: dict[tuple[str, str], Provider] = {}
    dup_kind: set[tuple[str, str]] = set()
    for p in existing:
        k = (p.vendor or "", p.access_kind or "api")
        if k in db_by_kind:
            dup_kind.add(k)
        db_by_kind[k] = p
    for k in dup_kind:
        db_by_kind.pop(k, None)

    # 目录内 (vendor, access_kind) 索引，同样要求唯一
    cat_by_kind: dict[tuple[str, str], object] = {}
    dup_cat_kind: set[tuple[str, str]] = set()
    for cp in CATALOG:
        for ch in cp.channels:
            k = (cp.vendor, ch.access_kind)
            if k in cat_by_kind:
                dup_cat_kind.add(k)
            cat_by_kind[k] = ch
    for k in dup_cat_kind:
        cat_by_kind.pop(k, None)
    unique_cat_kinds = set(cat_by_kind)

    claimed: set[int] = set()
    """已被某个目录通道认领的库内记录 id，防止一条记录被两个通道同时匹配。"""

    lines.append("[接入通道]")
    # base_url **未必唯一**：MiniMax 的按量与 Token Plan 共用同一个端点，
    # 官方就是靠 Key 前缀（sk-api- / sk-cp-）区分计费方式的。
    # 所以只有「在整个目录里只出现一次」的 base_url 才配当回退匹配键——
    # 否则会把按量通道认成订阅通道，改名覆盖（实测踩到：Token Plan 会吃掉按量那条）。
    url_occurrences: dict[str, int] = {}
    for cp in CATALOG:
        for ch in cp.channels:
            url_occurrences[_norm(ch.base_url)] = url_occurrences.get(_norm(ch.base_url), 0) + 1
    ambiguous_urls = {u for u, n in url_occurrences.items() if n > 1}
    if ambiguous_urls:
        lines.append(f"  [注意] 以下 base_url 在目录内被多条通道共用，不参与回退匹配：")
        for u in sorted(ambiguous_urls):
            lines.append(f"         {u}")

    for cp in CATALOG:
        lines.append(f"  ── {cp.name}  (vendor={cp.vendor})")
        if cp.blurb:
            lines.append(f"     {cp.blurb}")

        for ch in cp.channels:
            name = channel_name(cp.name, ch)
            routable = is_channel_routable(ch)
            subscription = ch.access_kind in ("coding_plan", "token_plan")
            flag = "可路由" if routable else "不参与路由"
            if subscription:
                flag += "·订阅"
            if not ch.models or not with_models:
                flag += "·无模型"
            # ---- 三级匹配，从最可靠到最宽松 ----
            # 1) 通道名精确匹配（目录自己写进去的名字）
            # 2) 同厂商 + 同接入形态（目录内该组合唯一时）——处理「目录改了端点后
            #    旧行的名字与 base_url 都变了」：此时前两级都匹配不上，会凭空多出一条
            #    重复通道，而旧行还留着错的 protocol（实测：旧智谱 Coding 行的
            #    base_url 是 Anthropic 端点，protocol 却写着 openai —— 协议与端点矛盾，
            #    一旦启用就会拿 OpenAI 格式去请求 Anthropic 端点，必然失败）
            # 3) base_url（仅当它在目录里唯一）
            # claimed 保证一条库内记录不会被两个目录通道同时认领。
            provider = None
            matched_by = ""
            cand = by_name.get(name.strip().lower())
            if cand is not None and cand.id not in claimed:
                provider, matched_by = cand, "name"
            if provider is None and (cp.vendor, ch.access_kind) in unique_cat_kinds:
                cand = db_by_kind.get((cp.vendor, ch.access_kind))
                if cand is not None and cand.id not in claimed and cand.name != name:
                    provider, matched_by = cand, "vendor+kind"
            if provider is None and _norm(ch.base_url) not in ambiguous_urls:
                cand = by_url.get(_norm(ch.base_url))
                if cand is not None and cand.id not in claimed:
                    provider, matched_by = cand, "base_url"
            if provider is not None:
                claimed.add(provider.id)

            remark = build_remark(ch)
            terms_note = build_terms_note(ch)

            if provider is None:
                provider = Provider(
                    name=name, base_url=ch.base_url,
                    api_key_encrypted=placeholder_key(name),
                    enabled=False, remark=remark, terms_note=terms_note,
                    vendor=cp.vendor, access_kind=ch.access_kind, protocol=ch.protocol,
                )
                session.add(provider)
                await session.flush()  # 取 id 供下面的模型挂载
                n_new += 1
                lines.append(f"    + 新增通道  {name:<34} [{flag}]")
                lines.append(f"               {ch.base_url}")
            else:
                if matched_by == "vendor+kind":
                    # 目录改了端点。这是唯一允许改写 base_url 的路径——
                    # 匹配依据是「同厂商同形态且目录内唯一」，语义上就是同一条通道。
                    n_hit_kind += 1
                    lines.append(f"    ~ 按 厂商+形态 命中库中「{provider.name}」  [{flag}]")
                    if provider.base_url != ch.base_url:
                        lines.append(f"      ~ 端点更新：{provider.base_url}")
                        lines.append(f"              → {ch.base_url}")
                        provider.base_url = ch.base_url
                    if provider.protocol != ch.protocol:
                        lines.append(f"      ~ 协议修正：{provider.protocol} → {ch.protocol}")
                        provider.protocol = ch.protocol
                    if provider.name != name and not keep_names:
                        lines.append(f"      ~ 规范化通道名：{provider.name} → {name}")
                        provider.name = name
                        n_renamed += 1
                elif matched_by == "base_url":
                    n_hit_url += 1
                    lines.append(f"    ~ 按 base_url 命中库中「{provider.name}」  [{flag}]")
                    # 名字与目录不一致时规范化。base_url 在目录内唯一，命中它就说明
                    # 这就是目录里的那条通道，名字应跟随目录——同厂商可能有多条通道，
                    # 「DeepSeek」这种没有形态后缀的旧名无法区分是哪一条。
                    # 若使用者刻意改过名，用 keep_names 保留。
                    if provider.name != name and not keep_names:
                        lines.append(f"      ~ 规范化通道名：{provider.name} → {name}")
                        provider.name = name
                        n_renamed += 1
                else:
                    n_hit_name += 1
                    lines.append(f"    = 已存在    {name:<34} id={provider.id}  [{flag}]")

                # 补全通道身份字段：迁移前的老行没有这些值（列为新增、走默认）。
                if provider.vendor != cp.vendor:
                    provider.vendor = cp.vendor
                if provider.access_kind != ch.access_kind:
                    provider.access_kind = ch.access_kind
                if provider.protocol != ch.protocol:
                    provider.protocol = ch.protocol
                if overwrite or not (provider.remark or "").strip():
                    provider.remark = remark
                # terms_note 与 remark 分开处理：remark 是「去哪拿 Key」，
                # terms_note 是「官方条款警示」。只在为空或显式 overwrite 时写入，
                # 不动使用者可能已经改动过的合规说明。
                if terms_note and (overwrite or not (provider.terms_note or "").strip()):
                    provider.terms_note = terms_note

            if not routable:
                lines.append("      ! 该通道不参与路由（形态/协议未支持），"
                             "其模型不会进入候选池")
                if ch.unroutable_reason:
                    lines.append(f"        原因：{ch.unroutable_reason}")
            elif subscription:
                lines.append("      * 订阅制通道：已纳入路由；成本列为参照值（套餐无 token 单价）。"
                             "厂商条款限定仅可在官方工具内交互式使用，详见库内 terms_note")

            if not with_models:
                lines.append("      * 未预置模型（本次仅铺接入通道）——"
                             "填入 API Key 后请在「模型池」页按控制台确认的 Model ID 手工添加")
            elif not ch.models:
                lines.append("      * 该通道目录内无收录模型（官方未公布可折算的单价）——"
                             "填 Key 后请在「模型池」页按控制台确认的 Model ID 手工添加")

            # ---- 该通道下的模型（仅 with_models=True 时预置） ----
            if not with_models:
                continue

            rows = (await session.execute(
                select(Model).where(Model.provider_id == provider.id)
            )).scalars().all()
            existing_models = {m.model_name: m for m in rows}

            for cm in ch.models:
                cur = existing_models.get(cm.model_name)
                if cur is None:
                    # capabilities 列是 Text，必须显式 json.dumps：
                    # 直接塞 Python list 会被 psycopg 适配成 PostgreSQL 数组字面量 `{general,code_generation}`，
                    # 而不是 JSON `["general","code_generation"]`——下游 json.loads 会直接抛异常。
                    session.add(Model(
                        provider_id=provider.id, model_name=cm.model_name,
                        display_name=cm.display_name,
                        capabilities=json.dumps(list(cm.capabilities), ensure_ascii=False),
                        input_price=cm.input_price, output_price=cm.output_price,
                        context_window=cm.context_window, priority=cm.priority,
                        enabled=False,  # 目录 ≠ 已接入；填 Key 时随通道一起启用
                    ))
                    n_model_new += 1
                    lines.append(f"      + 模型 {cm.model_name:<34} "
                                 f"{cm.input_price}/{cm.output_price} 元  ctx={cm.context_window}")
                elif overwrite:
                    cur.display_name = cm.display_name
                    cur.capabilities = json.dumps(list(cm.capabilities), ensure_ascii=False)
                    cur.input_price = cm.input_price
                    cur.output_price = cm.output_price
                    cur.context_window = cm.context_window
                    cur.priority = cm.priority
                    n_model_upd += 1
                    lines.append(f"      ~ 覆盖 {cm.model_name:<34} 已存在，按目录值刷新")
                else:
                    n_model_skip += 1
                    lines.append(f"      = 跳过 {cm.model_name:<34} 已存在（保留现有配置）")

    # ---- 清理目录残留行 ----
    # 目录改了端点（例如智谱 Coding Plan 从 Anthropic 端点改为 OpenAI 端点）之后，
    # 旧 base_url 匹配不上、名字也变了，于是旧行会变成「没人再管的孤儿」：
    # 界面上还显示为一条通道，实际已不在目录里。三重条件同时满足才删——
    # 仍是占位密钥（人类没配过） + 没挂任何模型 + base_url 不在当前目录里。
    n_pruned = 0
    orphan_lines: list[str] = []
    catalog_urls = {_norm(ch.base_url) for cp in CATALOG for ch in cp.channels}
    all_rows = (await session.execute(select(Provider))).scalars().all()
    model_counts = dict((await session.execute(
        select(Model.provider_id, func.count(Model.id)).group_by(Model.provider_id)
    )).all())
    for p in all_rows:
        if _norm(p.base_url) in catalog_urls:
            continue
        if not (p.api_key_encrypted or "").startswith("ENC_PLACEHOLDER_"):
            continue                      # 使用者配过密钥 → 真实数据，不碰
        if model_counts.get(p.id, 0):
            continue                      # 挂着模型 → 不碰
        orphan_lines.append(f"    - 目录残留行 id={p.id} 「{p.name}」 {p.base_url}")
        if prune_orphans:
            await session.delete(p)
            n_pruned += 1
    if orphan_lines:
        lines.append("")
        lines.append("[目录残留行]")
        lines.extend(orphan_lines)
        if not prune_orphans:
            lines.append("    （未开 prune_orphans，仅列出；这些行已不在目录中）")

    lines.append("")
    lines.append("[汇总]")
    lines.append(f"  通道：新增 {n_new} / 按名命中 {n_hit_name} / 按 base_url 命中 {n_hit_url} / "
                 f"按厂商+形态命中 {n_hit_kind}（其中规范化改名 {n_renamed}）/ 清理残留 {n_pruned}")
    if with_models:
        lines.append(f"  模型：新增 {n_model_new} / 跳过 {n_model_skip} / 覆盖 {n_model_upd}")
    else:
        lines.append(f"  模型：**未预置**（目录内共 {n_model_total} 个可选用 --with-models 一并灌入）")
    n_sub = sum(1 for cp in CATALOG for c in cp.channels
                if c.access_kind in ("coding_plan", "token_plan"))
    lines.append(f"  订阅类通道：{n_sub} 条（已纳入路由，条款警示见库内 terms_note）")
    lines.append("")
    lines.append("[接入方式] 控制台「厂商接入」按厂商分组展示该厂商的全部接入通道。")
    lines.append("           填入 API Key 后，该通道会自动启用并进入路由候选池——"
                 "**包含订阅类通道**。")
    lines.append("           模型需在「模型池」页手工添加（本网关不猜测你的账号有哪些模型）。")
    lines.append("")
    lines.append(f"[接入形态说明] " + " / ".join(f"{k}={v}" for k, v in ACCESS_KINDS.items()))
    return lines
