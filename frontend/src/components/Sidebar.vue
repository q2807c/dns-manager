<template>
  <div class="sidebar">
    <div class="sidebar-logo">
      <div class="logo-icon">DNS</div>
      <div class="logo-text">Zone Manager</div>
    </div>
    <el-menu
      :default-active="activeMenu"
      background-color="#1A2332"
      text-color="#C8D6E5"
      active-text-color="#FFFFFF"
      router
    >
      <el-menu-item index="/zones">
        <el-icon><List /></el-icon>
        <span>Zone 列表</span>
      </el-menu-item>
      <el-menu-item index="/named-config" v-if="isAdmin">
        <el-icon><Document /></el-icon>
        <span>named 配置</span>
      </el-menu-item>
      <el-divider style="margin: 8px 0; border-color: #2C3E50;" />
      <el-menu-item index="/change-requests" v-if="canApprove">
        <el-icon><Checked /></el-icon>
        <span>变更审批</span>
      </el-menu-item>
      <el-menu-item index="/audit" v-if="isAdmin">
        <el-icon><Clock /></el-icon>
        <span>审计日志</span>
      </el-menu-item>
      <el-menu-item index="/users" v-if="user?.role === 'super_admin'">
        <el-icon><User /></el-icon>
        <span>用户管理</span>
      </el-menu-item>
      <el-menu-item index="/devices" v-if="user?.role === 'super_admin'">
        <el-icon><Monitor /></el-icon>
        <span>设备管理</span>
      </el-menu-item>
    </el-menu>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const authStore = useAuthStore()

const user = computed(() => authStore.user)
const isAdmin = computed(() => ['super_admin', 'zone_admin'].includes(user.value?.role || ''))
const canApprove = computed(() => ['super_admin', 'zone_admin', 'approver'].includes(user.value?.role || ''))

const activeMenu = computed(() => {
  if (route.path.startsWith('/zones/') && route.path.includes('/records')) return '/zones'
  return route.path
})
</script>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
  background: var(--bg-sidebar);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.sidebar-logo {
  padding: 20px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid #2C3E50;
}

.logo-icon {
  width: 42px;
  height: 42px;
  background: linear-gradient(135deg, #1565C0, #42A5F5);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 700;
  font-size: 14px;
  letter-spacing: -0.5px;
}

.logo-text {
  color: #FFFFFF;
  font-size: 15px;
  font-weight: 600;
}

.el-menu {
  border-right: none;
  flex: 1;
}

.el-menu-item {
  font-size: 14px;
  height: 44px;
  line-height: 44px;
}

.el-menu-item .el-icon {
  font-size: 16px;
}
</style>
