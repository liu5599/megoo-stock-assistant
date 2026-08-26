// 后端 API 地址配置
// 1. 优先：构建时注入 VITE_API_BASE（.env.production，打包 APK 用）
// 2. 其次：localStorage 用户设置（日报 Tab 可改）
// 3. 再次：页面 URL 自动探测（手机浏览器访问 IP:5173 → 自动用同 IP:8010）
// 4. 兜底：开发默认 localhost:8010
const DEFAULT_API_BASE = (import.meta.env.VITE_API_BASE || 'http://localhost:8010').replace(/\/+$/, '')

function detectApiBase() {
  try {
    const host = window.location.hostname
    if (host && host !== 'localhost' && host !== '127.0.0.1' && /^\d+\.\d+\.\d+\.\d+$/.test(host)) {
      return `http://${host}:8010`
    }
  } catch (e) { /* ignore */ }
  return DEFAULT_API_BASE
}

export function getApiBase() {
  return localStorage.getItem('megoo_api_base') || detectApiBase()
}

export function setApiBase(url) {
  localStorage.setItem('megoo_api_base', url.replace(/\/+$/, ''))
}

export function getWatchlistCodes() {
  const raw = localStorage.getItem('megoo_watchlist')
  if (!raw) return '000001,600519,300750'
  return raw
}

export function setWatchlistCodes(codes) {
  localStorage.setItem('megoo_watchlist', codes)
}
