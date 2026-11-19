const BASE = '/api'

export function getTenant() {
  return localStorage.getItem('lms_tenant') || 'default'
}

export function setTenant(v) {
  localStorage.setItem('lms_tenant', v || 'default')
}

async function errorFrom(resp) {
  let detail = `${resp.status} ${resp.statusText}`
  try {
    const body = await resp.json()
    if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
  } catch {
    /* non-JSON body */
  }
  return new Error(detail)
}

async function request(path, { method = 'GET', body, json = true, headers = {} } = {}) {
  const opts = { method, headers: { 'X-Tenant-Id': getTenant(), ...headers } }
  if (body !== undefined) {
    if (json) {
      opts.headers['Content-Type'] = 'application/json'
      opts.body = JSON.stringify(body)
    } else {
      opts.body = body
    }
  }
  const resp = await fetch(BASE + path, opts)
  if (!resp.ok) throw await errorFrom(resp)
  if (resp.status === 204) return null
  return resp.json()
}

export const api = {
  health: () => request('/health'),
  version: () => request('/version'),
  listKbs: () => request('/kbs'),
  createKb: (body) => request('/kbs', { method: 'POST', body }),
  getKb: (id) => request(`/kbs/${id}`),
  deleteKb: (id) => request(`/kbs/${id}`, { method: 'DELETE' }),
  listDocs: (kbId) => request(`/kbs/${kbId}/documents`),
  getDoc: (id) => request(`/documents/${id}`),
  deleteDoc: (id) => request(`/documents/${id}`, { method: 'DELETE' }),
  reingest: (id) => request(`/documents/${id}/reingest`, { method: 'POST' }),
  uploadDoc: (kbId, file) => {
    const fd = new FormData()
    fd.append('file', file, file.name)
    return request(`/kbs/${kbId}/documents`, { method: 'POST', body: fd, json: false })
  },
  search: (body) => request('/search', { method: 'POST', body }),
  getConversation: (id) => request(`/conversations/${id}`),
}

/**
 * Stream a chat answer over SSE (POST + fetch reader; EventSource cannot POST).
 * handlers: onEvent({event, data})
 */
export async function streamChat({ kbIds, question, conversationId }, handlers, signal) {
  const resp = await fetch(BASE + '/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Tenant-Id': getTenant() },
    body: JSON.stringify({
      kb_ids: kbIds,
      question,
      conversation_id: conversationId || null,
      stream: true,
    }),
    signal,
  })
  if (!resp.ok || !resp.body) throw await errorFrom(resp)

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx = buffer.indexOf('\n\n')
    while (idx >= 0) {
      const frame = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const line = frame.split('\n').find((l) => l.startsWith('data: '))
      if (line) {
        try {
          handlers(JSON.parse(line.slice(6)))
        } catch {
          /* keep streaming on malformed frame */
        }
      }
      idx = buffer.indexOf('\n\n')
    }
  }
}