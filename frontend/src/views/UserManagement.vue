<template>
  <div class="users-page">
    <div class="page-header">
      <h2 class="page-title">用户管理</h2>
      <el-button type="primary" @click="openAddDialog" v-if="isSuperAdmin">
        <el-icon><Plus /></el-icon> 添加用户
      </el-button>
    </div>

    <!-- Info bar -->
    <div class="info-bar">
      <span><el-icon><User /></el-icon> 共 <strong>{{ users.length }}</strong> 个用户</span>
      <span class="separator">|</span>
      <span><el-icon><UserFilled /></el-icon> 角色：超级管理员 · Zone 管理员 · Zone 操作员 · Zone 查看者 · 审批人</span>
    </div>

    <!-- Loading skeleton -->
    <template v-if="loading">
      <el-skeleton :rows="5" animated style="margin-top: 16px;" />
    </template>

    <!-- Empty state -->
    <el-empty v-else-if="users.length === 0" description="暂无用户" />

    <!-- User table -->
    <template v-else>
      <el-table :data="users" stripe>
        <el-table-column prop="username" label="用户名" width="160">
          <template #default="{ row }">
            <div class="user-name-cell">
              <el-icon :size="16" class="user-avatar-icon"><User /></el-icon>
              <span>{{ row.username }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="display_name" label="显示名称" width="150" />
        <el-table-column prop="email" label="邮箱" min-width="200">
          <template #default="{ row }">
            <span class="email-cell">{{ row.email || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="role" label="角色" width="150">
          <template #default="{ row }">
            <span :class="['role-badge', row.role]">{{ formatRole(row.role) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" align="center">
          <template #default="{ row }">
            <el-button size="small" @click="openEditDialog(row)" :disabled="!isSuperAdmin && row.role === 'super_admin'">
              编辑
            </el-button>
            <el-button
              size="small"
              :type="row.is_active ? 'warning' : 'success'"
              @click="confirmToggleUser(row)"
              :disabled="row.username === authStore.user?.username"
            >
              {{ row.is_active ? '禁用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <!-- Add/Edit User Dialog -->
    <el-dialog v-model="dialogVisible" :title="editingUser ? '编辑用户' : '添加用户'" width="600px" destroy-on-close @opened="fetchZonesForForm">
      <el-form :model="userForm" label-width="120px">
        <el-form-item label="用户名" required>
          <el-input v-model="userForm.username" :disabled="!!editingUser" placeholder="字母数字，3-32 位" />
        </el-form-item>
        <el-form-item label="密码" :required="!editingUser">
          <el-input v-model="userForm.password" type="password" show-password :placeholder="editingUser ? '留空则保持不变' : '至少 6 个字符'" />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="userForm.display_name" placeholder="例如 张三" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="userForm.email" placeholder="user@example.com" />
        </el-form-item>
        <el-form-item label="角色" required>
          <el-select v-model="userForm.role" style="width: 100%;" @change="onRoleChange">
            <el-option label="超级管理员 — 全部权限" value="super_admin" />
            <el-option label="Zone 管理员 — 完整 Zone 管理" value="zone_admin" />
            <el-option label="Zone 操作员 — CRUD 操作" value="zone_operator" />
            <el-option label="Zone 查看者 — 只读" value="zone_viewer" />
            <el-option label="审批人 — 仅审批" value="approver" />
          </el-select>
        </el-form-item>

        <!-- Zone Access Section (for zone_operator and zone_viewer) -->
        <el-form-item v-if="showZoneAccess" label="Zone 访问权限">
          <div class="zone-access-section">
            <!-- Multi-zone selector -->
            <el-select
              v-model="selectedZones"
              multiple
              filterable
              placeholder="选择 Zone（可多选）"
              style="width: 100%; margin-bottom: 12px;"
            >
              <el-option
                v-for="zone in zoneList"
                :key="zone.id"
                :label="zone.zone_name"
                :value="zone.id"
              />
            </el-select>

            <!-- Permission checkboxes -->
            <el-checkbox-group v-model="defaultPermissions" class="perm-checkboxes">
              <el-checkbox label="zone_view">查看 Zone</el-checkbox>
              <el-checkbox label="record_view">查看记录</el-checkbox>
              <el-checkbox v-if="userForm.role !== 'zone_viewer'" label="record_add">添加记录</el-checkbox>
              <el-checkbox v-if="userForm.role !== 'zone_viewer'" label="record_modify">修改记录</el-checkbox>
              <el-checkbox v-if="userForm.role !== 'zone_viewer'" label="record_delete">删除记录</el-checkbox>
            </el-checkbox-group>

            <!-- Existing zone access list (read-only summary) -->
            <div v-if="userForm.zone_access.length > 0" class="zone-access-list">
              <div class="zone-access-list-header">
                <span>已配置权限（{{ userForm.zone_access.length }} 个 Zone）</span>
                <el-button type="danger" link size="small" @click="clearAllZoneAccess">
                  清空全部
                </el-button>
              </div>
              <el-tag
                v-for="(za, idx) in userForm.zone_access"
                :key="idx"
                closable
                class="zone-tag"
                @close="removeZoneAccess(idx)"
              >
                {{ getZoneName(za.zone_id) }} — {{ za.permissions.length }} 项权限
              </el-tag>
            </div>

            <el-button type="primary" size="small" :icon="Plus" @click="addZoneAccess" :disabled="selectedZones.length === 0">
              添加所选 Zone 权限
            </el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveUser">{{ editingUser ? '更新' : '创建' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'

const authStore = useAuthStore()

const isSuperAdmin = computed(() => authStore.user?.role === 'super_admin')

const users = ref<any[]>([])
const zoneList = ref<any[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingUser = ref<any | null>(null)
const saving = ref(false)

// Multi-select state
const selectedZones = ref<number[]>([])
const defaultPermissions = ref<string[]>(['zone_view', 'record_view'])

interface ZoneAccessItem {
  zone_id: number | null
  zone_pattern: string | null
  permissions: string[]
}

const userForm = ref({
  username: '',
  password: '',
  display_name: '',
  email: '',
  role: 'zone_viewer',
  zone_access: [] as ZoneAccessItem[],
})

const showZoneAccess = computed(() =>
  ['zone_operator', 'zone_viewer'].includes(userForm.value.role)
)

function getZoneName(zoneId: number | null): string {
  const zone = zoneList.value.find(z => z.id === zoneId)
  return zone?.zone_name || `Zone #${zoneId}`
}

async function fetchUsers() {
  loading.value = true
  try {
    const { data } = await api.get('/users')
    users.value = data.items || data
  } catch {
    ElMessage.error('加载用户列表失败')
  } finally {
    loading.value = false
  }
}

async function fetchZonesForForm() {
  try {
    const { data } = await api.get('/zones', { params: { page_size: 100 } })
    zoneList.value = data.items || []
  } catch (e: any) {
    console.error('Failed to load zone list:', e)
  }
}

async function openAddDialog() {
  editingUser.value = null
  if (zoneList.value.length === 0) {
    await fetchZonesForForm()
  }
  userForm.value = {
    username: '',
    password: '',
    display_name: '',
    email: '',
    role: 'zone_viewer',
    zone_access: [],
  }
  selectedZones.value = []
  defaultPermissions.value = ['zone_view', 'record_view']
  dialogVisible.value = true
}

async function openEditDialog(user: any) {
  editingUser.value = user
  // Pre-load zone list before showing dialog so select renders correctly
  if (zoneList.value.length === 0) {
    await fetchZonesForForm()
  }
  userForm.value = {
    username: user.username,
    password: '',
    display_name: user.display_name || '',
    email: user.email || '',
    role: user.role,
    zone_access: (user.zone_access || []).map((za: any) => ({
      zone_id: za.zone_id,
      zone_pattern: za.zone_pattern,
      permissions: [...za.permissions],
    })),
  }
  selectedZones.value = []
  defaultPermissions.value = user.role === 'zone_operator'
    ? ['zone_view', 'record_view', 'record_add', 'record_modify', 'record_delete']
    : ['zone_view', 'record_view']
  dialogVisible.value = true
}

function onRoleChange() {
  if (userForm.value.role === 'zone_operator') {
    defaultPermissions.value = ['zone_view', 'record_view', 'record_add', 'record_modify', 'record_delete']
  } else if (userForm.value.role === 'zone_viewer') {
    defaultPermissions.value = ['zone_view', 'record_view']
  }
}

function onZoneSelect(_idx: number, _zoneId: any) {}

function addZoneAccess() {
  if (selectedZones.value.length === 0) return

  const perms = [...defaultPermissions.value]

  for (const zoneId of selectedZones.value) {
    // Skip if already exists
    const exists = userForm.value.zone_access.some(za => za.zone_id === zoneId)
    if (exists) continue

    userForm.value.zone_access.push({
      zone_id: zoneId,
      zone_pattern: null,
      permissions: perms,
    })
  }

  selectedZones.value = []
}

function removeZoneAccess(idx: number) {
  userForm.value.zone_access.splice(idx, 1)
}

function clearAllZoneAccess() {
  userForm.value.zone_access = []
}

async function saveUser() {
  saving.value = true
  try {
    const payload: any = { ...userForm.value }
    if (!payload.password) delete payload.password

    // Clean up zone_access: remove empty entries
    if (showZoneAccess.value) {
      payload.zone_access = payload.zone_access.filter((za: ZoneAccessItem) => za.zone_id)
    } else {
      payload.zone_access = []
    }

    if (editingUser.value) {
      await api.put(`/users/${editingUser.value.id}`, payload)
      ElMessage.success('用户已更新')
    } else {
      await api.post('/users', payload)
      ElMessage.success('用户已创建')
    }
    dialogVisible.value = false
    fetchUsers()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存用户失败')
  } finally {
    saving.value = false
  }
}

async function confirmToggleUser(user: any) {
  const action = user.is_active ? '禁用' : '启用'
  try {
    await ElMessageBox.confirm(
      `确定要${action}用户 "${user.username}" 吗？`,
      '确认操作',
      { confirmButtonText: action, cancelButtonText: '取消', type: 'warning' }
    )
    await api.put(`/users/${user.id}`, { is_active: !user.is_active })
    ElMessage.success(`用户已${action}`)
    fetchUsers()
  } catch {
    // cancelled
  }
}

function formatRole(role: string): string {
  const map: Record<string, string> = {
    super_admin: '超级管理员',
    zone_admin: 'Zone 管理员',
    zone_operator: 'Zone 操作员',
    zone_viewer: 'Zone 查看者',
    approver: '审批人',
  }
  return map[role] || role
}

onMounted(() => {
  fetchUsers()
  fetchZonesForForm()
})
</script>

<style scoped>
.user-name-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.user-avatar-icon {
  color: var(--color-primary);
  opacity: 0.7;
}

.email-cell {
  color: var(--text-secondary);
  font-size: 13px;
}

.role-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 3px;
  font-size: 12px;
  font-weight: 600;
}

.role-badge.super_admin { background: #FFEBEE; color: #C62828; }
.role-badge.zone_admin { background: #FFF3E0; color: #E65100; }
.role-badge.zone_operator { background: #E3F2FD; color: #1565C0; }
.role-badge.zone_viewer { background: #E8F5E9; color: #2E7D32; }
.role-badge.approver { background: #F3E5F5; color: #7B1FA2; }

.zone-access-section {
  width: 100%;
}

.zone-access-list {
  margin: 12px 0;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 6px;
}

.zone-access-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.zone-tag {
  margin: 4px 6px 4px 0;
}

.zone-access-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.perm-checkboxes {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding-top: 2px;
}
</style>
