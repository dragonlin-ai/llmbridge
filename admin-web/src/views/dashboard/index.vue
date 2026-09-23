<template>
  <div class="app-anim-fade">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">{{ t('dashboard.title') }}</h2>
        <p class="app-page-desc">{{ t('dashboard.subtitle') }}</p>
      </div>
      <div class="app-page-actions">
        <el-button :loading="loading" @click="load">{{ t('dashboard.refresh') }}</el-button>
      </div>
    </div>

    <!-- 关键指标 -->
    <div class="app-grid app-grid-5">
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

    <div class="app-grid app-grid-2 section">
      <!-- 层级命中分布 -->
      <div class="app-card">
        <div class="app-card-header">
          <span>{{ t('dashboard.layersTitle') }}</span>
          <span class="app-badge is-gray">{{ t('dashboard.layerChain') }}</span>
        </div>
        <div class="app-card-body">
          <div v-if="total" class="layers">
            <div v-for="(n, layer) in layerRows" :key="layer" class="layer-row">
              <span class="app-badge" :class="toneOf(layer)">{{ layer }}</span>
              <div class="app-progress layer-bar">
                <div class="app-progress-bar" :style="{ width: pctOf(n) + '%' }" />
              </div>
              <span class="layer-count">{{ n }}</span>
              <span class="layer-pct">{{ pctOf(n) }}%</span>
            </div>
          </div>
          <el-empty v-else :description="t('dashboard.emptyRequest')" :image-size="72" />
        </div>
      </div>

      <!-- 模型池与规则 -->
      <div class="app-card">
        <div class="app-card-header">
          <span>{{ t('dashboard.modelsTitle') }}</span>
        </div>
        <div class="app-card-body">
          <el-descriptions :column="1" border>
            <el-descriptions-item :label="t('dashboard.modelCount')">
              {{ opts?.models?.length ?? '—' }}
            </el-descriptions-item>
            <el-descriptions-item :label="t('dashboard.ruleCount')">
              {{ opts?.rules_total ?? '—' }}
            </el-descriptions-item>
            <el-descriptions-item :label="t('dashboard.decider')">
              <span class="app-badge" :class="deciderTone">{{ opts?.active_decider ?? '—' }}</span>
              <span class="hint" :class="{ 'hint-warn': deciderMismatch }">{{ deciderHint }}</span>
            </el-descriptions-item>
            <el-descriptions-item :label="t('dashboard.cache')">
              <span class="app-badge is-gray">{{ t('dashboard.degradedMode') }}</span>
              <span class="hint">{{ t('dashboard.cacheHint') }}</span>
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  CircleCheck,
  Coin,
  Odometer,
  RefreshRight,
  Timer,
} from '@element-plus/icons-vue'
import { options, statsOverview } from '../../api'
import type { StatsOverview } from '../../types'
import { t } from '../../i18n'

const stats = ref<StatsOverview | null>(null)
const opts = ref<{
  models: unknown[]
  rules_total: number
  judge_provider: string
  active_decider: string
} | null>(null)
const loading = ref(false)

/** 判定器实际生效值（jev / mock），由后端 build_decider 给出，不看配置值 */
const deciderTone = computed(() => (opts.value?.active_decider === 'jev' ? 'is-primary' : 'is-gray'))

/** 配置了 jev 却回退到 mock（多为缺 JEV_API_KEY），必须显式提示，否则会误判「已切 jev」 */
const deciderMismatch = computed(
  () => !!opts.value && opts.value.judge_provider !== opts.value.active_decider,
)

const deciderHint = computed(() => {
  const o = opts.value
  if (!o) return ''
  if (o.judge_provider === o.active_decider) return `judge_provider = ${o.judge_provider}`
  return t('dashboard.deciderMismatch', { provider: o.judge_provider, decider: o.active_decider })
})

function fmt(value: number, digits = 0) {
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

const cards = computed(() => [
  {
    label: t('dashboard.cardTotal'),
    display: fmt(stats.value?.total_requests ?? 0),
    icon: Odometer,
    tone: 'is-primary',
  },
  {
    label: t('dashboard.cardSuccess'),
    display: `${fmt((stats.value?.success_rate ?? 0) * 100, 2)}%`,
    icon: CircleCheck,
    tone: 'is-success',
  },
  {
    label: t('dashboard.cardLatency'),
    display: `${fmt(stats.value?.p95_route_latency_ms ?? 0)} ms`,
    icon: Timer,
    tone: 'is-purple',
  },
  {
    label: t('dashboard.cardFallback'),
    display: `${fmt((stats.value?.fallback_rate ?? 0) * 100, 2)}%`,
    icon: RefreshRight,
    tone: 'is-warning',
  },
  {
    label: t('dashboard.cardCost'),
    display: `¥ ${fmt(stats.value?.total_cost ?? 0, 4)}`,
    icon: Coin,
    tone: 'is-danger',
  },
])

const total = computed(() => stats.value?.total_requests ?? 0)

/** 固定 L1/L2/L3 顺序，缺项补 0，避免分布跳动 */
const layerRows = computed(() => {
  const dist = (stats.value?.layer_distribution ?? {}) as Record<string, number>
  return ['L1', 'L2', 'L3'].reduce<Record<string, number>>((acc, k) => {
    acc[k] = dist[k] ?? 0
    return acc
  }, {})
})

function pctOf(n: number) {
  return total.value ? Math.round((n / total.value) * 100) : 0
}

function toneOf(layer: string) {
  if (layer === 'L1') return 'is-success'
  if (layer === 'L2') return 'is-purple'
  return 'is-danger'
}

async function load() {
  loading.value = true
  try {
    const [s, o] = await Promise.all([statsOverview(), options()])
    stats.value = s
    opts.value = o as never
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.section {
  margin-top: 20px;
}
.layers {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.layer-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.layer-bar {
  flex: 1;
}
.layer-count {
  width: 56px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
  font-variant-numeric: tabular-nums;
}
.layer-pct {
  width: 46px;
  text-align: right;
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--text-3);
}
.hint-warn {
  color: var(--c-warning-text);
}
</style>
