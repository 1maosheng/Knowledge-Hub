<template>
  <div class="chat-shell">
    <div class="chat-toolbar">
      <el-select v-model="selectedKbIds" multiple collapse-tags collapse-tags-tooltip placeholder="选择知识库"
        style="min-width: 260px; max-width: 420px" :disabled="busy">
        <el-option v-for="kb in store.kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
      </el-select>
      <el-button :icon="Plus" :disabled="busy" @click="newConversation">新对话</el-button>
      <span class="muted" v-if="selectedKbIds.length === 0" style="color: #e6a23c">请选择至少一个知识库</span>
      <div style="flex: 1" />
      <el-tag v-if="store.health?.llm?.mode === 'mock'" size="small" type="warning" effect="plain">
        Mock 模型（未配置 LLM_BASE_URL）
      </el-tag>
    </div>

    <div ref="scroller" class="chat-messages">
      <div v-if="!messages.length" style="max-width: 720px; margin: 8vh auto 0; text-align: center">
        <h2 style="margin-bottom: 8px">基于知识库的可溯源问答</h2>
        <div class="muted" style="margin-bottom: 22px">
          回答只依据已上传资料，句末 [n] 对应下方引用片段；资料不足时会明确说明。
        </div>
        <div style="display: flex; flex-wrap: wrap; gap: 8px; justify-content: center">
          <el-button v-for="q in samples" :key="q" plain @click="ask(q)">{{ q }}</el-button>
        </div>
      </div>

      <div v-for="(msg, idx) in messages" :key="idx" class="msg-row" :class="msg.role">
        <div class="avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
        <div>
          <div class="bubble">
            <template v-if="msg.role === 'assistant'">
              <template v-for="(seg, si) in segments(msg.content)" :key="si">
                <span v-if="seg.cite" class="cite-inline" @click="openCitation(msg, seg.cite)">[{{ seg.cite }}]</span>
                <span v-else>{{ seg.text }}</span>
              </template>
              <span v-if="msg.streaming" class="cursor">▍</span>
            </template>
            <template v-else>{{ msg.content }}</template>
          </div>

          <div v-if="msg.role === 'assistant' && msg.citations?.length" class="msg-meta">
            <span class="cite-chip" v-for="c in msg.citations" :key="c.index" @click="showCitation(c)">
              [{{ c.index }}] {{ c.doc_name }}<template v-if="c.page"> · 第{{ c.page }}页</template>
            </span>
          </div>

          <div v-if="msg.role === 'assistant' && msg.done" class="msg-meta">
            <el-tag size="small" effect="plain" :type="msg.verify?.ok ? 'success' : 'warning'">
              {{ msg.verify?.ok ? '引用校验通过' : '引用待人工核对' }}
            </el-tag>
            <span v-if="msg.route && Object.keys(msg.route).length">路径：{{ routeLabel(msg.route) }}</span>
            <span v-if="msg.rounds">检索 {{ msg.rounds }} 轮</span>
            <span v-if="msg.degraded?.length" style="color: #e6a23c">降级：{{ msg.degraded.join(', ') }}</span>
            <span v-if="msg.stats?.length">{{ totalHits(msg) }} 条证据</span>
          </div>
        </div>
      </div>

      <div v-if="error" class="msg-row">
        <div class="avatar" style="background: #fee2e2; color: #b91c1c">!</div>
        <div class="bubble" style="border-color: #fecaca; color: #b91c1c">{{ error }}</div>
      </div>
    </div>

    <div class="composer">
      <textarea v-model="question" :disabled="busy" placeholder="输入问题，Enter 发送，Shift+Enter 换行"
        @keydown.enter.exact.prevent="send" />
      <div class="composer-actions">
        <span class="muted">回答会标注引用来源；图谱关系推理（Neo4j）在 P1 接入</span>
        <div>
          <el-button v-if="busy" @click="stop">停止</el-button>
          <el-button type="primary" :loading="busy" :disabled="!canSend" @click="send">发送</el-button>
        </div>
      </div>
    </div>

    <el-drawer v-model="drawer" size="440px" :title="activeCitation ? `引用 [${activeCitation.index}]` : '引用'">
      <template v-if="activeCitation">
        <h3 style="margin-top: 0">{{ activeCitation.doc_name }}</h3>
        <div class="muted" style="margin-bottom: 12px">
          <span v-if="activeCitation.page">第 {{ activeCitation.page }} 页</span>
          <span v-if="activeCitation.section"> · {{ activeCitation.section }}</span>
          <span v-if="activeCitation.score != null"> · 相关度 {{ Number(activeCitation.score).toFixed(4) }}</span>
        </div>
        <div style="white-space: pre-wrap; line-height: 1.8">{{ activeCitation.text }}</div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { streamChat } from '../api'
