<template>
  <div class="page">
    <div class="page-title">💰 资金追踪</div>

    <!-- 多空 -->
    <div class="card">
      <div class="section-title" style="margin-top:0">⚔️ 多空资金</div>
      <div class="stat-grid">
        <div class="stat-card">
          <div class="stat-value up">{{ bb.bull_count ?? '-' }}</div>
          <div class="stat-label">多方板块</div>
        </div>
        <div class="stat-card">
          <div class="stat-value down">{{ bb.bear_count ?? '-' }}</div>
          <div class="stat-label">空方板块</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ bb.net_total ?? '-' }}</div>
          <div class="stat-label">净流入(亿)</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" :class="String(bb.direction).includes('多方') ? 'up' : 'down'">
            {{ bb.direction || '-' }}</div>
          <div class="stat-label">方向</div>
        </div>
      </div>
    </div>

    <!-- 龙虎榜 -->
    <div class="card">
      <div class="section-title" style="margin-top:0">💎 龙虎榜大资金</div>
      <div v-for="(l, i) in lhb" :key="i" class="list-item">
        <div class="item-main">
          <div class="item-title">{{ l.name }}（{{ l.code }}）</div>
          <div class="item-sub">{{ l.reason }}</div>
        </div>
        <div class="item-title" :class="Number(l.net_buy) >= 0 ? 'up' : 'down'">
          {{ fmtYi(l.net_buy) }} 亿
        </div>
      </div>
      <van-empty v-if="!lhb.length" description="龙虎榜数据暂不可用" />
    </div>

    <!-- 主力 -->
    <div class="card">
      <div class="section-title" style="margin-top:0">💪 主力资金榜（今日）</div>
      <div v-for="(m, i) in mainFlow" :key="i" class="list-item">
        <div class="item-main">
          <div class="item-title">{{ m.name }}（{{ m.code }}）</div>
          <div class="item-sub">{{ m.indicator }} {{ fmtPct(m.pct_chg) }}</div>
        </div>
        <div class="item-title up">{{ fmtYi(m.net_buy ?? m.main_net) }} 亿</div>
      </div>
      <van-empty v-if="!mainFlow.length" description="主力数据暂不可用" />
    </div>

    <!-- 敢死队 -->
    <div class="card">
      <div class="section-title" style="margin-top:0">⚡ 敢死队资金</div>
      <div v-for="(d, i) in daredevil" :key="i" class="list-item">
        <div class="item-main">
          <div class="item-title">{{ d.name }}（{{ d.code }}）
            <span class="badge badge-buy">{{ d.tag }}</span>
          </div>
          <div class="item-sub">涨幅 {{ fmtPct(d.pct_chg) }} ｜ {{ d.source || '游资接力' }}</div>
        </div>
      </div>
      <van-empty v-if="!daredevil.length" description="敢死队数据暂不可用" />
    </div>

    <van-button type="danger" block round :loading="loading" loading-text="刷新中..." @click="load">🔄 刷新资金</van-button>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { showToast } from 'vant'
import { fetchOverview } from '../api'

const data = ref(null)
const loading = ref(false)
const bb = computed(() => data.value?.money?.bull_bear || {})
const lhb = computed(() => data.value?.money?.lhb || [])
const mainFlow = computed(() => data.value?.money?.main_flow?.today || [])
const daredevil = computed(() => data.value?.money?.daredevil || [])

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

async function load() {
  loading.value = true
  try {
    data.value = await fetchOverview()
  } catch (e) {
    showToast('加载失败：' + e.message)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
