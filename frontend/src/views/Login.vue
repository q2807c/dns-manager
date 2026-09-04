<template>
  <div class="login-page">
    <!-- Background decoration -->
    <div class="login-bg">
      <div class="bg-circle c1"></div>
      <div class="bg-circle c2"></div>
      <div class="bg-circle c3"></div>
      <div class="bg-grid"></div>
    </div>

    <div class="login-card">
      <div class="login-header">
        <div class="login-logo">DNS</div>
        <h1>Zone Manager</h1>
        <p>中国海油 DNS Zone 管理平台</p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" @submit.prevent="handleLogin">
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            placeholder="用户名"
            :prefix-icon="User"
            size="large"
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            :prefix-icon="Lock"
            size="large"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="large" :loading="loading" class="login-btn" @click="handleLogin">
            <el-icon v-if="!loading"><Right /></el-icon>
            {{ loading ? '登录中...' : '登录' }}
          </el-button>
        </el-form-item>
      </el-form>

      <transition name="fade">
        <div v-if="error" class="login-error">
          <el-icon><WarningFilled /></el-icon>
          {{ error }}
        </div>
      </transition>

      <div class="login-footer">
        <span>F5 BIG-IP DNS</span>
        <span class="separator">·</span>
        <span>v0.2.0</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { User, Lock, Right, WarningFilled } from '@element-plus/icons-vue'

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref()
const loading = ref(false)
const error = ref('')

const form = reactive({
  username: '',
  password: '',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  error.value = ''

  try {
    await authStore.login(form.username, form.password)
    router.push('/zones')
  } catch (e: any) {
    error.value = e.response?.data?.detail || '认证失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #0D1B2A 0%, #1B3A5C 30%, #1565C0 60%, #0D47A1 100%);
  overflow: hidden;
}

/* Animated background */
.login-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.bg-circle {
  position: absolute;
  border-radius: 50%;
  opacity: 0.06;
}

.bg-circle.c1 {
  width: 600px;
  height: 600px;
  background: #42A5F5;
  top: -150px;
  right: -100px;
  animation: float 20s ease-in-out infinite;
}

.bg-circle.c2 {
  width: 400px;
  height: 400px;
  background: #1565C0;
  bottom: -100px;
  left: -80px;
  animation: float 25s ease-in-out infinite reverse;
}

.bg-circle.c3 {
  width: 300px;
  height: 300px;
  background: #64B5F6;
  top: 50%;
  left: 50%;
  animation: float 18s ease-in-out infinite 5s;
}

.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.03) 1px, transparent 1px);
  background-size: 40px 40px;
}

@keyframes float {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -20px) scale(1.05); }
  66% { transform: translate(-20px, 15px) scale(0.95); }
}

/* Card */
.login-card {
  position: relative;
  width: 420px;
  padding: 48px 40px 32px;
  background: rgba(255, 255, 255, 0.97);
  border-radius: 12px;
  box-shadow:
    0 20px 60px rgba(0, 0, 0, 0.3),
    0 0 0 1px rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(20px);
  animation: cardIn 0.6s ease-out;
}

@keyframes cardIn {
  from {
    opacity: 0;
    transform: translateY(24px) scale(0.97);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.login-header {
  text-align: center;
  margin-bottom: 36px;
}

.login-logo {
  width: 60px;
  height: 60px;
  background: linear-gradient(135deg, #1565C0, #42A5F5);
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 800;
  font-size: 20px;
  margin-bottom: 16px;
  box-shadow: 0 4px 16px rgba(21, 101, 192, 0.3);
}

.login-header h1 {
  font-size: 26px;
  color: #1A2332;
  margin: 0 0 6px;
  font-weight: 700;
  letter-spacing: -0.5px;
}

.login-header p {
  font-size: 14px;
  color: #90A4AE;
  margin: 0;
}

.login-btn {
  width: 100%;
  height: 44px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.login-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--color-danger);
  font-size: 13px;
  background: #FFEBEE;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 8px;
}

.login-footer {
  text-align: center;
  margin-top: 24px;
  font-size: 12px;
  color: var(--text-muted);
}

.login-footer .separator {
  margin: 0 6px;
}
</style>
