<template>
  <div class="page">
    <div class="page-title">🎯 操盘台</div>

    <van-pull-refresh v-model="refreshing" @refresh="load">
      <!-- 加载提示（首次数据源约20秒） -->
      <van-notice-bar v-if="loading" mode="link" color="#1989fa" background="#ecf5ff">
        正在获取盘面数据，首次约需 20 秒，请稍候...
      </van-notice-bar>
      <van-notice-bar v-else-if="errorMsg" mode="link" color="#ee0a24" background="#fffbe8">
        {{ errorMsg }}
      </van-notice-bar>
      <!-- 市场温度 -->
      <div class="card">
        <div class="section-title" style="margin-top:0">🌡️ 市场温度计</div>
        <div v-if="temp" class="temp-hero">
          <div class="temp-circle" :style="{ background: tempColor }">
            <div class="num">{{ temp.temperature ?? '-' }}</div>
            <div class="label">温度</div>
          </div>
          <div style="flex:1;min-width:0">
            <div class="temp-zone" :style="{ color: tempColor }">{{ temp.zone || '未知' }}</div>
            <div class="temp-advice">{{ temp.advice }}</div>
            <div class="temp-bar">
              <div class="cursor" :style="{ left: pct + '%' }"></div>
            </div>
            <div class="temp-meta">
              情绪 {{ temp.scores?.emotion ?? '-' }} ｜ 量能 {{ temp.scores?.volume ?? '-' }} ｜ 估值分位 {{ temp.scores?.valuation ?? '-' }}%
            </div>
          </div>
        </div>
        <van-empty v-else description="暂无温度数据" />
      </div>

      <!-- 涨跌 + 多空 -->
      <div class="stat-grid" style="margin-bottom:12px">
        <div class="stat-card">
          <div class="stat-value up">{{ act['上涨'] ?? '-' }}</div>
          <div class="stat-label">上涨</div>
        </div>
        <div class="stat-card">
          <div class="stat-value down">{{ act['下跌'] ?? '-' }}</div>
          <div class="stat-label">下跌</div>
        </div>
        <div class="stat-card">
          <div class="stat-value up">{{ act['涨停'] ?? '-' }}</div>
          <div class="stat-label">涨停</div>
        </div>
        <div class="stat-card">
          <div class="stat-value down">{{ act['跌停'] ?? '-' }}</div>
          <div class="stat-label">跌停</div>
        </div>
      </div>

      <div class="card">
        <div class="section-title" style="margin-top:0">⚔️ 多空资金</div>
        <div v-if="bb.direction" class="list-item">
          <div class="item-main">
            <div class="item-title">{{ bb.direction }}</div>
            <div class="item-sub">多方 {{ bb.bull_count }} ｜ 空方 {{ bb.bear_count }} ｜ 净流入 {{ bb.net_total }} 亿</div>
          </div>
          <van-tag :type="String(bb.direction).includes('多方') ? 'danger' : 'success'">{{ bb.source }}</van-tag>
        </div>
        <van-empty v-else description="暂无数据" />
      </div>

      <!-- 题材热点 -->
      <div class="card">
        <div class="section-title" style="margin-top:0">🔥 今日题材热点</div>
        <div v-for="(t, i) in hotThemes" :key="i" class="list-item">
          <div class="item-main">
            <div class="item-title">{{ t.name }}
              <span :class="Number(t.pct_chg) >= 0 ? 'up' : 'down'">{{ fmtPct(t.pct_chg) }}</span>
            </div>
            <div class="item-sub">领涨：{{ t.leader || '—' }} {{ t.leader_pct ? fmtPct(t.leader_pct) : '' }}</div>
          </div>
          <div>
            <van-tag plain type="warning">热度 {{ t.heat_score }}</van-tag>
          </div>
        </div>
        <van-empty v-if="!hotThemes.length" description="题材数据暂不可用" />
      </div>

      <!-- 情绪高标 -->
      <div class="card">
        <div class="section-title" style="margin-top:0">⚡ 情绪高标</div>
        <div v-for="(s, i) in senti" :key="i" class="list-item">
          <div class="item-main">
            <div class="item-title">{{ s.name }}
              <span class="badge badge-buy">{{ s.tag }}</span>
            </div>
            <div class="item-sub">连板 {{ s.consecutive_days }} ｜ 封板 {{ fmtYi(s.seal_amount) }} 亿</div>
          </div>
          <div class="item-title up">{{ fmtPct(s.pct_chg) }}</div>
        </div>
        <van-empty v-if="!senti.length" description="今日无涨停数据" />
      </div>

      <van-button type="danger" block round style="margin-top:8px" :loading="refreshing"
        loading-text="刷新中..." @click="load">🔄 刷新盘面</van-button>
      <div v-if="data && data.timestamp" style="text-align:center;font-size:11px;color:#969799;margin-top:8px">
        数据时间：{{ data.timestamp }}（盘面数据自动缓存，刷新秒回）
      </div>
    </van-pull-refresh>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { showToast } from 'vant'
import { fetchOverview } from '../api'

const refreshing = ref(false)
const loading = ref(false)
const errorMsg = ref('')
const data = ref(null)

const temp = computed(() => data.value?.temperature || null)
const act = computed(() => temp.value?.details?.activity || {})
const bb = computed(() => data.value?.money?.bull_bear || {})
const hotThemes = computed(() => data.value?.themes?.hot_themes?.slice(0, 6) || [])
const senti = computed(() => data.value?.themes?.sentiment_stocks?.slice(0, 6) || [])

const tempColor = computed(() => {
  const t = temp.value?.temperature ?? 50
  if (t >= 70) return '#d32f2f'
  if (t >= 45) return '#f57f17'
  if (t >= 25) return '#2e7d32'
  return '#1565c0'
})
const pct = computed(() => Math.min(100, Math.max(0, temp.value?.temperature ?? 50)))

function fmtPct(v) {
  const n = parseFloat(v)
  if (isNaN(n)) return '-'
  return (n > 0 ? '+' : '') + n.toFixed(2) + '%'
}
function fmtYi(v) {
  const n = parseFloat(v || 0)
  return (n / 1e8).toFixed(2)
}

async function load() {
  refreshing.value = true
  loading.value = true
  errorMsg.value = ''
  try {
    data.value = await fetchOverview()
  } catch (e) {
    errorMsg.value = '加载失败：' + e.message + '（检查后端地址是否可访问）'
    showToast('加载失败：' + e.message)
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

onMounted(load)
</script>
