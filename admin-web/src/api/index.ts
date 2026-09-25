import request from './request'
import type { ApiKeyItem, DeciderSettings, DeciderTestResult, EvalReport, LogItem, ModelItem, ModelReferences, PageResult, PreviewResult, Provider, ProviderAutoEnabled, RouteRule, StatsOverview, UsageReport } from '../types'

// ---- auth ----
export const login = (username: string, password: string) =>
  request.post<never, { access_token: string; role: string }>('/admin/auth/login', { username, password })

/** 登录后修改自己的密码。 */
export const changePassword = (old_password: string, new_password: string) =>
  request.post<never, null>('/admin/auth/change-password', { old_password, new_password })

// ---- providers ----
export const listProviders = (params?: Record<string, unknown>) =>
  request.get<never, PageResult<Provider>>('/admin/providers', { params })
export const createProvider = (data: {
  name: string; base_url: string; api_key: string; remark?: string
  /** 厂商官方条款警示（订阅类通道建议填写）。不设长度上限，条款原文常超 255 字符 */
  terms_note?: string
  /** 厂商标识（分组键）：相同值的通道会在控制台被归为同一家厂商 */
  vendor?: string; access_kind?: string; protocol?: string
}) =>
  request.post('/admin/providers', data)
export const updateProvider = (
  id: number,
  data: Partial<{
    name: string; base_url: string; api_key: string; enabled: boolean; remark: string
    /** 传空串 = 清空警示 */
    terms_note: string
    vendor: string; access_kind: string; protocol: string
  }>,
) =>
  // 首次录入密钥时后端会自动启用该厂商与其目录模型，并把动了什么回报在 auto_enabled
  request.put<never, Provider & { auto_enabled?: ProviderAutoEnabled | null }>(
    `/admin/providers/${id}`, data)
export const deleteProvider = (id: number) => request.delete(`/admin/providers/${id}`)
export const testProvider = (id: number) =>
  // applicable=false 表示「本测试对该通道不适用」（非 OpenAI 协议 / 未配密钥），
  // 此时 detail 是说明而非故障——界面据此区分「测不了」与「测了不通」。
  request.post<never, { ok: boolean; latency_ms: number; detail: string; applicable?: boolean }>(
    `/admin/providers/${id}/test`)

// ---- models ----
// 注意必须显式传 page_size：后端默认 20，而模型池在预置厂商目录后远超 20 条。
// 且后端按 priority 升序返回，列表页会先看到目录里的低优先模型，
// 使用者真正在用的模型（priority 较大）反而被静默截断在分页之外。
export const listModels = (params?: Record<string, unknown>) =>
  request.get<never, PageResult<ModelItem>>('/admin/models', { params })
export const createModel = (data: Partial<ModelItem>) => request.post('/admin/models', data)
export const updateModel = (id: number, data: Partial<ModelItem>) => request.put(`/admin/models/${id}`, data)
/** 删除前的引用预检：有路由规则引用时 forceable=false，删除必须先去规则页处理。 */
export const getModelReferences = (id: number) =>
  request.get<never, ModelReferences>(`/admin/models/${id}/references`)
/** force=true 时会清空引用该模型的评测用例「期望模型」（用例保留）。 */
export const deleteModel = (id: number, force = false) =>
  request.delete<never, { unbound_logs: number; unbound_samples: number; unbound_evals: number }>(
    `/admin/models/${id}`, { params: force ? { force: true } : undefined })

// ---- rules ----
export const listRules = () => request.get<never, { total: number; items: RouteRule[] }>('/admin/rules')
export const createRule = (data: Record<string, unknown>) => request.post('/admin/rules', data)
export const updateRule = (id: number, data: Record<string, unknown>) => request.put(`/admin/rules/${id}`, data)
export const deleteRule = (id: number) => request.delete(`/admin/rules/${id}`)
export const reorderRules = (ordered_ids: number[]) => request.put('/admin/rules/priorities', { ordered_ids })

// ---- preview ----
export const routePreview = (text: string, session_id?: string, execute = false, max_tokens = 512) =>
  request.post<never, PreviewResult>('/admin/route/preview', { text, session_id, execute, max_tokens })

// ---- logs ----
export const listLogs = (params: Record<string, unknown>) =>
  request.get<never, PageResult<LogItem>>('/admin/logs', { params })
export const getTrace = (traceId: string) => request.get<never, LogItem>(`/admin/logs/${traceId}`)

// ---- stats ----
export const statsOverview = () => request.get<never, StatsOverview>('/admin/stats/overview')
export const options = () =>
  request.get<never, {
    models: ModelItem[]
    rules_total: number
    judge_provider: string
    active_decider: string
  }>('/admin/options')

// ---- samples ----
export const listSamples = (params?: Record<string, unknown>) =>
  request.get<never, PageResult<{ id: number; input_text: string; task_type: string; source: string; created_at: string }>>('/admin/samples', { params })
export const createSample = (data: { input_text: string; task_type: string }) => request.post('/admin/samples', data)

// ---- decider settings（判定器配置：库 > .env > 代码默认） ----
export const getDeciderSettings = () =>
  request.get<never, DeciderSettings>('/admin/decider/settings')
/** 密钥语义：明文=落库、空串=清空回落 .env、含 **** 掩码=未改忽略。保存后免重启即时生效。
 *  提交类型独立于回显类型 DeciderSettings（回显只有 masked/set，无明文 jev_api_key）。 */
export const updateDeciderSettings = (data: Partial<{
  judge_provider: string
  jev_api_key: string
  jev_base_url: string
  decider_timeout_ms: number
  route_confidence_threshold_t2: number
}>) =>
  request.put<never, DeciderSettings>('/admin/decider/settings', data)
/** 用当前保存的配置真实探活 Jev（不受表单未保存改动影响）。 */
export const testDeciderSettings = () =>
  request.post<never, DeciderTestResult>('/admin/decider/settings/test')

// ---- api-keys（第三方调用密钥） ----
export const listApiKeys = () =>
  request.get<never, { total: number; items: ApiKeyItem[] }>('/admin/api-keys')
export const createApiKey = (name: string) =>
  request.post<never, ApiKeyItem>('/admin/api-keys', { name })
/** 返回含完整明文 key（列表接口不带明文）。 */
export const revealApiKey = (id: number) =>
  request.get<never, ApiKeyItem>(`/admin/api-keys/${id}`)
export const updateApiKey = (id: number, data: { name?: string; enabled?: boolean }) =>
  request.put<never, ApiKeyItem>(`/admin/api-keys/${id}`, data)
export const deleteApiKey = (id: number) =>
  request.delete<never, { deleted: boolean }>(`/admin/api-keys/${id}`)

// ---- eval（评测看板）----
/** 即时评测：对 eval_case 样本分别跑 Mock / Jev 两个判定器，返回双侧准确率与逐条明细。
 *  后端按批并发执行，但样本多时整轮仍可能达数十秒（Jev 是真实网络调用，约 1.5s/条），
 *  故这里单独放宽超时——沿用实例默认的 30s 会在样本上 20 条时直接失败。 */
export const getEvalReport = (limit = 50) =>
  request.get<never, EvalReport>('/admin/eval/report', { params: { limit }, timeout: 300000 })

// ---- usage（用量与成本）----
/** 按模型/路由层聚合 + 按日趋势。天数窗口上限 365（后端 ge=1, le=365）。 */
export const getUsageReport = (days = 30) =>
  request.get<never, UsageReport>('/admin/usage/report', { params: { days } })
