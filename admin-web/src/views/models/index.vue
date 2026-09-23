<template>
  <div class="app-anim-fade">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">{{ t('models.page.title') }}</h2>
        <p class="app-page-desc">{{ t('models.page.desc') }}</p>
      </div>
    </div>

    <div class="app-card">
      <div class="app-toolbar">
        <el-button type="primary" @click="openCreate">{{ t('models.toolbar.create') }}</el-button>
        <el-button @click="load">{{ t('common.refresh') }}</el-button>
        <el-checkbox v-model="onlyRoutable" style="margin-left: 8px">{{ t('models.toolbar.onlyRoutable') }}</el-checkbox>
        <span class="app-badge is-gray">{{ t('models.toolbar.count', { a: shown.length, b: items.length }) }}</span>
      </div>
      <el-table :data="shown" v-loading="loading" size="default">
        <el-table-column :label="t('models.table.provider')" min-width="120">
          <template #default="{ row }">
            <span style="color: var(--text-2)">{{ providerName(row.provider_id) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="display_name" :label="t('models.table.displayName')" min-width="140" />
        <el-table-column prop="model_name" :label="t('models.table.modelId')" min-width="160">
          <template #default="{ row }"><code class="app-code">{{ row.model_name }}</code></template>
        </el-table-column>
        <el-table-column :label="t('models.table.capability')" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="c in row.capabilities" :key="c" size="small" style="margin-right:4px">{{ capLabel(c) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('models.table.price')" width="160">
          <template #default="{ row }">{{ row.input_price }} / {{ row.output_price }}</template>
        </el-table-column>
        <el-table-column prop="priority" :label="t('models.table.priority')" width="80" />
        <el-table-column :label="t('models.table.routeState')" width="120">
          <template #default="{ row }">
            <span class="app-badge" :class="routeState(row).tone">{{ t('models.state.' + routeState(row).code) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('models.table.enabled')" width="80">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="(v: unknown) => toggle(row, v as boolean)" />
          </template>
        </el-table-column>
        <el-table-column :label="t('models.table.action')" width="140" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-button link type="danger" @click="remove(row)">{{ t('common.delete') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dlg" :title="t(form.id ? 'models.dialog.title.edit' : 'models.dialog.title.create')" width="560px" append-to-body>
      <el-form :model="form" label-width="120px">
        <el-form-item :label="t('models.form.provider')" required>
          <el-select
            v-model="form.provider_id"
            :placeholder="t('models.form.providerPlaceholder')"
            filterable
            :loading="providersLoading"
            style="width: 100%"
          >
            <el-option v-for="p in providers" :key="p.id" :label="p.name" :value="p.id">
              <span>{{ p.name }}</span>
              <span v-if="!p.routable" class="opt-warn">{{ t('models.form.providerNotConnected') }}</span>
              <span style="float: right; margin-left: 12px; color: var(--text-3); font-size: 12px">
                {{ p.base_url }}
              </span>
            </el-option>
          </el-select>
          <div v-if="!providersLoading && !providers.length" class="model-provider-tip">
            {{ t('models.form.noProviderTip') }}
          </div>
        </el-form-item>
        <el-form-item :label="t('models.form.modelId')" required>
          <el-input v-model="form.model_name" placeholder="deepseek-chat" />
        </el-form-item>
        <el-form-item :label="t('models.form.displayName')" required>
          <el-input v-model="form.display_name" placeholder="DeepSeek Chat" />
        </el-form-item>
        <el-form-item :label="t('models.form.capabilities')">
          <el-select v-model="form.capabilities" multiple filterable allow-create :placeholder="t('models.form.capabilitiesPlaceholder')">
            <el-option v-for="tp in TASK_TYPES" :key="tp" :label="capLabel(tp)" :value="tp" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('models.form.inputPrice')">
          <el-input-number v-model="form.input_price" :min="0" :precision="2" />
        </el-form-item>
        <el-form-item :label="t('models.form.outputPrice')">
          <el-input-number v-model="form.output_price" :min="0" :precision="2" />
        </el-form-item>
        <el-form-item :label="t('models.form.contextWindow')">
          <el-input-number v-model="form.context_window" :min="1024" :step="1024" />
        </el-form-item>
        <el-form-item :label="t('models.form.priority')">
          <el-input-number v-model="form.priority" :min="1" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { t, capLabel } from '../../i18n'
import { createModel, deleteModel, getModelReferences, listModels, listProviders, updateModel } from '../../api'
import type { ModelItem, ModelReferences, Provider } from '../../types'
import { TASK_TYPES } from '../../types'

/** 表单态：provider_id 允许为空（未选择），提交前校验后转成数字；enabled 由列表开关单独维护。 */
type ModelForm = Omit<ModelItem, 'provider_id' | 'enabled'> & { provider_id: number | null }

const items = ref<ModelItem[]>([])
const providers = ref<Provider[]>([])
const providersLoading = ref(false)
const loading = ref(false)
const dlg = ref(false)
const saving = ref(false)

const emptyForm = (): ModelForm => ({
  id: 0, provider_id: null, model_name: '', display_name: '',
  capabilities: [] as string[], input_price: 0, output_price: 0,
  context_window: 8192, priority: 100,
})
const form = ref<ModelForm>(emptyForm())

/** 厂商 id → 名称，列表列展示用。 */
function providerName(id: number) {
  return providers.value.find((p) => p.id === id)?.name ?? `#${id}`
}

/** 厂商是否已接入（已启用且已配密钥）。模型的「启用」只有在此前提下才真正生效。 */
function providerReady(id: number): boolean {
  return providers.value.find((p) => p.id === id)?.routable === true
}

/**
 * 模型是否有机会被路由选中。刻意做成三态而非两态：
 * 只显示模型自身的开关，「已启用但厂商未接入」会被看成正常，
 * 而那种模型一次也不会被选中——界面与真实行为就对不上了。
 */
function routeState(row: ModelItem): { code: string; tone: string } {
  if (!providerReady(row.provider_id)) return { code: 'providerOff', tone: 'is-warning' }
  if (!row.enabled) return { code: 'disabled', tone: 'is-gray' }
  return { code: 'routable', tone: 'is-success' }
}

const onlyRoutable = ref(false)

/** 列表排序权重：正在参与路由的排最前。 */
const STATE_RANK: Record<string, number> = { routable: 0, disabled: 1, providerOff: 2 }
function stateRank(m: ModelItem): number {
  return STATE_RANK[routeState(m).code] ?? 9
}

/**
 * 默认展示全部：「哪些还没接入」本身就是要传达的信息，不该默认藏起来。
 * 但排序要先按路由状态：接入厂商目录后库里有几十个待接入的模型，
 * 若沿用后端的 priority 排序，使用者真正在用的那几个会沉到列表末尾——
 * 最该被看到的东西反而最难看到。
 */
const shown = computed(() => {
  const list = onlyRoutable.value
    ? items.value.filter((m) => m.enabled && providerReady(m.provider_id))
    : items.value
  return [...list].sort((a, b) =>
    stateRank(a) - stateRank(b) || a.priority - b.priority || a.id - b.id)
})

async function load() {
  loading.value = true
  try {
    // page_size 必须给足：后端默认 20，预置厂商目录后模型池会超过这个数，
    // 超出部分会被静默截断（界面上看不出少了东西）
    const data = await listModels({ page_size: 100 })
    items.value = data.items
  } finally {
    loading.value = false
  }
}

async function loadProviders() {
  providersLoading.value = true
  try {
    const data = await listProviders({ page: 1, page_size: 100 })
    providers.value = data.items
  } catch {
    providers.value = [] // 加载失败不阻塞页面，表单会提示「暂无可用厂商」
  } finally {
    providersLoading.value = false
  }
}

function openCreate() {
  form.value = emptyForm()
  // 仅有一个厂商时预选，省一次点击
  if (providers.value.length === 1) form.value.provider_id = providers.value[0].id
  dlg.value = true
}

function openEdit(row: ModelItem) {
  form.value = {
    id: row.id, provider_id: row.provider_id, model_name: row.model_name,
    display_name: row.display_name, capabilities: [...(row.capabilities ?? [])],
    input_price: row.input_price, output_price: row.output_price,
    context_window: row.context_window, priority: row.priority,
  }
  dlg.value = true
}

async function save() {
  const f = form.value
  if (!f.provider_id) {
    ElMessage.warning(t('models.msg.selectProvider'))
    return
  }
  if (!f.model_name.trim() || !f.display_name.trim()) {
    ElMessage.warning(t('models.msg.fillIdName'))
    return
  }
  const payload: Partial<ModelItem> = {
    provider_id: f.provider_id,
    model_name: f.model_name.trim(),
    display_name: f.display_name.trim(),
    capabilities: f.capabilities,
    input_price: f.input_price,
    output_price: f.output_price,
    context_window: f.context_window,
    priority: f.priority,
  }
  saving.value = true
  try {
    if (f.id) await updateModel(f.id, payload)
    else await createModel(payload)
    ElMessage.success(t('models.msg.saved'))
    dlg.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function toggle(row: ModelItem, enabled: boolean) {
  await updateModel(row.id, { enabled })
  if (enabled && !providerReady(row.provider_id)) {
    // 允许启用，但必须说清后果：厂商没接入时，启用了也不会进候选池
    ElMessage.warning(
      t('models.msg.providerNotConnected', { name: providerName(row.provider_id) }))
  }
  await load()
}

async function remove(row: ModelItem) {
  // 1) 先预检引用，避免「点了才发现删不掉」
  let refs: ModelReferences
  try {
    refs = await getModelReferences(row.id)
  } catch {
    return // 预检失败已由 axios 拦截器统一提示
  }

  // 2) 路由规则是 NOT NULL 强引用，无法解绑 —— 只给出路，不给强制选项
  if (refs.route_rules > 0) {
    await ElMessageBox.alert(
      `${t('models.msg.cannotDeleteBody', { rules: refs.route_rules })}<br/><br/>${t('models.msg.cannotDeleteHint')}`,
      t('models.msg.cannotDeleteTitle'),
      { type: 'warning', dangerouslyUseHTMLString: true, confirmButtonText: t('common.confirm') },
    ).catch(() => {}) // 关闭弹窗即 reject，静默处理
    return
  }

  // 3) 组装影响清单，让用户在确认前就看到后果
  const impacts: string[] = []
  if (refs.eval_cases) impacts.push(t('models.msg.impactEval', { n: refs.eval_cases }))
  if (refs.request_logs) impacts.push(t('models.msg.impactLogs', { n: refs.request_logs }))
  if (refs.decision_samples) impacts.push(t('models.msg.impactSamples', { n: refs.decision_samples }))
  const impactHtml = impacts.length
    ? `<div style="margin-top:8px;color:var(--text-2)">${t('models.msg.deleteAfter')}<br/>• ${impacts.join('<br/>• ')}</div>`
    : `<div style="margin-top:8px;color:var(--text-2)">${t('models.msg.noRefs')}</div>`

  const needsForce = refs.eval_cases > 0
  try {
    await ElMessageBox.confirm(
      `${t('models.msg.deleteConfirmPrefix', { name: row.display_name })}${impactHtml}`,
      t('models.msg.deleteConfirmTitle'),
      {
        type: 'warning',
        dangerouslyUseHTMLString: true,
        confirmButtonText: needsForce ? t('models.msg.forceDelete') : t('common.delete'),
        confirmButtonClass: needsForce ? 'el-button--danger' : undefined,
      },
    )
  } catch {
    return // 用户取消：ElMessageBox 以 reject 表示取消，静默返回即可
  }

  try {
    const res = await deleteModel(row.id, needsForce)
    const parts: string[] = []
    if (res?.unbound_evals) parts.push(t('models.msg.deletedEvals', { n: res.unbound_evals }))
    const unbound = (res?.unbound_logs ?? 0) + (res?.unbound_samples ?? 0)
    if (unbound) parts.push(t('models.msg.deletedUnbound', { n: unbound }))
    ElMessage.success(parts.length ? `${t('models.msg.deleted')}，${parts.join('，')}` : t('models.msg.deleted'))
    await load()
  } catch {
    // 409（存在引用）等错误已由 axios 拦截器统一提示，此处仅避免 Promise 逃逸成未处理异常
  }
}

onMounted(() => {
  load()
  loadProviders()
})
</script>

<style scoped>
.model-provider-tip {
  margin-top: 4px;
  color: var(--c-warning-text);
  font-size: 12px;
  line-height: 1.6;
}
.opt-warn {
  margin-left: 8px;
  padding: 0 6px;
  border-radius: 4px;
  background: var(--c-warning-bg, #fef3c7);
  color: var(--c-warning-text, #b45309);
  font-size: 11px;
}
</style>
