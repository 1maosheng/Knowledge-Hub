import { createRouter, createWebHistory } from 'vue-router'
import KbListView from './views/KbListView.vue'
import KbDetailView from './views/KbDetailView.vue'
import ChatView from './views/ChatView.vue'
import GraphView from './views/GraphView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/kbs' },
    { path: '/kbs', name: 'kbs', component: KbListView, meta: { title: '知识库' } },
    { path: '/kbs/:id', name: 'kb-detail', component: KbDetailView, meta: { title: '知识库详情' } },
    { path: '/chat', name: 'chat', component: ChatView, meta: { title: '智能问答' } },
    { path: '/graph', name: 'graph', component: GraphView, meta: { title: '知识图谱' } },
  ],
})