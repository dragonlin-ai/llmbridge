import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('../views/login/index.vue') },
  {
    path: '/',
    component: () => import('../layout/index.vue'),
    redirect: '/playground',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('../views/dashboard/index.vue'), meta: { titleKey: 'title.dashboard', title: '概览', priority: 'P1' } },
      { path: 'providers', name: 'providers', component: () => import('../views/providers/index.vue'), meta: { titleKey: 'title.providers', title: '厂商接入', priority: 'P0' } },
      { path: 'models', name: 'models', component: () => import('../views/models/index.vue'), meta: { titleKey: 'title.models', title: '模型池', priority: 'P0' } },
      { path: 'rules', name: 'rules', component: () => import('../views/rules/index.vue'), meta: { titleKey: 'title.rules', title: '路由规则', priority: 'P0' } },
      { path: 'apikeys', name: 'apikeys', component: () => import('../views/apikeys/index.vue'), meta: { titleKey: 'title.apikeys', title: '第三方接入', priority: 'P0' } },
      { path: 'playground', name: 'playground', component: () => import('../views/playground/index.vue'), meta: { titleKey: 'title.playground', title: '路由试跑台', priority: 'P0' } },
      { path: 'logs', name: 'logs', component: () => import('../views/logs/index.vue'), meta: { titleKey: 'title.logs', title: '调用日志', priority: 'P0' } },
      { path: 'samples', name: 'samples', component: () => import('../views/samples/index.vue'), meta: { titleKey: 'title.samples', title: '决策样本', priority: 'P1' } },
      { path: 'eval', name: 'eval', component: () => import('../views/eval/index.vue'), meta: { titleKey: 'title.eval', title: '评测看板', priority: 'P1' } },
      { path: 'usage', name: 'usage', component: () => import('../views/usage/index.vue'), meta: { titleKey: 'title.usage', title: '用量与成本', priority: 'P2' } },
      { path: 'settings', name: 'settings', component: () => import('../views/settings/index.vue'), meta: { titleKey: 'title.settings', title: '系统设置', priority: 'P1' } },
    ],
  },
]

const router = createRouter({ history: createWebHashHistory(), routes })

router.beforeEach((to) => {
  if (to.path !== '/login' && !localStorage.getItem('token')) return '/login'
})

export default router
