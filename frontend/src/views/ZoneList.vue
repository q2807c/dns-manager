<template>
  <div class="zone-list-page">
    <div class="page-header">
      <h2 class="page-title">
        <el-icon :size="20"><Collection /></el-icon>
        Zone 列表
      </h2>
      <el-button type="primary" @click="showCreateDialog = true" v-if="canCreate">
        <el-icon><Plus /></el-icon> 创建 Zone
      </el-button>
    </div>

    <div class="toolbar">
      <el-input
        v-model="search"
        placeholder="搜索 Zone 名称..."
        clearable
        @clear="fetchZones"
        @keyup.enter="fetchZones"
        style="width: 260px;"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="viewFilter" placeholder="视图" clearable @change="fetchZones">
        <el-option label="external" value="external" />
        <el-option label="internal" value="internal" />
      </el-select>
      <el-button @click="fetchZones">搜索</el-button>
      <el-button @click="syncZones" :loading="syncing" v-if="canCreate" type="success" plain>
        <el-icon><Refresh /></el-icon> 同步 Zone
      </el-button>
      <span class="toolbar-info" v-if="total > 0">共 {{ total }} 个 Zone</span>
    </div>

    <!-- Loading skeleton -->
    <el-skeleton v-if="loading && zones.length === 0" :rows="8" animated />

    <!-- Empty state -->
    <el-empty v-else-if="!loading && zones.length === 0" description="暂无 Zone">
      <template #image>
        <el-icon :size="64" color="#C0C4CC"><FolderOpened /></el-icon>
      </template>
      <el-button type="primary" @click="showCreateDialog = true" v-if="canCreate">创建第一个 Zone</el-button>
    </el-empty>

    <!-- Zone table -->
    <el-table
      v-else
      :data="zones"
      v-loading="loading"
      stripe
      @row-click="goToRecords"
      style="cursor: pointer;"
      highlight-current-row
    >
      <el-table-column prop="zone_name" label="Zone 名称" min-width="220">
        <template #default="{ row }">
          <span class="zone-name-link">
            <el-icon :size="14"><Folder /></el-icon>
            {{ row.zone_name }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="view_name" label="视图" width="100">
        <template #default="{ row }">
          <span class="status-badge master">{{ row.view_name }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="device_name" label="设备" width="120" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="text-muted">{{ getDeviceName(row.device_id) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="zone_type" label="类型" width="100">
        <template #default="{ row }">
          <span :class="['status-badge', row.zone_type === 'master' ? 'active' : 'slave']">
            {{ row.zone_type === 'master' ? '主' : '从' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="file_name" label="Zone 文件" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <code class="inline-code">{{ row.file_name || '-' }}</code>
        </template>
      </el-table-column>
      <el-table-column prop="record_count" label="记录数" width="90" align="center">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ row.record_count }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_serial" label="序列号" width="140" align="center">
        <template #default="{ row }">
          <span class="data-mono">{{ row.last_serial || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click.stop="goToRecords(row)">
            <el-icon><View /></el-icon> 记录
          </el-button>
          <el-button size="small" @click.stop="viewRawZone(row)">
            <el-icon><Document /></el-icon> 源文件
          </el-button>
          <el-button
            v-if="canDelete"
            size="small"
            type="danger"
            :icon="Delete"
            @click.stop="confirmDelete(row)"
          />
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
      @current-change="fetchZones"
    />

    <!-- Raw Zone Dialog -->
    <el-dialog v-model="rawVisible" title="Zone 文件内容" width="70%" top="5vh">
      <div class="code-block">{{ rawContent }}</div>
    </el-dialog>

    <!-- Create Zone Dialog -->
    <el-dialog v-model="showCreateDialog" title="创建 Zone" width="580px">
      <el-form :model="createForm" label-width="140px">
        <el-form-item label="Zone 名称" required>
          <el-input v-model="createForm.zone_name" placeholder="例如 example.com">
            <template #suffix>. </template>
          </el-input>
        </el-form-item>
        <el-form-item label="目标设备" required>
          <el-select v-model="createForm.device_id" style="width: 100%;" placeholder="选择 F5 设备">
            <el-option
              v-for="d in deviceList"
              :key="d.id"
              :label="`${d.group_name} (${d.host})`"
              :value="d.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="视图名称">
          <el-select v-model="createForm.view_name" style="width: 100%;">
            <el-option label="external" value="external" />
            <el-option label="internal" value="internal" />
          </el-select>
        </el-form-item>
        <el-form-item label="Zone 类型">
          <el-select v-model="createForm.zone_type" style="width: 100%;">
            <el-option label="Master" value="master" />
            <el-option label="Slave" value="slave" />
          </el-select>
        </el-form-item>
        <el-form-item label="TTL">
          <el-input-number v-model="createForm.ttl" :min="0" :max="86400" style="width: 200px;" />
          <span class="form-hint">秒</span>
        </el-form-item>
        <el-form-item label="主服务器">
          <el-input v-model="createForm.master_server" placeholder="dns1.cnooc.com." />
        </el-form-item>
        <el-form-item label="主服务器 IP" required>
          <el-input v-model="createForm.master_server_ip" placeholder="例如 192.168.1.1">
            <template #append>A 记录</template>
          </el-input>
          <div class="form-hint">当主服务器属于该 Zone 时，必须提供 IP 地址</div>
        </el-form-item>
        <el-form-item label="邮箱联系人">
          <el-input v-model="createForm.email_contact" placeholder="hostmaster.cnooc.com." />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createZone">
          <el-icon><Plus /></el-icon> 创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'

const router = useRouter()
const authStore = useAuthStore()

const zones = ref<any[]>([])
const loading = ref(false)
const syncing = ref(false)
const search = ref('')
const viewFilter = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const canCreate = computed(() => ['super_admin', 'zone_admin'].includes(authStore.user?.role || ''))
const canDelete = computed(() => ['super_admin', 'zone_admin'].includes(authStore.user?.role || ''))

const rawVisible = ref(false)
const rawContent = ref('')

const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({
  zone_name: '',
  view_name: 'external',
  zone_type: 'master',
  ttl: 300,
  master_server: 'dns1.cnooc.com.',
  master_server_ip: '',
  email_contact: 'hostmaster.cnooc.com.',
  device_id: null as number | null,
})

// Device list for selectors
const deviceList = ref<any[]>([])

function getDeviceName(deviceId: number | null): string {
  if (!deviceId) return '-'
  const d = deviceList.value.find((item: any) => item.id === deviceId)
  return d ? d.group_name : `#${deviceId}`
}

async function fetchDevices() {
  try {
    const { data } = await api.get('/devices')
    deviceList.value = data.items
    // Set default device_id to first active device
    const active = data.items.find((d: any) => d.is_active)
    if (active && !createForm.value.device_id) {
      createForm.value.device_id = active.id
    }
  } catch {
    // Device list not critical for zone listing
  }
}

async function fetchZones() {
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (search.value) params.search = search.value
    if (viewFilter.value) params.view_name = viewFilter.value
    const { data } = await api.get('/zones', { params })
    zones.value = data.items
    total.value = data.total
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载 Zone 列表失败')
  } finally {
    loading.value = false
  }
}

function goToRecords(zone: any) {
  router.push(`/zones/${zone.zone_name}/records`)
}

async function viewRawZone(zone: any) {
  try {
    const { data } = await api.get(`/zones/${zone.zone_name}/raw`)
    rawContent.value = data.content
    rawVisible.value = true
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载 Zone 文件失败')
  }
}

async function confirmDelete(zone: any) {
  try {
    await ElMessageBox.confirm(
      `确定要永久删除 Zone "${zone.zone_name}" 吗？\n\n此操作将删除 F5 设备上的 Zone 文件，且不可撤销。`,
      '删除 Zone',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      }
    )
    await api.delete(`/zones/${zone.zone_name}`)
    ElMessage.success(`Zone "${zone.zone_name}" 已删除`)
    fetchZones()
  } catch {
    // cancelled
  }
}

async function syncZones() {
  syncing.value = true
  try {
    const { data } = await api.post('/zones/sync')
    const parts: string[] = []
    if (data.synced > 0) parts.push(`新增 ${data.synced} 个 Zone`)
    if (data.updated > 0) parts.push(`更新 ${data.updated} 个 Zone`)
    if (data.already_exists > 0) parts.push(`${data.already_exists} 个已存在`)
    if (data.errors > 0) parts.push(`${data.errors} 个失败`)
    if (parts.length === 0) {
      ElMessage.info('F5 设备上没有发现 Zone')
    } else {
      ElMessage.success(`同步完成：${parts.join('，')}`)
    }
    if (data.synced > 0) fetchZones()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '同步 Zone 失败')
  } finally {
    syncing.value = false
  }
}

async function createZone() {
  creating.value = true
  try {
    if (!createForm.value.device_id) {
      ElMessage.warning('请选择目标设备')
      creating.value = false
      return
    }
    const payload = {
      ...createForm.value,
      a_record_ip: createForm.value.master_server_ip,
    }
    await api.post('/zones', payload)
    ElMessage.success(`Zone "${createForm.value.zone_name}" 创建成功`)
    showCreateDialog.value = false
    createForm.value.zone_name = ''
    createForm.value.master_server_ip = ''
    fetchZones()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '创建 Zone 失败')
  } finally {
    creating.value = false
  }
}

onMounted(() => {
  fetchZones()
  fetchDevices()
})
</script>

<style scoped>
.zone-name-link {
  color: var(--color-primary);
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: color 0.2s;
}

.zone-name-link:hover {
  color: var(--color-primary-dark);
}

.toolbar-info {
  font-size: 13px;
  color: var(--text-muted);
  margin-left: auto;
}

.form-hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--text-muted);
}
</style>
