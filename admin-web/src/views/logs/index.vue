<template>
  <div class="logs-page app-anim-fade">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">{{ t('logs.page.title') }}</h2>
        <p class="app-page-desc">{{ t('logs.page.desc') }}</p>
      </div>
    </div>

    <div class="app-card logs-card">
      <div class="app-toolbar">
        <el-select v-model="filters.layer" :placeholder="t('logs.filter.allLayer')" clearable style="width:130px" @change="onFilterChange">
          <el-option label="L1" value="L1" /><el-option label="L2" value="L2" /><el-option label="L3" value="L3" />
        </el-select>
        <el-select v-model="filters.status" :placeholder="t('logs.filter.allStatus')" clearable style="width:130px" @change="onFilterChange">
          <el-option label="success" value="success" /><el-option label="error" value="error" />
        </el-select>
        <el-select v-model="filters.source" :placeholder="t('logs.filter.allSource')" clearable style="width:150px" @change="onFilterChange">
          <el-option :label="t('logs.source.live')" value="live" /><el-option :label="t('logs.source.preview')" value="preview" />
        </el-select>
        <el-input v-model="filters.trace_id" :placeholder="t('logs.filter.tracePlaceholder')" clearable style="width:240px" @change="onFilterChange" />
        <el-button @click="onFilterChange">{{ t('logs.btn.query') }}</el-button>
      </div>

      <div ref="tableWrap" class="logs-table-wrap app-scroll-area">
        <el-table :data="items" :height="tableHeight" v-loading="loading" @row-click="showTrace">
          <el-table-column prop="trace_id" label="trace_id" min-width="160">
            <template #default="{ row }">
              <code class="app-code" :title="row.trace_id">{{ row.trace_id.slice(0, 14) }}…</code>
              <span v-if="row.is_preview" class="app-badge is-info" :title="t('logs.badge.previewTitle')">{{ t('logs.badge.preview') }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('logs.layer')" width="80">
            <template #default="{ row }">
              <span class="app-badge" :class="layerTone(row.router_layer)">{{ row.router_layer }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('logs.actualModel')" min-width="200">
            <template #default="{ row }">
              <div v-if="row.final_model_name || row.final_model_key" class="model-cell">
                <span>{{ row.final_model_name ?? row.final_model_key }}</span>
                <code
                  v-if="row.final_model_key && row.final_model_key !== row.final_model_name"
                  class="app-code"
                  :title="t('logs.title.modelKey')"
                >{{ row.final_model_key }}</code>
              </div>
              <span v-else class="text-muted" :title="t('logs.title.modelDeleted')">{{ t('logs.modelDeleted') }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('logs.routeLatency')" width="90">
            <template #default="{ row }">{{ row.route_latency_ms }}ms</template>
          </el-table-column>
          <el-table-column :label="t('logs.totalLatency')" width="90">
            <template #default="{ row }">{{ row.latency_ms }}ms</template>
          </el-table-column>
          <el-table-column :label="t('logs.tokens')" width="120">
            <template #default="{ row }">{{ row.prompt_tokens }} / {{ row.completion_tokens }}</template>
          </el-table-column>
          <el-table-column :label="t('logs.cost')" width="90">
            <template #default="{ row }">{{ row.cost?.toFixed(4) ?? '—' }}</template>
          </el-table-column>
          <el-table-column :label="t('logs.status')" width="90">
            <template #default="{ row }">
              <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="fallback_reason" :label="t('logs.fallbackReason')" min-width="180" show-overflow-tooltip />
          <el-table-column prop="created_at" :label="t('logs.time')" width="172" />
        </el-table>
      </div>

      <div class="app-card-footer pagination-row">
        <el-pagination
          layout="total, sizes, prev, pager, next, jumper"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          v-model:current-page="page"
          v-model:page-size="pageSize"
          @current-change="load"
          @size-change="onSizeChange"
        />
      </div>
    </div>

    <el-dialog v-model="traceDlg" :title="t('logs.dialog.trace.title')" width="640px" append-to-body>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="trace_id"><code class="app-code">{{ trace?.trace_id }}</code></el-descriptions-item>
        <el-descriptions-item :label="t('logs.layer')">{{ trace?.router_layer }}</el-descriptions-item>
        <el-descriptions-item :label="t('logs.source.label')">
          <span v-if="trace?.is_preview" class="app-badge is-info">{{ t('logs.source.preview') }}</span>
          <span v-else class="app-badge is-primary">{{ t('logs.source.live') }}</span>
        </el-descriptions-item>
        <el-descriptions-item :label="t('logs.actualModel')" :span="2">
          <template v-if="trace?.final_model_name || trace?.final_model_key">
            {{ trace.final_model_name ?? '—' }}
            <code v-if="trace.final_model_key && trace.final_model_key !== trace.final_model_name"
                  class="app-code">{{ trace.final_model_key }}</code>
            <span class="model-note">{{ t('logs.dialog.trace.modelNote') }}</span>
          </template>
          <span v-else class="text-muted">{{ t('logs.dialog.trace.modelDeleted') }}</span>
        </el-descriptions-item>
        <el-descriptions-item :label="t('logs.totalLatency')">{{ trace?.latency_ms }}ms</el-descriptions-item>
        <el-descriptions-item :label="t('logs.routeLatency')">{{ trace?.route_latency_ms }}ms</el-descriptions-item>
        <el-descriptions-item :label="t('logs.status')">{{ trace?.status }}</el-descriptions-item>
        <el-descriptions-item :label="t('logs.fallbackReason')">{{ trace?.fallback_reason ?? '—' }}</el-descriptions-item>
      </el-descriptions>
      <template v-if="decisionSnap">
        <div class="sec">{{ t('logs.dialog.trace.snapshot') }}</div>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item :label="t('logs.dialog.trace.snap.taskType')">{{ decisionSnap.task_type ?? '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('logs.dialog.trace.snap.confidence')">{{ decisionSnap.confidence ?? '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('logs.dialog.trace.snap.decider')">{{ decisionSnap.decider ?? '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('logs.dialog.trace.snap.hitLayer')">{{ decisionSnap.hit_layer ?? '—' }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="decisionSnap.probabilities" class="sec">{{ t('logs.dialog.trace.probDist') }}</div>
        <ProbChart v-if="decisionSnap.probabilities" :probabilities="decisionSnap.probabilities as Record<string, number>" />
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import { getTrace, listLogs } from '../../api'
import { t } from '../../i18n'
import type { LogItem } from '../../types'
import ProbChart from '../../components/ProbChart.vue'

const items = ref<LogItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const filters = reactive({ layer: '', status: '', trace_id: '', source: '' })
const traceDlg = ref(false)
const trace = ref<LogItem | null>(null)
const decisionSnap = ref<Record<string, unknown> | null>(null)

// 表格自身撑满卡片剩余高度并内部滚动：用 ResizeObserver 把可用高度喂给 el-table 的 height。
const tableWrap = ref<HTMLElement | null>(null)
const tableHeight = ref(400)
let ro: ResizeObserver | null = null

/** 路由层级 → 徽章色调（与概览看板保持一致） */
function layerTone(layer: string) {
  if (layer === 'L1') return 'is-success'
  if (layer === 'L2') return 'is-purple'
  return 'is-danger'
}

async function load() {
  loading.value = true
  try {
    const data = await listLogs({
      page: page.value, page_size: pageSize.value,
      router_layer: filters.layer || undefined,
      status: filters.status || undefined,
      trace_id: filters.trace_id || undefined,
      source: filters.source || undefined,
    })
    items.value = data.items.map((it: LogItem) => ({
      ...it,
      is_preview: (it.trace_id || '').startsWith('preview-'),
    }))
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  page.value = 1
  load()
}

function onSizeChange() {
  page.value = 1
  load()
}

async function showTrace(row: LogItem) {
  const full = await getTrace(row.trace_id)
  trace.value = { ...full, is_preview: (full.trace_id || '').startsWith('preview-') }
  decisionSnap.value = (trace.value as unknown as { router_output_json?: Record<string, unknown> }).router_output_json ?? null
  traceDlg.value = true
}

onMounted(() => {
  if (tableWrap.value && 'ResizeObserver' in window) {
    ro = new ResizeObserver((entries) => {
      const h = entries[0]?.contentRect.height
      if (h && h > 0) tableHeight.value = Math.floor(h)
    })
    ro.observe(tableWrap.value)
  }
  load()
})

onBeforeUnmount(() => {
  ro?.disconnect()
  ro = null
})
</script>

<style scoped>
/* 整页恰好填满内容区，不出现整页滚动；滚动条只出现在表格内部。 */
.logs-page {
  height: calc(100vh - 120px);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.logs-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
/* 表格区域撑满卡片剩余空间，内部滚动由 el-table 的 height 承接 */
.logs-table-wrap {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.pagination-row {
  display: flex;
  justify-content: flex-end;
  flex: none;
}
.sec {
  font-weight: 600;
  margin: 16px 0 8px;
  color: var(--text-1);
}
.model-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.model-note {
  margin-left: 8px;
  font-size: 12px;
  color: var(--text-3);
}
.text-muted {
  color: var(--text-3);
  font-size: 12px;
}
</style>
