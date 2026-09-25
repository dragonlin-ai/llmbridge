<template>
  <div class="app-anim-fade">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">{{ t('playground.page.title') }}</h2>
        <p class="app-page-desc">
          {{ t('playground.page.desc') }}
        </p>
      </div>
    </div>

    <div class="app-card">
      <div class="app-card-header">
        <span>{{ t('playground.input.title') }}</span>
        <span v-if="result" class="app-badge is-gray">
          {{ result.latency_ms }}ms · {{ result.trace_id }}
        </span>
      </div>
      <div class="app-card-body">
        <el-input v-model="text" type="textarea" :rows="4" maxlength="2000" show-word-limit
                  :placeholder="t('playground.input.placeholder')" />
        <div class="actions">
          <el-button type="primary" :loading="loading" @click="run">{{ t('playground.btn.run') }}</el-button>
          <el-button @click="reset">{{ t('playground.btn.clear') }}</el-button>
          <div class="exec-toggle">
            <el-switch v-model="execute" :disabled="loading" />
            <span class="exec-label">{{ t('playground.exec.label') }}</span>
            <el-input-number v-if="execute" v-model="maxTokens" :min="1" :max="4096" :step="128"
                             size="small" :disabled="loading" class="exec-tokens" />
            <span class="exec-hint">
              {{ t('playground.exec.hint') }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="result" class="app-card mt">
      <div class="app-card-header">
        <span>{{ t('playground.chain.title') }}</span>
        <span class="app-badge" :class="layerTone(result.hit_layer)">{{ t('playground.chain.hit', { layer: result.hit_layer }) }}</span>
      </div>
      <div class="app-card-body">
        <RouteChainBar :hit-layer="result.hit_layer" />
        <el-descriptions :column="3" border class="mt">
          <el-descriptions-item :label="t('playground.desc.hitLayer')">
            <span class="app-badge" :class="layerTone(result.hit_layer)">{{ result.hit_layer }}</span>
          </el-descriptions-item>
          <el-descriptions-item :label="t('playground.desc.taskType')">
            {{ result.task_type ? taskLabel(result.task_type) : '—' }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('playground.desc.confidence')">{{ result.confidence ?? '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('playground.desc.decider')">
            <span class="app-badge" :class="deciderTone">{{ deciderName }}</span>
            <span class="decider-hint" v-if="deciderHint">{{ deciderHint }}</span>
          </el-descriptions-item>
          <el-descriptions-item :label="t('playground.desc.selectedModel')" :span="2">
            {{ result.selected_model?.display_name }}（{{ result.selected_model?.model_name }}）
          </el-descriptions-item>
          <el-descriptions-item :label="t('playground.desc.fallbackReason')" :span="3">{{ result.fallback_reason ?? '—' }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </div>

    <!-- 真实调用结果：仅开启「调用选中模型」时出现 -->
    <div v-if="result?.execution" class="app-card mt">
      <div class="app-card-header">
        <span>{{ t('playground.execResult.title') }}</span>
        <span class="app-badge" :class="result.execution.ok ? 'is-success' : 'is-danger'">
          {{ result.execution.ok
            ? t('playground.execResult.ok', { ms: result.execution.latency_ms ?? '—' })
            : t('playground.execResult.fail', { code: result.execution.error_code ?? '—' }) }}
        </span>
      </div>
      <div class="app-card-body">
        <div class="exec-note">
          {{ t('playground.execResult.note') }}
        </div>
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item :label="t('playground.execResult.actualModel')">
            {{ result.execution.display_name }}（{{ result.execution.model_name }}）
          </el-descriptions-item>
          <el-descriptions-item :label="t('playground.execResult.provider')">{{ result.execution.provider_name ?? '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('playground.execResult.upstreamLatency')">{{ result.execution.latency_ms ?? '—' }} ms</el-descriptions-item>
          <el-descriptions-item :label="t('playground.execResult.finishReason')">{{ result.execution.finish_reason ?? '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('playground.execResult.token')">
            <template v-if="result.execution.usage">
              {{ t('playground.execResult.in') }} {{ result.execution.usage.prompt_tokens }} / {{ t('playground.execResult.out') }} {{ result.execution.usage.completion_tokens }}
              （{{ t('playground.execResult.total') }} {{ result.execution.usage.total_tokens }}）
              <span v-if="result.execution.usage.reasoning_tokens" class="token-note">
                {{ t('playground.execResult.reasoning', { n: result.execution.usage.reasoning_tokens }) }}
              </span>
            </template>
            <template v-else>—</template>
          </el-descriptions-item>
          <el-descriptions-item :label="t('playground.execResult.cost')">
            ¥{{ (result.execution.cost ?? 0).toFixed(6) }}
            <span v-if="!result.execution.cost" class="token-note">{{ t('playground.execResult.noPrice') }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <template v-if="result.execution.ok">
          <div class="output-title">
            {{ t('playground.execResult.outputTitle') }}
            <span class="output-note">
              {{ t('playground.execResult.outputNote') }}
            </span>
          </div>
          <pre class="output-block">{{ result.execution.content || emptyContentHint }}</pre>
        </template>
        <div v-else class="call-error">
          <strong>{{ result.execution.error_code }}</strong>
          <span>{{ result.execution.error }}</span>
          <span class="call-error-note">{{ t('playground.execResult.callErrorNote') }}</span>
        </div>
      </div>
    </div>

    <div v-if="result && !result.execution" class="call-skip">
      {{ t('playground.callSkip') }}
    </div>

    <div v-if="result?.probabilities" class="app-card mt">
      <div class="app-card-header">
        <span>{{ t('playground.prob.title') }}</span>
        <span class="app-badge" :class="deciderTone">{{ t('playground.prob.decidedBy', { name: deciderName }) }}</span>
      </div>
      <div class="app-card-body">
        <ProbChart :probabilities="result.probabilities" />
        <el-descriptions v-if="result.features" :column="3" border class="mt" size="small">
          <el-descriptions-item label="complexity">{{ result.features.complexity }}</el-descriptions-item>
          <el-descriptions-item label="has_code">{{ result.features.has_code }}</el-descriptions-item>
          <el-descriptions-item label="is_sensitive">{{ result.features.is_sensitive }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </div>

    <div v-if="result?.candidates?.length" class="app-card mt">
      <div class="app-card-header">
        <span>{{ t('playground.candidates.title') }}</span>
        <span class="app-badge is-gray">{{ t('playground.candidates.count', { n: result.candidates.length }) }}</span>
      </div>
      <div class="app-card-body">
        <div class="basis-note">
          <span class="basis-label">{{ t('playground.candidates.basisLabel') }}</span>
          <span>{{ result.selection_basis }}</span>
        </div>
        <el-table :data="result.candidates" size="small" class="basis-table">
          <el-table-column :label="t('playground.candidates.colModel')" min-width="170">
            <template #default="{ row }">
              <div class="model-cell">
                <span>{{ row.display_name }}</span>
                <span v-if="row.picked" class="app-badge is-primary">{{ t('playground.candidates.selected') }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="model_name" :label="t('playground.candidates.colId')" min-width="140">
            <template #default="{ row }"><code class="app-code">{{ row.model_name }}</code></template>
          </el-table-column>
          <el-table-column :label="t('playground.candidates.colInputPrice')" width="100">
            <template #default="{ row }">{{ row.input_price }}</template>
          </el-table-column>
          <el-table-column :label="t('playground.candidates.colCapability')" width="100">
            <template #default="{ row }">
              <span v-if="row.eligibility === 'hit'" class="app-badge is-success">{{ t('playground.candidates.hit') }}</span>
              <span v-else-if="row.eligibility === 'none'" class="app-badge is-warning">{{ t('playground.candidates.notDeclared') }}</span>
              <span v-else class="app-badge is-gray">{{ t('playground.candidates.ruleDirected') }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('playground.candidates.colScore')" width="200">
            <template #default="{ row }">
              <div class="score-cell">
                <div class="app-progress score-bar">
                  <div
                    class="app-progress-bar"
                    :class="{ 'is-dim': !row.picked }"
                    :style="{ width: Math.round(row.score * 100) + '%' }"
                  />
                </div>
                <span class="score-num">{{ (row.score * 100).toFixed(1) }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="t('playground.candidates.colRule')" width="140">
            <template #default="{ row }">{{ ruleName(row.matched_rule) }}</template>
          </el-table-column>
        </el-table>
        <div class="basis-legend">
          {{ t('playground.candidates.legend') }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { t, taskLabel } from '../../i18n'
import RouteChainBar from '../../components/RouteChainBar.vue'
import ProbChart from '../../components/ProbChart.vue'
import { routePreview } from '../../api'
import type { PreviewResult } from '../../types'

const text = ref('')
const loading = ref(false)
const result = ref<PreviewResult | null>(null)
/** 是否在决策之外真实调用选中模型（默认关，保持「零成本试跑」为默认行为） */
const execute = ref(false)
const maxTokens = ref(512)

/** 路由层级 → 徽章色调（与概览看板 / 调用日志保持一致） */
function layerTone(layer: string) {
  if (layer === 'L1') return 'is-success'
  if (layer === 'L2') return 'is-purple'
  return 'is-danger'
}

/** 判定器名：优先显示实际产出判定的实现，其次显示本次装载的实现 */
const deciderName = computed(
  () => result.value?.decider ?? result.value?.active_decider ?? '—',
)

const deciderTone = computed(() => {
  const n = result.value?.decider
  if (n === 'jev') return 'is-primary'
  if (n === 'mock') return 'is-gray'
  return 'is-warning'
})

/**
 * 判定器该出结果却没出结果 = 异常（L1 规则短路不经过判定器，属正常）。
 * 没有这个提示的话，「Jev 调用失败」会伪装成「置信度低走了 L3」。
 */
const showDeciderWarn = computed(() => {
  const r = result.value
  if (!r) return false
  return r.hit_layer !== 'L1' && !r.decider
})

/**
 * 配置值 ≠ 生效值：选了 jev 但判定器实际是 mock（缺 JEV_API_KEY，或 JEV API 对大陆不可达）。
 * 试跑台必须把这点讲清，否则「我明明选了 JEV 怎么还是 Mock」无从解释 —— 这是设置页
 * 已有 mismatch 提示的镜像，用户在试跑台看到 mock 时同样需要这层解释。
 */
const deciderMismatch = computed(() => {
  const r = result.value
  if (!r) return false
  return r.judge_provider === 'jev' && r.active_decider !== 'jev'
})

/** 判定器行的最终提示文案：mismatch 优先（配置≠生效），其次才是「判定器没出结果」。 */
const deciderHint = computed(() => {
  const r = result.value
  if (!r) return ''
  if (deciderMismatch.value) return t('playground.desc.deciderMismatch')
  if (showDeciderWarn.value) {
    return r.decider_error ?? r.fallback_reason ?? t('playground.desc.deciderNoOutput')
  }
  return ''
})

/**
 * 输出为空的解释。
 * 推理模型的思考 token 计入 completion_tokens，max_tokens 太小时会被思考全部占满，
 * 返回 content="" 且 finish_reason=length —— 必须说清，否则会被误判成「调用失败」。
 */
const emptyContentHint = computed(() => {
  const ex = result.value?.execution
  if (ex && ex.finish_reason === 'length') {
    return t('playground.execResult.emptyLength')
  }
  return t('playground.execResult.empty')
})

async function run() {
  if (!text.value.trim()) {
    ElMessage.warning(t('playground.msg.emptyText'))
    return
  }
  loading.value = true
  try {
    result.value = await routePreview(text.value.trim(), undefined, execute.value, maxTokens.value)
  } finally {
    loading.value = false
  }
}

function reset() {
  text.value = ''
  result.value = null
}

function ruleName(r: unknown): string {
  if (r && typeof r === 'object' && 'name' in r) return String((r as { name: unknown }).name)
  return '—'
}
</script>

<style scoped>
.mt {
  margin-top: 20px;
}
.actions {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.exec-toggle {
  margin-left: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.exec-label {
  font-size: 13px;
  color: var(--text-2);
}
.exec-hint {
  font-size: 12px;
  color: var(--text-3);
}
.exec-tokens {
  width: 110px;
}
.output-title {
  margin: 16px 0 8px;
  font-size: 13px;
  color: var(--text-2);
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.output-note {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-3);
}
.exec-note {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--bg-subtle);
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-2);
}
.basis-note {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--bg-subtle);
  border-left: 3px solid var(--p-600);
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-1);
}
html.dark .basis-note {
  border-left-color: var(--p-400);
}
.basis-label {
  flex: none;
  font-weight: 600;
  color: var(--p-700);
}
html.dark .basis-label {
  color: var(--p-300);
}
.basis-table {
  margin-top: 12px;
}
.basis-legend {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-3);
}
.model-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.output-block {
  margin: 0;
  padding: 14px 16px;
  border-radius: 10px;
  background: var(--bg-subtle);
  color: var(--text-1);
  font-size: 13px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 340px;
  overflow: auto;
}
.call-error {
  margin-top: 16px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--c-danger-soft);
  color: var(--c-danger-text);
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}
.call-error-note {
  opacity: 0.85;
  font-size: 12px;
}
.call-skip {
  margin-top: 16px;
  font-size: 12px;
  color: var(--text-3);
}
.token-note {
  font-size: 12px;
  color: var(--text-3);
}
.score-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.score-bar {
  flex: 1;
}
.score-bar .app-progress-bar.is-dim {
  background: var(--n-300);
}
html.dark .score-bar .app-progress-bar.is-dim {
  background: var(--n-600);
}
.score-num {
  width: 44px;
  text-align: right;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: var(--text-3);
}
.decider-hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--c-warning-text);
}
</style>
