<template>
  <div class="app-anim-fade">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">{{ t('rules.page.title') }}</h2>
        <p class="app-page-desc">{{ t('rules.page.desc') }}</p>
      </div>
    </div>

    <div class="app-card">
      <div class="app-toolbar">
        <el-button type="primary" @click="openCreate">{{ t('rules.btn.create') }}</el-button>
        <el-button @click="load">{{ t('rules.btn.refresh') }}</el-button>
        <span class="app-toolbar-spacer" />
        <span class="hint">{{ t('rules.hint') }}</span>
      </div>
      <el-table :data="items" v-loading="loading">
        <el-table-column prop="priority" :label="t('rules.priority')" width="80" />
        <el-table-column prop="name" :label="t('rules.ruleName')" min-width="160" />
        <el-table-column prop="type" :label="t('rules.table.type')" width="110">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('rules.condition')" min-width="260">
          <template #default="{ row }"><code class="cond">{{ condText(row.condition_json) }}</code></template>
        </el-table-column>
        <el-table-column :label="t('rules.targetModel')" width="150">
          <template #default="{ row }">{{ modelName(row.target_model_id) }}</template>
        </el-table-column>
        <el-table-column :label="t('rules.enabled')" width="80">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="(v: unknown) => toggle(row, v as boolean)" />
          </template>
        </el-table-column>
        <el-table-column :label="t('rules.actions')" width="170" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="move(row, -1)" :disabled="row === items[0]">{{ t('rules.btn.up') }}</el-button>
            <el-button link type="primary" @click="move(row, 1)" :disabled="row === items[items.length - 1]">{{ t('rules.btn.down') }}</el-button>
            <el-button link type="danger" @click="remove(row)">{{ t('rules.btn.delete') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dlg" :title="form.id ? t('rules.dialog.edit') : t('rules.dialog.create')" width="620px" append-to-body>
      <el-form :model="form" label-width="110px">
        <el-form-item :label="t('rules.ruleName')" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item :label="t('rules.priority')"><el-input-number v-model="form.priority" :min="1" /></el-form-item>
        <el-form-item :label="t('rules.form.type')">
          <el-select v-model="form.type" @change="applyTypeToConds">
            <el-option :label="t('rules.type.keyword')" value="keyword" />
            <el-option :label="t('rules.type.regex')" value="regex" />
            <el-option :label="t('rules.type.tokenLen')" value="token_len" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('rules.form.condition')">
          <div class="conds">
            <p class="cond-hint">{{ t('rules.condHint') }}</p>
            <div v-for="(c, i) in conds" :key="i" class="cond-row">
              <el-select v-model="c.op" style="width:130px">
                <el-option v-for="o in opsFor(form.type)" :key="o" :label="t(`rules.op.${o}`)" :value="o" />
              </el-select>
              <el-input-number
                v-if="form.type === 'token_len'"
                v-model="(c.value as number)"
                :min="0" :controls="false" style="width:180px"
              />
              <el-input
                v-else
                v-model="c.value"
                :placeholder="form.type === 'regex' ? t('rules.placeholder.regex') : t('rules.placeholder.keyword')"
                style="width:180px"
              />
              <el-button link type="danger" @click="conds.splice(i, 1)">{{ t('rules.btn.removeCond') }}</el-button>
            </div>
            <el-button link type="primary" @click="addCond">
              {{ t('rules.btn.addCond') }}
            </el-button>
          </div>
        </el-form-item>
        <el-form-item :label="t('rules.targetModel')" required>
          <el-select v-model="form.target_model_id" style="width:260px">
            <el-option v-for="m in modelOpts" :key="m.id" :label="`${m.display_name} (${m.model_name})`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('rules.remark')"><el-input v-model="form.remark" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">{{ t('rules.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="save">{{ t('rules.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { t } from '../../i18n'
import { createRule, deleteRule, listModels, listRules, reorderRules, updateRule } from '../../api'
import type { RouteRule } from '../../types'

interface Cond { field: string; op: string; value: string | number }

const items = ref<RouteRule[]>([])
const modelOpts = ref<{ id: number; display_name: string; model_name: string }[]>([])
const loading = ref(false)
const dlg = ref(false)
const saving = ref(false)
const conds = reactive<Cond[]>([])

const emptyForm = () => ({ id: 0, name: '', priority: 100, type: 'keyword', target_model_id: 1, remark: '' })
const form = ref(emptyForm())

const NUM_OPS = ['gt', 'gte', 'lt', 'lte']

/** 规则类型 → 条件形态（type 必须忠实描述 condition，后端有同口径校验） */
const TYPE_FIELD: Record<string, string> = { keyword: 'text', regex: 'text', token_len: 'token_len' }
const OPS_BY_TYPE: Record<string, string[]> = {
  keyword: ['contains', 'not_contains'],
  regex: ['regex'],
  token_len: NUM_OPS,
}
const DEFAULT_OP: Record<string, string> = { keyword: 'contains', regex: 'regex', token_len: 'gt' }

function opsFor(type: string): string[] {
  return OPS_BY_TYPE[type] ?? OPS_BY_TYPE.keyword
}

/** 切换规则类型后，把已有条件归一到该类型：field 强制、op 按法集合纠正、value 尽量保留。 */
function applyTypeToConds() {
  const type = form.value.type
  const field = TYPE_FIELD[type] ?? 'text'
  const ops = opsFor(type)
  for (const c of conds) {
    if (c.field !== field) {
      c.value = field === 'token_len' ? Number(c.value) || 0 : String(c.value ?? '')
    }
    c.field = field
    if (!ops.includes(c.op)) c.op = ops[0]
  }
  if (!conds.length) {
    conds.push({ field, op: DEFAULT_OP[type] ?? 'contains', value: field === 'token_len' ? 0 : '' })
  }
}

function addCond() {
  const type = form.value.type
  conds.push({ field: TYPE_FIELD[type] ?? 'text', op: DEFAULT_OP[type] ?? 'contains', value: type === 'token_len' ? 0 : '' })
}

async function load() {
  loading.value = true
  try {
    const [ruleData, modelData] = await Promise.all([listRules(), listModels()])
    items.value = ruleData.items
    modelOpts.value = modelData.items
  } finally {
    loading.value = false
  }
}

function modelName(id: number): string {
  return modelOpts.value.find((m) => m.id === id)?.display_name ?? `#${id}`
}

function condText(cond: RouteRule['condition_json']): string {
  return (cond?.all ?? []).map((c) => `${c.field} ${c.op} "${c.value}"`).join(' AND ')
}

function openCreate() {
  form.value = emptyForm()
  conds.splice(0, conds.length)
  applyTypeToConds()  // 按默认类型（keyword）生成第一条条件
  dlg.value = true
}

function conditionJson(): string {
  const all = conds.map((c) => ({
    field: c.field, op: c.op,
    value: c.field === 'token_len' ? Number(c.value) || 0 : c.value,
  }))
  return JSON.stringify({ all })
}

async function save() {
  saving.value = true
  try {
    const payload = { ...form.value, condition_json: conditionJson() }
    if (form.value.id) await updateRule(form.value.id, payload)
    else await createRule(payload)
    ElMessage.success(t('rules.saved'))
    dlg.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function toggle(row: RouteRule, enabled: boolean) {
  await updateRule(row.id, { enabled })
  await load()
}

async function move(row: RouteRule, dir: -1 | 1) {
  const idx = items.value.indexOf(row)
  const swapWith = items.value[idx + dir]
  if (!swapWith) return
  await reorderRules(items.value.map((r) => r.id).map((id) => (id === row.id ? swapWith.id : id === swapWith.id ? row.id : id)))
  await load()
}

async function remove(row: RouteRule) {
  try {
    await ElMessageBox.confirm(t('rules.confirmDelete', { name: row.name }), t('rules.confirmTitle'), { type: 'warning' })
  } catch {
    return // 用户取消
  }
  try {
    await deleteRule(row.id)
    ElMessage.success(t('rules.deleted'))
    await load()
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}

onMounted(load)
</script>

<style scoped>
.hint {
  font-size: 12px;
  color: var(--text-3);
}
.cond {
  font-size: 12px;
}
.conds {
  width: 100%;
}
.cond-hint {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--text-3);
}
.cond-row {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
  align-items: center;
}
</style>
