<template>
  <el-container style="height: 100%">
    <el-aside width="212px" class="sidebar">
      <div class="brand">
        <div class="brand-mark">L</div>
        <div>
          <div class="brand-name">LMS 知识中枢</div>
          <div class="brand-sub">RAG · Graph · Agents</div>
        </div>
      </div>

      <el-menu :default-active="$route.path" router background-color="#111827" text-color="#9ca3af"
        active-text-color="#ffffff" style="border-right: none">
        <el-menu-item index="/kbs">
          <el-icon><FolderOpened /></el-icon><span>知识库</span>
        </el-menu-item>
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon><span>智能问答</span>
        </el-menu-item>
        <el-menu-item index="/graph">
          <el-icon><Share /></el-icon><span>知识图谱</span>
          <el-tag size="small" effect="plain" type="info" style="margin-left: 8px">P1</el-tag>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-foot">
        <el-tag v-if="store.health" size="small" :type="store.health.llm?.mode === 'mock' ? 'warning' : 'success'"
          effect="dark">
          {{ store.health.llm?.mode === 'mock' ? 'Mock 模式' : 'LLM 已接入' }}
        </el-tag>
        <el-tag v-else size="small" type="danger" effect="dark">服务未连接</el-tag>
        <div class="muted" style="margin-top: 8px">向量库：{{ store.health?.vector_backend || '—' }}</div>
      </div>
    </el-aside>

    <el-container>
      <el-header height="48px" class="topbar">
        <span class="muted">{{ $route.meta.title || '' }}</span>
        <div style="display: flex; align-items: center; gap: 8px">
          <span class="muted">租户</span>
          <el-input v-model="tenantInput" size="small" style="width: 130px" @keyup.enter="applyTenant" />
          <el-button size="small" text @click="applyTenant">切换</el-button>
        </div>
      </el-header>
      <el-main style="padding: 0; overflow: auto">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { loadHealth, loadKbs, store, switchTenant } from './store'

const route = useRoute()
const tenantInput = ref(store.tenant)

onMounted(() => {
  loadHealth()
  loadKbs()
})

watch(() => route.path, () => loadHealth())

function applyTenant() {
  switchTenant(tenantInput.value.trim() || 'default')
  tenantInput.value = store.tenant
}
</script>

<style scoped>
.sidebar {
  background: #111827;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.brand {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 18px 16px;
  color: #fff;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}

.brand-name { font-size: 14px; font-weight: 600; }
.brand-sub { font-size: 11px; color: #6b7280; }

.sidebar-foot {
  padding: 14px 16px 20px;
  border-top: 1px solid #1f2937;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
}
</style>