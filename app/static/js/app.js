// megoo股票助手 — 全局 JS

// ===== 导航栏搜索 =====
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('nav-stock-search');
    const dropdown = document.getElementById('nav-search-results');

    if (!searchInput || !dropdown) return;

    let debounceTimer;
    searchInput.addEventListener('input', function() {
        clearTimeout(debounceTimer);
        const q = this.value.trim();
        if (q.length < 2) {
            dropdown.classList.remove('show');
            return;
        }
        debounceTimer = setTimeout(async () => {
            try {
                const resp = await fetch(`${window.SEARCH_API_URL}?q=${encodeURIComponent(q)}`);
                const data = await resp.json();
                if (data.stocks && data.stocks.length > 0) {
                    dropdown.innerHTML = data.stocks.map(s =>
                        `<div class="search-result-item" onclick="location.href='/stock/${s.code}'">
                            <span><span class="code">${s.code}</span> ${s.name}</span>
                            <span style="color:var(--text-muted)">${s.sector || ''}</span>
                        </div>`
                    ).join('');
                    dropdown.classList.add('show');
                } else {
                    dropdown.innerHTML = '<div class="search-result-item" style="color:var(--text-muted)">未找到匹配结果</div>';
                    dropdown.classList.add('show');
                }
            } catch(e) {
                dropdown.classList.remove('show');
            }
        }, 300);
    });

    // 点击外部关闭下拉
    document.addEventListener('click', function(e) {
        if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.remove('show');
        }
    });

    // 回车直接跳转
    searchInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            const q = this.value.trim();
            if (q.length === 6 && /^\d{6}$/.test(q)) {
                location.href = `/stock/${q}`;
            }
        }
    });
});

// ===== 涨跌颜色 =====
function formatChange(val) {
    if (val == null || isNaN(val)) return '<span class="text-muted">-</span>';
    const sign = val > 0 ? '+' : '';
    const cls = val > 0 ? 'up' : val < 0 ? 'down' : '';
    return `<span class="${cls}">${sign}${val.toFixed(2)}%</span>`;
}

function formatScore(val) {
    if (val == null || isNaN(val)) return '-';
    const cls = val >= 65 ? 'score-high' : val >= 45 ? 'score-mid' : 'score-low';
    return `<span class="score-badge ${cls}">${val.toFixed(1)}</span>`;
}

// ===== Chart.js 全局配置 =====
Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#30363d';
Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
