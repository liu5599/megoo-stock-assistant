import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '操盘台' } },
  { path: '/stocks', name: 'stocks', component: () => import('../views/Stocks.vue'), meta: { title: '个股' } },
  { path: '/themes', name: 'themes', component: () => import('../views/Themes.vue'), meta: { title: '题材' } },
  { path: '/money', name: 'money', component: () => import('../views/Money.vue'), meta: { title: '资金' } },
  { path: '/report', name: 'report', component: () => import('../views/Report.vue'), meta: { title: '日报' } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
