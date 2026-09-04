<template>
  <div class="device-page">
    <div class="page-header">
      <h2 class="page-title">
        <el-icon :size="20"><Monitor /></el-icon>
        设备管理
      </h2>
      <el-button type="primary" @click="openAddDialog" v-if="isSuperAdmin">
        <el-icon><Plus /></el-icon> 添加设备
      </el-button>
    </div>

    <!-- Device table -->
    <el-table :data="devices" v-loading="loading" stripe>
      <el-table-column prop="group_name" label="同步组" min-width="140">
        <template #default="{ row }">
          <span class="device-name">
            <el-icon :size="14"><Connection /></el-icon>
            {{ row.group_name }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="host" label="地址" min-width="160">
        <template #default="{ row }">
          <code>{{ row.host }}:{{ row.port }}</code>
        </template>
      </el-table-column>
      <el-table-column prop="username" label="用户" width="80" />
      <el-table-column prop="zone_count" label="Zone 数" width="90" align="center">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ row.zone_count }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="is_active" label="状态" width="90" align="center">
        <template #default="{ row }">
          <span :class="['status-badge', row.is_active ? 'active' : 'off']">
            {{ row.is_active ? '启用' : '禁用' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="text-muted">{{ row.description || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right" v-if="isSuperAdmin">
        <template #default="{ row }">
          <el-button size="small" @click="testConnection(row)" :loading="row._testing">
            <el-icon><Link /></el-icon> 测试
          </el-button>
          <el-button size="small" @click="openEditDialog(row)">
            <el-icon><Edit /></el-icon> 编辑
          </el-button>
          <el-button size="small" type="danger" :icon="Delete" @click="confirmDelete(row)" />
        </template>
      </el-table-column>
    </el-table>

    <!-- Create/Edit Dialog -->
    <el-dialog v-model="dialogVisible" :title="isEditing ? '编辑设备' : '添加设备'" width="580px">
      <el-form :model="form" label-width="140px">
        <el-form-item label="同步组名称" required>
          <el-input v-model="form.group_name" placeholder="例如 BQJ-01" />
        </el-form-item>
        <el-form-item label="设备地址" required>
          <el-input v-model="form.host" placeholder="172.18.1.202" />
        </el-form-item>
        <el-form-item label="SSH 端口">
          <el-input-number v-model="form.port" :min="1" :max="65535" style="width: 160px;" />
        </el-form-item>
        <el-form-item label="SSH 用户">
          <el-input v-model="form.username" placeholder="root" />
        </el-form-item>
        <el-form-item label="SSH 密码">
          <el-input v-model="form.password" type="password" show-password placeholder="留空使用密钥认证" />
        </el-form-item>
        <el-form-item label="私钥路径">
          <el-input v-model="form.key_path" placeholder="/app/keys/id_ed25519" />
        </el-form-item>
        <el-form-item label="私钥密码短语">
          <el-input v-model="form.key_passphrase" type="password" show-password placeholder="（可选）" />
        </el-form-item>
        <el-form-item label="named.conf 路径">
          <el-input v-model="form.named_conf_path" placeholder="/var/named/config/named.conf" />
        </el-form-item>
        <el-form-item label="Zone 目录">
          <el-input v-model="form.zone_dir" placeholder="/var/named/config/namedb" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="设备用途说明" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveDevice">
          <el-icon><Plus /></el-icon> {{ isEditing ? '保存' : '添加' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Test Result Dialog -->
    <el-dialog v-model="testVisible" title="连接测试" width="420px">
      <div v-if="testResult">
        <el-alert
          :type="testResult.status === 'success' ? 'success' : 'error'"
          :title="testResult.status === 'success' ? '连接成功' : '连接失败'"
          :closable="false"
          show-icon
        >
          <template v-if="testResult.status === 'success'">
            <p>主机名：{{ testResult.hostname }}</p>
          </template>
          <template v-else>
            <p>{{ testResult.error || '未知错误' }}</p>
          </template>
        </el-alert>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'

const authStore = useAuthStore()
const isSuperAdmin = computed(() => authStore.user?.role === 'super_admin')

const devices = ref<any[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const isEditing = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)

const testVisible = ref(false)
const testResult = ref<any>(null)

const defaultForm = () => ({
  group_name: '',
  host: '',
  port: 22,
  username: 'root',
  password: '',
  key_path: '',
  key_passphrase: '',
  named_conf_path: '/var/named/config/named.conf',
  zone_dir: '/var/named/config/namedb',
  is_active: true,
  description: '',
})

const form = ref(defaultForm())

async function fetchDevices() {
  loading.value = true
  try {
    const { data } = await api.get('/devices')
    devices.value = data.items
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载设备列表失败')
  } finally {
    loading.value = false
  }
}

function openAddDialog() {
  isEditing.value = false
  editingId.value = null
  form.value = defaultForm()
  dialogVisible.value = true
}

function openEditDialog(device: any) {
  isEditing.value = true
  editingId.value = device.id
  form.value = {
    group_name: device.group_name,
    host: device.host,
    port: device.port,
    username: device.username,
    password: '',
    key_path: device.key_path || '',
    key_passphrase: '',
    named_conf_path: device.named_conf_path,
    zone_dir: device.zone_dir,
    is_active: device.is_active,
    description: device.description || '',
  }
  dialogVisible.value = true
}

async function saveDevice() {
  if (!form.value.group_name || !form.value.host) {
    ElMessage.warning('请填写同步组名称和设备地址')
    return
  }
  saving.value = true
  try {
    if (isEditing.value) {
      const payload: any = { ...form.value }
      if (!payload.password) delete payload.password
      if (!payload.key_passphrase) delete payload.key_passphrase
      await api.put(`/devices/${editingId.value}`, payload)
      ElMessage.success('设备更新成功')
    } else {
      await api.post('/devices', form.value)
      ElMessage.success('设备添加成功')
    }
    dialogVisible.value = false
    fetchDevices()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    saving.value = false
  }
}

async function confirmDelete(device: any) {
  try {
    await ElMessageBox.confirm(
      `确定要删除设备 "${device.group_name}" 吗？\n\n该操作不可撤销，且设备上不能有已关联的 Zone。`,
      '删除设备',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      }
    )
    await api.delete(`/devices/${device.id}`)
    ElMessage.success(`设备 "${device.group_name}" 已删除`)
    fetchDevices()
  } catch {
    // cancelled
  }
}

async function testConnection(device: any) {
  device._testing = true
  try {
    const { data } = await api.post(`/devices/${device.id}/test`)
    testResult.value = data
    testVisible.value = true
  } catch (e: any) {
    testResult.value = { status: 'failed', error: e.response?.data?.detail || '测试请求失败' }
    testVisible.value = true
  } finally {
    device._testing = false
  }
}

onMounted(fetchDevices)
</script>

<style scoped>
.device-name {
  color: var(--color-primary);
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.status-badge.off {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
}

.text-muted {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
