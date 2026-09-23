<template>
  <div class="app-anim-fade">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">{{ t('usage.title') }}</h2>
        <p class="app-page-desc">{{ t('usage.subtitle') }}</p>
      </div>
      <div class="app-page-actions">
        <el-radio-group v-model="days" size="default" :disabled="loading" @change="load">
          <el-radio-button :value="1">{{ t('usage.d1') }}</el-radio-button>
          <el-radio-button :value="7">{{ t('usage.d7') }}</el-radio-button>
          <el-radio-button :value="30">{{ t('usage.d30') }}</el-radio-button>
          <el-radio-button :value="90">{{ t('usage.d90') }}</el-radio-button>
        </el-radio-group>
        <el-button :loading="loading" @click="load">{{ t('common.refresh') }}</el-button>
      </div>
    </div>

    <!-- 口径声明：用量页与概览页必须同源，否则同一批请求会出现两个成本数字。
         这里把「已排除哪些流量」「窗口从哪一刻起」「多少条真有用量数据」全部摆明。 -->
    <div v-if="report" class="app-card">
      <div class="app-card-body scope">
        <span class="app-badge" :class="report.excludes_preview ? 'is-success' : 'is-danger'">
          {{ report.excludes_preview ? t('usage.scopeClean') : t('usage.scopeDirty') }}
        </span>
        <span class="scope-item">{{ t('usage.windowStart') }}：<code class="app-code">{{ windowStartText }}</code></span>
        <span class="scope-item">{{ t('usage.card.models') }}：<b>{{ report.summary.models }}</b></span>
        <span class="scope-item">{{ t('usage.card.latency') }}：<b>{{ fmt(report.summary.avg_latency_ms, 0) }} ms</b></span>
        <span class="scope-note">{{ qualityText }}</span>
      </div>
    </div>

    <!-- 关键指标 -->
    <div v-if="report" class="app-grid app-grid-5 section">
      <div v-for="c in cards" :key="c.label" class="app-stat-card">
        <div class="app-stat-icon" :class="c.tone">
          <el-icon><component :is="c.icon" /></el-icon>
        </div>
        <div class="app-stat-meta">
          <div class="app-stat-value">{{ c.display }}</div>
          <div class="app-stat-label">{{ c.label }}</div>
        </div>
      </div>
    </div>

    <!-- 按模型聚合 -->
    <div v-if="report" class="app-card section">
      <div class="app-card-header">
        <span>{{ t('usage.byModel') }}</span>
        <span class="app-badge is-gray">{{ t('usage.byModelCount', { n: report.by_model.length }) }}</span>
      </div>
      <el-table v-if="report.by_model.length" :data="report.by_model" size="default">
        <el-table-column :label="t('usage.col.model')" min-width="180">
          <template #default="{ row }">
            <code v-if="row.model_key" class="app-code">{{ row.model_key }}</code>
            <span v-else class="app-badge is-gray">{{ t('usage.noModel') }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="calls" :label="t('usage.col.calls')" width="100" />
        <el-table-column :label="t('usage.col.tokens')" min-width="140">
          <template #default="{ row }">
            <span class="mono">{{ fmt(row.total_tokens) }}</span>
            <span class="sub">{{ row.prompt_tokens }} / {{ row.completion_tokens }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('usage.col.cost')" width="130">
          <template #default="{ row }"><span class="mono">¥ {{ cost(row.cost) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('usage.col.avgCost')" width="130">
          <template #default="{ row }"><span class="mono">¥ {{ cost(row.avg_cost) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('usage.col.success')" width="130">
          <template #default="{ row }">
            <span class="app-badge" :class="rateTone(row.success_rate)">
              {{ (row.success_rate * 100).toFixed(2) }}%
            </span>
            <span class="sub">{{ row.success_count }} / {{ row.calls }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('usage.col.latency')" width="110">
          <template #default="{ row }">{{ fmt(row.avg_latency_ms, 0) }} ms</template>
        </el-table-column>
      </el-table>
      <div v-else class="app-card-body">
        <el-empty :description="t('usage.empty')" :image-size="72" />
      </div>
    </div>

    <div v-if="report" class="app-grid app-grid-2 section">
      <!-- 按路由层：兜底链路的真实代价 -->
      <div class="app-card">
        <div class="app-card-header">
          <span>{{ t('usage.byLayer') }}</span>
          <span class="app-badge is-gray">L1 / L2 / L3</span>
        </div>
        <el-table :data="report.by_layer" size="small">
          <el-table-column :label="t('usage.col.layer')" width="70">
            <template #default="{ row }">
              <span class="app-badge" :class="layerTone(row.layer)">{{ row.layer }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="calls" :label="t('usage.col.calls')" width="80" />
          <el-table-column :label="t('usage.col.success')" width="90">
            <template #default="{ row }">{{ (row.success_rate * 100).toFixed(2) }}%</template>
          </el-table-column>
          <el-table-column prop="fallback_count" :label="t('usage.col.fallback')" width="90" />
          <el-table-column :label="t('usage.col.cost')" min-width="110">
            <template #default="{ row }"><span class="mono">¥ {{ cost(row.cost) }}</span></template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 状态分布 -->
      <div class="app-card">
        <div class="app-card-header">
          <span>{{ t('usage.byStatus') }}</span>
        </div>
        <div class="app-card-body">
          <div v-for="s in report.by_status" :key="s.status" class="status-row">
            <span class="app-badge" :class="s.status === 'success' ? 'is-success' : 'is-danger'">
              {{ s.status }}
            </span>
            <div class="app-progress status-bar">
              <div
                class="app-progress-bar"
                :class="{ 'is-error': s.status !== 'success' }"
                :style="{ width: statusPct(s.calls) + '%' }"
              />
            </div>
            <span class="status-count">{{ s.calls }}</span>
            <span class="status-pct">{{ statusPct(s.calls) }}%</span>
          </div>
          <el-empty v-if="!report.by_status.length" :description="t('usage.empty')" :image-size="72" />
        </div>
      </div>
    </div>

    <!-- 按日趋势（CSS 柱状，不引入图表库：本项目所有图表均为 CSS 原生实现） -->
    <div v-if="report" class="app-card section">
      <div class="app-card-header">
        <span>{{ t('usage.trend') }}</span>
        <span class="app-badge is-gray">{{ t('usage.trendHint') }}</span>
      </div>
      <div class="app-card-body">
        <div v-if="report.trend.length" class="trend">
          <div v-for="d in report.trend" :key="d.day" class="trend-col">
            <span class="trend-cost">¥ {{ cost(d.cost) }}</span>
            <div class="trend-track">
              <div
                class="trend-bar"
                :style="{ height: barPct(d.calls) + '%' }"
                :title="`${d.day} · ${d.calls} calls · ¥ ${cost(d.cost)}`"
              />
            </div>
            <span class="trend-calls">{{ d.calls }}</span>
            <span class="trend-day">{{ d.day.slice(5) }}</span>
          </div>
        </div>
        <el-empty v-else :description="t('usage.empty')" :image-size="72" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CircleCheck, Coin, DataLine, Odometer, RefreshRight } from '@element-plus/icons-vue'
import { getUsageReport } from '../../api'
import type { UsageReport } from '../../types'
import { t } from '../../i18n'

const report = ref<UsageReport | null>(null)
const loading = ref(false)
const days = ref(30)

async function load() {
  loading.value = true
  try {
    report.value = await getUsageReport(days.value)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function fmt(value: number | null | undefined, digits = 0) {
  return (value ?? 0).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/** 成本量级极小（实测 30 天窗口为 ¥0.0001 级），定点 6 位可读且不丢精度 */
function cost(value: number | null | undefined) {
  return (value ?? 0).toFixed(6)
}

/** 后端窗口起点是 DB 的 UTC 时间；这里只做字符串截断，不交给 Date 做时区换算（否则偏 8 小时） */
const windowStartText = computed(
  () => `${(report.value?.window_start ?? '').replace('T', ' ').slice(0, 19)} UTC`,
)

const qualityText = computed(() => {
  const q = report.value?.data_quality
  if (!q) return ''
  return t('usage.qualityNote', { n: q.calls, tok: q.with_token_data, cost: q.with_cost_data })
})

const cards = computed(() => [
  { label: t('usage.card.calls'), display: fmt(report.value?.summary.calls), icon: Odometer, tone: 'is-primary' },
  { label: t('usage.card.cost'), display: `¥ ${cost(report.value?.summary.cost)}`, icon: Coin, tone: 'is-danger' },
  { label: t('usage.card.tokens'), display: fmt(report.value?.summary.total_tokens), icon: DataLine, tone: 'is-purple' },
  {
    label: t('usage.card.success'),
    display: `${((report.value?.summary.success_rate ?? 0) * 100).toFixed(2)}%`,
    icon: CircleCheck,
    tone: 'is-success',
  },
  {
    label: t('usage.card.fallback'),
    display: `${((report.value?.summary.fallback_rate ?? 0) * 100).toFixed(2)}%`,
    icon: RefreshRight,
    tone: 'is-warning',
  },
])

function statusPct(n: number) {
  const total = report.value?.summary.calls ?? 0
  return total ? Math.round((n / total) * 100) : 0
}

/** 趋势柱高按窗口内最大值归一，最少留 4%，避免「有调用但量小」的日子柱子消失 */
function barPct(n: number) {
  const max = Math.max(1, ...(report.value?.trend ?? []).map((d) => d.calls))
  return Math.max(4, Math.round((n / max) * 100))
}

function rateTone(v: number) {
  if (v >= 0.99) return 'is-success'
  if (v >= 0.8) return 'is-warning'
  return 'is-danger'
}

function layerTone(layer: string) {
  if (layer === 'L1') return 'is-success'
  if (layer === 'L2') return 'is-purple'
  return 'is-danger'
}
</script>

<style scoped>
.section {
  margin-top: 20px;
}
.scope {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
  font-size: 12.5px;
  color: var(--text-2);
}
.scope-item b {
  color: var(--text-1);
  font-variant-numeric: tabular-nums;
}
.scope-note {
  flex: 1 1 100%;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
}
.mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.sub {
  margin-left: 6px;
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.status-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 10px 0;
}
.status-bar {
  flex: 1;
}
.status-bar .app-progress-bar.is-error {
  background: var(--c-danger);
}
.status-count {
  width: 44px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
  font-variant-numeric: tabular-nums;
}
.status-pct {
  width: 48px;
  text-align: right;
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.trend {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  min-height: 210px;
  padding-top: 8px;
  overflow-x: auto;
}
.trend-col {
  flex: 0 0 auto;
  min-width: 64px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.trend-cost {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
}
.trend-track {
  width: 44px;
  height: 130px;
  display: flex;
  align-items: flex-end;
  background: var(--n-100);
  border-radius: 6px;
  overflow: hidden;
}
html.dark .trend-track {
  background: var(--n-800);
}
.trend-bar {
  width: 100%;
  background: linear-gradient(180deg, var(--p-400), var(--p-500));
  border-radius: 6px 6px 0 0;
  transition: height 0.3s ease;
}
.trend-calls {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
  font-variant-numeric: tabular-nums;
}
.trend-day {
  font-size: 11.5px;
  color: var(--text-3);
}
</style>
