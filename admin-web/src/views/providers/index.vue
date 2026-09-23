<template>
  <div class="app-anim-fade">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">{{ t('providers.page.title') }}</h2>
        <p class="app-page-desc" v-html="t('providers.page.desc')"></p>
      </div>
    </div>

    <div class="app-card">
      <div class="app-toolbar">
        <el-button type="primary" @click="openCreate">{{ t('providers.toolbar.create') }}</el-button>
        <el-button @click="load">{{ t('providers.toolbar.refresh') }}</el-button>
        <span class="app-badge is-success">{{ t('providers.toolbar.badge.ready', { n: readyCount }) }}</span>
        <span class="app-badge is-warning">{{ t('providers.toolbar.badge.pending', { n: pendingCount }) }}</span>
        <span class="app-badge is-gray">{{ t('providers.toolbar.badge.stopped', { n: stoppedCount }) }}</span>
        <span class="app-badge is-warning">{{ t('providers.toolbar.badge.subscription', { n: subscriptionCount }) }}</span>
        <span v-if="excludedCount" class="app-badge is-purple">{{ t('providers.toolbar.badge.excluded', { n: excludedCount }) }}</span>
        <div class="app-toolbar-spacer"></div>
        <div class="app-seg">
          <button v-for="f in filters" :key="f.value" class="app-seg-btn"
                  :class="{ 'is-active': filter === f.value }" @click="filter = f.value">
            {{ t(f.label) }}
          </button>
        </div>
      </div>

      <div v-loading="loading" class="vendor-list">
        <div v-if="!groups.length && !loading" class="vendor-empty">{{ t('providers.list.empty') }}</div>

        <div v-for="g in groups" :key="g.key" class="vendor-card">
          <div class="vendor-head">
            <div class="vendor-title">
              <span class="vendor-name">{{ g.title }}</span>
              <span class="vendor-meta">
                {{ t('providers.group.meta', { n: g.rows.length, m: g.readyCount }) }}
              </span>
            </div>
            <span v-if="g.blockedCount" class="app-badge is-purple">
              {{ t('providers.group.blocked', { n: g.blockedCount }) }}
            </span>
          </div>

          <div class="chan-list">
            <div v-for="row in g.rows" :key="row.id" class="chan-row" :class="{ 'is-blocked': isExcluded(row) }">
              <div class="chan-main">
                <div class="chan-tags">
                  <span class="app-badge" :class="ACCESS_KIND_TONE[row.access_kind] || 'is-gray'">
                    {{ row.access_kind_label }}
                  </span>
                  <span class="app-badge is-gray">{{ row.protocol_label }}</span>
                  <span class="app-badge" :class="credOf(row).tone">{{ credOf(row).text }}</span>
                  <!-- 「能参与路由」是常态，不逐行标注；只把例外（按设计不参与）显式标出来，
                       否则 20+ 行里会堆满同色徽章，真正的例外反而被淹没。 -->
                  <span v-if="isExcluded(row)" class="app-badge is-purple">{{ t('providers.badge.excluded') }}</span>
                  <!-- 订阅类单价是「成本参照值」而非真实边际成本，必须标出来，
                       否则使用者会把 0.92 当成报价去比较。 -->
                  <span v-if="row.is_subscription" class="app-badge is-info">{{ t('providers.badge.refprice') }}</span>
                  <button v-if="row.terms_note" class="terms-toggle" type="button"
                          @click="toggleTerms(row.id)">
                    {{ expandedTerms.has(row.id) ? t('providers.terms.collapse') : '⚠ ' + t('providers.terms.warn') }}
                  </button>
                  <span class="chan-id">#{{ row.id }}</span>
                </div>

                <div class="chan-url">{{ row.base_url }}</div>

                <div class="chan-key">
                  <template v-if="row.has_key">
                    <code class="app-code">{{ row.api_key_masked }}</code>
                    <span v-if="row.model_count" class="chan-models">{{ t('providers.chan.models', { n: row.model_count }) }}</span>
                    <span v-else class="chan-nomodel">{{ t('providers.chan.nomodel') }}</span>
                  </template>
                  <template v-else>
                    <span class="key-missing">{{ t('providers.chan.nokey') }}</span>
                    <a v-if="keyUrl(row.remark)" class="key-link" :href="keyUrl(row.remark)!"
                       target="_blank" rel="noreferrer">{{ t('providers.chan.apply') }} →</a>
                    <span v-if="row.model_count" class="chan-models">{{ t('providers.chan.models', { n: row.model_count }) }}</span>
                    <span v-else class="chan-nomodel">{{ t('providers.chan.nomodel') }}</span>
                  </template>
                </div>

                <!-- 条款警示：订阅类通道必读。默认收起，点击徽章展开，
                     避免 10 条订阅通道各摊开一大段原文把界面冲垮。 -->
                <div v-if="row.terms_note && expandedTerms.has(row.id)" class="terms-box">
                  {{ row.terms_note }}
                </div>

                <div v-if="isExcluded(row)" class="blocked-hint">
                  <div v-for="(b, i) in row.routable_blockers" :key="i">· {{ b }}</div>
                  <div class="blocked-note">{{ t('providers.chan.blockedNote') }}</div>
                </div>

                <!-- 官方未公布可折算单价的通道会没有模型。这是刻意的：
                     宁可空着，也不填 0（填 0 会让它在成本因子上拿满分而霸占路由）。 -->
                <div v-else-if="!row.model_count" class="empty-models-hint">
                  <div>{{ t('providers.chan.emptyModels') }}</div>
                  <div class="blocked-note" v-html="t('providers.chan.emptyModelsHint2')"></div>
                  <div>{{ t('providers.chan.emptyModelsHint1') }}</div>
                  <router-link class="key-link" to="/models">{{ t('providers.chan.gotoModels') }} →</router-link>
                </div>
              </div>

              <div class="chan-actions">
                <el-button v-if="!row.has_key" link type="primary" @click="fillKey(row)">{{ t('providers.action.fillKey') }}</el-button>
                <el-button link type="primary" :loading="testingId === row.id" @click="test(row)">{{ t('providers.action.test') }}</el-button>
                <el-button link type="primary" @click="openEdit(row)">{{ t('providers.action.edit') }}</el-button>
                <el-switch class="chan-switch" :model-value="row.enabled"
                           @change="(v: unknown) => toggle(row, v as boolean)" />
                <el-button link type="danger" @click="remove(row)">{{ t('providers.action.delete') }}</el-button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-dialog v-model="dlg" :title="form.id ? t('providers.dialog.title.edit') : t('providers.dialog.title.create')" width="600px" append-to-body>
      <el-form :model="form" label-width="110px">
        <el-form-item :label="t('providers.form.vendor')">
          <el-input v-model="form.vendor" :placeholder="t('providers.form.vendorPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('providers.form.accessKind')" required>
          <el-select v-model="form.access_kind" style="width: 100%">
            <el-option v-for="(label, k) in ACCESS_KINDS" :key="k" :label="t(label)" :value="k" />
          </el-select>
          <div v-if="form.access_kind === 'coding_plan' || form.access_kind === 'token_plan'"
               class="form-hint" v-html="t('providers.form.hint.subscription')"></div>
          <div v-else-if="form.access_kind === 'package' || form.access_kind === 'batch'" class="form-hint" v-html="t('providers.form.hint.package')"></div>
        </el-form-item>
        <el-form-item :label="t('providers.form.protocol')" required>
          <el-select v-model="form.protocol" style="width: 100%">
            <el-option v-for="(label, k) in PROTOCOLS" :key="k" :label="t(label)" :value="k" />
          </el-select>
          <div v-if="form.protocol !== 'openai'" class="form-hint" v-html="t('providers.form.hint.protocol')"></div>
        </el-form-item>
        <el-form-item :label="t('providers.form.name')" required>
          <el-input v-model="form.name" :placeholder="t('providers.form.namePlaceholder')" />
        </el-form-item>
        <el-form-item label="Base URL" required>
          <el-input v-model="form.base_url" placeholder="https://api.deepseek.com/v1" />
        </el-form-item>
        <el-form-item :label="form.id ? t('providers.form.newKey') : 'API Key'" :required="!form.id">
          <el-input v-model="form.api_key" type="password" show-password
                    :placeholder="form.id ? t('providers.form.keyPlaceholderEdit') : 'sk-...'" />
        </el-form-item>
        <el-form-item :label="t('providers.form.remark')">
          <el-input v-model="form.remark" type="textarea" :rows="2"
                    :placeholder="t('providers.form.remarkPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('providers.form.terms')">
          <el-input v-model="form.terms_note" type="textarea" :rows="3"
                    :placeholder="t('providers.form.termsPlaceholder')" />
          <div class="form-hint" v-html="t('providers.form.hint.terms')"></div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">{{ t('providers.dialog.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="save">{{ t('providers.dialog.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { t } from '../../i18n'
