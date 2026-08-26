<template>
  <div class="page">
    <div class="page-title">📋 交易计划</div>

    <van-field v-model="codes" label="自选股" placeholder="逗号分隔代码，如 000001,600519"
      rows="1" autosize />
    <div style="display:flex;gap:8px;margin:8px 0 14px">
      <van-button type="primary" round block :loading="loading" @click="load">生成交易计划</van-button>
      <van-button round block @click="saveCodes">保存自选</van-button>
    </div>

    <!-- 组合仓位 -->
    <div v-if="portfolio.market_zone" class="card" style="background:linear-gradient(135deg,#d32f2f,#b71c1c);color:#fff">
      <div style="font-size:13px;opacity:.85">市场温度 {{ portfolio.market_temp }} · {{ portfolio.market_zone }}</div>
      <div style="font-size:22px;font-weight:700;margin:4px 0">建议总仓位：{{ portfolio.total_position }}</div>
      <div style="font-size:12px;opacity:.9">{{ portfolio.note }}</div>
    </div>

    <!-- 交易计划卡片 -->
    <div v-for="p in plans" :key="p.code" class="card">
      <div class="list-item" style="border:none;padding:0 0 10px">
        <div class="item-main">
          <div class="item-title">{{ p.name }}（{{ p.code }}）</div>
          <div class="item-sub">现价 {{ p.price }} ｜ 胜率预期 {{ Math.round(p.win_rate * 100) }}%</div>
        </div>
        <div style="text-align:right">
          <span class="badge" :class="ratingClass(p.rating)">{{ p.rating }} 级</span>
          <div class="item-title" :class="actionClass(p.action)" style="margin-top:4px">{{ p.action }}</div>
        </div>
      </div>

      <van-cell-group inset style="margin:0 0 8px">
        <van-cell title="主力行为" :label="wyckoffText(p)" :value="wyckoffBadge(p)" />
        <van-cell title="入场区间" :value="`${p.entry_low} ~ ${p.entry_high}`" />
        <van-cell title="目标价" :value="`${p.target_price}（+${p.target_pct}%）`" value-class="up" />
        <van-cell title="止损价" :value="`${p.stop_loss}（${p.stop_pct}%）`" value-class="down" />
        <van-cell title="建议仓位" :value="`${p.position_pct}%（${p.position_shares}股）`" />
        <van-cell title="持有周期" :value="p.holding_period" />
        <van-cell title="单笔风险" :value="`≤${(p.risk_amount / 10000).toFixed(0)}万`" />
      </van-cell-group>

      <div style="background:#f7f8fa;border-radius:8px;padding:10px;font-size:12px;color:#646566;line-height:1.6">
        <div>📌 逻辑：{{ p.logic.join('；') }}</div>
        <div style="margin-top:4px">⚠️ 风险：{{ p.risks.join('；') }}</div>
      </div>
    </div>

    <van-empty v-if="!loading && !plans.length" description="输入自选股代码后点击生成交易计划" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { showToast } from 'vant'
import { fetchPlans } from '../api'
import { getWatchlistCodes, setWatchlistCodes } from '../config'

const codes = ref(getWatchlistCodes())
const plans = ref([])
const portfolio = ref({})
const loading = ref(false)

function ratingClass(r) {
  return { S: 'badge-buy', A: 'badge-buy', B: 'badge-hold', C: 'badge-sell' }[r] || 'badge-hold'
}
function actionClass(a) {
  if (String(a).includes('买入')) return 'up'
  if (String(a).includes('卖出')) return 'down'
  return ''
}

function wyckoffText(p) {
  const w = p.wyckoff
  if (!w) return '-'
  return `${w.phase}（吸筹分 ${w.accumulation_score}）${w.spring_note ? '｜' + w.spring_note : ''}`
}

function wyckoffBadge(p) {
  const w = p.wyckoff
  if (!w) return '-'
  if (w.spring_signal) return '🪤 Spring抄底'
  if (w.sos_signal) return '🚀 SOS突破'
  if (['吸筹完成/拉升前夜', '吸筹中', '吸筹初期'].includes(w.phase)) return '🏗️ 吸筹中'
  return '👀 观察'
}

async function load() {
  if (!codes.value.trim()) { showToast('请输入股票代码'); return }
  loading.value = true
  try {
    const d = await fetchPlans(codes.value.trim())
    plans.value = d.plans || []
    portfolio.value = d.portfolio || {}
    if (!plans.value.length) showToast('未获取到数据，请检查代码或网络')
  } catch (e) {
    showToast('加载失败：' + e.message)
  } finally {
    loading.value = false
  }
}

function saveCodes() {
  setWatchlistCodes(codes.value.trim())
  showToast('自选已保存 ✅')
}

onMounted(load)
</script>
