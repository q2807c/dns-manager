<template>
  <div class="record-list-page">
    <div class="page-header">
      <h2 class="page-title">
        资源记录列表
        <span class="zone-label">{{ zoneName }}</span>
      </h2>
      <el-button type="primary" @click="openAddDialog" v-if="canAdd">
        <el-icon><Plus /></el-icon> 添加资源记录
      </el-button>
    </div>

    <!-- Zone Info Bar -->
    <div class="zone-info-bar">
      <span>Zone：<strong>{{ zoneName }}</strong></span>
      <span class="separator">|</span>
      <span>视图：<strong>external</strong></span>
      <span class="separator">|</span>
      <span>序列号：<strong>{{ zoneSerial || 'N/A' }}</strong></span>
      <span class="separator">|</span>
      <span>共 <strong>{{ total }}</strong> 条记录</span>
    </div>

    <div class="toolbar">
      <el-input v-model="search" placeholder="搜索名称或数据..." clearable @keyup.enter="fetchRecords" style="width: 260px;">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="recordTypeFilter" placeholder="全部类型" clearable @change="fetchRecords" style="width: 140px;">
        <el-option label="全部" value="" />
        <el-option label="A" value="A" />
        <el-option label="AAAA" value="AAAA" />
        <el-option label="CNAME" value="CNAME" />
        <el-option label="MX" value="MX" />
        <el-option label="NS" value="NS" />
        <el-option label="SOA" value="SOA" />
        <el-option label="SRV" value="SRV" />
        <el-option label="TXT" value="TXT" />
        <el-option label="PTR" value="PTR" />
      </el-select>
      <el-button @click="fetchRecords">搜索</el-button>
    </div>

    <!-- Loading skeleton -->
    <template v-if="loading">
      <el-skeleton :rows="8" animated style="margin-top: 16px;" />
    </template>

    <!-- Empty state -->
    <el-empty v-else-if="records.length === 0 && !search && !recordTypeFilter" description="该 Zone 暂无资源记录" />
    <el-empty v-else-if="records.length === 0" description="没有匹配的记录" />

    <!-- Records table -->
    <template v-else>
      <el-table :data="records" stripe>
        <el-table-column prop="name" label="名称" min-width="200">
          <template #default="{ row }">
            <code class="record-name">{{ row.name }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="type" label="类型" width="100">
          <template #default="{ row }">
            <span :class="['record-type', row.type]">{{ row.type }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="ttl" label="TTL" width="80" align="right">
          <template #default="{ row }">{{ row.ttl }}</template>
        </el-table-column>
        <el-table-column label="数据" min-width="300">
          <template #default="{ row }">
            <span class="record-data" :class="{ 'record-data-mono': isMonoType(row.type) }">
              {{ row.data }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right" v-if="canModify">
          <template #default="{ row }">
            <el-button size="small" @click="openEditDialog(row)" v-if="row.type !== 'SOA'">编辑</el-button>
            <el-button
              size="small"
              type="danger"
              @click="confirmDelete(row)"
              v-if="row.type !== 'SOA'"
            >删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="fetchRecords"
      />
    </template>

    <!-- Add/Edit Record Dialog -->
    <el-dialog v-model="dialogVisible" :title="editingRecord ? '编辑资源记录' : '添加资源记录'" width="550px">
      <el-form :model="recordForm" label-width="120px">
        <el-form-item label="Zone 名称">
          <el-input :model-value="zoneName" disabled />
        </el-form-item>
        <el-form-item label="视图">
          <el-input model-value="external" disabled />
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="recordForm.name" placeholder="例如 www 或 @" />
        </el-form-item>
        <el-form-item label="TTL">
          <el-input-number v-model="recordForm.ttl" :min="0" :max="86400" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="recordForm.type" :disabled="!!editingRecord" @change="onTypeChange">
            <el-option label="A - IPv4 地址" value="A" />
            <el-option label="AAAA - IPv6 地址" value="AAAA" />
            <el-option label="CNAME - 别名" value="CNAME" />
            <el-option label="MX - 邮件交换" value="MX" />
            <el-option label="NS - 域名服务器" value="NS" />
            <el-option label="SRV - 服务记录" value="SRV" />
            <el-option label="TXT - 文本" value="TXT" />
            <el-option label="PTR - 指针" value="PTR" />
          </el-select>
        </el-form-item>
        <!-- Type-specific fields -->
        <el-form-item v-if="recordForm.type === 'MX'" label="优先级">
          <el-input-number v-model="recordForm.priority" :min="0" :max="65535" />
        </el-form-item>
        <el-form-item v-if="recordForm.type === 'SRV'" label="优先级">
          <el-input-number v-model="recordForm.priority" :min="0" :max="65535" />
        </el-form-item>
        <el-form-item v-if="recordForm.type === 'SRV'" label="权重">
          <el-input-number v-model="recordForm.weight" :min="0" :max="65535" />
        </el-form-item>
        <el-form-item v-if="recordForm.type === 'SRV'" label="端口">
          <el-input-number v-model="recordForm.port" :min="0" :max="65535" />
        </el-form-item>
        <el-form-item :label="dataFieldLabel" required>
          <el-input v-model="recordForm.data" :placeholder="dataFieldPlaceholder" />
        </el-form-item>
      </el-form>

      <!-- Preview -->
      <div v-if="previewText" class="record-preview">
        <div class="preview-label">预览：</div>
        <code>{{ previewText }}</code>
      </div>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="warning" :loading="saving" @click="submitForApproval">
          提交审批
        </el-button>
        <el-button type="primary" :loading="saving" @click="saveRecord" v-if="canDirectExecute">
          {{ editingRecord ? '更新' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'

const route = useRoute()
const authStore = useAuthStore()

const zoneName = computed(() => route.params.zoneName as string)

const records = ref<any[]>([])
const loading = ref(false)
const search = ref('')
const recordTypeFilter = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const zoneSerial = ref<string | null>(null)

const canAdd = computed(() => {
  const role = authStore.user?.role
  return role === 'super_admin' || role === 'zone_admin' || role === 'zone_operator'
})
const canModify = computed(() => canAdd.value)
const canDirectExecute = computed(() => {
  const role = authStore.user?.role
  return role === 'super_admin' || role === 'zone_admin' || role === 'zone_operator'
})

// Dialog
const dialogVisible = ref(false)
const editingRecord = ref<any | null>(null)
const saving = ref(false)
const recordForm = ref({
  name: '@',
  type: 'A',
  ttl: 300,
  data: '',
  priority: undefined as number | undefined,
  weight: undefined as number | undefined,
  port: undefined as number | undefined,
})

const dataFieldLabel = computed(() => {
  const labels: Record<string, string> = {
    A: 'IP 地址',
    AAAA: 'IPv6 地址',
    CNAME: '别名目标',
    MX: '邮件服务器',
    NS: '域名服务器',
    SRV: '目标主机',
    TXT: '文本数据',
    PTR: '域名',
  }
  return labels[recordForm.value.type] || '数据'
})

const dataFieldPlaceholder = computed(() => {
  const placeholders: Record<string, string> = {
    A: '10.63.2.100',
    AAAA: '2001:db8::1',
    CNAME: 'target.example.com.',
    MX: 'mail.example.com.',
    NS: 'ns1.example.com.',
    SRV: 'sip.example.com.',
    TXT: 'v=spf1 ~all',
    PTR: 'host.example.com.',
  }
  return placeholders[recordForm.value.type] || ''
})

const previewText = computed(() => {
  if (!recordForm.value.data) return ''
  const f = recordForm.value
  let line = `${f.name}  ${f.ttl}  IN  ${f.type}  `
  if (f.type === 'MX') line += `${f.priority || 10} ${f.data}.`
  else if (f.type === 'SRV') line += `${f.priority || 0} ${f.weight || 0} ${f.port || 0} ${f.data}.`
  else if (f.type === 'TXT') line += `"${f.data}"`
  else if (['CNAME', 'NS', 'PTR'].includes(f.type)) line += `${f.data}.`
  else line += f.data
  return line
})

function isMonoType(type: string) {
  return ['A', 'AAAA', 'PTR', 'SRV'].includes(type)
}

function onTypeChange() {
  recordForm.value.data = ''
  recordForm.value.priority = undefined
  recordForm.value.weight = undefined
  recordForm.value.port = undefined
}

async function fetchRecords() {
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (search.value) params.search = search.value
    if (recordTypeFilter.value) params.record_type = recordTypeFilter.value
    const { data } = await api.get(`/zones/${zoneName.value}/records`, { params })
    records.value = data.items
    total.value = data.total
    zoneSerial.value = data.zone_serial
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载记录失败')
  } finally {
    loading.value = false
  }
}

function openAddDialog() {
  editingRecord.value = null
  recordForm.value = { name: '@', type: 'A', ttl: 300, data: '', priority: undefined, weight: undefined, port: undefined }
  dialogVisible.value = true
}

function openEditDialog(record: any) {
  editingRecord.value = record
  const form: any = {
    name: record.name,
    type: record.type,
    ttl: record.ttl,
    data: record.data,
    priority: undefined,
    weight: undefined,
    port: undefined,
  }
  if (record.type === 'MX') {
    const m = record.data.match(/^(\d+)\s+(.+)/)
    if (m) { form.priority = parseInt(m[1]); form.data = m[2] }
  }
  if (record.type === 'SRV') {
    const m = record.data.match(/^(\d+)\s+(\d+)\s+(\d+)\s+(.+)/)
    if (m) { form.priority = parseInt(m[1]); form.weight = parseInt(m[2]); form.port = parseInt(m[3]); form.data = m[4] }
  }
  recordForm.value = form
  dialogVisible.value = true
}

async function saveRecord() {
  saving.value = true
  try {
    const f = recordForm.value
    let dataValue = f.data
    if (f.type === 'MX') {
      dataValue = `${f.priority || 10} ${f.data}`
    } else if (f.type === 'SRV') {
      dataValue = `${f.priority || 0} ${f.weight || 0} ${f.port || 0} ${f.data}`
    }
    const payload = { name: f.name, type: f.type, ttl: f.ttl, data: dataValue }
    if (editingRecord.value) {
      await api.put(`/zones/${zoneName.value}/records/${editingRecord.value.id}`, payload)
      ElMessage.success('记录已更新')
    } else {
      await api.post(`/zones/${zoneName.value}/records`, payload)
      ElMessage.success('记录已添加')
    }
    dialogVisible.value = false
    fetchRecords()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存记录失败')
  } finally {
    saving.value = false
  }
}

async function submitForApproval() {
  saving.value = true
  try {
    const f = recordForm.value
    let dataValue = f.data
    if (f.type === 'MX') {
      dataValue = `${f.priority || 10} ${f.data}`
    } else if (f.type === 'SRV') {
      dataValue = `${f.priority || 0} ${f.weight || 0} ${f.port || 0} ${f.data}`
    }
    const payload = {
      name: f.name,
      type: f.type,
      ttl: f.ttl,
      data: dataValue,
      ...(editingRecord.value ? { record_id: editingRecord.value.id } : {}),
    }
    const action = editingRecord.value ? 'record_modify' : 'record_create'
    const summary = editingRecord.value
      ? `修改 ${zoneName.value} 的记录 ${f.name} ${f.type} ${f.data}`
      : `添加 ${f.name} ${f.type} ${f.data} 到 ${zoneName.value}`

    await api.post('/change-requests', {
      action,
      zone_name: zoneName.value,
      summary,
      payload,
    })
    ElMessage.success('变更请求已提交审批')
    dialogVisible.value = false
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '提交审批失败')
  } finally {
    saving.value = false
  }
}

async function confirmDelete(record: any) {
  try {
    await ElMessageBox.confirm(
      `确定要删除记录 "${record.name} ${record.type} ${record.data}" 吗？`,
      '删除记录',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        distinguishCancelAndClose: true,
      }
    )

    if (canDirectExecute.value) {
      await api.delete(`/zones/${zoneName.value}/records/${record.id}`)
      ElMessage.success('记录已删除')
    } else {
      await api.post('/change-requests', {
        action: 'record_delete',
        zone_name: zoneName.value,
        summary: `删除 ${zoneName.value} 的记录 ${record.name} ${record.type} ${record.data}`,
        payload: { record_id: record.id, name: record.name, type: record.type, data: record.data },
      })
      ElMessage.success('删除请求已提交审批')
    }
    fetchRecords()
  } catch {
    // cancelled
  }
}

watch(() => zoneName.value, fetchRecords, { immediate: true })
</script>

<style scoped>
.zone-label {
  font-size: 14px;
  font-weight: normal;
  color: var(--text-secondary);
  margin-left: 12px;
  padding: 2px 12px;
  background: #E3F2FD;
  border-radius: 12px;
}

.zone-info-bar {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 10px 16px;
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--text-secondary);
  display: flex;
  gap: 12px;
  align-items: center;
}

.zone-info-bar strong {
  color: var(--text-primary);
}

.zone-info-bar .separator {
  color: var(--border-color);
}

.record-name {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--color-primary);
  background: #E3F2FD;
  padding: 2px 6px;
  border-radius: 3px;
}

.record-data {
  font-size: 13px;
}

.record-data-mono {
  font-family: var(--font-mono);
  color: var(--text-secondary);
}

.record-preview {
  margin-top: 16px;
  padding: 12px;
  background: #F5F6FA;
  border: 1px solid var(--border-color);
  border-radius: 4px;
}

.preview-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.record-preview code {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-primary);
}
</style>