import { createProvider, deleteProvider, listProviders, testProvider, updateProvider } from '../../api'
import type { Provider } from '../../types'

const ACCESS_KINDS: Record<string, string> = {
  api: 'providers.kind.api',
  package: 'providers.kind.package',
  batch: 'providers.kind.batch',
  coding_plan: 'providers.kind.codingPlan',
  token_plan: 'providers.kind.tokenPlan',
}
const PROTOCOLS: Record<string, string> = {
  openai: 'providers.proto.openai',
  anthropic: 'providers.proto.anthropic',
}
const ACCESS_KIND_TONE: Record<string, string> = {
  api: 'is-primary',
  package: 'is-purple',
  batch: 'is-gray',
  coding_plan: 'is-warning',
  token_plan: 'is-warning',
}
/** 同一厂商内的通道排列顺序：按量 API 永远排最前（使用者的主力通道、合规风险最低） */
const ACCESS_KIND_ORDER: Record<string, number> = {
  api: 0, package: 1, batch: 2, coding_plan: 3, token_plan: 4,
}

/**
 * 筛选器。「不参与路由」只在真的存在这类通道时才出现——
 * 订阅类已纳入路由，正常情况下它是空的，常驻一个恒为 0 的筛选项只会让人以为坏了。
 */
const BASE_FILTERS = [
  { value: 'all', label: 'providers.filter.all' },
  { value: 'pending', label: 'providers.filter.pending' },
  { value: 'ready', label: 'providers.filter.ready' },
  { value: 'subscription', label: 'providers.filter.subscription' },
] as const
const BLOCKED_FILTER = { value: 'blocked', label: 'providers.filter.excluded' } as const
type FilterValue = (typeof BASE_FILTERS)[number]['value'] | 'blocked'

