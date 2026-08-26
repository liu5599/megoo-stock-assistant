<template>
  <div class="page">
    <div class="page-title">📰 AI 操盘日报</div>

    <van-cell-group inset style="margin:0 0 12px">
      <van-cell title="后端地址" :label="apiBase" @click="showApiDialog" is-link />
      <van-cell title="自选股" :label="codes" @click="showCodesDialog" is-link />
    </van-cell-group>

    <div style="display:flex;gap:8px;margin-bottom:12px">
      <van-button type="danger" round block :loading="generating" @click="generate(false)">
        生成日报
      </van-button>
      <van-button type="primary" round block :loading="pushing" @click="generate(true)">
        生成并推送微信
      </van-button>
    </div>

    <div v-if="report" class="report-box">{{ report }}</div>
    <van-empty v-else description="点击上方按钮生成操盘日报" />

    <!-- API 地址设置 -->
    <van-dialog v-model:show="showApi" title="后端地址" show-cancel-button
      :before-close="saveApi">
      <van-field v-model="apiInput" placeholder="http://192.168.1.100:8010" />
      <div style="padding:0 16px 16px;font-size:12px;color:#969799">
        手机需与电脑同一 WiFi，地址填电脑局域网 IP + 端口 8010
      </div>
    </van-dialog>

    <!-- 自选股设置 -->
    <van-dialog v-model:show="showCodes" title="自选股代码" show-cancel-button
      :before-close="saveCodesDlg">
      <van-field v-model="codesInput" placeholder="000001,600519,300750" />
    </van-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { showToast } from 'vant'
import { fetchReport, pushReport } from '../api'
import { getApiBase, setApiBase, getWatchlistCodes, setWatchlistCodes } from '../config'

const apiBase = ref(getApiBase())
const codes = ref(getWatchlistCodes())
const apiInput = ref('')
const codesInput = ref('')
const showApi = ref(false)
const showCodes = ref(false)
const report = ref('')
const generating = ref(false)
const pushing = ref(false)

function showApiDialog() { apiInput.value = apiBase.value; showApi.value = true }
function showCodesDialog() { codesInput.value = codes.value; showCodes.value = true }

function saveApi(action) {
  if (action === 'confirm' && apiInput.value.trim()) {
    setApiBase(apiInput.value.trim())
    apiBase.value = getApiBase()
  }
  showApi.value = false
  return true
}

function saveCodesDlg(action) {
  if (action === 'confirm' && codesInput.value.trim()) {
    setWatchlistCodes(codesInput.value.trim())
    codes.value = getWatchlistCodes()
  }
  showCodes.value = false
  return true
}

async function generate(push) {
  if (push) pushing.value = true; else generating.value = true
  try {
    if (push) {
      const d = await pushReport(codes.value)
      if (d.pushed?.ok) showToast('已推送到微信 ✅')
      else showToast('推送失败：' + (d.pushed?.msg || '未知错误'))
      report.value = d.content || ''
    } else {
      const d = await fetchReport(codes.value)
      report.value = d.content || ''
      showToast('日报已生成 ✅')
    }
  } catch (e) {
    showToast('失败：' + e.message)
  } finally {
    generating.value = false; pushing.value = false
  }
}

onMounted(() => {})
</script>
