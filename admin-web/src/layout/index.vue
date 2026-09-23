<template>
  <div class="admin-shell" :class="{ 'is-collapsed': collapsed }">
    <!-- ===== 侧边栏 ===== -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="brand-logo">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 7h11a4 4 0 0 1 0 8H8" />
            <path d="M11 4l-3 3 3 3" />
            <path d="M13 15l3 3-3 3" />
          </svg>
        </div>
        <div v-show="!collapsed" class="brand-text">
          <span class="brand-name">{{ t('layout.brand') }}</span>
          <span class="brand-sub">{{ t('layout.brandSub') }}</span>
        </div>
      </div>

      <nav class="sidebar-nav app-scroll">
        <div class="sidebar-section" v-for="group in menuGroups" :key="group.title">
          <div v-show="!collapsed" class="sidebar-section-title">{{ t(group.title) }}</div>
          <template v-for="item in group.items" :key="item.path">
            <router-link
              v-if="!item.disabled"
              :to="item.path"
              class="sidebar-link"
              :class="{ 'is-active': isActive(item.path) }"
              :title="collapsed ? t(item.title) : undefined"
            >
              <el-icon class="sidebar-link-icon"><component :is="item.icon" /></el-icon>
              <span v-show="!collapsed" class="sidebar-link-text">{{ t(item.title) }}</span>
              <span v-if="item.badge && !collapsed" class="sidebar-link-badge">{{ item.badge }}</span>
            </router-link>
            <span
              v-else
              class="sidebar-link is-disabled"
              :title="collapsed ? t(item.title) : undefined"
            >
              <el-icon class="sidebar-link-icon"><component :is="item.icon" /></el-icon>
              <span v-show="!collapsed" class="sidebar-link-text">{{ t(item.title) }}</span>
              <span v-if="item.badge && !collapsed" class="sidebar-link-badge">{{ item.badge }}</span>
            </span>
          </template>
        </div>
      </nav>

      <div class="sidebar-footer">
        <button class="sidebar-collapse" type="button" @click="toggleCollapse">
          <el-icon><component :is="collapsed ? Expand : Fold" /></el-icon>
          <span v-show="!collapsed">{{ t('layout.collapse') }}</span>
        </button>
      </div>
    </aside>

    <!-- ===== 主区域 ===== -->
    <div class="main-area">
      <header class="topbar">
        <div class="topbar-left">
          <h1 class="topbar-title">{{ pageTitle }}</h1>
        </div>
        <div class="topbar-right">
          <!-- 多语言切换：中文 / English -->
          <el-dropdown trigger="click" @command="onLangCommand">
            <button class="icon-btn lang-btn" type="button" :title="t('layout.language')">
              <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="10" />
                <path d="M2 12h20" />
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
              </svg>
              <span class="lang-code">{{ locale === 'zh' ? '中' : 'EN' }}</span>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="l in LANGS"
                  :key="l.value"
                  :command="l.value"
                  :class="{ 'is-checked': locale === l.value }"
                >
                  <span class="lang-item">{{ l.label }}</span>
                  <el-icon v-if="locale === l.value" class="lang-tick"><Check /></el-icon>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <button
            class="icon-btn"
            type="button"
            :title="isDark ? t('layout.toLight') : t('layout.toDark')"
            @click="toggleTheme"
          >
            <el-icon><component :is="isDark ? Sunny : Moon" /></el-icon>
          </button>

          <el-dropdown trigger="click" @command="onCommand">
            <button class="user-btn" type="button">
              <span class="user-avatar">{{ avatarText }}</span>
              <span class="user-name">{{ username }}</span>
              <el-icon class="user-caret"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">
                  <el-icon><SwitchButton /></el-icon>
                  <span>{{ t('layout.logout') }}</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="content app-scroll">
        <div class="content-inner">
          <router-view v-slot="{ Component }">
            <transition name="page" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowDown,
  Check,
  Coin,
  Connection,
  Cpu,
  DataAnalysis,
  Document,
  Expand,
  Fold,
  Key,
  MagicStick,
  Moon,
  Odometer,
  Setting,
  Share,
  Sunny,
  SwitchButton,
  TrendCharts,
} from '@element-plus/icons-vue'
import { useTheme } from '../composables/useTheme'
import { LANGS, locale, setLang, t, type Lang } from '../i18n'

