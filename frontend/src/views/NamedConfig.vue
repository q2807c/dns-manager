<template>
  <div class="named-config-page">
    <div class="page-header">
      <h2 class="page-title">
        <el-icon :size="20"><Document /></el-icon>
        named 配置
      </h2>
      <el-tag v-if="content.startsWith('#')" type="info">预览</el-tag>
    </div>

    <el-skeleton v-if="loading" :rows="10" animated />
    <div v-else class="code-block">{{ content }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const content = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    const { data } = await api.get('/health')
    content.value = `# F5 BIG-IP 活跃节点: ${data.f5_active_host}\n# 版本: ${data.version}\n# \n# named.conf 位于 /var/named/config/named.conf\n# 通过 SSH 查看器访问（后续版本支持）`
  } catch {
    ElMessage.error('无法连接到 F5')
    content.value = '# 连接失败'
  } finally {
    loading.value = false
  }
})
</script>
