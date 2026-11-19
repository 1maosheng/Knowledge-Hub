import { reactive } from 'vue'
import { api, getTenant, setTenant } from './api'

export const store = reactive({
  kbs: [],
  loading: false,
  tenant: getTenant(),
  health: null,
  activeKbId: localStorage.getItem('lms_active_kb') || '',
})

export function switchTenant(tenant) {
  store.tenant = tenant || 'default'
  setTenant(store.tenant)
  store.kbs = []
  store.activeKbId = ''
  localStorage.removeItem('lms_active_kb')
  loadHealth()
  loadKbs()
}

export async function loadHealth() {
  try {
    store.health = await api.health()
  } catch {
    store.health = null
  }
}

export async function loadKbs() {
  store.loading = true
  try {
    store.kbs = await api.listKbs()
    if (store.activeKbId && !store.kbs.some((k) => k.id === store.activeKbId)) {
      setActiveKb('')
    }
    if (!store.activeKbId && store.kbs.length) setActiveKb(store.kbs[0].id)
  } finally {
    store.loading = false
  }
}

export function setActiveKb(id) {
  store.activeKbId = id || ''
  if (id) localStorage.setItem('lms_active_kb', id)
  else localStorage.removeItem('lms_active_kb')
}

export async function createKb(payload) {
  const kb = await api.createKb(payload)
  await loadKbs()
  setActiveKb(kb.id)
  return kb
}