<template>
  <div class="page">
    <div class="detail-header">
      <van-icon name="arrow-left" size="18" @click="goBack" style="padding:4px" />
      <div class="detail-title">{{ name }} <span class="muted">题材成分</span></div>
    </div>

    <van-notice-bar v-if="loading" mode="link" color="#1989fa" background="#ecf5ff">
      正在获取成分股与评级，约需 30 秒...
    </van-notice-bar>
    <van-notice-bar v-if="errorMsg" mode="link" color="#ee0a24" background="#fef0f0">{{ errorMsg }}</van-notice-bar>

    <!-- 值得买入 -->
    <div class="card buy-card" v-if="buyList.length">
      <div class="section-title" style="margin-top:0">🎯 值得买入（S/A级）</div>
      <div v-for="s in buyList" :key="'buy' + s.code" class="buy-item" @click="goStock(s.code)">
        <div class="buy-head">
          <span class="rating" :class="'rating-' + s.rating">{{ s.rating }}级</span>
          <span class="buy-name">{{ s.name }}（{{ s.code }}）</span>
          <span class="buy-action up">{{ s.action }}</span>
        </div>
        <div class="buy-meta">
          现价 <b>{{ s.price }}</b> ｜ 目标 <b>{{ s.target_price }}</b> ｜ 止损 <b>{{ s.stop_loss }}</b><br/>
          入场 {{ s.entry_low }}~{{ s.entry_high }} ｜ 仓位 <b>{{ s.position_pct }}%</b> ｜ PE分位 {{ s.pe_pct }}%<br/>
          威科夫：{{ s.wyckoff_phase || '-' }} ｜ 综合分 {{ s.score }}
        </div>
      </div>
    </div>

    <!-- 全部成分股 -->
    <div class="card" v-if="stocks.length">
      <div class="section-title" style="margin-top:0">🔥 {{ name }} 成分股（{{ stocks.length }}）</div>
      <div v-for="s in stocks" :key="s.code" class="list-item" style="border:none;padding:8px 0" @click="goStock(s.code)">
        <div class="item-main">
          <div class="item-title">
            <span class="rating-mini" :class="'rating-' + (s.rating || 'C')">{{ s.rating || '-' }}</span>
            {{ s.name }}（{{ s.code }}）
          </div>
          <div class="item-sub">现价 {{ s.price }} ｜ 目标 {{ s.target_price || '-' }} ｜ 止损 {{ s.stop_loss || '-' }} ｜ 仓位 {{ s.position_pct ? s.position_pct + '%' : '-' }}</div>
          <div class="item-sub" v-if="s.wyckoff_phase">威科夫：{{ s.wyckoff_phase }}</div>
        </div>
        <van-icon name="arrow" style="color:#c8c9cc" />
      </div>
      <div class="item-sub" v-if="source" style="padding-top:6px">数据源：{{ source }}</div>
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
const buyList = ref([])
const source = ref('')
const loading = ref(true)
const errorMsg = ref('')

function goBack() { router.back() }
function goStock(code) { router.push('/stock/' + code) }

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const d = await fetchThemeDetail(encodeURIComponent(name))
    stocks.value = d.stocks || []
    buyList.value = d.buy_recommend || []
    source.value = d.source || ''
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
.buy-card { background: linear-gradient(135deg, #fff5f5, #fff); border: 1px solid #ffd6d6; }
.buy-item { border: 1px solid #ffd6d6; border-radius: 10px; padding: 10px; margin-bottom: 8px; background: #fff; }
.buy-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.rating { padding: 1px 8px; border-radius: 4px; color: #fff; font-weight: 600; font-size: 12px; }
.rating-S { background: #d32f2f; } .rating-A { background: #ff6f00; }
.rating-B { background: #1989fa; } .rating-C { background: #969799; }
.rating-mini { display: inline-block; padding: 0 5px; border-radius: 3px; color: #fff; font-size: 11px; font-weight: 600; margin-right: 4px; }
.buy-name { font-size: 13px; font-weight: 600; }
.buy-action { font-size: 12px; font-weight: 600; }
.buy-meta { font-size: 12px; color: #646566; margin-top: 6px; line-height: 1.7; }
.buy-meta b { color: #d32f2f; }
</style>
