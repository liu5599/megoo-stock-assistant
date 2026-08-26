<template>
  <div class="page">
    <div class="detail-header">
      <van-icon name="arrow-left" size="18" @click="goBack" style="padding:4px" />
      <div class="detail-title">{{ name }} <span class="muted">题材成分</span></div>
    </div>

    <van-notice-bar v-if="loading" mode="link" color="#1989fa" background="#ecf5ff">
      正在获取成分股...
    </van-notice-bar>
    <van-notice-bar v-if="errorMsg" mode="link" color="#ee0a24" background="#fef0f0">{{ errorMsg }}</van-notice-bar>

    <div class="card" v-if="stocks.length">
      <div class="section-title" style="margin-top:0">🔥 {{ name }} 成分股（{{ stocks.length }}）</div>
      <div v-for="s in stocks" :key="s.code" class="list-item" style="border:none;padding:8px 0" @click="goStock(s.code)">
        <div class="item-main">
          <div class="item-title">{{ s.name }}（{{ s.code }}）</div>
          <div class="item-sub" v-if="s.pct_chg !== null && s.pct_chg !== undefined">涨跌 {{ fmtPct(s.pct_chg) }} ｜ {{ s.boards ? s.boards + '连板' : '' }}</div>
        </div>
        <van-tag v-if="s.seal_amount" type="danger">{{ (s.seal_amount / 1e8).toFixed(1) }}亿封板</van-tag>
        <van-icon name="arrow" style="color:#c8c9cc" />
      </div>
    </div>
    <van-empty v-else-if="!loading" description="暂无成分股数据" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchThemeDetail } from '../api'

const route = useRoute()
const router = useRouter()
const name = route.params.name
const stocks = ref([])
const loading = ref(true)
const errorMsg = ref('')

function goBack() { router.back() }
function goStock(code) { router.push('/stock/' + code) }
function fmtPct(v) {
  const n = Number(v)
  if (isNaN(n)) return '-'
  return (n > 0 ? '+' : '') + n.toFixed(2) + '%'
}

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const d = await fetchThemeDetail(encodeURIComponent(name))
    stocks.value = d.stocks || []
    if (d.source) errorMsg.value = '（数据源：' + d.source + '）'
  } catch (e) {
    errorMsg.value = '加载失败：' + e.message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.detail-header { display: flex; align-items: center; gap: 8px; padding: 12px 16px; background: #fff; position: sticky; top: 0; z-index: 9; border-bottom: 1px solid #f2f3f5; }
.detail-title { flex: 1; font-size: 16px; font-weight: 600; }
.muted { font-size: 12px; color: #969799; font-weight: 400; }
</style>