const items = ref<Provider[]>([])
const loading = ref(false)
const dlg = ref(false)
const saving = ref(false)
const testingId = ref<number | null>(null)
const filter = ref<FilterValue>('all')
/** 已展开条款警示的通道 id。订阅类条款原文较长，默认收起。 */
const expandedTerms = ref<Set<number>>(new Set())

const emptyForm = () => ({
  id: 0, name: '', vendor: '', base_url: '', api_key: '', remark: '', terms_note: '',
  access_kind: 'api', protocol: 'openai',
})
const form = ref(emptyForm())

const readyCount = computed(() => items.value.filter((i) => i.routable).length)
const pendingCount = computed(() => items.value.filter((i) => !i.has_key).length)
const stoppedCount = computed(() => items.value.filter((i) => i.has_key && !i.enabled).length)
const subscriptionCount = computed(() => items.value.filter((i) => i.is_subscription).length)
const excludedCount = computed(() => items.value.filter(isExcluded).length)

const filters = computed(() =>
  excludedCount.value ? [...BASE_FILTERS, BLOCKED_FILTER] : [...BASE_FILTERS])

function toggleTerms(id: number) {
  const next = new Set(expandedTerms.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedTerms.value = next
}

/** 是否属于「按设计不参与路由」。与配没配密钥无关——配了也一样不参与。 */
function isExcluded(row: Provider): boolean {
  return (row.routable_blockers?.length ?? 0) > 0
}

/**
 * 凭证状态由「有没有密钥」和「有没有启用」共同决定。
 * 只看 enabled 会把「已启用但没填 Key」显示成正常——那种状态下该通道的模型
 * 根本进不了候选池，界面却在骗人。
 */
function credOf(row: Provider): { text: string; tone: string } {
  if (!row.has_key) return { text: t('providers.cred.pending'), tone: 'is-warning' }
  if (!row.enabled) return { text: t('providers.cred.disabled'), tone: 'is-gray' }
  return { text: t('providers.cred.ready'), tone: 'is-success' }
}

/**
 * 「可参与路由」是默认状态，不单独出徽章——只有例外才值得标注。
 * 当前是否真的在跑，要看「已接入」徽章 + 通道开关，两者分开显示，使用者才知道该改什么。
 */
function matchFilter(row: Provider): boolean {
  switch (filter.value) {
    case 'pending': return !row.has_key
    case 'ready': return !!row.routable
    case 'subscription': return !!row.is_subscription
    case 'blocked': return isExcluded(row)
    default: return true
  }
}

interface VendorGroup {
  key: string
  title: string
  rows: Provider[]
  readyCount: number
  blockedCount: number
}

/**
 * 按 vendor 分组：一家厂商一张卡片，卡内列出它的全部接入方式。
 *
 * 为什么不在表格里平铺：同厂商的多条通道 base_url 不同、密钥也不同，
 * 平铺后使用者无法一眼看出「这两个是同厂的两种东西」，
 * 很容易拿按量 API 的 Key 去填订阅通道，然后困惑「为什么填了还是不通」。
 */
const groups = computed<VendorGroup[]>(() => {
  const map = new Map<string, Provider[]>()
  for (const row of items.value) {
    if (!matchFilter(row)) continue
    const key = row.vendor || `__solo__${row.id}`
    const list = map.get(key)
    if (list) list.push(row)
    else map.set(key, [row])
  }
  const out: VendorGroup[] = []
  for (const [key, rows] of map) {
    rows.sort((a, b) =>
      (ACCESS_KIND_ORDER[a.access_kind] ?? 9) - (ACCESS_KIND_ORDER[b.access_kind] ?? 9) || a.id - b.id)
    out.push({
      key,
      title: rows[0].name.split(' · ')[0],
      rows,
      readyCount: rows.filter((r) => r.routable).length,
      blockedCount: rows.filter(isExcluded).length,
    })
  }
  out.sort((a, b) => a.title.localeCompare(b.title, 'zh-Hans-CN'))
  return out
})

/** 从接入说明里取出密钥申请地址（remark 形如「密钥申请：<url>；<说明>」）。 */
function keyUrl(remark?: string | null): string | null {
  if (!remark) return null
  const m = remark.match(/https?:\/\/[^\s；;，,]+/)
  return m ? m[0] : null
}

async function load() {
  loading.value = true
  try {
    // page_size 拉满：预置后通道数已超过默认分页的 20，分页会静默漏掉尾部通道
    items.value = (await listProviders({ page_size: 200 })).items
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = emptyForm()
  dlg.value = true
}

function openEdit(row: Provider) {
  form.value = {
    id: row.id, name: row.name, vendor: row.vendor ?? '', base_url: row.base_url,
    api_key: '', remark: row.remark ?? '', terms_note: row.terms_note ?? '',
    access_kind: row.access_kind, protocol: row.protocol,
  }
  dlg.value = true
}

async function save() {
  saving.value = true
  try {
    if (form.value.id) {
      const { name, base_url, api_key, remark, terms_note, vendor, access_kind, protocol } = form.value
      const res = await updateProvider(form.value.id, {
        name, base_url, remark, vendor, access_kind, protocol,
        terms_note: terms_note || '',   // 空串 = 清空警示
        api_key: api_key || undefined,
      })
      notifyAutoEnabled(name, res?.auto_enabled)
    } else {
      await createProvider({
        name: form.value.name, base_url: form.value.base_url,
        api_key: form.value.api_key, remark: form.value.remark || undefined,
        terms_note: form.value.terms_note || undefined,
        vendor: form.value.vendor || undefined,
        access_kind: form.value.access_kind, protocol: form.value.protocol,
      } as never)
      ElMessage.success(t('providers.msg.saved'))
    }
    dlg.value = false
    await load()
  } finally {
    saving.value = false
  }
}

/** 行内快捷填 Key：这是「接入成本 = 一个 Key」的主路径。 */
async function fillKey(row: Provider) {
  const blocked = isExcluded(row)
  const link = keyUrl(row.remark)
  const linkText = link ? t('providers.fill.linkHint') : ''
  const subNote = row.is_subscription ? t('providers.fill.tip.subscription') : ''
  const tip = (blocked
    ? t('providers.fill.tip.blocked', { name: row.name })
    : t('providers.fill.tip.normal', { name: row.name, link: linkText }))
    + subNote
  let raw: string
  try {
    const res = await ElMessageBox.prompt(tip, t('providers.fill.title'), {
      inputType: 'password',
      inputPlaceholder: 'sk-...',
      confirmButtonText: t('providers.dialog.save'),
      cancelButtonText: t('providers.dialog.cancel'),
      inputValidator: (v: string) => (v && v.trim().length >= 8) || t('providers.fill.validator'),
    })
    raw = res.value
  } catch {
    return // 用户取消
  }
  const res = await updateProvider(row.id, { api_key: raw.trim() })
  notifyAutoEnabled(row.name, res?.auto_enabled)
  await load()
}

/**
 * 自动启用是后端顺带做的，必须如实告知——否则使用者不知道哪些模型被一起打开了。
 * 订阅类通道若带条款警示，用 alert 而不是 toast：toast 几秒就消失，
 * 而「启用了一条条款受限的通道」这件事值得占用一次点击。
 */
function notifyAutoEnabled(name: string, auto?: {
  models_enabled?: string[]; skipped_reason?: string; terms_note?: string
} | null) {
  if (auto?.skipped_reason) {
    ElMessage.warning(t('providers.msg.keySavedButSkipped', { name, reason: auto.skipped_reason }))
    return
  }
  const models = auto?.models_enabled ?? []
  const summary = models.length
    ? t('providers.msg.autoEnabledWithModels', { name, n: models.length, list: models.join('、') })
    : t('providers.msg.keySaved', { name })
  if (auto?.terms_note) {
    const title = `${summary}｜${t('providers.msg.termsAlert')}`
    void ElMessageBox.alert(auto.terms_note, title, {
      confirmButtonText: t('providers.msg.gotIt'),
      type: 'warning',
    }).catch(() => undefined)
    return
  }
  ElMessage.success(summary)
}

async function toggle(row: Provider, enabled: boolean) {
  await updateProvider(row.id, { enabled })
  if (enabled && !row.has_key) {
    ElMessage.warning(t('providers.msg.enabledNoKey', { name: row.name }))
  }
  await load()
}

async function test(row: Provider) {
  testingId.value = row.id
  try {
    const r = await testProvider(row.id)
    if (r.applicable === false) ElMessage.info(r.detail)
    else if (r.ok) ElMessage.success(t('providers.msg.reachable', { ms: r.latency_ms }))
    else ElMessage.warning(t('providers.msg.unreachable', { detail: r.detail, ms: r.latency_ms }))
  } finally {
    testingId.value = null
  }
}

async function remove(row: Provider) {
  try {
    await ElMessageBox.confirm(
      t('providers.confirm.deleteMsg', { name: row.name }),
      t('providers.confirm.deleteTitle'),
      { type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteProvider(row.id)
    ElMessage.success(t('providers.msg.deleted'))
    await load()
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}

onMounted(load)
</script>

<style scoped>
.vendor-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.vendor-empty {
  padding: 32px;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.vendor-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  overflow: hidden;
}
.vendor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  background: var(--el-fill-color-light);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.vendor-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}
.vendor-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.vendor-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.chan-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 16px;
}
.chan-row + .chan-row {
  border-top: 1px dashed var(--el-border-color-lighter);
}
.chan-main {
  flex: 1;
  min-width: 0;
}
.chan-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.chan-id {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.chan-url {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  word-break: break-all;
}
.chan-key {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  flex-wrap: wrap;
}
.chan-models {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.chan-nomodel {
  font-size: 12px;
  color: var(--el-color-info);
}
.terms-toggle {
  padding: 2px 10px;
  font-size: 12px;
  line-height: 1.6;
  border: 1px solid var(--el-color-warning-light-5);
  border-radius: 999px;
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
  cursor: pointer;
}
.terms-toggle:hover {
  background: var(--el-color-warning-light-8);
}
.terms-box {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--el-color-warning-light-7);
  border-left: 3px solid var(--el-color-warning);
  background: var(--el-color-warning-light-9);
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-color-warning-dark-2);
}
.empty-models-hint {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-lighter);
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}
.key-missing {
  font-size: 12px;
  color: var(--el-color-warning);
}
.key-link {
  font-size: 12px;
  color: var(--app-primary, #14b8a6);
  text-decoration: none;
}
.key-link:hover {
  text-decoration: underline;
}
.blocked-hint {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--el-color-warning-light-9);
  border: 1px solid var(--el-color-warning-light-7);
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-color-warning-dark-2);
}
.blocked-note {
  margin-top: 2px;
  opacity: 0.85;
}
.chan-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding-top: 2px;
}
.chan-switch {
  margin: 0 4px;
}
.form-hint {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
}
.app-seg {
  display: inline-flex;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  overflow: hidden;
}
.app-seg-btn {
  padding: 5px 12px;
  font-size: 12px;
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--el-text-color-regular);
}
.app-seg-btn + .app-seg-btn {
  border-left: 1px solid var(--el-border-color-lighter);
}
.app-seg-btn:hover {
  background: var(--el-fill-color-light);
}
.app-seg-btn.is-active {
  background: var(--app-primary, #14b8a6);
  color: #fff;
}
</style>
