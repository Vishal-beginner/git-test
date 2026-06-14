export interface Agent {
  id: string
  name: string
  role: string
  system_prompt: string
  model: string
  tools: string[]
  channels: ChannelConfig[]
  memory_config: MemoryConfig
  schedule: string | null
  guardrails: Guardrails
  skills: string[]
  interaction_rules: string[]
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ChannelConfig {
  type: string
  enabled: boolean
  [key: string]: unknown
}

export interface MemoryConfig {
  type: 'buffer' | 'summary'
  window_size: number
}

export interface Guardrails {
  max_tokens: number
  max_iterations: number
  timeout: number
}

export interface WorkflowNode {
  id: string
  agent_id: string | null
  label: string
  position: { x: number; y: number }
  config: Record<string, unknown>
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  condition?: string
  label?: string
}

export interface Workflow {
  id: string
  name: string
  description: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  status: 'draft' | 'active' | 'archived'
  template_id: string | null
  created_at: string
  updated_at: string
}

export interface WorkflowTemplate {
  id: string
  name: string
  description: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export interface Execution {
  id: string
  workflow_id: string | null
  agent_id: string | null
  status: 'pending' | 'running' | 'completed' | 'failed'
  input_data: Record<string, unknown>
  output_data: Record<string, unknown>
  error: string | null
  started_at: string | null
  completed_at: string | null
  total_tokens: number
  total_cost: number
  created_at: string
}

export interface Message {
  id: string
  execution_id: string | null
  from_agent_name: string
  to_agent_name: string
  content: string
  message_type: string
  channel: string
  tokens_used: number
  cost: number
  created_at: string
}

export interface WSEvent {
  type: string
  data: Record<string, unknown>
  timestamp: string
}
