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

// Quant 量化大数据分析
export function fetchQuant() {
  return request('/api/ops/quant')
}

// 组合风险（VaR/夏普/回撤/相关性）
export function fetchPortfolioRisk(codes) {
  return request('/api/ops/portfolio/risk?codes=' + encodeURIComponent(codes))
}

// 个股深度详情（K线/信号/估值/计划 —— 第二层钻取）
export function fetchStockDetail(code) {
  return request('/api/ops/stock/' + code + '/detail')
}

// 题材详情（成分股 —— 第二层钻取）
export function fetchThemeDetail(name) {
  return request('/api/ops/theme/' + name + '/detail')
}

// 完整龙虎榜（免费东财源）
export function fetchLhb(limit = 50) {
  return request('/api/ops/lhb?limit=' + limit)
}

export default { fetchOverview, fetchStocks, fetchReport, pushReport, fetchPlans, fetchQuant, fetchPortfolioRisk, fetchStockDetail, fetchThemeDetail, fetchLhb }
