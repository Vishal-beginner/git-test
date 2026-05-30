import { useState, useEffect } from 'react'
import { X, Plus, Minus } from 'lucide-react'
import type { Agent } from '../../types'

interface Props {
  agent?: Agent | null
  availableTools: Record<string, string>
  onSave: (data: Partial<Agent>) => void
  onClose: () => void
}

const MODELS = [
  'gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo',
  'claude-3-5-sonnet-20241022', 'claude-3-haiku-20240307',
]

export default function AgentForm({ agent, availableTools, onSave, onClose }: Props) {
  const [form, setForm] = useState({
    name: '',
    role: 'assistant',
    system_prompt: 'You are a helpful AI assistant.',
    model: 'gpt-4o-mini',
    tools: [] as string[],
    schedule: '',
    memory_type: 'buffer',
    window_size: 10,
    max_tokens: 2000,
    max_iterations: 10,
    timeout: 60,
    skills: [] as string[],
    interaction_rules: [] as string[],
    is_active: true,
  })
  const [newSkill, setNewSkill] = useState('')
  const [newRule, setNewRule] = useState('')

  useEffect(() => {
    if (agent) {
      setForm({
        name: agent.name,
        role: agent.role,
        system_prompt: agent.system_prompt,
        model: agent.model,
        tools: agent.tools,
        schedule: agent.schedule ?? '',
        memory_type: agent.memory_config?.type ?? 'buffer',
        window_size: agent.memory_config?.window_size ?? 10,
        max_tokens: agent.guardrails?.max_tokens ?? 2000,
        max_iterations: agent.guardrails?.max_iterations ?? 10,
        timeout: agent.guardrails?.timeout ?? 60,
        skills: agent.skills ?? [],
        interaction_rules: agent.interaction_rules ?? [],
        is_active: agent.is_active,
      })
    }
  }, [agent])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSave({
      name: form.name,
      role: form.role,
      system_prompt: form.system_prompt,
      model: form.model,
      tools: form.tools,
      schedule: form.schedule || null,
      memory_config: { type: form.memory_type as 'buffer' | 'summary', window_size: form.window_size },
      guardrails: { max_tokens: form.max_tokens, max_iterations: form.max_iterations, timeout: form.timeout },
      skills: form.skills,
      interaction_rules: form.interaction_rules,
      is_active: form.is_active,
    })
  }

  const toggleTool = (tool: string) => {
    setForm(f => ({
      ...f,
      tools: f.tools.includes(tool) ? f.tools.filter(t => t !== tool) : [...f.tools, tool],
    }))
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-6 border-b border-gray-800 sticky top-0 bg-gray-900">
          <h2 className="text-lg font-semibold">{agent ? 'Edit Agent' : 'Create Agent'}</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-800 rounded-lg">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {/* Basic Info */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Name *</label>
              <input
                value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                placeholder="My Agent" required
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Role</label>
              <input
                value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                placeholder="assistant"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">Model</label>
            <select
              value={form.model} onChange={e => setForm(f => ({ ...f, model: e.target.value }))}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
            >
              {MODELS.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">System Prompt *</label>
            <textarea
              value={form.system_prompt}
              onChange={e => setForm(f => ({ ...f, system_prompt: e.target.value }))}
              rows={4}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 resize-none"
              required
            />
          </div>

          {/* Tools */}
          <div>
            <label className="block text-xs text-gray-400 mb-2">Tools</label>
            <div className="grid grid-cols-3 gap-2">
              {Object.entries(availableTools).map(([name, desc]) => (
                <button
                  key={name} type="button"
                  onClick={() => toggleTool(name)}
                  className={`text-xs px-3 py-2 rounded-lg text-left transition-colors ${
                    form.tools.includes(name)
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                  }`}
                >
                  <div className="font-medium">{name}</div>
                  <div className="text-[10px] opacity-70 truncate">{desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Memory */}
          <div>
            <label className="block text-xs text-gray-400 mb-2">Memory</label>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Type</label>
                <select
                  value={form.memory_type}
                  onChange={e => setForm(f => ({ ...f, memory_type: e.target.value }))}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                >
                  <option value="buffer">Buffer (last N messages)</option>
                  <option value="summary">Summary</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Window Size</label>
                <input
                  type="number" min={1} max={50}
                  value={form.window_size}
                  onChange={e => setForm(f => ({ ...f, window_size: +e.target.value }))}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>
          </div>

          {/* Guardrails */}
          <div>
            <label className="block text-xs text-gray-400 mb-2">Guardrails</label>
            <div className="grid grid-cols-3 gap-3">
              {[
                { key: 'max_tokens', label: 'Max Tokens' },
                { key: 'max_iterations', label: 'Max Iterations' },
                { key: 'timeout', label: 'Timeout (s)' },
              ].map(({ key, label }) => (
                <div key={key}>
                  <label className="block text-xs text-gray-500 mb-1">{label}</label>
                  <input
                    type="number" min={1}
                    value={form[key as keyof typeof form] as number}
                    onChange={e => setForm(f => ({ ...f, [key]: +e.target.value }))}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Schedule */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">Schedule (cron)</label>
            <input
              value={form.schedule}
              onChange={e => setForm(f => ({ ...f, schedule: e.target.value }))}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
              placeholder="e.g. 0 9 * * * (9am daily)"
            />
          </div>

          {/* Skills */}
          <div>
            <label className="block text-xs text-gray-400 mb-2">Skills</label>
            <div className="flex gap-2 mb-2">
              <input
                value={newSkill} onChange={e => setNewSkill(e.target.value)}
                placeholder="Add skill…"
                className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); if (newSkill) { setForm(f => ({ ...f, skills: [...f.skills, newSkill] })); setNewSkill('') } } }}
              />
              <button type="button" onClick={() => { if (newSkill) { setForm(f => ({ ...f, skills: [...f.skills, newSkill] })); setNewSkill('') } }}
                className="p-2 bg-gray-700 hover:bg-gray-600 rounded-lg"><Plus size={14} /></button>
            </div>
            <div className="flex flex-wrap gap-2">
              {form.skills.map((s, i) => (
                <span key={i} className="flex items-center gap-1 text-xs bg-gray-800 text-gray-300 px-2 py-1 rounded">
                  {s}
                  <button type="button" onClick={() => setForm(f => ({ ...f, skills: f.skills.filter((_, j) => j !== i) }))}><Minus size={10} /></button>
                </span>
              ))}
            </div>
          </div>

          {/* Interaction Rules */}
          <div>
            <label className="block text-xs text-gray-400 mb-2">Interaction Rules</label>
            <div className="flex gap-2 mb-2">
              <input
                value={newRule} onChange={e => setNewRule(e.target.value)}
                placeholder="Add rule…"
                className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); if (newRule) { setForm(f => ({ ...f, interaction_rules: [...f.interaction_rules, newRule] })); setNewRule('') } } }}
              />
              <button type="button" onClick={() => { if (newRule) { setForm(f => ({ ...f, interaction_rules: [...f.interaction_rules, newRule] })); setNewRule('') } }}
                className="p-2 bg-gray-700 hover:bg-gray-600 rounded-lg"><Plus size={14} /></button>
            </div>
            <div className="flex flex-wrap gap-2">
              {form.interaction_rules.map((r, i) => (
                <span key={i} className="flex items-center gap-1 text-xs bg-gray-800 text-gray-300 px-2 py-1 rounded">
                  {r}
                  <button type="button" onClick={() => setForm(f => ({ ...f, interaction_rules: f.interaction_rules.filter((_, j) => j !== i) }))}><Minus size={10} /></button>
                </span>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <input type="checkbox" id="active" checked={form.is_active}
              onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))}
              className="rounded" />
            <label htmlFor="active" className="text-sm text-gray-300">Active</label>
          </div>

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose}
              className="flex-1 py-2 border border-gray-700 text-gray-300 rounded-lg hover:bg-gray-800 transition-colors text-sm">
              Cancel
            </button>
            <button type="submit"
              className="flex-1 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors text-sm font-medium">
              {agent ? 'Update Agent' : 'Create Agent'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
