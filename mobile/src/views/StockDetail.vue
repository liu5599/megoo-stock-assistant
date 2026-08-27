<template>
  <div class="page">
    <div class="detail-header">
      <van-icon name="arrow-left" size="18" @click="goBack" style="padding:4px" />
      <div class="detail-title">{{ detail.name || code }} <span class="muted">{{ code }}</span></div>
      <div class="detail-price">{{ detail.price ? '¥' + detail.price : '' }}</div>
    </div>

    <van-notice-bar v-if="loading" mode="link" color="#1989fa" background="#ecf5ff">
      正在获取深度数据，约需 20 秒...
    </van-notice-bar>
    <van-notice-bar v-if="errorMsg" mode="link" color="#ee0a24" background="#fef0f0">{{ errorMsg }}</van-notice-bar>

    <!-- 交易计划 -->
    <div class="card" v-if="detail.plan">
      <div class="plan-head">
        <span class="rating" :class="'rating-' + detail.plan.rating">{{ detail.plan.rating }}级</span>
        <span class="action">{{ detail.plan.action }}</span>
        <span class="badge-hold" v-if="detail.plan.wyckoff">
          {{ wyckoffText(detail.plan) }}
        </span>
      </div>
      <van-cell-group inset style="margin:8px 0 0">
        <van-cell title="入场区间" :value="`${detail.plan.entry_low} ~ ${detail.plan.entry_high}`" />
        <van-cell title="目标价" :value="`${detail.plan.target_price}（+${detail.plan.target_pct}%）`" value-class="up" />
        <van-cell title="止损价" :value="`${detail.plan.stop_loss}（${detail.plan.stop_pct}%）`" value-class="down" />
        <van-cell title="建议仓位" :value="`${detail.plan.position_pct}%（${detail.plan.position_shares}股）`" />
        <van-cell title="持有周期" :value="detail.plan.holding_period" />
      </van-cell-group>
    </div>

    <!-- K线图 -->
    <div class="card" v-if="kline.length">
      <div class="section-title" style="margin-top:0">📈 近90日K线</div>
      <div ref="chartEl" style="height:260px;width:100%"></div>
    </div>

    <!-- 三维信号 -->
    <div class="card" v-if="detail.decision">
      <div class="section-title" style="margin-top:0">🎯 三维决策</div>
      <div class="sig-row">
        <div class="sig-item">
          <div class="sig-signal" :class="sigClass(detail.decision.long_term?.signal)">{{ detail.decision.long_term?.signal || '-' }}</div>
          <div class="sig-label">长线</div>
        </div>
        <div class="sig-item">
          <div class="sig-signal" :class="sigClass(detail.decision.swing?.signal)">{{ detail.decision.swing?.signal || '-' }}</div>
          <div class="sig-label">波段</div>
        </div>
        <div class="sig-item">
          <div class="sig-signal" :class="sigClass(detail.decision.short_term?.signal)">{{ detail.decision.short_term?.signal || '-' }}</div>
          <div class="sig-label">短线</div>
        </div>
        <div class="sig-item">
          <div class="sig-score">{{ detail.decision.composite_score ?? '-' }}</div>
          <div class="sig-label">综合分</div>
        </div>
      </div>
      <div class="item-sub" style="padding:8px 0 0">
        长线：{{ detail.decision.long_term?.reason || '-' }}
      </div>
      <div class="item-sub">
        波段：{{ detail.decision.swing?.reason || '-' }}
      </div>
    </div>

    <!-- 估值空间 -->
    <div class="card" v-if="detail.valuation && detail.valuation.available">
      <div class="section-title" style="margin-top:0">💎 估值空间</div>
      <van-cell-group inset style="margin:0 0 8px">
        <van-cell title="估值区间" :value="detail.valuation.zone" />
        <van-cell title="PE分位" :value="`${detail.valuation.pe_pct}%`" />
        <van-cell title="PB分位" :value="`${detail.valuation.pb_pct}%`" />
      </van-cell-group>
      <div class="item-sub">{{ detail.valuation.reason }}</div>
    </div>

    <!-- 逻辑与风险 -->
    <div class="card" v-if="detail.plan">
      <div class="section-title" style="margin-top:0">📌 操作逻辑</div>
      <div class="logic-box" v-for="(l, i) in detail.plan.logic" :key="'l' + i">{{ l }}</div>
      <div class="section-title" style="margin-top:10px">⚠️ 风险提示</div>
      <div class="logic-box down" v-for="(r, i) in detail.plan.risks" :key="'r' + i">{{ r }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import * as echarts from 'echarts/core'
import { CandlestickChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([CandlestickChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])
import { fetchStockDetail } from '../api'

const route = useRoute()
const router = useRouter()
const code = route.params.code
const detail = ref({})
const kline = ref([])
const loading = ref(true)
const errorMsg = ref('')
const chartEl = ref(null)

function goBack() { router.back() }

function sigClass(s) {
  if (s === '多') return 'up'
  if (s === '空') return 'down'
  return ''
}

function wyckoffText(p) {
  const w = p.wyckoff
  if (!w) return ''
  if (w.spring_signal) return '🪤 Spring抄底'
  if (w.sos_signal) return '🚀 SOS突破'
  return w.phase || ''
}

function drawChart() {
  if (!chartEl.value || !kline.value.length) return
  const chart = echarts.init(chartEl.value)
  const k = kline.value
  chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 8, right: 8, top: 12, bottom: 28, containLabel: true },
    xAxis: {
      type: 'category', data: k.map(i => i.date.slice(5)),
      axisLine: { lineStyle: { color: '#c8c9cc' } }, axisLabel: { fontSize: 10 },
    },
    yAxis: {
      type: 'value', scale: true,
      splitLine: { lineStyle: { color: '#f2f3f5' } }, axisLabel: { fontSize: 10 },
    },
    tooltip: {
      trigger: 'axis',
      formatter: params => {
        const d = k[params[0].dataIndex]
        return `${d.date}<br/>开 ${d.open} 高 ${d.high}<br/>低 ${d.low} 收 ${d.close}`
      },
    },
    dataZoom: [{ type: 'inside' }],
    series: [{
      type: 'candlestick',
      data: k.map(i => [i.open, i.close, i.low, i.high]),
      itemStyle: { color: '#ee0a24', color0: '#07c160', borderColor: '#ee0a24', borderColor0: '#07c160' },
    }],
  })
  window.addEventListener('resize', () => chart.resize())
}

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    detail.value = await fetchStockDetail(code)
    kline.value = detail.value.kline || []
    if (detail.value.error) errorMsg.value = detail.value.error
    await nextTick()
    drawChart()
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
.detail-price { font-size: 15px; font-weight: 600; color: #d32f2f; }
.muted { font-size: 12px; color: #969799; font-weight: 400; }
.plan-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rating { padding: 2px 10px; border-radius: 4px; color: #fff; font-weight: 600; font-size: 14px; }
.rating-S { background: #d32f2f; }
.rating-A { background: #ff6f00; }
.rating-B { background: #1989fa; }
.rating-C { background: #969799; }
.action { font-size: 14px; font-weight: 600; color: #323233; }
.badge-hold { font-size: 12px; color: #1989fa; background: #ecf5ff; padding: 2px 8px; border-radius: 4px; }
.sig-row { display: flex; gap: 8px; }
.sig-item { flex: 1; text-align: center; padding: 8px 0; background: #f7f8fa; border-radius: 8px; }
.sig-signal { font-size: 18px; font-weight: 700; }
.sig-score { font-size: 18px; font-weight: 700; color: #323233; }
.sig-label { font-size: 11px; color: #969799; margin-top: 2px; }
.logic-box { font-size: 13px; color: #323233; background: #f7f8fa; border-radius: 6px; padding: 8px 10px; margin-bottom: 6px; line-height: 1.5; }
.logic-box.down { color: #d32f2f; background: #fef0f0; }
</style>
