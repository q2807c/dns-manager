<template>
  <div id="app-root">
    <template v-if="!authStore.isAuthenticated">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </template>
    <template v-else>
      <div class="app-layout">
        <Sidebar />
        <div class="app-main">
          <TopBar />
          <div class="app-content">
            <router-view v-slot="{ Component, route }">
              <transition name="slide-up" mode="out-in">
                <component :is="Component" :key="route.fullPath" />
              </transition>
            </router-view>
          </div>
          <div class="app-footer">
            <span class="footer-left">
              F5 BIG-IP 活跃节点：<strong>{{ f5Host }}</strong>
            </span>
            <span class="footer-right">
              <span>v0.2.0</span>
              <span class="separator">|</span>
              <span>{{ connectionStatus }}</span>
            </span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import Sidebar from '@/components/Sidebar.vue'
import TopBar from '@/components/TopBar.vue'
import api from '@/api'

const authStore = useAuthStore()
const f5Host = ref('...')
const connectionStatus = ref('连接中...')

let healthInterval: ReturnType<typeof setInterval> | null = null

async function checkHealth() {
  try {
    const { data } = await api.get('/health')
    f5Host.value = data.f5_active_host || 'N/A'
    connectionStatus.value = '已连接'
  } catch {
    f5Host.value = 'N/A'
    connectionStatus.value = '未连接'
  }
}

onMounted(async () => {
  await authStore.tryRestoreSession()
  await checkHealth()
  // Periodic health check every 60 seconds
  healthInterval = setInterval(checkHealth, 60000)
})

onUnmounted(() => {
  if (healthInterval) clearInterval(healthInterval)
})
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.app-content {
  flex: 1;
  overflow: auto;
  padding: 20px;
  background: var(--bg-main);
}

.app-footer {
  height: var(--footer-height);
  line-height: var(--footer-height);
  padding: 0 20px;
  background: var(--bg-sidebar);
  color: var(--text-sidebar);
  font-size: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid var(--border-color);
  flex-shrink: 0;
}

.app-footer strong {
  color: #FFFFFF;
  font-weight: 500;
}

.app-footer .separator {
  margin: 0 8px;
  opacity: 0.4;
}

.footer-right {
  display: flex;
  align-items: center;
}
</style>
