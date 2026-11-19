<template>
  <div class="page">
    <div class="page-title">
      <div>
        <el-breadcrumb separator="/">
          <el-breadcrumb-item :to="{ path: '/kbs' }">知识库</el-breadcrumb-item>
          <el-breadcrumb-item>{{ kb?.name || '…' }}</el-breadcrumb-item>
        </el-breadcrumb>
        <h2 style="margin-top: 8px">{{ kb?.name }}</h2>
        <div class="muted">{{ kb?.description || '上传 PDF / Word / Markdown / Excel 文档，系统自动解析、分块并建立索引' }}</div>
      </div>
      <el-button type="primary" :icon="ChatDotRound" @click="goChat">去问答</el-button>
    </div>

    <el-card shadow="never" style="margin-bottom: 16px">
      <el-upload drag multiple :show-file-list="false" :http-request="upload" accept=".pdf,.docx,.md,.markdown,.txt,.xlsx">
        <el-icon size="38" color="#9ca3af"><UploadFilled /></el-icon>
        <div style="margin-top: 8px">拖拽文件到此处，或 <em>点击上传</em></div>
        <template #tip>
          <div class="muted" style="margin-top: 6px">支持 PDF、DOCX、MD、TXT、XLSX，单文件上限 100MB；解析在后台执行</div>
        </template>
      </el-upload>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between">
          <span>文档（{{ docs.length }}）</span>
          <el-button size="small" text :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        </div>
      </template>

      <el-table :data="docs" v-loading="loading" empty-text="尚未上传文档">
        <el-table-column prop="filename" label="文件名" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="220">
          <template #default="{ row }">
            <div style="display: flex; align-items: center; gap: 8px">
              <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row) }}</el-tag>
              <el-progress v-if="row.status !== 'ready' && row.status !== 'failed'" :percentage="row.progress || 0"
                :stroke-width="6" style="width: 80px" />
            </div>
            <el-tooltip v-if="row.status === 'failed'" :content="row.error || '解析失败'">
              <div class="muted" style="margin-top: 4px; max-width: 190px; overflow: hidden; text-overflow: ellipsis">
                {{ row.error }}
              </div>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="分块" width="80">
          <template #default="{ row }">{{ row.chunk_count ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="页数" width="80">
          <template #default="{ row }">{{ row.page_count ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ fmtSize(row.size) }}</template>
        </el-table-column>
        <el-table-column label="上传时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text :disabled="row.status === 'processing'" @click="reingest(row)">重解析</el-button>
            <el-button size="small" text type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header>检索测试（不调用大模型）</template>
      <div style="display: flex; gap: 8px">
        <el-input v-model="query" placeholder="输入问题，查看召回片段与相关度" @keyup.enter="runSearch" />
        <el-button type="primary" :loading="searching" :disabled="!query.trim()" @click="runSearch">检索</el-button>
      </div>
      <div v-if="searchResult" style="margin-top: 14px">
        <div class="muted" style="margin-bottom: 8px">
          命中 {{ searchResult.hits.length }} 条 · 向量 {{ searchResult.stats?.vector_hits ?? 0 }} / 关键词
          {{ searchResult.stats?.keyword_hits ?? 0 }} · 耗时 {{ searchResult.stats?.latency_ms ?? '—' }}ms
          <el-tag v-if="searchResult.degraded?.length" size="small" type="warning" style="margin-left: 6px">
            降级：{{ searchResult.degraded.join(', ') }}
          </el-tag>
        </div>
        <div v-for="(hit, i) in searchResult.hits" :key="hit.chunk_id" class="hit">
          <div style="display: flex; justify-content: space-between; gap: 12px">
            <strong>[{{ i + 1 }}] {{ hit.doc_name }} · 第 {{ hit.page || '?' }} 页</strong>
            <span class="muted mono">{{ hit.score?.toFixed?.(4) ?? hit.score }}</span>
          </div>
          <div class="muted" v-if="hit.section">{{ hit.section }}</div>
          <div style="white-space: pre-wrap; margin-top: 6px">{{ hit.text }}</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Refresh, UploadFilled } from '@element-plus/icons-vue'
import { api } from '../api'
import { setActiveKb, store } from '../store'

const route = useRoute()
const router = useRouter()
const kbId = computed(() => route.params.id)
const kb = computed(() => store.kbs.find((k) => k.id === kbId.value))
const docs = ref([])
const loading = ref(false)
const query = ref('')
const searching = ref(false)
const searchResult = ref(null)
let timer = null

const STATUS = {
  queued: { label: '排队中', type: 'info' },
  downloading: { label: '下载中', type: 'info' },
  parsing: { label: '解析中', type: 'warning' },
  chunking: { label: '分块中', type: 'warning' },
  embedding: { label: '向量化', type: 'warning' },
  ready: { label: '就绪', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  processing: { label: '处理中', type: 'warning' },
}

function statusType(s) {
  return STATUS[s]?.type || 'info'
}

function statusLabel(row) {
  const base = STATUS[row.status]?.label || row.status
  if (row.status === 'ready' || row.status === 'failed') return base
  return row.stage ? `${base} · ${row.stage}` : base
}

function fmtSize(n) {
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function fmtTime(t) {
  return t ? new Date(t).toLocaleString() : '—'
}

async function load() {
  if (!kbId.value) return
  loading.value = true
  try {
    docs.value = await api.listDocs(kbId.value)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
  schedulePoll()
}

function schedulePoll() {
  if (timer) clearTimeout(timer)
  const busy = docs.value.some((d) => !['ready', 'failed'].includes(d.status))
  if (!busy) return
  timer = setTimeout(async () => {
    try {
      docs.value = await api.listDocs(kbId.value)
    } catch {
      /* transient */
    }
    schedulePoll()
  }, 2000)
}

async function upload({ file }) {
  try {
    await api.uploadDoc(kbId.value, file)
    ElMessage.success(`${file.name} 已提交解析`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function reingest(row) {
  try {
    await api.reingest(row.id)
    ElMessage.success('已重新提交解析')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`删除文档「${row.filename}」及其索引？`, '删除文档', { type: 'warning' })
  } catch {
    return
  }
  try {
    await api.deleteDoc(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function runSearch() {
  if (!query.value.trim()) return
  searching.value = true
  try {
    searchResult.value = await api.search({ kb_ids: [kbId.value], query: query.value.trim() })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    searching.value = false
  }
}

function goChat() {
  setActiveKb(kbId.value)
  router.push('/chat')
}

onMounted(async () => {
  setActiveKb(kbId.value)
  if (!store.kbs.length) {
    const { loadKbs } = await import('../store')
    await loadKbs()
  }
  await load()
})

onBeforeUnmount(() => timer && clearTimeout(timer))
</script>

<style scoped>
.hit {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: #fafafa;
  font-size: 13px;
  line-height: 1.7;
}
</style>