const route = useRoute()
const router = useRouter()
const { isDark, toggle: toggleTheme } = useTheme()

const COLLAPSE_KEY = 'llmbridge-sidebar-collapsed'
const collapsed = ref(localStorage.getItem(COLLAPSE_KEY) === '1')

interface MenuItem {
  path: string
  title: string
  icon: Component
  disabled: boolean
  badge?: string
}
interface MenuGroup {
  title: string
  items: MenuItem[]
}

const menuGroups: MenuGroup[] = [
  {
    title: 'menu.group.routing',
    items: [
      { path: '/dashboard', title: 'nav.dashboard', icon: Odometer, disabled: false },
      { path: '/playground', title: 'nav.playground', icon: MagicStick, disabled: false },
    ],
  },
  {
    title: 'menu.group.config',
    items: [
      { path: '/providers', title: 'nav.providers', icon: Connection, disabled: false },
      { path: '/models', title: 'nav.models', icon: Cpu, disabled: false },
      { path: '/rules', title: 'nav.rules', icon: Share, disabled: false },
      { path: '/apikeys', title: 'nav.apikeys', icon: Key, disabled: false },
      { path: '/settings', title: 'nav.settings', icon: Setting, disabled: false },
    ],
  },
  {
    title: 'menu.group.observe',
    items: [
      { path: '/logs', title: 'nav.logs', icon: Document, disabled: false },
      { path: '/samples', title: 'nav.samples', icon: DataAnalysis, disabled: false },
    ],
  },
  {
    title: 'menu.group.optimize',
    items: [
      { path: '/eval', title: 'nav.eval', icon: TrendCharts, disabled: false },
      { path: '/usage', title: 'nav.usage', icon: Coin, disabled: false },
    ],
  },
]

const pageTitle = computed(() => t((route.meta.titleKey as string) || 'page.default'))

const username = ref('admin')
const avatarText = computed(() => username.value.slice(0, 1).toUpperCase())

function isActive(path: string) {
  return route.path === path || route.path.startsWith(`${path}/`)
}

function toggleCollapse() {
  collapsed.value = !collapsed.value
  localStorage.setItem(COLLAPSE_KEY, collapsed.value ? '1' : '0')
}

function onCommand(command: string) {
  if (command === 'logout') {
    localStorage.removeItem('token')
    router.push('/login')
  }
}

function onLangCommand(command: string | number | object) {
  setLang(command as Lang)
}

/** 窄屏自动收起侧栏 */
function syncViewport() {
  if (window.innerWidth < 1024) {
    collapsed.value = true
  }
}

onMounted(() => {
  const saved = localStorage.getItem('token')
  try {
    if (saved) {
      const payload = JSON.parse(atob(saved.split('.')[1] || ''))
      if (payload?.username) username.value = payload.username
      else if (payload?.sub) username.value = String(payload.sub)
    }
  } catch {
    /* token 非标准 JWT 时保留默认值 */
  }
  syncViewport()
  window.addEventListener('resize', syncViewport)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncViewport)
})
</script>

<style scoped>
.admin-shell {
  --sw: var(--sidebar-w);
  display: flex;
  min-height: 100vh;
  background: var(--bg-app);
}
.admin-shell.is-collapsed {
  --sw: var(--sidebar-w-collapsed);
}

/* ===== 侧边栏 ===== */
.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 40;
  width: var(--sw);
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-right: 1px solid var(--border-base);
  transition: width 0.25s var(--ease);
}

