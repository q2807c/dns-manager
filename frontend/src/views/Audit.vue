<template>
  <div class="audit-page">
    <div class="page-header">
      <h2 class="page-title">审计日志</h2>
      <el-button @click="exportCsv" :loading="exporting">
        <el-icon><Download /></el-icon> 导出 CSV
      </el-button>
    </div>

    <div class="toolbar">
      <el-input v-model="filterUser" placeholder="用户名..." clearable style="width: 160px;" />
      <el-select v-model="filterAction" placeholder="操作类型" clearable style="width: 160px;">
        <el-option label="record_create" value="record_create" />
        <el-option label="record_modify" value="record_modify" />
        <el-option label="record_delete" value="record_delete" />
        <el-option label="zone_create" value="zone_create" />
        <el-option label="zone_delete" value="zone_delete" />
        <el-option label="raw_zone_update" value="raw_zone_update" />
      </el-select>
      <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 120px;">
        <el-option label="成功" value="success" />
        <el-option label="失败" value="failed" />
      </el-select>
      <el-button @click="fetchLogs">搜索</el-button>
    </div>

    <el-skeleton v-if="loading && logs.length === 0" :rows="8" animated />
    <el-empty v-else-if="!loading && logs.length === 0" description="暂无审计日志" />
    <el-table v-else :data="logs" v-loading="loading" stripe>
      <el-table-column prop="timestamp" label="时间" width="170">
        <template #default="{ row }">{{ formatTime(row.timestamp) }}</template>
      </el-table-column>
      <el-table-column prop="username" label="用户" width="120" />
      <el-table-column prop="action" label="操作" width="140">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="zone_name" label="Zone" width="180" />
      <el-table-column prop="target_record" label="目标" min-width="180">
        <template #default="{ row }">{{ row.target_record || '-' }}</template>
      </el-table-column>
      <el-table-column prop="before_value" label="变更前" min-width="150" show-overflow-tooltip />
      <el-table-column prop="after_value" label="变更后" min-width="150" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">
            {{ row.status === 'success' ? '成功' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
      @current-change="fetchLogs"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const logs = ref<any[]>([])
const loading = ref(false)
const exporting = ref(false)
const filterUser = ref('')
const filterAction = ref('')
const filterStatus = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)

function formatTime(ts: string) {
  return ts ? new Date(ts).toLocaleString('zh-CN') : '-'
}

async function fetchLogs() {
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (filterUser.value) params.username = filterUser.value
    if (filterAction.value) params.action = filterAction.value
    if (filterStatus.value) params.status = filterStatus.value
    const { data } = await api.get('/audit', { params })
    logs.value = data.items
    total.value = data.total
  } catch (e: any) {
    ElMessage.error('加载审计日志失败')
  } finally {
    loading.value = false
  }
}

async function exportCsv() {
  exporting.value = true
  try {
    const params: any = {}
    if (filterUser.value) params.username = filterUser.value
    if (filterAction.value) params.action = filterAction.value
    const response = await api.get('/audit/export', { params, responseType: 'blob' })
    const url = URL.createObjectURL(response.data)
    const a = document.createElement('a')
    a.href = url
    a.download = 'audit_export.csv'
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

onMounted(fetchLogs)
</script>
