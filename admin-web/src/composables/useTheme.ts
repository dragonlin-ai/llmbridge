import { computed, ref, watch } from 'vue'

export type ThemeMode = 'light' | 'dark'

const STORAGE_KEY = 'llmbridge-theme'

function readInitial(): ThemeMode {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    /* localStorage 不可用时忽略 */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** 模块级状态：同一页面内所有调用方共享 */
const mode = ref<ThemeMode>(readInitial())

function apply(next: ThemeMode) {
  document.documentElement.classList.toggle('dark', next === 'dark')
}

apply(mode.value)

watch(mode, (next) => {
  apply(next)
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    /* 忽略写入失败 */
  }
})

export function useTheme() {
  const isDark = computed(() => mode.value === 'dark')

  function toggle() {
    mode.value = mode.value === 'dark' ? 'light' : 'dark'
  }

  function set(next: ThemeMode) {
    mode.value = next
  }

  return { mode, isDark, toggle, set }
}
