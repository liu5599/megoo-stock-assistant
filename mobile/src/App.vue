<template>
  <div class="app-container">
    <keep-alive>
      <router-view />
    </keep-alive>

    <van-tabbar v-model="active" active-color="#d32f2f" route placeholder safe-area-inset-bottom>
      <van-tabbar-item icon="chart-trend-o" to="/dashboard">操盘台</van-tabbar-item>
      <van-tabbar-item icon="search" to="/stocks">个股</van-tabbar-item>
      <van-tabbar-item icon="fire-o" to="/themes">题材</van-tabbar-item>
      <van-tabbar-item icon="gold-coin-o" to="/money">资金</van-tabbar-item>
      <van-tabbar-item icon="description-o" to="/report">日报</van-tabbar-item>
    </van-tabbar>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const tabMap = { '/dashboard': 0, '/stocks': 1, '/themes': 2, '/money': 3, '/report': 4 }
const active = ref(tabMap[route.path] || 0)
</script>
