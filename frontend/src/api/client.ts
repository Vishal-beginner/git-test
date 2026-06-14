import axios from 'axios'
import type { Agent, Execution, Message, Workflow, WorkflowTemplate } from '../types'

const api = axios.create({ baseURL: '/api' })

export const agentsApi = {
  list: () => api.get<Agent[]>('/agents/').then(r => r.data),
  get: (id: string) => api.get<Agent>(`/agents/${id}`).then(r => r.data),
  create: (data: Partial<Agent>) => api.post<Agent>('/agents/', data).then(r => r.data),
  update: (id: string, data: Partial<Agent>) => api.put<Agent>(`/agents/${id}`, data).then(r => r.data),
  delete: (id: string) => api.delete(`/agents/${id}`).then(r => r.data),
  tools: () => api.get<Record<string, string>>('/agents/tools').then(r => r.data),
}

export const workflowsApi = {
  list: () => api.get<Workflow[]>('/workflows/').then(r => r.data),
  get: (id: string) => api.get<Workflow>(`/workflows/${id}`).then(r => r.data),
  create: (data: Partial<Workflow>) => api.post<Workflow>('/workflows/', data).then(r => r.data),
  update: (id: string, data: Partial<Workflow>) => api.put<Workflow>(`/workflows/${id}`, data).then(r => r.data),
  delete: (id: string) => api.delete(`/workflows/${id}`).then(r => r.data),
  templates: () => api.get<WorkflowTemplate[]>('/workflows/templates').then(r => r.data),
}

export const executionsApi = {
  list: () => api.get<Execution[]>('/executions/').then(r => r.data),
  get: (id: string) => api.get<Execution>(`/executions/${id}`).then(r => r.data),
  create: (data: { workflow_id?: string; agent_id?: string; input_data: Record<string, unknown> }) =>
    api.post<Execution>('/executions/', data).then(r => r.data),
  messages: (id: string) => api.get<Message[]>(`/executions/${id}/messages`).then(r => r.data),
  allMessages: () => api.get<Message[]>('/executions/messages/all').then(r => r.data),
}

export const channelsApi = {
  status: () => api.get('/channels/status').then(r => r.data),
  connectTelegram: (agentId: string) =>
    api.post('/channels/telegram/connect-agent', { agent_id: agentId }).then(r => r.data),
}
