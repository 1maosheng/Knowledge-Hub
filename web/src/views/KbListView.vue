<template>
  <div class="page">
    <div class="page-title">
      <div>
        <h2>知识库</h2>
        <div class="muted">上传企业文档，构建可追溯的问答语料</div>
      </div>
      <el-button type="primary" :icon="Plus" @click="dialog = true">新建知识库</el-button>
    </div>

    <el-skeleton v-if="store.loading && !store.kbs.length" :rows="3" animated />

    <el-empty v-else-if="!store.kbs.length" description="还没有知识库，先创建一个">
      <el-button type="primary" @click="dialog = true">新建知识库</el-button>
    </el-empty>

    <div v-else class="kb-grid">
      <el-card v-for="kb in store.kbs" :key="kb.id" class="kb-card" shadow="hover" @click="open(kb)">
        <div style="display: flex; justify-content: space-between; align-items: start">
          <h3>{{ kb.name }}</h3>
          <el-dropdown trigger="click" @command="(cmd) => onCommand(cmd, kb)" @click.stop>
            <el-icon style="color: #9ca3af" @click.stop><MoreFilled /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="delete">删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <div class="desc">{{ kb.description || '暂无描述' }}</div>
        <div style="margin-top: 14px; display: flex; gap: 6px; align-items: center">
          <el-tag size="small" effect="plain">{{ kb.doc_count ?? 0 }} 篇文档</el-tag>
          <el-tag size="small" effect="plain" type="info">{{ shortId(kb.id) }}</el-tag>
        </div>
      </el-card>
    </div>

    <el-dialog v-model="dialog" title="新建知识库" width="440px">
      <el-form :model="form" label-width="72px" @submit.prevent>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="60" placeholder="例如：人事制度库" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" maxlength="300" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!form.name.trim()" @click="submit">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, MoreFilled } from '@element-plus/icons-vue'
import { api } from '../api'
import { createKb, loadKbs, setActiveKb, store } from '../store'

const router = useRouter()
const dialog = ref(false)
const saving = ref(false)
const form = reactive({ name: '', description: '' })

function shortId(id) {
  return (id || '').slice(0, 8)
}

function open(kb) {
  setActiveKb(kb.id)
  router.push(`/kbs/${kb.id}`)
}

async function submit() {
  saving.value = true
  try {
    const kb = await createKb({ name: form.name.trim(), description: form.description.trim() })
    ElMessage.success('知识库已创建')
    dialog.value = false
    form.name = ''
    form.description = ''
    open(kb)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function onCommand(cmd, kb) {
  if (cmd !== 'delete') return
  try {
    await ElMessageBox.confirm(`删除「${kb.name}」及其全部文档与索引？`, '删除知识库', { type: 'warning' })
  } catch {
    return
  }
  try {
    await api.deleteKb(kb.id)
    ElMessage.success('已删除')
    await loadKbs()
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>