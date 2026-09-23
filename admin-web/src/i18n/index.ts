import { computed, ref } from 'vue'
import common from './lang/common'
import layoutLang from './lang/layout'
import routerLang from './lang/router'
import apikeysLang from './lang/apikeys'
import dashboardLang from './lang/dashboard'
import evalLang from './lang/eval'
import loginLang from './lang/login'
import logsLang from './lang/logs'
import modelsLang from './lang/models'
import playgroundLang from './lang/playground'
import providersLang from './lang/providers'
import rulesLang from './lang/rules'
import samplesLang from './lang/samples'
import usageLang from './lang/usage'
import requestLang from './lang/request'
import routeChainLang from './lang/route-chain'
import settingsLang from './lang/settings'

/** 支持的语言。zh = 管理端原始文案，en = 翻译。 */
export type Lang = 'zh' | 'en'

export const LANGS: { value: Lang; label: string }[] = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
]

const STORAGE_KEY = 'llmbridge-lang'

function initialLang(): Lang {
  const saved = localStorage.getItem(STORAGE_KEY)
  return saved === 'en' ? 'en' : 'zh'
}

/** 当前语言（ref，模板内直接读即响应式）。 */
export const locale = ref<Lang>(initialLang())

const DICTIONARIES: Record<Lang, Record<string, string>> = {
  zh: {},
  en: {},
}

for (const mod of [
  common, layoutLang, routerLang, apikeysLang, dashboardLang, evalLang,
  loginLang, logsLang, modelsLang, playgroundLang, providersLang,
  rulesLang, samplesLang, usageLang, requestLang, routeChainLang, settingsLang,
]) {
  Object.assign(DICTIONARIES.zh, mod.zh)
  Object.assign(DICTIONARIES.en, mod.en)
}

/** 切换语言并持久化。 */
export function setLang(lang: Lang): void {
  locale.value = lang
  localStorage.setItem(STORAGE_KEY, lang)
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
}

/**
 * 取文案。模板/脚本里用 `t('key')` —— 因为读了 locale.value，
 * 语言切换后所有用到的组件会自动重渲染。
 * 插值：`t('key', { n: 3 })` 替换语料里的 `{n}`。
 * 缺 key 时回退 zh，再缺则原样返回 key（方便定位漏翻译）。
 */
export function t(key: string, params?: Record<string, string | number>): string {
  const table = DICTIONARIES[locale.value]
  let s = table[key] ?? DICTIONARIES.zh[key]
  if (s === undefined) return key
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      s = s.split(`{${k}}`).join(String(v))
    }
  }
  return s
}

/** 当前语言的响应式 computed —— 给需要拼接/条件判断的场景用。 */
export const lang = computed(() => locale.value)

/** 6 类内置能力标签的枚举值（数据库稳定标识，勿改）。 */
const KNOWN_CAPS = new Set([
  'general', 'code_generation', 'translation', 'summarize',
  'complex_reasoning', 'long_context',
])

/**
 * 能力标签展示名：内置 6 类按当前语言映射（code_generation → 代码生成 / Code generation），
 * 自定义/未知标签原样返回（标签输入框 allow-create，池里可能有非枚举值）。
 * 因为内部读了 locale.value，切语言后自动重渲染。
 */
export function capLabel(cap: string): string {
  return KNOWN_CAPS.has(cap) ? t(`cap.${cap}`) : cap
}

/**
 * 任务类型展示名：与能力标签是**同一张枚举表**（TASK_TYPES == KNOWN_CAPS），
 * 因此直接复用 capLabel 的映射与兜底逻辑，保证两者永不漂移。
 * 存在的意义是调用点语义准确（概率分布 / 混淆矩阵 / 明细里显示的是 task_type，
 * 不是模型能力），而不是另建一套映射。未知/自定义值原样返回。
 */
export function taskLabel(taskType: string): string {
  return capLabel(taskType)
}
