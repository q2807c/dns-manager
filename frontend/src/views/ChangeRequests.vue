<template>
  <div class="cr-page">
    <div class="page-header">
      <h2 class="page-title">变更审批</h2>
      <el-button type="primary" @click="showSubmitDialog = true" v-if="canSubmit">
        <el-icon><Plus /></el-icon> 新建变更请求
      </el-button>
    </div>

    <el-tabs v-model="activeTab" @tab-change="fetchRequests">
      <el-tab-pane label="待审批" name="pending" v-if="isApprover">
        <template #label>
          <span>待审批 <el-badge :value="pendingCount" :hidden="!pendingCount" class="tab-badge" /></span>
        </template>
      </el-tab-pane>
      <el-tab-pane label="我的申请" name="mine" />
      <el-tab-pane label="全部请求" name="all" v-if="isApprover" />
    </el-tabs>

    <div class="toolbar">
      <el-select v-model="statusFilter" placeholder="状态" clearable @change="fetchRequests" style="width: 140px;">
        <el-option label="待审批" value="pending" />
        <el-option label="已通过" value="approved" />
        <el-option label="已拒绝" value="rejected" />
        <el-option label="已执行" value="executed" />
        <el-option label="执行失败" value="execution_failed" />
      </el-select>
      <el-select v-model="actionFilter" placeholder="操作" clearable @change="fetchRequests" style="width: 160px;">
        <el-option label="添加记录" value="record_create" />
        <el-option label="修改记录" value="record_modify" />
        <el-option label="删除记录" value="record_delete" />
        <el-option label="创建 Zone" value="zone_create" />
        <el-option label="删除 Zone" value="zone_delete" />
        <el-option label="编辑 Zone 源文件" value="raw_zone_edit" />
      </el-select>
      <el-input v-model="zoneFilter" placeholder="按 Zone 筛选..." clearable @keyup.enter="fetchRequests" style="width: 200px;">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button @click="fetchRequests">搜索</el-button>
    </div>

    <!-- Loading skeleton -->
    <template v-if="loading">
      <el-skeleton :rows="6" animated />
    </template>

    <!-- Empty state -->
    <el-empty v-else-if="requests.length === 0" description="暂无变更请求" />

    <!-- Request list -->
    <div v-else class="cr-list">
      <div v-for="cr in requests" :key="cr.id" class="cr-card" :class="`cr-${cr.status}`">
        <div class="cr-card-header">
          <div class="cr-card-left">
            <span :class="['cr-action-badge', cr.action]">{{ formatAction(cr.action) }}</span>
            <span class="cr-zone">{{ cr.zone_name }}</span>
            <span :class="['cr-status', cr.status]">{{ formatStatus(cr.status) }}</span>
          </div>
          <div class="cr-card-right">
            <span class="cr-time">{{ formatTime(cr.submitted_at) }}</span>
          </div>
        </div>

        <div class="cr-card-body">
          <div class="cr-meta">
            <span><el-icon><User /></el-icon> {{ cr.submitted_by }}</span>
            <span v-if="cr.reviewer"><el-icon><Checked /></el-icon> {{ cr.reviewer }}</span>
          </div>
          <div class="cr-summary" v-if="cr.summary">{{ cr.summary }}</div>
          <div class="cr-payload" v-if="cr.payload && Object.keys(cr.payload).length">
            <div class="payload-label">变更详情：</div>
            <pre class="payload-json">{{ JSON.stringify(cr.payload, null, 2) }}</pre>
          </div>
          <div class="cr-comment" v-if="cr.review_comment">
            <div class="comment-label">审批意见：</div>
            <div class="comment-text">{{ cr.review_comment }}</div>
          </div>
        </div>

        <div class="cr-card-actions" v-if="cr.status === 'pending' && isApprover">
          <el-button type="success" size="small" @click="approveRequest(cr)">
            <el-icon><Select /></el-icon> 通过
          </el-button>
          <el-button type="danger" size="small" @click="rejectRequest(cr)">
            <el-icon><CloseBold /></el-icon> 拒绝
          </el-button>
        </div>
      </div>
    </div>

    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
      @current-change="fetchRequests"
    />

    <!-- Submit Change Request Dialog -->
    <el-dialog v-model="showSubmitDialog" title="新建变更请求" width="600px">
      <el-form :model="submitForm" label-width="140px">
        <el-form-item label="操作" required>
          <el-select v-model="submitForm.action" @change="onActionChange" style="width: 100%;">
            <el-option label="添加记录" value="record_create" />
            <el-option label="修改记录" value="record_modify" />
            <el-option label="删除记录" value="record_delete" />
            <el-option label="创建 Zone" value="zone_create" />
            <el-option label="删除 Zone" value="zone_delete" />
            <el-option label="编辑 Zone 源文件" value="raw_zone_edit" />
          </el-select>
        </el-form-item>
        <el-form-item label="Zone 名称" required>
          <el-input v-model="submitForm.zone_name" placeholder="例如 example.com" />
        </el-form-item>
        <el-form-item label="变更摘要" required>
          <el-input v-model="submitForm.summary" placeholder="简要描述变更内容" />
        </el-form-item>

        <!-- Record-specific fields -->
        <template v-if="isRecordAction">
          <el-form-item label="记录名称">
            <el-input v-model="submitForm.payload.name" placeholder="例如 www 或 @" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="submitForm.payload.type" style="width: 100%;">
              <el-option label="A" value="A" />
              <el-option label="AAAA" value="AAAA" />
              <el-option label="CNAME" value="CNAME" />
              <el-option label="MX" value="MX" />
              <el-option label="NS" value="NS" />
              <el-option label="SRV" value="SRV" />
              <el-option label="TXT" value="TXT" />
              <el-option label="PTR" value="PTR" />
            </el-select>
          </el-form-item>
          <el-form-item label="TTL">
            <el-input-number v-model="submitForm.payload.ttl" :min="0" :max="86400" />
          </el-form-item>
          <el-form-item label="数据">
            <el-input v-model="submitForm.payload.data" />
          </el-form-item>
        </template>

        <!-- Record ID for modify/delete -->
        <el-form-item v-if="['record_modify', 'record_delete'].includes(submitForm.action)" label="记录 ID">
          <el-input-number v-model="submitForm.payload.record_id" :min="0" />
        </el-form-item>

        <!-- Zone-specific fields -->
        <template v-if="submitForm.action === 'raw_zone_edit'">
          <el-form-item label="内容">
            <el-input v-model="submitForm.payload.content" type="textarea" :rows="6" placeholder="$TTL 300..." />
          </el-form-item>
        </template>

        <el-form-item label="JSON 负载">
          <el-input v-model="payloadJson" type="textarea" :rows="4" placeholder='{"name": "www", "type": "A", ...}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSubmitDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitRequest">提交</el-button>
      </template>
    </el-dialog>

    <!-- Reject Reason Dialog -->
    <el-dialog v-model="showRejectDialog" title="拒绝变更请求" width="450px">
      <el-form>
        <el-form-item label="原因">
          <el-input v-model="rejectComment" type="textarea" :rows="3" placeholder="请说明拒绝原因" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRejectDialog = false">取消</el-button>
        <el-button type="danger" :loading="rejecting" @click="doReject">确认拒绝</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'

