<template>
  <div class="login-page app-mesh-bg">
    <div class="login-orb login-orb-a" />
    <div class="login-orb login-orb-b" />

    <div class="login-card app-anim-up">
      <div class="login-brand">
        <div class="login-logo">
          <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 7h11a4 4 0 0 1 0 8H8" />
            <path d="M11 4l-3 3 3 3" />
            <path d="M13 15l3 3-3 3" />
          </svg>
        </div>
        <h1 class="login-title">{{ t('login.title') }}</h1>
        <p class="login-sub">{{ t('login.sub') }}</p>
      </div>

      <form class="login-form" @submit.prevent="onLogin">
        <div class="login-field">
          <label class="login-label">{{ t('login.username') }}</label>
          <el-input
            v-model="username"
            size="large"
            :placeholder="t('login.usernamePlaceholder')"
            :prefix-icon="User"
            autocomplete="username"
          />
        </div>

        <div class="login-field">
          <label class="login-label">{{ t('login.password') }}</label>
          <el-input
            v-model="password"
            type="password"
            size="large"
            :placeholder="t('login.passwordPlaceholder')"
            :prefix-icon="Lock"
            show-password
            autocomplete="current-password"
            @keyup.enter="onLogin"
          />
        </div>

        <el-button
          class="login-submit"
          type="primary"
          size="large"
          native-type="submit"
          :loading="loading"
        >
          {{ t('login.submit') }}
        </el-button>
      </form>

      <p class="login-hint">{{ t('login.defaultAccount') }} <code class="app-code">admin</code> / <code class="app-code">admin123</code></p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { login } from '../../api'
import { t } from '../../i18n'

const username = ref('')
const password = ref('')
const loading = ref(false)
const router = useRouter()

async function onLogin() {
  if (!username.value || !password.value) {
    ElMessage.warning(t('login.requiredMsg'))
    return
  }
  loading.value = true
  try {
    const data = await login(username.value, password.value)
    localStorage.setItem('token', data.access_token)
    router.push('/')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  overflow: hidden;
  background-color: var(--bg-app);
}

/* 背景光斑 */
.login-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  pointer-events: none;
}
.login-orb-a {
  width: 420px;
  height: 420px;
  top: -120px;
  left: -80px;
  background: rgba(20, 184, 166, 0.28);
}
.login-orb-b {
  width: 460px;
  height: 460px;
  right: -140px;
  bottom: -160px;
  background: rgba(6, 182, 212, 0.2);
}
html.dark .login-orb-a {
  background: rgba(20, 184, 166, 0.18);
}
html.dark .login-orb-b {
  background: rgba(6, 182, 212, 0.14);
}

.login-card {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 400px;
  padding: 40px 36px 32px;
  border-radius: 20px;
  background: var(--bg-glass);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid var(--border-base);
  box-shadow: var(--sh-glass);
}

.login-brand {
  text-align: center;
  margin-bottom: 28px;
}
.login-logo {
  width: 56px;
  height: 56px;
  margin: 0 auto 16px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: linear-gradient(135deg, var(--p-500) 0%, var(--p-600) 100%);
  box-shadow: 0 8px 24px rgba(20, 184, 166, 0.32);
}
.login-title {
  font-size: 21px;
  font-weight: 700;
  color: var(--text-1);
  letter-spacing: -0.01em;
}
.login-sub {
  margin-top: 6px;
  font-size: 13px;
  color: var(--text-3);
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.login-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.login-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-2);
}
.login-submit {
  margin-top: 8px;
  width: 100%;
  height: 44px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.login-hint {
  margin-top: 20px;
  text-align: center;
  font-size: 12px;
  color: var(--text-3);
}
</style>