import { loadKbs, setActiveKb, store } from '../store'

const messages = ref([])
const question = ref('')
const busy = ref(false)
const error = ref('')
const conversationId = ref('')
const selectedKbIds = ref([])
const scroller = ref(null)
const drawer = ref(false)
const activeCitation = ref(null)
let controller = null

const samples = [
  '一线城市住宿标准是多少？',
  '报销需要哪些材料？',
  '超过 20000 元的报销由谁审批？',
]

const canSend = computed(() => question.value.trim().length > 0 && selectedKbIds.value.length > 0 && !busy.value)

onMounted(async () => {
  if (!store.kbs.length) await loadKbs()
  const active = store.activeKbId
  selectedKbIds.value = store.kbs.some((k) => k.id === active) ? [active] : store.kbs.slice(0, 1).map((k) => k.id)
})

watch(
  () => store.activeKbId,
  (id) => {
    if (id && !selectedKbIds.value.includes(id)) selectedKbIds.value = [id, ...selectedKbIds.value]
  },
)

function scrollBottom() {
  nextTick(() => {
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  })
}

function segments(text) {
  const out = []
  const re = /\[(\d+)\]/g
  let last = 0
  let m
  while ((m = re.exec(text || ''))) {
    if (m.index > last) out.push({ text: text.slice(last, m.index) })
    out.push({ cite: Number(m[1]) })
    last = m.index + m[0].length
  }
  if (last < (text || '').length) out.push({ text: text.slice(last) })
  return out
}

function openCitation(msg, index) {
  const c = msg.citations?.find((x) => x.index === index)
  if (c) showCitation(c)
}

function showCitation(c) {
  activeCitation.value = c
  drawer.value = true
}

function routeLabel(route) {
  if (route.need_graph) return '图谱增强（P1 前回退向量）'
  if (route.need_sql) return '结构化查询'
  return route.complexity === 'simple' ? '向量检索' : '多查询检索'
}

function totalHits(msg) {
  return (msg.stats || []).reduce((n, s) => n + (s.returned || 0), 0)
}

function newConversation() {
  if (busy.value) stop()
  messages.value = []
  conversationId.value = ''
  error.value = ''
  question.value = ''
}

function ask(q) {
  question.value = q
  send()
}

function stop() {
  if (controller) controller.abort()
  controller = null
  busy.value = false
  const last = messages.value[messages.value.length - 1]
  if (last && last.streaming) {
    last.streaming = false
    last.done = true
  }
}

async function send() {
  if (!canSend.value) return
  error.value = ''
  const text = question.value.trim()
  question.value = ''
  messages.value.push({ role: 'user', content: text })
  const msg = {
    role: 'assistant',
    content: '',
    streaming: true,
    done: false,
    citations: [],
    verify: {},
    route: {},
    stats: [],
    degraded: [],
    rounds: 0,
  }
  messages.value.push(msg)
  scrollBottom()
  busy.value = true
  controller = new AbortController()

  try {
    await streamChat(
      { kbIds: selectedKbIds.value, question: text, conversationId: conversationId.value },
      (evt) => {
        const d = evt.data
        if (evt.event === 'route') msg.route = d || {}
        else if (evt.event === 'token') {
          msg.content += typeof d === 'string' ? d : d?.text || ''
          scrollBottom()
        } else if (evt.event === 'retrieve') {
          msg.stats.push(...(d.stats || []))
          msg.degraded.push(...(d.degraded || []))
        } else if (evt.event === 'degrade') msg.degraded.push(String(d))
        else if (evt.event === 'verify') msg.verify = d || {}
        else if (evt.event === 'done') {
          msg.streaming = false
          msg.done = true
          msg.content = d.answer || msg.content
          msg.citations = d.citations || []
          msg.verify = d.verify || msg.verify
          msg.route = d.route || msg.route
          msg.rounds = d.rounds || 0
          msg.stats = d.stats || msg.stats
          msg.degraded = d.degraded || msg.degraded
          conversationId.value = d.conversation_id || conversationId.value
        } else if (evt.event === 'error') {
          error.value = String(d)
        }
        scrollBottom()
      },
      controller.signal,
    )
  } catch (e) {
    if (e.name === 'AbortError') return
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    busy.value = false
    controller = null
    const last = messages.value[messages.value.length - 1]
    if (last && last.streaming) {
      last.streaming = false
      last.done = true
    }
  }
}
</script>

<style scoped>
.cursor { animation: blink 1s steps(1) infinite; color: var(--lms-accent); }
@keyframes blink { 50% { opacity: 0; } }
</style>