.sidebar-header {
  height: var(--header-h);
  flex: none;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  border-bottom: 1px solid var(--border-base);
  overflow: hidden;
}
.brand-logo {
  flex: none;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: linear-gradient(135deg, var(--p-500) 0%, var(--p-600) 100%);
  box-shadow: 0 4px 12px rgba(20, 184, 166, 0.3);
}
.brand-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  white-space: nowrap;
}
.brand-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-1);
  line-height: 1.3;
}
.brand-sub {
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.3;
}

.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 16px 12px;
}
.sidebar-section {
  margin-bottom: 20px;
}
.sidebar-section:last-child {
  margin-bottom: 0;
}
.sidebar-section-title {
  margin-bottom: 6px;
  padding: 0 10px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-3);
  white-space: nowrap;
}
.sidebar-link {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px;
  margin-bottom: 2px;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-2);
  white-space: nowrap;
  transition: background-color 0.2s var(--ease), color 0.2s var(--ease);
}
.sidebar-link:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}
.sidebar-link.is-active {
  background: var(--p-50);
  color: var(--p-600);
}
html.dark .sidebar-link.is-active {
  background: rgba(19, 78, 74, 0.35);
  color: var(--p-300);
}
.sidebar-link.is-disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.sidebar-link.is-disabled:hover {
  background: transparent;
  color: var(--text-2);
}
.sidebar-link-icon {
  flex: none;
  font-size: 18px;
}
.sidebar-link-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sidebar-link-badge {
  flex: none;
  padding: 0 7px;
  border-radius: 9999px;
  font-size: 10px;
  font-weight: 600;
  line-height: 17px;
  background: var(--bg-subtle);
  color: var(--text-3);
}

.sidebar-footer {
  flex: none;
  padding: 12px;
  border-top: 1px solid var(--border-base);
}
.sidebar-collapse {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 9px 10px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--text-3);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 0.2s var(--ease), color 0.2s var(--ease);
}
.sidebar-collapse:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}

/* ===== 主区域 ===== */
.main-area {
  flex: 1;
  min-width: 0;
  margin-left: var(--sw);
  display: flex;
  flex-direction: column;
  transition: margin-left 0.25s var(--ease);
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  height: var(--header-h);
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 var(--content-pad);
  background: var(--bg-glass);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border-base);
}
.topbar-left {
  min-width: 0;
}
.topbar-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.icon-btn {
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-base);
  border-radius: 12px;
  background: var(--bg-surface);
  color: var(--text-2);
  font-size: 17px;
  cursor: pointer;
  transition: all 0.2s var(--ease);
}
.icon-btn:hover {
  border-color: var(--p-400);
  color: var(--p-600);
  box-shadow: 0 0 0 3px rgba(20, 184, 166, 0.12);
}

.user-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 10px 0 6px;
  border: 1px solid var(--border-base);
  border-radius: 12px;
  background: var(--bg-surface);
  color: var(--text-2);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.2s var(--ease);
}
.user-btn:hover {
  border-color: var(--border-strong);
}
.user-avatar {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, var(--p-500) 0%, var(--p-600) 100%);
}
.user-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-caret {
  font-size: 12px;
  color: var(--text-3);
}

/* ===== 多语言切换 ===== */
.lang-btn {
  gap: 6px;
  width: auto;
  padding: 0 10px;
}
.lang-code {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
}
.lang-item {
  flex: 1;
}
.lang-tick {
  margin-left: 16px;
  color: var(--p-600);
}

/* ===== 内容区 ===== */
.content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--content-pad);
}
.content-inner {
  max-width: 1600px;
  margin: 0 auto;
}

/* 页面切换动画 */
.page-enter-active,
.page-leave-active {
  transition: opacity 0.18s var(--ease), transform 0.18s var(--ease);
}
.page-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.page-leave-to {
  opacity: 0;
}

@media (max-width: 768px) {
  .content {
    padding: 16px;
  }
  .user-name {
    display: none;
  }
}
</style>
