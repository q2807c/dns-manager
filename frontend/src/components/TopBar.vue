<template>
  <div class="top-bar">
    <div class="top-bar-left">
      <el-breadcrumb separator=">">
        <el-breadcrumb-item :to="{ path: '/' }">DNS</el-breadcrumb-item>
        <el-breadcrumb-item :to="{ path: '/zones' }">Zones</el-breadcrumb-item>
        <el-breadcrumb-item :to="{ path: '/zones' }">ZoneRunner</el-breadcrumb-item>
        <el-breadcrumb-item v-if="currentPage">{{ currentPage }}</el-breadcrumb-item>
      </el-breadcrumb>
    </div>
    <div class="top-bar-right">
      <el-dropdown trigger="click">
        <span class="user-info">
          <el-icon><UserFilled /></el-icon>
          <span>{{ user?.display_name || user?.username }}</span>
          <el-icon><ArrowDown /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>
              角色：{{ user?.role }}
            </el-dropdown-item>
            <el-dropdown-item divided @click="handleLogout">
              <el-icon><SwitchButton /></el-icon> 退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const user = computed(() => authStore.user)

const currentPage = computed(() => {
  if (route.name === 'ZoneList') return 'Zone 列表'
  if (route.name === 'RecordList') return '资源记录列表'
  if (route.name === 'NamedConfig') return 'named 配置'
  if (route.name === 'Audit') return '审计日志'
  if (route.name === 'ChangeRequests') return '变更审批'
  if (route.name === 'UserManagement') return '用户管理'
  return ''
})

function handleLogout() {
  authStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.top-bar {
  height: 48px;
  background: linear-gradient(180deg, var(--bg-header-start), var(--bg-header-end));
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  flex-shrink: 0;
}

.top-bar-left :deep(.el-breadcrumb__inner) {
  color: rgba(255, 255, 255, 0.8);
  font-size: 13px;
}

.top-bar-left :deep(.el-breadcrumb__inner.is-link:hover) {
  color: #FFFFFF;
}

.top-bar-right {
  display: flex;
  align-items: center;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #FFFFFF;
  cursor: pointer;
  font-size: 13px;
  padding: 4px 8px;
  border-radius: 4px;
}

.user-info:hover {
  background: rgba(255, 255, 255, 0.15);
}
</style>