const authStore = useAuthStore()

const activeTab = ref('pending')
const isApprover = computed(() => {
  const role = authStore.user?.role
  return role === 'super_admin' || role === 'zone_admin' || role === 'approver'
})
const canSubmit = computed(() => {
  const role = authStore.user?.role
  return role === 'super_admin' || role === 'zone_admin' || role === 'zone_operator'
})

const requests = ref<any[]>([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const pendingCount = ref(0)
const statusFilter = ref('')
const actionFilter = ref('')
const zoneFilter = ref('')

const isRecordAction = computed(() =>
  ['record_create', 'record_modify', 'record_delete'].includes(submitForm.value.action)
)

// Submit dialog
const showSubmitDialog = ref(false)
const submitting = ref(false)
const submitForm = ref({
  action: 'record_create',
  zone_name: '',
  summary: '',
  payload: {} as Record<string, any>,
})
const payloadJson = ref('')

// Reject dialog
const showRejectDialog = ref(false)
const rejectTarget = ref<any>(null)
const rejectComment = ref('')
const rejecting = ref(false)

async function fetchRequests() {
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize.value }

    if (activeTab.value === 'pending') {
      params.status = 'pending'
    } else if (activeTab.value === 'mine') {
      params.my_requests = true
    }

    if (statusFilter.value) params.status = statusFilter.value
    if (actionFilter.value) params.action = actionFilter.value
    if (zoneFilter.value) params.zone_name = zoneFilter.value

    const { data } = await api.get('/change-requests', { params })
    requests.value = data.items
    total.value = data.total

    if (isApprover.value) {
      const { data: pendingData } = await api.get('/change-requests', {
        params: { status: 'pending', page: 1, page_size: 1 },
      })
      pendingCount.value = pendingData.total
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载变更请求失败')
  } finally {
    loading.value = false
  }
}

async function submitRequest() {
  submitting.value = true
  try {
    let payload = submitForm.value.payload
    if (payloadJson.value) {
      try {
        payload = JSON.parse(payloadJson.value)
      } catch {
        ElMessage.error('JSON 格式无效')
        submitting.value = false
        return
      }
    }

    await api.post('/change-requests', {
      action: submitForm.value.action,
      zone_name: submitForm.value.zone_name,
      summary: submitForm.value.summary,
      payload,
    })
    ElMessage.success('变更请求已提交')
    showSubmitDialog.value = false
    resetSubmitForm()
    fetchRequests()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '提交请求失败')
  } finally {
    submitting.value = false
  }
}

function resetSubmitForm() {
  submitForm.value = { action: 'record_create', zone_name: '', summary: '', payload: {} }
  payloadJson.value = ''
}

function onActionChange() {
  submitForm.value.payload = {}
  payloadJson.value = ''
}

