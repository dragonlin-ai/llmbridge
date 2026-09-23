/** 与后端 schemas 对齐的类型（snake_case 不转驼峰，逐字对齐减少心智映射）。 */

export interface PageResult<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

export interface Provider {
  id: number
  /** 通道显示名，形如「月之暗面 Kimi · 按量 API」。一条记录 = 一条接入通道，不是一家厂商 */
  name: string
  /** 厂商标识（分组键）。同厂商的多条接入通道共用它，控制台据此聚成一张厂商卡片 */
  vendor?: string | null
  /** 接入形态：api 按量 / package 资源包 / batch 批处理 / coding_plan 编程订阅 / token_plan Token 订阅 */
  access_kind: string
  access_kind_label: string
  /** 上游协议：openai / anthropic */
  protocol: string
  protocol_label: string
  base_url: string
  api_key_masked: string
  enabled: boolean
  /** 目录预置的接入说明（含密钥申请地址），可能为空 */
  remark?: string | null
  /**
   * 厂商官方条款警示（订阅类通道通常有值）。
   * 订阅套餐已纳入路由，风险由使用者承担，所以这条警示必须能到达界面——
   * 否则就是默默替使用者做了决定。
   */
  terms_note?: string | null
  /**
   * 是否订阅制通道（包月额度 / Credits / 请求次数限流，没有 token 单价）。
   * 界面据此标注「单价为参照值」，避免把成本参照值当成真实报价去比较。
   */
  is_subscription?: boolean
  /** 是否已录入可用密钥。注意与 enabled 不是一回事：目录预置的厂商「已存在但还没配密钥」 */
  has_key?: boolean
  /** 是否真正能进候选池 = 已接入 + 形态/协议被支持。只有它为 true，该通道的模型才会参与路由 */
  routable?: boolean
  /**
   * 为什么这条通道不参与路由。列出的是**配置解决不了**的原因
   * （如「接入方式为编程订阅套餐」），避免使用者反复填 Key 却始终不生效。
   */
  routable_blockers?: string[]
  /** 该通道下的模型数量 */
  model_count?: number
  created_at: string
}

/** 首次录入密钥时后端顺带启用的对象（副作用可见，不是静默行为） */
export interface ProviderAutoEnabled {
  provider_enabled: boolean
  models_enabled: string[]
  /** 通道不参与路由时不会自动启用，这里说明原因；有值即表示「只存了密钥，没开任何东西」 */
  skipped_reason?: string
  /** 该通道的厂商官方条款警示（订阅类通道）。启用与知情应当同时发生，故随本响应回传 */
  terms_note?: string
}

export interface ModelItem {
  id: number
  provider_id: number
  model_name: string
  display_name: string
  capabilities: string[]
  input_price: number
  output_price: number
  context_window: number
  priority: number
  enabled: boolean
}

/** 删除模型前的引用预检（GET /admin/models/{id}/references）。 */
export interface ModelReferences {
  route_rules: number
  eval_cases: number
  request_logs: number
  decision_samples: number
  /** 无路由规则引用时才允许强制删除（路由规则的目标模型是 NOT NULL 强引用） */
  forceable: boolean
}

export interface RouteRule {
  id: number
  name: string
  priority: number
  type: string
  condition_json: { all: { field: string; op: string; value: unknown }[] }
  target_model_id: number
  enabled: boolean
  remark: string | null
}

export type HitLayer = 'L1' | 'L2' | 'L3'

export interface PreviewResult {
  hit_layer: HitLayer
  task_type: string | null
  selected_model: { model_id: number; model_name: string; display_name: string } | null
  confidence: number | null
  probabilities: Record<string, number> | null
  features: Record<string, number> | null
  candidates: PreviewCandidate[]
  /** 一句话解释「为什么选它」（含「无能力标签→按成本兜底」这类退化说明） */
  selection_basis: string
  hit_rule: unknown
  fallback_reason: string | null
  latency_ms: number
  trace_id: string
  /** 当前配置的判定器（mock / jev） */
  judge_provider: string
  /** 实际产出判定的实现；为 null 表示判定器未产出（调用失败或未命中） */
  decider: string | null
  /** 本次请求实际装载的判定器实例名 */
  active_decider: string | null
  /** 判定器失败原因（如 HTTP 401），用于区分「判定器挂了」与「置信度低」 */
  decider_error: string | null
  /** 真实调用结果；null = 本次仅决策（未开启「调用选中模型」） */
  execution: PreviewExecution | null
}

