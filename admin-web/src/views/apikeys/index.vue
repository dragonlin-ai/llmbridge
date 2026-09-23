<template>
  <div class="app-anim-fade">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">{{ t('apikeys.page.title') }}</h2>
        <p class="app-page-desc">{{ t('apikeys.page.desc') }}</p>
      </div>
      <el-button type="primary" @click="openCreate">{{ t('apikeys.page.createBtn') }}</el-button>
    </div>

    <!-- ==================== 调用说明（页面主体，居中展示） ==================== -->
    <div class="app-card guide-card">
      <div class="guide-head">
        <h3 class="guide-title">{{ t('apikeys.guide.title') }}</h3>
        <p class="guide-sub">{{ t('apikeys.guide.sub') }}</p>
      </div>

      <div class="guide-body">
        <!-- 三步接入 -->
        <div class="steps">
          <div class="step">
            <span class="step-no">1</span>
            <div class="step-text">
              <b>{{ t('apikeys.guide.step1.title') }}</b>
              <span>{{ t('apikeys.guide.step1.descPre') }}<code class="app-code">sk-lb-…</code>{{ t('apikeys.guide.step1.descPost') }}</span>
            </div>
          </div>
          <div class="step">
            <span class="step-no">2</span>
            <div class="step-text">
              <b>{{ t('apikeys.guide.step2.title') }}</b>
              <span>{{ t('apikeys.guide.step2.desc') }}</span>
            </div>
          </div>
          <div class="step">
            <span class="step-no">3</span>
            <div class="step-text">
              <b>{{ t('apikeys.guide.step3.title') }}</b>
              <span><code class="app-code">model</code> {{ t('apikeys.guide.step3.desc1') }} <code class="app-code">auto</code> {{ t('apikeys.guide.step3.desc2') }}</span>
            </div>
          </div>
        </div>

        <!-- 端点 -->
        <div class="guide-section">
          <div class="guide-label">{{ t('apikeys.guide.section.endpoint') }}</div>
          <div class="endpoint-row">
            <code class="endpoint">POST {{ base }}/v1/chat/completions</code>
            <el-button link type="primary" @click="copy(`${base}/v1/chat/completions`)">{{ t('apikeys.copy') }}</el-button>
          </div>
        </div>

        <!-- curl 示例 -->
        <div class="guide-section">
          <div class="guide-label">{{ t('apikeys.guide.section.curl') }}</div>
          <pre class="code-block"><code>{{ curlExample }}</code></pre>
          <el-button link type="primary" @click="copy(curlExample)">{{ t('apikeys.copyExample') }}</el-button>
        </div>

        <!-- Python 示例 -->
        <div class="guide-section">
          <div class="guide-label">{{ t('apikeys.guide.section.python') }}</div>
          <pre class="code-block"><code>{{ pythonExample }}</code></pre>
          <el-button link type="primary" @click="copy(pythonExample)">{{ t('apikeys.copyExample') }}</el-button>
        </div>

        <!-- 参数说明 -->
        <div class="guide-section">
          <div class="guide-label">{{ t('apikeys.guide.section.requestParams') }}</div>
          <table class="guide-table">
            <thead>
              <tr><th>{{ t('apikeys.table.field') }}</th><th>{{ t('apikeys.table.required') }}</th><th>{{ t('apikeys.table.desc') }}</th></tr>
            </thead>
            <tbody>
              <tr><td><code>model</code></td><td>{{ t('apikeys.table.yes') }}</td><td><code>auto</code> {{ t('apikeys.table.model.desc') }} <code>qwen3.8-flash</code></td></tr>
              <tr><td><code>messages</code></td><td>{{ t('apikeys.table.yes') }}</td><td>{{ t('apikeys.table.messages.desc') }} <code>[{role, content}]</code></td></tr>
              <tr><td><code>stream</code></td><td>{{ t('apikeys.table.no') }}</td><td><code>true</code> {{ t('apikeys.table.stream.desc') }} <code>false</code></td></tr>
              <tr><td><code>temperature</code> / <code>max_tokens</code></td><td>{{ t('apikeys.table.no') }}</td><td>{{ t('apikeys.table.temp.desc') }}</td></tr>
            </tbody>
          </table>
        </div>

        <!-- 响应头 -->
        <div class="guide-section">
          <div class="guide-label">{{ t('apikeys.guide.section.responseHeaders') }}</div>
          <table class="guide-table">
            <thead>
              <tr><th>{{ t('apikeys.table.responseHeader') }}</th><th>{{ t('apikeys.table.desc') }}</th></tr>
            </thead>
            <tbody>
              <tr><td><code>x-router-trace-id</code></td><td>{{ t('apikeys.table.traceId.desc') }}</td></tr>
              <tr><td><code>x-router-layer</code></td><td>{{ t('apikeys.table.layer.desc') }}</td></tr>
              <tr><td><code>x-router-model</code></td><td>{{ t('apikeys.table.modelHeader.desc') }}</td></tr>
              <tr><td><code>x-router-confidence</code></td><td>{{ t('apikeys.table.confidence.desc') }}</td></tr>
              <tr><td><code>x-router-task-type</code></td><td>{{ t('apikeys.table.taskType.desc') }}</td></tr>
            </tbody>
          </table>
        </div>

        <div class="guide-note">
          {{ t('apikeys.note.auth') }}<code>Authorization: Bearer &lt;你的 Key&gt;</code>{{ t('apikeys.note.invalid') }}
          <code>401 invalid API key</code>{{ t('apikeys.note.rateLimit') }} <code>429</code>{{ t('apikeys.note.upstream') }}
          <code>502</code>{{ t('apikeys.note.tracePre') }}<code>x-router-*</code>{{ t('apikeys.note.tracePost') }}
        </div>
      </div>
    </div>

    <!-- ==================== 密钥列表 ==================== -->
    <div class="app-card">
      <div class="app-toolbar">
        <span class="app-badge is-gray">{{ t('apikeys.list.badge', { n: items.length }) }}</span>
        <el-button @click="load">{{ t('apikeys.list.refresh') }}</el-button>
      </div>
      <el-table :data="items" v-loading="loading">
        <el-table-column prop="name" :label="t('apikeys.table.col.name')" min-width="140" />
        <el-table-column :label="t('apikeys.table.col.key')" min-width="220">
          <template #default="{ row }">
            <code class="app-code">{{ maskedOf(row) }}</code>
          </template>
        </el-table-column>
        <el-table-column :label="t('apikeys.table.col.status')" width="100">
          <template #default="{ row }">
            <span class="app-badge" :class="row.enabled ? 'is-success' : 'is-gray'">
              {{ row.enabled ? t('apikeys.status.enabled') : t('apikeys.status.disabled') }}
            </span>
          </template>
        </el-table-column>
        <el-table-column :label="t('apikeys.table.col.lastUsed')" width="180">
          <template #default="{ row }">
            <span class="cell-muted">{{ row.last_used_at || t('apikeys.list.neverUsed') }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" :label="t('apikeys.table.col.createdAt')" width="180" />
        <el-table-column :label="t('apikeys.table.col.actions')" width="240" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="reveal(row)">{{ t('apikeys.action.viewKey') }}</el-button>
            <el-button link type="primary" @click="toggle(row)">
              {{ row.enabled ? t('apikeys.status.disabled') : t('apikeys.status.enabled') }}
            </el-button>
            <el-button link type="danger" @click="remove(row)">{{ t('apikeys.action.delete') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="!loading && !items.length" class="empty-tip">
        {{ t('apikeys.list.empty') }}
      </div>
    </div>

    <!-- 生成对话框 -->
    <el-dialog v-model="dlg" :title="t('apikeys.dialog.create.title')" width="440px" append-to-body>
      <el-form label-width="80px">
        <el-form-item :label="t('apikeys.dialog.create.label')" required>
          <el-input v-model="newName" :placeholder="t('apikeys.dialog.create.placeholder')" maxlength="64" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">{{ t('apikeys.dialog.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="create">{{ t('apikeys.dialog.create.submit') }}</el-button>
      </template>
    </el-dialog>

    <!-- 查看明文 Key -->
    <el-dialog v-model="revealDlg" :title="t('apikeys.dialog.view.title')" width="560px" append-to-body>
      <div class="reveal-box">
        <code class="reveal-key">{{ revealedKey }}</code>
        <el-button type="primary" @click="copy(revealedKey)">{{ t('apikeys.dialog.view.copy') }}</el-button>
      </div>
      <div class="reveal-tip">{{ t('apikeys.dialog.view.tipPre') }} <code>Authorization: Bearer &lt;Key&gt;</code> {{ t('apikeys.dialog.view.tipPost') }}</div>
      <template #footer>
        <el-button @click="revealDlg = false">{{ t('apikeys.dialog.view.close') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createApiKey, deleteApiKey, listApiKeys, revealApiKey, updateApiKey } from '../../api'
import type { ApiKeyItem } from '../../types'
import { t } from '../../i18n'

const items = ref<ApiKeyItem[]>([])
const loading = ref(false)
const dlg = ref(false)
const saving = ref(false)
const newName = ref('')
const revealDlg = ref(false)
const revealedKey = ref('')

/** 网关地址（第三方实际调用的是后端端口，不是控制台前端端口） */
const base = ref('http://127.0.0.1:8000')

/** 示例里的占位 Key（真实 Key 由「查看 Key」获取；列表接口不回明文） */
const EXAMPLE_KEY = 'sk-lb-你的Key'

const curlExample = computed(() => `curl ${base.value}/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${EXAMPLE_KEY}" \\
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "用一句话介绍自己"}],
    "stream": false
  }'`)

const pythonExample = computed(() => `from openai import OpenAI

client = OpenAI(
    base_url="${base.value}/v1",
    api_key="${EXAMPLE_KEY}",
)
resp = client.chat.completions.create(
    model="auto",  # 智能路由；或填具体模型标识
    messages=[{"role": "user", "content": "用一句话介绍自己"}],
)
print(resp.choices[0].message.content)`)

function maskedOf(row: ApiKeyItem) {
  return `${row.key_prefix}…`
}

async function load() {
  loading.value = true
  try {
    const data = await listApiKeys()
    items.value = data.items
  } finally {
    loading.value = false
  }
}

function openCreate() {
  newName.value = ''
  dlg.value = true
}

async function create() {
  if (!newName.value.trim()) {
    ElMessage.warning(t('apikeys.msg.nameRequired'))
    return
  }
  saving.value = true
  try {
    const row = await createApiKey(newName.value.trim())
    dlg.value = false
    revealedKey.value = row.key ?? ''
    revealDlg.value = true
    await load()
  } finally {
    saving.value = false
  }
}

async function reveal(row: ApiKeyItem) {
  try {
    const data = await revealApiKey(row.id)
    revealedKey.value = data.key || t('apikeys.msg.cipherUndecryptable')
    revealDlg.value = true
  } catch {
    /* 拦截器已提示 */
  }
}

async function toggle(row: ApiKeyItem) {
  await updateApiKey(row.id, { enabled: !row.enabled })
  ElMessage.success(row.enabled ? t('apikeys.msg.disabled') : t('apikeys.msg.enabled'))
  await load()
}

async function remove(row: ApiKeyItem) {
  try {
    await ElMessageBox.confirm(
      t('apikeys.msg.deleteConfirm', { name: row.name }),
      t('apikeys.msg.deleteTitle'), { type: 'warning', confirmButtonText: t('apikeys.action.delete'), confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  await deleteApiKey(row.id)
  ElMessage.success(t('apikeys.msg.deleted'))
  await load()
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(t('apikeys.msg.copied'))
  } catch {
    ElMessage.warning(t('apikeys.msg.copyFailed'))
  }
}

onMounted(() => {
  // 后端与前端同机部署时网关即本机 8000；将来独立部署改这里或读配置
  if (location.hostname) base.value = `http://${location.hostname}:8000`
  load()
})
</script>

<style scoped>
/* ---- 调用说明：与页面其它卡片同宽，左右边缘对齐（不居中收窄） ---- */
/* 该卡片内容是裸放的（无 app-card-body 包裹），必须自带内边距，
   否则文字/代码块贴死卡片边框（撑满后尤其明显）。 */
.guide-card {
  margin: 0 0 16px;
  padding: 20px 24px;
}
.guide-head {
  margin-bottom: 16px;
}
.guide-title {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-1);
}
.guide-sub {
  margin: 0;
  font-size: 13px;
  color: var(--text-3);
}

.steps {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}
.step {
  flex: 1;
  display: flex;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border-base);
  border-radius: 12px;
  background: var(--bg-subtle, rgba(0, 0, 0, 0.02));
}
.step-no {
  flex: none;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  background: var(--p-500);
}
.step-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12.5px;
  color: var(--text-2);
  line-height: 1.5;
}
.step-text b {
  color: var(--text-1);
}

.guide-section {
  margin-bottom: 18px;
}
.guide-label {
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-3);
}
.endpoint-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.endpoint {
  flex: 1;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--bg-subtle, rgba(0, 0, 0, 0.04));
  font-size: 13.5px;
  font-weight: 600;
  color: var(--p-600);
  overflow-x: auto;
  white-space: nowrap;
}
.code-block {
  margin: 0;
  padding: 14px 16px;
  border-radius: 10px;
  background: var(--bg-code, #0f172a);
  color: var(--code-fg, #e2e8f0);
  font-size: 12.5px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre;
}
.code-block code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: none;
  padding: 0;
  color: inherit;
}

.guide-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.guide-table th,
.guide-table td {
  padding: 8px 12px;
  border: 1px solid var(--border-base);
  text-align: left;
  color: var(--text-2);
  line-height: 1.55;
}
.guide-table th {
  background: var(--bg-subtle, rgba(0, 0, 0, 0.03));
  color: var(--text-1);
  font-weight: 600;
}
.guide-table code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--bg-subtle, rgba(0, 0, 0, 0.06));
  font-size: 12px;
  color: var(--p-600);
}

.guide-note {
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--c-info-bg, rgba(59, 130, 246, 0.08));
  border: 1px solid var(--c-info-border, rgba(59, 130, 246, 0.25));
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
}
.guide-note code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--bg-subtle, rgba(0, 0, 0, 0.06));
  font-size: 12px;
}

.cell-muted {
  color: var(--text-3);
  font-size: 12.5px;
}
.empty-tip {
  padding: 28px 0;
  text-align: center;
  color: var(--text-3);
  font-size: 13px;
}

.reveal-box {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px;
  border-radius: 10px;
  background: var(--bg-subtle, rgba(0, 0, 0, 0.04));
}
.reveal-key {
  flex: 1;
  font-size: 13.5px;
  word-break: break-all;
  color: var(--p-600);
  font-weight: 600;
}
.reveal-tip {
  margin-top: 10px;
  font-size: 12.5px;
  color: var(--text-3);
  line-height: 1.6;
}

@media (max-width: 768px) {
  .steps {
    flex-direction: column;
  }
}
</style>