async function approveRequest(cr: any) {
  try {
    await ElMessageBox.confirm(
      `确认通过并执行变更："${cr.summary || cr.action}"，Zone "${cr.zone_name}"？`,
      '通过变更请求',
      { confirmButtonText: '通过并执行', cancelButtonText: '取消', type: 'info' }
    )
    const { data } = await api.put(`/change-requests/${cr.id}/review`, {
      action: 'approve',
      comment: '已通过并执行',
    })
    if (data.status === 'executed') {
      ElMessage.success('变更请求已通过并执行成功')
    } else {
      ElMessage.warning(`已通过但执行失败：${data.review_comment || '未知错误'}`)
    }
    fetchRequests()
  } catch {
    // cancelled
  }
}

function rejectRequest(cr: any) {
  rejectTarget.value = cr
  rejectComment.value = ''
  showRejectDialog.value = true
}

async function doReject() {
  rejecting.value = true
  try {
    await api.put(`/change-requests/${rejectTarget.value.id}/review`, {
      action: 'reject',
      comment: rejectComment.value || '已拒绝',
    })
    ElMessage.info('变更请求已拒绝')
    showRejectDialog.value = false
    fetchRequests()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '拒绝请求失败')
  } finally {
    rejecting.value = false
  }
}

function formatAction(action: string): string {
  const map: Record<string, string> = {
    record_create: '添加记录',
    record_modify: '修改记录',
    record_delete: '删除记录',
    zone_create: '创建 Zone',
    zone_delete: '删除 Zone',
    raw_zone_edit: '编辑 Zone 源文件',
  }
  return map[action] || action
}

function formatStatus(status: string): string {
  const map: Record<string, string> = {
    pending: '待审批',
    approved: '已通过',
    rejected: '已拒绝',
    executed: '已执行',
    execution_failed: '执行失败',
  }
  return map[status] || status
}

function formatTime(ts: string): string {
  if (!ts) return '-'
  const d = new Date(ts)
  return d.toLocaleString('zh-CN', { hour12: false })
}

watch(activeTab, () => {
  page.value = 1
  statusFilter.value = ''
  fetchRequests()
})

onMounted(fetchRequests)
</script>

<style scoped>
.cr-page :deep(.el-tabs__header) {
  margin-bottom: 12px;
}

.tab-badge {
  margin-left: 6px;
  vertical-align: middle;
}

.cr-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.cr-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
  transition: box-shadow 0.2s;
}

.cr-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.cr-card.cr-pending { border-left: 4px solid var(--color-warning); }
.cr-card.cr-approved { border-left: 4px solid var(--color-info); }
.cr-card.cr-rejected { border-left: 4px solid var(--color-danger); opacity: 0.75; }
.cr-card.cr-executed { border-left: 4px solid var(--color-success); }
.cr-card.cr-execution_failed { border-left: 4px solid var(--color-danger); }

.cr-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #F8F9FB;
  border-bottom: 1px solid var(--border-color);
}

.cr-card-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cr-card-right {
  display: flex;
  align-items: center;
}

.cr-action-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 3px;
  font-size: 12px;
  font-weight: 600;
  background: #E3F2FD;
  color: #1565C0;
}

.cr-action-badge.record_create { background: #E8F5E9; color: #2E7D32; }
.cr-action-badge.record_modify { background: #FFF3E0; color: #E65100; }
.cr-action-badge.record_delete { background: #FFEBEE; color: #C62828; }
.cr-action-badge.zone_create { background: #E3F2FD; color: #1565C0; }
.cr-action-badge.zone_delete { background: #FFEBEE; color: #C62828; }
.cr-action-badge.raw_zone_edit { background: #F3E5F5; color: #7B1FA2; }

.cr-zone {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.cr-time {
  font-size: 12px;
  color: var(--text-muted);
}

.cr-status {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.cr-status.pending { background: #FFF3E0; color: #E65100; }
.cr-status.approved { background: #E1F5FE; color: #0277BD; }
.cr-status.rejected { background: #FFEBEE; color: #C62828; }
.cr-status.executed { background: #E8F5E9; color: #2E7D32; }
.cr-status.execution_failed { background: #FFEBEE; color: #C62828; }

.cr-card-body { padding: 12px 16px; }

.cr-meta {
  display: flex;
  gap: 20px;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.cr-meta .el-icon {
  font-size: 14px;
  vertical-align: -2px;
}

.cr-summary {
  font-size: 14px;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.cr-payload { margin-top: 8px; }

.payload-label, .comment-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
  font-weight: 500;
}

.payload-json {
  background: #F5F6FA;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 10px;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  max-height: 200px;
  white-space: pre-wrap;
}

.cr-comment { margin-top: 8px; }

.comment-text {
  background: #FFF8E1;
  border: 1px solid #FFE082;
  border-radius: 4px;
  padding: 8px 12px;
  font-size: 13px;
  color: #F57F17;
  white-space: pre-wrap;
}

.cr-card-actions {
  padding: 10px 16px;
  border-top: 1px solid var(--border-color);
  background: #FAFBFC;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