/** 试跑台的候选打分行（与 pipeline 的 l3_pick 同源，分数排序 = 实际挑选顺序） */
export interface PreviewCandidate {
  model_id: number
  model_name: string
  display_name: string
  /** 加权总分：能力 0.6 / 成本 0.25 / 延迟 0.15 */
  score: number
  /** 该模型的输入单价，用于解释成本因子 */
  input_price: number
  /** hit = 声明了本次任务类型的能力标签；none = 未声明；null = L1 规则命中（不走打分） */
  eligibility: 'hit' | 'none' | null
  /** 是否参与本次实际挑选（无模型命中能力标签时，全部候选回退进入池子） */
  in_pool: boolean
  /** 本次真实选中的模型 */
  picked: boolean
  matched_rule: unknown
}

/** 试跑台的「真实调用」结果（开启 execute 时才有） */
export interface PreviewExecution {
  attempted: boolean
  ok: boolean
  model_id: number
  model_name: string
  display_name: string
  provider_id: number
  provider_name: string | null
  base_url: string | null
  /** 上游调用耗时（不含路由决策耗时） */
  latency_ms: number | null
  content: string | null
  finish_reason: string | null
  /** reasoning_tokens：推理模型的思考 token，已含在 completion_tokens 内 */
  usage: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    reasoning_tokens?: number
  } | null
  cost: number | null
  model_echo: string | null
  /** PROVIDER_UNAVAILABLE / KEY_DECRYPT_FAILED / UPSTREAM_UNAVAILABLE / UPSTREAM_ERROR */
  error_code: string | null
  error: string | null
}

export interface LogItem {
  id: number
  trace_id: string
  router_layer: string
  final_model_id: number | null
  /** 运营别名（display_name） */
  final_model_name: string | null
  /** 真实模型标识（model_name）—— 与上游实际调用的名字一致 */
  final_model_key: string | null
  route_latency_ms: number
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
  cost: number
  status: string
  fallback_reason: string | null
  created_at: string
  /** 是否试跑台「执行」调用的诊断流量（trace_id 以 preview- 开头） */
  is_preview?: boolean
}

export interface StatsOverview {
  total_requests: number
  success_rate: number
  p95_route_latency_ms: number
  fallback_rate: number
  total_cost: number
  layer_distribution: Record<string, number>
}

/** 第三方调用密钥（/admin/api-keys）。明文仅在创建与「查看 Key」时返回。 */
export interface ApiKeyItem {
  id: number
  /** 用途备注，如「订单系统-生产」 */
  name: string
  /** 明文前 12 位，列表掩码展示用 */
  key_prefix: string
  enabled: boolean
  last_used_at: string | null
  expires_at: string | null
  created_at: string | null
  /** 完整明文，仅创建响应与 reveal 接口返回 */
  key?: string
}

/** 判定器设置回显（GET/PUT /admin/decider/settings）。 */
export interface DeciderSettings {
  judge_provider: string
  /** 密钥掩码（如 api****8921）；未配置为 null。明文永不出接口 */
  jev_api_key_masked: string | null
  jev_api_key_set: boolean
  jev_base_url: string
  decider_timeout_ms: number
  route_confidence_threshold_t2: number
  /** 每项配置的来源：db = 数据库覆盖；env = .env 或代码默认 */
  sources: Record<string, 'db' | 'env'>
  /** 实际生效的判定器（运行时事实；配置 jev 但缺密钥时为 mock） */
  active_decider: string
}

/** 连通性测试结果（POST /admin/decider/settings/test）。 */
export interface DeciderTestResult {
  healthy: boolean
  latency_ms: number | null
  /** 失败原因（如 HTTP 401、未配置密钥）；成功为 null */
  reason: string | null
}

/** 层级配色（全局约定，UI 说明书 §一）：L1 绿 / L2 紫(Jev) / L3 红(兜底)
 *  色值对齐设计系统语义色，见 src/styles/tokens.css */
