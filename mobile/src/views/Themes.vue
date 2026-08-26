<template>
  <div class="page">
    <div class="page-title">🔥 题材热点</div>

    <van-tabs v-model:active="tab" sticky>
      <van-notice-bar v-if="loading" mode="link" color="#1989fa" background="#ecf5ff">
        正在获取题材数据，首次约需 15 秒...
      </van-notice-bar>
      <van-tab title="新题材">
        <div class="card" v-for="(t, i) in newThemes" :key="i">
          <div class="list-item" style="border:none;padding:0 0 8px">
            <div class="item-main">
              <div class="item-title">{{ t.name }}
                <span :class="Number(t.pct_chg) >= 0 ? 'up' : 'down'">{{ fmtPct(t.pct_chg) }}</span>
              </div>
              <div class="item-sub">指数 {{ t.index_price ?? '-' }}</div>
            </div>
            <div style="text-align:right">
              <div class="item-title up">{{ fmtYi(t.net_flow) }}</div>
              <div class="item-sub">净流入(亿)</div>
            </div>
          </div>
          <div style="font-size:12px;color:#969799;background:#f7f8fa;border-radius:8px;padding:8px">
            领涨：{{ t.leader }} {{ t.leader_pct ? fmtPct(t.leader_pct) : '' }} ｜ {{ t.stock_count }} 家公司
          </div>
        </div>
        <van-empty v-if="!newThemes.length" description="题材数据暂不可用" />
      </van-tab>

      <van-tab title="热题材">
        <div class="card" v-for="(t, i) in hotThemes" :key="i">
          <div class="list-item" style="border:none;padding:0 0 8px">
            <div class="item-main">
              <div class="item-title">{{ t.name }}
                <span :class="Number(t.pct_chg) >= 0 ? 'up' : 'down'">{{ fmtPct(t.pct_chg) }}</span>
              </div>
              <div class="item-sub">领涨：{{ t.leader || '—' }}</div>
            </div>
            <van-tag plain type="warning">热度 {{ t.heat_score }}</van-tag>
          </div>
        </div>
        <van-empty v-if="!hotThemes.length" description="题材数据暂不可用" />
      </van-tab>

      <van-tab title="情绪高标">
        <div class="card" v-for="(s, i) in senti" :key="i">
          <div class="list-item" style="border:none;padding:0 0 8px">
            <div class="item-main">
              <div class="item-title">{{ s.name }}
                <span class="badge badge-buy">{{ s.tag }}</span>
              </div>
              <div class="item-sub">{{ s.industry || '' }} ｜ 连板 {{ s.consecutive_days }} ｜
                封板 {{ fmtYi(s.seal_amount) }} 亿 ｜ 换手 {{ s.turnover ?? '-' }}%</div>
            </div>
            <div class="item-title up">{{ fmtPct(s.pct_chg) }}</div>
          </div>
        </div>
        <van-empty v-if="!senti.length" description="今日无涨停数据" />
      </van-tab>
    </van-tabs>

    <van-button type="danger" block round style="margin-top:12px" :loading="loading"
      loading-text="刷新中..." @click="load">🔄 刷新题材</van-button>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { showToast } from 'vant'
import { fetchOverview } from '../api'

const tab = ref(0)
const loading = ref(false)
const data = ref(null)
const newThemes = ref([])
const hotThemes = ref([])
const senti = ref([])

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
  loading.value = true
  try {
    data.value = await fetchOverview()
    newThemes.value = data.value.themes?.new_themes || []
    hotThemes.value = data.value.themes?.hot_themes || []
    senti.value = data.value.themes?.sentiment_stocks || []
  } catch (e) {
    showToast('加载失败：' + e.message)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
