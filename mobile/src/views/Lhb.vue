<template>
  <div class="page">
    <div class="page-title">💎 龙虎榜大资金</div>
    <div class="page-sub">免费东财源 ｜ 点击行查看个股</div>

    <van-tabs v-model:active="limitTab" @change="load">
      <van-tab title="前50" name="50" />
      <van-tab title="前100" name="100" />
    </van-tabs>

    <div class="card" v-if="rows.length">
      <div class="list-item" v-for="(l, i) in rows" :key="i" @click="$router.push('/stock/' + l.code)">
        <div class="item-main">
          <div class="item-title">{{ l.name }}（{{ l.code }}）</div>
          <div class="item-sub">{{ fmtPct(l.pct_chg) }} ｜ {{ l.reason }}</div>
        </div>
        <div class="item-right">
          <div class="item-title" :class="Number(l.net_buy) >= 0 ? 'up' : 'down'">{{ fmtYi(l.net_buy) }} 亿</div>
          <div class="item-sub">换手 {{ fmtTurnover(l.turnover) }}</div>
        </div>
      </div>
    </div>
    <van-empty v-else-if="!loading" description="龙虎榜数据暂不可用（非交易日或数据源异常）" />

    <van-button type="danger" block round :loading="loading" loading-text="加载中..." @click="load" style="margin-top:14px">🔄 刷新榜单</van-button>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { showToast } from 'vant'
import { fetchLhb } from '../api'

const rows = ref([])
const loading = ref(false)
const limitTab = ref('50')

function fmtPct(v) {
  const n = parseFloat(v)
  if (isNaN(n)) return '-'
  return (n > 0 ? '+' : '') + n.toFixed(2) + '%'
}
function fmtYi(v) {
  const n = parseFloat(v || 0)
  if (isNaN(n) || n === 0) return '-'
  return (n / 1e8).toFixed(2)
}
function fmtTurnover(v) {
  const n = parseFloat(v)
  if (isNaN(n)) return '-'
  return n.toFixed(1) + '%'
}

async function load() {
  loading.value = true
  try {
    const d = await fetchLhb(parseInt(limitTab.value))
    rows.value = d.lhb || []
  } catch (e) {
    showToast('加载失败：' + e.message)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
