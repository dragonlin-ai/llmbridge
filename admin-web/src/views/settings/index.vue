<template>
  <div class="app-anim-fade">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">{{ t('settings.page.title') }}</h2>
        <p class="app-page-desc">{{ t('settings.page.desc') }}</p>
      </div>
    </div>

    <div class="app-card" v-loading="loading">
      <div class="app-toolbar">
        <el-tag v-if="data" :type="activeTagType" effect="plain" :style="activeStyle">
          {{ t('settings.status.active') }}：{{ activeLabel }}
        </el-tag>
        <el-tag v-if="mismatch" type="warning" effect="plain">{{ t('settings.status.mismatch') }}</el-tag>
        <span class="app-toolbar-spacer" />
        <el-button @click="load">{{ t('settings.action.refresh') }}</el-button>
      </div>

      <div class="form-body">
        <el-form :model="form" label-width="170px">
          <el-form-item :label="t('settings.field.judge')">
            <div class="field-block">
              <div class="field-row">
                <el-select v-model="form.judge_provider" style="width: 250px">
                  <el-option :label="t('settings.option.mock')" value="mock" />
                  <el-option :label="t('settings.option.jev')" value="jev" />
                </el-select>
                <el-tag size="small" effect="circle" type="info">{{ sourceLabel('judge_provider') }}</el-tag>
                <span class="field-hint">
                  {{ form.judge_provider === 'jev' ? t('settings.hint.judge.jev') : t('settings.hint.judge.mock') }}
                </span>
              </div>
            </div>
          </el-form-item>

          <el-form-item :label="t('settings.field.apiKey')">
            <div class="field-block">
              <div class="field-row">
                <el-input
                  v-model="form.jev_api_key"
                  type="password"
                  show-password
                  clearable
                  :placeholder="keyPlaceholder"
                  style="width: 320px"
                />
                <el-tag v-if="data?.jev_api_key_set" size="small" effect="circle" type="success">
                  {{ t('settings.key.configured') }}
                </el-tag>
                <el-tag size="small" effect="circle" type="info">{{ sourceLabel('jev_api_key') }}</el-tag>
                <el-button
                  v-if="!readonly && data?.sources?.jev_api_key === 'db'"
                  link
                  type="danger"
                  :disabled="saving"
                  @click="clearKey"
                >
                  {{ t('settings.action.clearKey') }}
                </el-button>
              </div>
              <p class="field-hint">{{ t('settings.hint.apiKey') }}</p>
            </div>
          </el-form-item>

          <el-form-item :label="t('settings.field.baseUrl')">
            <div class="field-block">
              <div class="field-row">
                <el-input v-model="form.jev_base_url" style="width: 420px" />
                <el-tag size="small" effect="circle" type="info">{{ sourceLabel('jev_base_url') }}</el-tag>
              </div>
              <p class="field-hint">{{ t('settings.hint.baseUrl') }}</p>
            </div>
          </el-form-item>

          <el-form-item :label="t('settings.field.timeout')">
            <div class="field-block">
              <div class="field-row">
                <el-input-number
                  v-model="form.decider_timeout_ms"
                  :min="100"
                  :max="60000"
                  :step="100"
                />
                <el-tag size="small" effect="circle" type="info">{{ sourceLabel('decider_timeout_ms') }}</el-tag>
                <span class="field-hint">{{ t('settings.hint.timeout') }}</span>
              </div>
            </div>
          </el-form-item>

          <el-form-item :label="t('settings.field.threshold')">
            <div class="field-block">
              <div class="field-row">
                <el-input-number
                  v-model="form.route_confidence_threshold_t2"
                  :min="0"
                  :max="1"
                  :step="0.05"
                  :precision="2"
                />
                <el-tag size="small" effect="circle" type="info">
                  {{ sourceLabel('route_confidence_threshold_t2') }}
                </el-tag>
                <span class="field-hint">{{ t('settings.hint.threshold') }}</span>
              </div>
            </div>
          </el-form-item>
        </el-form>

        <div class="form-actions">
          <el-button
            type="primary"
            :loading="saving"
            :disabled="readonly"
            :title="readonly ? t('settings.readonly.tip') : undefined"
            @click="save"
          >
            {{ t('settings.action.save') }}
          </el-button>
          <el-button
            :loading="testing"
            :disabled="readonly"
            :title="readonly ? t('settings.readonly.tip') : undefined"
            @click="runTest"
          >
            {{ t('settings.action.test') }}
          </el-button>
          <span class="test-hint">{{ t('settings.test.hint') }}</span>
          <el-tag v-if="testResult?.healthy" type="success" effect="light">
            {{ t('settings.test.ok', { ms: testResult.latency_ms ?? 0 }) }}
          </el-tag>
          <el-tag v-else-if="testResult" type="danger" effect="light">
            {{ t('settings.test.fail', { reason: testResult.reason ?? '' }) }}
          </el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getDeciderSettings, testDeciderSettings, updateDeciderSettings } from '../../api'