export const LAYER_COLORS: Record<string, string> = {
  L1: '#10b981',
  L2: '#8b5cf6',
  L3: '#ef4444',
}

export const TASK_TYPES = [
  'general',
  'code_generation',
  'translation',
  'summarize',
  'complex_reasoning',
  'long_context',
]

// ---------------- 评测看板（GET /admin/eval/report） ----------------

/** 单侧（一个判定器）的汇总结果 */
export interface EvalSideSummary {
  task_total: number
  task_ok: number
  /** 任务类型准确率；无样本为 null */
  task_accuracy: number | null
  /** 参与模型维度评估的样本数 = 有 expected_model_id 真值的那些 */
  model_total: number
  model_ok: number
  /** 模型选择准确率。**无真值样本时为 null 而非 0** —— 界面不能把「测不了」画成「0 分」 */
  model_accuracy: number | null
  /** expected → predicted 计数 */
  confusion_matrix: Record<string, Record<string, number>>
  layer_distribution: Record<string, number>
}

/** 逐条明细：以 Mock 为主行，jev_* 字段是同一用例在 Jev 侧的对应结果 */
export interface EvalCaseItem {
  case_id: number
  input_text: string
  expected_task_type: string
  expected_model_id: number | null
  hit_layer: HitLayer | null
  predicted_task_type: string | null
  confidence: number | null
  selected_model_id: number | null
  selected_model_name: string | null
  task_ok: boolean
  /** null = 该用例无模型真值，模型维度不参与统计 */
  model_ok: boolean | null
  fallback_reason: string | null
  jev_task_ok: boolean | null
  jev_predicted_task_type: string | null
  jev_selected_model_id: number | null
}

export interface EvalReport {
  empty: boolean
  message?: string
  case_count?: number
  /** 样本表总量（截断前） */
  total_cases: number
  /** 本次实际评测条数 */
  used_cases: number
  /** 是否因 limit 被截断；true 时界面必须说明「准确率非全量口径」 */
  truncated: boolean
  /** 本次评测墙钟耗时（毫秒） */
  elapsed_ms?: number
  /** 可路由模型数（评测候选池规模）。池子过小时准确率不具代表性，需提示 */
  routable_models?: number
  /** 带模型真值的样本数。为 0 时模型准确率恒为 null */
  model_truth_cases?: number
  jev_healthy?: boolean
  jev_last_error?: string | null
  mock: EvalSideSummary
  jev: EvalSideSummary
  items: EvalCaseItem[]
}

// ---------------- 用量与成本（GET /admin/usage/report） ----------------

export interface UsageModelRow {
  /** 真实模型标识（model_name）；null = 该请求未落模型快照（L1 命中 / L3 兜底失败路径） */
  model_key: string | null
  calls: number
  success_count: number
  success_rate: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost: number
  avg_cost: number
  avg_latency_ms: number
}

export interface UsageLayerRow {
  layer: HitLayer
  calls: number
  success_count: number
  success_rate: number
  fallback_count: number
  cost: number
  avg_latency_ms: number
}

export interface UsageTrendRow {
  /** ISO 日期串（UTC 日切）。直接展示，不要交给 new Date() 二次换算 */
  day: string
  calls: number
  success_count: number
  cost: number
  prompt_tokens: number
  completion_tokens: number
}

export interface UsageReport {
  window_days: number
  /** 窗口起点（DB 为 UTC），界面只做文字说明，不做隐式时区换算 */
  window_start: string
  /** 是否已排除试跑台诊断流量（与概览页 R-01 同源口径） */
  excludes_preview: boolean
  summary: {
    calls: number
    success_count: number
    success_rate: number
    fallback_count: number
    fallback_rate: number
    cost: number
    avg_cost: number
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    avg_latency_ms: number
    models: number
  }
  /** 数据覆盖度：并非每条请求都有 token/成本（L1/L3 与失败请求常缺） */
  data_quality: {
    calls: number
    with_token_data: number
    with_cost_data: number
  }
  by_model: UsageModelRow[]
  by_layer: UsageLayerRow[]
  by_status: { status: string; calls: number }[]
  trend: UsageTrendRow[]
}
