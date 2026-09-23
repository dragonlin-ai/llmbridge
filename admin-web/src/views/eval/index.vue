<template>
  <div class="app-anim-fade">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">{{ t('eval.title') }}</h2>
        <p class="app-page-desc">{{ t('eval.subtitle') }}</p>
      </div>
      <div class="app-page-actions">
        <el-radio-group v-model="limit" size="default" :disabled="loading" @change="load">
          <el-radio-button :value="20">{{ t('eval.limit20') }}</el-radio-button>
          <el-radio-button :value="50">{{ t('eval.limit50') }}</el-radio-button>
          <el-radio-button :value="100">{{ t('eval.limit100') }}</el-radio-button>
        </el-radio-group>
        <el-button type="primary" :loading="loading" @click="load">
          {{ t('eval.run') }}
        </el-button>
      </div>
    </div>

    <!-- 评测口径与运行事实：样本数、耗时、候选池规模、判定器连通性一律明示，
         否则「准确率」会被误读成对全量样本、全量模型成立。 -->
    <div v-if="report && !report.empty" class="app-card runbar">
      <div class="app-card-body">
        <div class="facts">
          <span class="fact">
            <el-icon><Files /></el-icon>
            {{ t('eval.factSamples', { used: report.used_cases, total: report.total_cases }) }}
          </span>
          <span class="fact">
            <el-icon><Timer /></el-icon>
            {{ t('eval.factElapsed', { ms: report.elapsed_ms ?? 0 }) }}
          </span>
          <span class="fact">
            <el-icon><Connection /></el-icon>
            {{ t('eval.factPool', { n: report.routable_models ?? 0 }) }}
          </span>
          <span class="fact">
            <el-icon><Cpu /></el-icon>
            {{ t('eval.factModelTruth', { n: report.model_truth_cases ?? 0 }) }}
          </span>
          <span class="app-badge" :class="report.jev_healthy ? 'is-success' : 'is-danger'">
            {{ report.jev_healthy ? t('eval.jevOk') : t('eval.jevDown') }}
          </span>
        </div>

        <p v-if="report.truncated" class="warn">
          <el-icon><WarningFilled /></el-icon>
          {{ t('eval.truncatedHint', { used: report.used_cases, total: report.total_cases }) }}
        </p>
        <p v-if="!report.model_truth_cases" class="warn">
          <el-icon><WarningFilled /></el-icon>
          {{ t('eval.noModelTruthHint') }}
        </p>
        <p v-if="(report.routable_models ?? 0) < 5" class="warn">
          <el-icon><WarningFilled /></el-icon>
          {{ t('eval.smallPoolHint', { n: report.routable_models ?? 0 }) }}
        </p>
        <p v-if="report.jev_last_error" class="warn">
          <el-icon><WarningFilled /></el-icon>
          {{ t('eval.jevError', { msg: report.jev_last_error }) }}
        </p>
      </div>
    </div>

    <!-- 双侧对比 -->
    <div v-if="report && !report.empty" class="app-grid app-grid-2 section">
      <div v-for="s in sides" :key="s.key" class="app-card">
        <div class="app-card-header">
          <span>{{ t('eval.side.' + s.key) }}</span>
          <span class="app-badge" :class="s.tone">{{ t('eval.side.' + s.key + 'Tag') }}</span>
        </div>
        <div class="app-card-body">
          <div class="metrics">
            <div class="metric">
              <div class="metric-value">{{ pct(s.data?.task_accuracy) }}</div>
              <div class="metric-label">{{ t('eval.metric.taskAccuracy') }}</div>
              <div class="metric-sub">
                {{ t('eval.metric.hitOf', { ok: s.data?.task_ok ?? 0, n: s.data?.task_total ?? 0 }) }}
              </div>
            </div>
            <div class="metric">
              <div class="metric-value">{{ pct(s.data?.model_accuracy) }}</div>
              <div class="metric-label">{{ t('eval.metric.modelAccuracy') }}</div>
              <div class="metric-sub">
                {{ t('eval.metric.hitOf', { ok: s.data?.model_ok ?? 0, n: s.data?.model_total ?? 0 }) }}
              </div>
            </div>
          </div>

          <div class="layer-dist">
            <div v-for="l in layerRows" :key="l.layer" class="layer-row">
              <span class="app-badge" :class="toneOf(l.layer)">{{ l.layer }}</span>
              <div class="app-progress layer-bar">
                <div
                  class="app-progress-bar"
                  :style="{ width: layerPct(s.key === 'mock' ? l.mock : l.jev, s.key) + '%' }"
                />
              </div>
              <span class="layer-count">{{ s.key === 'mock' ? l.mock : l.jev }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 混淆矩阵：可在两测之间切换，同一坐标系下逐格对比 -->
    <div v-if="report && !report.empty" class="app-card section">
      <div class="app-card-header">
        <span>{{ t('eval.matrix.title') }}</span>
        <el-radio-group v-model="matrixSide" size="small">
          <el-radio-button value="mock">{{ t('eval.side.mock') }}</el-radio-button>
          <el-radio-button value="jev">{{ t('eval.side.jev') }}</el-radio-button>
        </el-radio-group>
      </div>
      <div class="app-card-body">
        <p class="hint-block">{{ t('eval.matrix.hint') }}</p>
        <el-table :data="matrixRows.rows" size="small" :border="true">
          <el-table-column prop="expected" :label="t('eval.matrix.expected')" min-width="160" fixed>
            <template #default="{ row }">
              <span :title="row.expected">{{ taskLabel(row.expected) }}</span>
            </template>
          </el-table-column>
          <el-table-column v-for="c in matrixRows.cols" :key="c" :label="taskLabel(c)" min-width="140">
            <template #default="{ row }">
              <span :class="{ 'cell-hit': row.cells[c] > 0 && c === row.expected }">
                {{ row.cells[c] }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="total" :label="t('eval.matrix.rowTotal')" width="90" />
        </el-table>
      </div>
    </div>

    <!-- 逐条明细 -->
    <div v-if="report && !report.empty" class="app-card section">
      <div class="app-card-header">
        <span>{{ t('eval.detail.title') }}</span>
        <span class="app-badge is-gray">{{ t('eval.detail.count', { n: report.items.length }) }}</span>
      </div>
      <el-table :data="report.items" size="default">
        <el-table-column prop="case_id" :label="t('eval.detail.id')" width="70" />
        <el-table-column :label="t('eval.detail.input')" min-width="220">
          <template #default="{ row }">
            <span :title="row.input_text">{{ row.input_text }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('eval.detail.expected')" min-width="130">
          <template #default="{ row }">
            <span :title="row.expected_task_type">{{ taskLabel(row.expected_task_type) }}</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('eval.detail.mockPredicted')" min-width="150">
          <template #default="{ row }">
            <span :title="row.predicted_task_type || ''">
              {{ row.predicted_task_type ? taskLabel(row.predicted_task_type) : t('eval.na') }}
            </span>
            <span class="app-badge" :class="row.task_ok ? 'is-success' : 'is-danger'">
              {{ row.task_ok ? t('eval.hit') : t('eval.miss') }}
            </span>
          </template>
        </el-table-column>

        <el-table-column :label="t('eval.detail.jevPredicted')" min-width="150">
          <template #default="{ row }">
            <span :title="row.jev_predicted_task_type || ''">
              {{ row.jev_predicted_task_type ? taskLabel(row.jev_predicted_task_type) : t('eval.na') }}
            </span>
            <span class="app-badge" :class="row.jev_task_ok ? 'is-success' : 'is-danger'">
              {{ row.jev_task_ok ? t('eval.hit') : t('eval.miss') }}
            </span>
          </template>
        </el-table-column>

        <el-table-column :label="t('eval.detail.layer')" width="90">
          <template #default="{ row }">
            <span class="app-badge" :class="toneOf(row.hit_layer)">{{ row.hit_layer || t('eval.na') }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('eval.detail.model')" min-width="140">
          <template #default="{ row }">
            <code class="app-code">{{ row.selected_model_name || t('eval.na') }}</code>
          </template>
        </el-table-column>
        <el-table-column :label="t('eval.detail.confidence')" width="110">
          <template #default="{ row }">
            {{ row.confidence === null ? t('eval.na') : row.confidence.toFixed(4) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('eval.detail.fallback')" min-width="150">
          <template #default="{ row }">
            <span :class="{ warn: !!row.fallback_reason }">{{ row.fallback_reason || t('eval.none') }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 两种空态：样本表为空 / 尚未发起评测 -->
    <div v-if="report && report.empty" class="app-card">
      <div class="app-card-body">
        <div class="app-empty">
          <p class="app-empty-title">{{ t('eval.empty.title') }}</p>
          <p class="app-empty-desc">{{ report.message || t('eval.empty.desc') }}</p>
        </div>
      </div>
    </div>
    <div v-else-if="!report" class="app-card">
      <div class="app-card-body">
        <el-empty :description="loading ? t('eval.loading') : t('eval.idle')" :image-size="72" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Connection, Cpu, Files, Timer, WarningFilled } from '@element-plus/icons-vue'
import { getEvalReport } from '../../api'
import type { EvalReport, EvalSideSummary } from '../../types'
import { t, taskLabel } from '../../i18n'

const report = ref<EvalReport | null>(null)
const loading = ref(false)
/** 单次评测的样本上限：Jev 是真实网络调用，样本越多整轮越慢，默认取中间档 */
const limit = ref(50)
/** 混淆矩阵当前查看的判定器侧 */
const matrixSide = ref<'mock' | 'jev'>('jev')

async function load() {
  loading.value = true
  try {
    report.value = await getEvalReport(limit.value)
  } finally {
    loading.value = false
  }
}

onMounted(load)

const sides = computed<{ key: 'mock' | 'jev'; data?: EvalSideSummary; tone: string }[]>(() => [
  { key: 'mock', data: report.value?.mock, tone: 'is-gray' },
  { key: 'jev', data: report.value?.jev, tone: 'is-purple' },
])

/** 固定 L1/L2/L3 顺序，缺项补 0，避免两侧条形长度因缺项而失真 */
const layerRows = computed(() =>
  (['L1', 'L2', 'L3'] as const).map((layer) => ({
    layer,
    mock: report.value?.mock.layer_distribution?.[layer] ?? 0,
    jev: report.value?.jev.layer_distribution?.[layer] ?? 0,
  })),
)

function layerTotal(key: 'mock' | 'jev') {
  const d = (key === 'mock' ? report.value?.mock : report.value?.jev)?.layer_distribution ?? {}
  return Object.values(d).reduce((s, n) => s + n, 0)
}

/** 每张卡按**自己的**层总数算百分比：两侧样本数一致，但层分布不同轴 */
function layerPct(n: number, key: 'mock' | 'jev') {
  const tot = layerTotal(key)
  return tot ? Math.round((n / tot) * 100) : 0
}

/** 准确率为 null = 无法计算（无真值样本），必须与「0%」区分开 */
function pct(v: number | null | undefined) {
  return v === null || v === undefined ? t('eval.na') : `${(v * 100).toFixed(2)}%`
}

function toneOf(layer: string | null | undefined) {
  if (layer === 'L1') return 'is-success'
  if (layer === 'L2') return 'is-purple'
  if (layer === 'L3') return 'is-danger'
  return 'is-gray'
}

/** 把 {expected: {predicted: n}} 摊平成表格：列取所有出现过的 predicted 值 */
const matrixRows = computed(() => {
  const m = (matrixSide.value === 'mock' ? report.value?.mock : report.value?.jev)?.confusion_matrix ?? {}
  const cols = [...new Set(Object.values(m).flatMap((r) => Object.keys(r)))].sort()
  const rows = Object.keys(m).sort().map((expected) => ({
    expected,
    cells: Object.fromEntries(cols.map((c) => [c, m[expected]?.[c] ?? 0])) as Record<string, number>,
    total: cols.reduce((s, c) => s + (m[expected]?.[c] ?? 0), 0),
  }))
  return { cols, rows }
})
</script>

<style scoped>
.section {
  margin-top: 20px;
}
.runbar .facts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 18px;
}
.fact {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.warn {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 10px 0 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--c-warning-text);
}
.hint-block {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--text-3);
}
.metrics {
  display: flex;
  gap: 24px;
}
.metric {
  flex: 1;
}
.metric-value {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--text-1);
  font-variant-numeric: tabular-nums;
}
.metric-label {
  margin-top: 2px;
  font-size: 12.5px;
  color: var(--text-2);
}
.metric-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.layer-dist {
  margin-top: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.layer-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.layer-bar {
  flex: 1;
}
.layer-count {
  width: 40px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
  font-variant-numeric: tabular-nums;
}
.cell-hit {
  font-weight: 700;
  color: var(--c-success-text);
}
</style>