import { t } from '../../i18n'
import { LAYER_COLORS, type DeciderSettings, type DeciderTestResult } from '../../types'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const readonly = ref(false)
const data = ref<DeciderSettings | null>(null)
const testResult = ref<DeciderTestResult | null>(null)

const form = reactive({
  judge_provider: 'mock',
  jev_api_key: '',
  jev_base_url: '',
  decider_timeout_ms: 3000,
  route_confidence_threshold_t2: 0.5,
})

/** 实际生效判定器的显示名（语料缺 key 时回退原始值）。 */
const activeLabel = computed(() => {
  const n = data.value?.active_decider
  if (!n) return '—'
  const key = `settings.deciderName.${n}`
  const label = t(key)
  return label === key ? n : label
})

const activeTagType = computed(() => (data.value?.active_decider === 'jev' ? 'primary' : 'info'))

/** Jev 即 L2：状态标沿用层级紫（LAYER_COLORS.L2），与日志/试跑台口径一致。 */
const activeStyle = computed(() =>
  data.value?.active_decider === 'jev'
    ? { color: LAYER_COLORS.L2, borderColor: LAYER_COLORS.L2 }
    : undefined,
)

/** 配置值 ≠ 生效值：选了 jev 但密钥缺失（build_decider 静默回退 mock）。 */
const mismatch = computed(
  () => data.value?.judge_provider === 'jev' && data.value?.active_decider !== 'jev',
)

const keyPlaceholder = computed(() =>
  t('settings.key.placeholder', {
    mask: data.value?.jev_api_key_masked ?? t('settings.key.none'),
  }),
)

function sourceLabel(key: string): string {
  return t(data.value?.sources?.[key] === 'db' ? 'settings.source.db' : 'settings.source.env')
}

async function load(): Promise<void> {
  loading.value = true
  try {
    data.value = await getDeciderSettings()
    form.judge_provider = data.value.judge_provider
    form.jev_api_key = ''
    form.jev_base_url = data.value.jev_base_url
    form.decider_timeout_ms = data.value.decider_timeout_ms
    form.route_confidence_threshold_t2 = data.value.route_confidence_threshold_t2
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  const payload: {
    judge_provider: string
    jev_base_url: string
    decider_timeout_ms: number
    route_confidence_threshold_t2: number
    jev_api_key?: string
  } = {
    judge_provider: form.judge_provider,
    jev_base_url: form.jev_base_url,
    decider_timeout_ms: form.decider_timeout_ms,
    route_confidence_threshold_t2: form.route_confidence_threshold_t2,
  }
  // 密钥只在用户真的输入时提交：留空 = 不修改（掩码占位不会进入 v-model）
  if (form.jev_api_key) payload.jev_api_key = form.jev_api_key
  saving.value = true
  try {
    data.value = await updateDeciderSettings(payload)
    form.jev_api_key = ''
    testResult.value = null // 配置已变，旧测试结果作废
    ElMessage.success(t('settings.msg.saved'))
  } finally {
    saving.value = false
  }
}

async function clearKey(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.clearKey'),
      t('settings.action.clearKey'),
      { type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  saving.value = true
  try {
    data.value = await updateDeciderSettings({ jev_api_key: '' })
    ElMessage.success(t('settings.msg.saved'))
  } finally {
    saving.value = false
  }
}

async function runTest(): Promise<void> {
  testing.value = true
  try {
    testResult.value = await testDeciderSettings()
  } finally {
    testing.value = false
  }
}

/** JWT 里带 role；readonly 账号直接禁用写操作（后端仍会拦 403，这里只是不给假动作）。 */
function detectReadonly(): void {
  try {
    const token = localStorage.getItem('token') || ''
    const payload = JSON.parse(atob(token.split('.')[1] || '{}'))
    if (payload?.role && payload.role !== 'admin') readonly.value = true
  } catch {
    /* token 非标准 JWT 时按可写处理，越权由后端 403 兜底 */
  }
}

onMounted(() => {
  detectReadonly()
  void load()
})
</script>

<style scoped>
.form-body {
  padding: 20px;
}
.field-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.field-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-3);
}
.form-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 4px;
  padding-top: 16px;
  border-top: 1px solid var(--border-base);
}
.test-hint {
  font-size: 12px;
  color: var(--text-3);
}
</style>
