import { Handle, Position } from '@xyflow/react'
import { Bot } from 'lucide-react'

interface AgentNodeData {
  label: string
  agentName?: string
  role?: string
  hasAgent?: boolean
}

export default function AgentNode({ data, selected }: { data: AgentNodeData; selected: boolean }) {
  return (
    <div className={`bg-gray-900 border-2 rounded-xl px-4 py-3 min-w-[140px] transition-colors ${
      selected ? 'border-blue-500' : data.hasAgent ? 'border-gray-700' : 'border-dashed border-gray-600'
    }`}>
      <Handle type="target" position={Position.Left} className="!bg-blue-500 !border-gray-900 !w-3 !h-3" />

      <div className="flex items-center gap-2">
        <div className={`p-1.5 rounded-lg ${data.hasAgent ? 'bg-blue-900' : 'bg-gray-800'}`}>
          <Bot size={14} className={data.hasAgent ? 'text-blue-400' : 'text-gray-600'} />
        </div>
        <div>
          <p className="text-xs font-semibold text-white leading-tight">{data.label}</p>
          {data.agentName && (
            <p className="text-[10px] text-gray-400 leading-tight truncate max-w-[100px]">{data.agentName}</p>
          )}
          {data.role && (
            <p className="text-[10px] text-blue-400 leading-tight">{data.role}</p>
          )}
        </div>
      </div>

      <Handle type="source" position={Position.Right} className="!bg-green-500 !border-gray-900 !w-3 !h-3" />
    </div>
  )
}
