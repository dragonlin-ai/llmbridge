<template>
  <div class="chain">
    <div v-for="seg in segments" :key="seg.layer" class="seg"
         :class="{ hit: seg.status === 'hit', failed: seg.status === 'failed' }"
         :style="segStyle(seg)" :title="seg.reason || ''">
      <div class="seg-title">{{ seg.layer }}</div>
      <div class="seg-sub">{{ seg.label }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { HitLayer } from '../types'
import { LAYER_COLORS } from '../types'
import { t } from '../i18n'

const props = defineProps<{
  hitLayer: HitLayer
  details?: { layer: string; status: 'hit' | 'skipped' | 'failed'; reason?: string; latencyMs?: number }[]
}>()

const segments = computed(() =>
  (['L1', 'L2', 'L3'] as HitLayer[]).map((layer) => {
    const detail = props.details?.find((d) => d.layer === layer)
    const status = layer === props.hitLayer ? 'hit' : (detail?.status ?? 'skipped')
    const skipReason = {
      L1: t('routechain.skipL1'),
      L2: t('routechain.skipL2'),
      L3: t('routechain.skipL3'),
    }[layer]
    return {
      layer,
      status,
      label: status === 'hit' ? t('routechain.hit') : (detail?.reason ?? skipReason ?? t('routechain.skipped')),
      reason: detail?.reason,
    }
  }),
)

function segStyle(seg: { layer: string; status: string }) {
  const color = LAYER_COLORS[seg.layer]
  if (seg.status === 'hit') return { background: color, borderColor: color, color: '#fff' }
  if (seg.status === 'failed') {
    return {
      borderColor: 'var(--c-danger)',
      color: 'var(--c-danger-text)',
      background: 'var(--c-danger-soft)',
    }
  }
  return {
    borderColor: 'var(--border-strong)',
    color: 'var(--text-3)',
    background: 'var(--bg-subtle)',
  }
}
</script>

<style scoped>
.chain {
  display: flex;
  gap: 12px;
}
.seg {
  flex: 1;
  border: 1px solid;
  border-radius: 12px;
  text-align: center;
  padding: 14px 0;
  transition: all 0.2s var(--ease);
}
.seg.hit {
  box-shadow: 0 4px 14px rgba(20, 184, 166, 0.22);
}
.seg-title {
  font-weight: 600;
  font-size: 15px;
}
.seg-sub {
  font-size: 12px;
  margin-top: 2px;
  opacity: 0.9;
}
</style>
