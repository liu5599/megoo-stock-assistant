// API 服务层 —— 对接 megoo股票助手 FastAPI
import { getApiBase } from '../config'

async function request(path, options = {}) {
  const url = getApiBase() + path
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 90000) // 后端冷加载最长约90秒
  try {
    const resp = await fetch(url, { ...options, signal: controller.signal })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err.detail || err.error || `HTTP ${resp.status}`)
    }
    return await resp.json()
  } finally {
    clearTimeout(timer)
  }
}

// 盘面总览（温度+题材+资金）
export function fetchOverview() {
  return request('/api/ops/overview')
}

// 自选股三维决策
export function fetchStocks(codes) {
  return request('/api/ops/stocks?codes=' + encodeURIComponent(codes))
}

// 生成日报
export function fetchReport(codes) {
  return request('/api/ops/report?codes=' + encodeURIComponent(codes))
}

// 生成并推送日报
export function pushReport(codes) {
  return request('/api/ops/report/push?codes=' + encodeURIComponent(codes), { method: 'POST' })
}

// 交易计划（评级/入场/目标/止损/仓位）
export function fetchPlans(codes, capital = 1000000) {
  return request('/api/ops/plan?codes=' + encodeURIComponent(codes) + '&capital=' + capital)
}

export default { fetchOverview, fetchStocks, fetchReport, pushReport, fetchPlans }
