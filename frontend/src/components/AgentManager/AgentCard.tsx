import { Bot, Wrench, Trash2, Edit, MessageSquare } from 'lucide-react'
import type { Agent } from '../../types'

interface Props {
  agent: Agent
  onEdit: (agent: Agent) => void
  onDelete: (id: string) => void
  onChat: (agent: Agent) => void
}

const MODEL_COLORS: Record<string, string> = {
  'gpt-4o': 'bg-green-900 text-green-300',
  'gpt-4o-mini': 'bg-emerald-900 text-emerald-300',
  'claude-3-5-sonnet': 'bg-purple-900 text-purple-300',
  'claude-3-haiku': 'bg-violet-900 text-violet-300',
}

export default function AgentCard({ agent, onEdit, onDelete, onChat }: Props) {
  const modelColor = MODEL_COLORS[agent.model] ?? 'bg-gray-800 text-gray-300'

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-700 transition-colors">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className={`p-2 rounded-lg ${agent.is_active ? 'bg-blue-900' : 'bg-gray-800'}`}>
            <Bot size={16} className={agent.is_active ? 'text-blue-400' : 'text-gray-500'} />
          </div>
          <div>
            <h3 className="font-semibold text-white text-sm">{agent.name}</h3>
            <p className="text-xs text-gray-500">{agent.role}</p>
          </div>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full font-mono ${modelColor}`}>
          {agent.model}
        </span>
      </div>

      <p className="text-xs text-gray-400 line-clamp-2 mb-3">{agent.system_prompt}</p>

      {agent.tools.length > 0 && (
        <div className="flex items-center gap-1 flex-wrap mb-3">
          <Wrench size={10} className="text-gray-500" />
          {agent.tools.map(t => (
            <span key={t} className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded">
              {t}
            </span>
          ))}
        </div>
      )}

      {agent.channels.length > 0 && (
        <div className="flex gap-1 mb-3">
          {agent.channels.map((c, i) => (
            <span key={i} className="text-xs bg-blue-900/50 text-blue-300 px-2 py-0.5 rounded">
              {c.type}
            </span>
          ))}
        </div>
      )}

      <div className="flex gap-2 mt-3 pt-3 border-t border-gray-800">
        <button
          onClick={() => onChat(agent)}
          className="flex-1 flex items-center justify-center gap-1 text-xs py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
        >
          <MessageSquare size={12} /> Chat
        </button>
        <button
          onClick={() => onEdit(agent)}
          className="flex items-center justify-center p-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors"
        >
          <Edit size={14} />
        </button>
        <button
          onClick={() => onDelete(agent.id)}
          className="flex items-center justify-center p-1.5 bg-gray-800 hover:bg-red-900 text-gray-300 hover:text-red-400 rounded-lg transition-colors"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  )
}
