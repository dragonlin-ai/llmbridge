<template>
  <div class="app-anim-fade">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">{{ t('samples.page.title') }}</h2>
        <p class="app-page-desc">{{ t('samples.page.desc') }}</p>
      </div>
    </div>

    <div class="app-card">
      <div class="app-toolbar">
        <el-button type="primary" @click="dlg = true">{{ t('samples.btn.create') }}</el-button>
        <el-select v-model="taskType" :placeholder="t('samples.filter.allType')" clearable style="width:200px" @change="load">
          <el-option v-for="tt in TASK_TYPES" :key="tt" :label="taskLabel(tt)" :value="tt" />
        </el-select>
        <el-button @click="load">{{ t('samples.btn.refresh') }}</el-button>
      </div>
      <el-table :data="items" v-loading="loading">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="input_text" :label="t('samples.inputText')" min-width="300" show-overflow-tooltip />
        <el-table-column prop="task_type" :label="t('samples.taskType')" width="160">
          <template #default="{ row }">
            <span class="app-badge is-primary">{{ taskLabel(row.task_type) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="source" :label="t('samples.source')" width="90" />
        <el-table-column prop="created_at" :label="t('samples.createdAt')" width="170" />
      </el-table>
      <div class="app-card-footer pagination-row">
        <el-pagination layout="total, prev, pager, next" :total="total"
                       :page-size="pageSize" v-model:current-page="page" @current-change="load" />
      </div>
    </div>

    <el-dialog v-model="dlg" :title="t('samples.dialog.create')" width="520px" append-to-body>
      <el-form label-width="90px">
        <el-form-item :label="t('samples.inputText')" required>
          <el-input v-model="form.text" type="textarea" :rows="3" maxlength="2000" />
        </el-form-item>
        <el-form-item :label="t('samples.taskType')" required>
          <el-select v-model="form.taskType" style="width:220px">
            <el-option v-for="tt in TASK_TYPES" :key="tt" :label="taskLabel(tt)" :value="tt" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">{{ t('samples.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="save">{{ t('samples.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { t, taskLabel } from '../../i18n'
import { createSample, listSamples } from '../../api'
import { TASK_TYPES } from '../../types'

const items = ref<{ id: number; input_text: string; task_type: string; source: string; created_at: string }[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const taskType = ref('')
const dlg = ref(false)
const saving = ref(false)
const form = ref({ text: '', taskType: 'general' })

async function load() {
  loading.value = true
  try {
    const data = await listSamples({ page: page.value, page_size: pageSize, task_type: taskType.value || undefined })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!form.value.text.trim()) {
    ElMessage.warning(t('samples.warn.inputRequired'))
    return
  }
  saving.value = true
  try {
    await createSample({ input_text: form.value.text.trim(), task_type: form.value.taskType })
    ElMessage.success(t('samples.saved'))
    dlg.value = false
    form.value = { text: '', taskType: 'general' }
    await load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.pagination-row {
  display: flex;
  justify-content: flex-end;
}
</style>
