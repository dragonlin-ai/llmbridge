<template>
  <div class="prob">
    <div v-for="row in rows" :key="row.type" class="row">
      <!-- 显示本地化标签；原始枚举值保留在 title 里，便于和接口/日志对账 -->
      <span class="type" :title="row.type">{{ taskLabel(row.type) }}</span>
      <div class="app-progress bar">
        <div
          class="app-progress-bar"
          :class="{ 'is-dim': !row.best }"
          :style="{ width: row.pct + '%' }"
        />
      </div>
      <span class="val">{{ row.prob.toFixed(4) }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { taskLabel } from '../i18n'

const props = defineProps<{ probabilities: Record<string, number> }>()

const rows = computed(() => {
  const entries = Object.entries(props.probabilities).sort((a, b) => b[1] - a[1])
  return entries.map(([type, prob]) => ({
    type,
    prob,
    pct: Math.round(prob * 100),
    best: type === entries[0]?.[0],
  }))
})
</script>

<style scoped>
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 8px 0;
}
.type {
  width: 160px;
  font-size: 13px;
  color: var(--text-2);
}
.bar {
  flex: 1;
}
.bar .app-progress-bar.is-dim {
  background: var(--n-300);
}
html.dark .bar .app-progress-bar.is-dim {
  background: var(--n-600);
}
.val {
  width: 70px;
  text-align: right;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
</style>
