import { useWebSocket } from '../../hooks/useWebSocket'
import { Activity, Wifi, WifiOff, Trash2, Zap, Bot, CheckCircle, XCircle } from 'lucide-react'
import type { WSEvent } from '../../types'

const EVENT_STYLES: Record<string, { color: string; icon: React.ReactNode }> = {
  execution_start: { color: 'text-blue-400', icon: <Zap size={12} /> },
  execution_complete: { color: 'text-green-400', icon: <CheckCircle size={12} /> },
  agent_start: { color: 'text-yellow-400', icon: <Bot size={12} /> },
  agent_complete: { color: 'text-green-400', icon: <Bot size={12} /> },
  agent_message: { color: 'text-gray-300', icon: <Activity size={12} /> },
  channel_message: { color: 'text-purple-400', icon: <Activity size={12} /> },
  channel_response: { color: 'text-purple-300', icon: <Activity size={12} /> },
}

function EventRow({ event }: { event: WSEvent }) {
  const style = EVENT_STYLES[event.type] ?? { color: 'text-gray-500', icon: <Activity size={12} /> }
  const time = new Date(event.timestamp).toLocaleTimeString()

  const summary = () => {
    const d = event.data
    switch (event.type) {
      case 'execution_start': return `Workflow "${d.workflow_name}" started`
      case 'execution_complete': return `Execution complete — ${d.total_tokens} tokens`
      case 'agent_start': return `${d.agent_name} processing: "${String(d.input ?? '').slice(0, 50)}"`
      case 'agent_complete': return `${d.agent_name} done (${d.tokens} tokens): "${String(d.output ?? '').slice(0, 60)}"`
      case 'agent_message': return `${d.agent_name}: "${String(d.content ?? '').slice(0, 80)}"`
      case 'channel_message': return `[${d.channel}] from ${d.from}: "${String(d.content ?? '').slice(0, 60)}"`
      case 'channel_response': return `[${d.channel}] response to ${d.to}: "${String(d.content ?? '').slice(0, 60)}"`
      default: return JSON.stringify(d).slice(0, 100)
    }
  }

  return (
    <div className="flex items-start gap-3 py-2 border-b border-gray-800/50 hover:bg-gray-800/30 px-2 rounded">
      <span className={`mt-0.5 flex-shrink-0 ${style.color}`}>{style.icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className={`text-xs font-mono font-medium ${style.color}`}>{event.type}</span>
          <span className="text-xs text-gray-600">{time}</span>
        </div>
        <p className="text-xs text-gray-300 truncate">{summary()}</p>
      </div>
    </div>
  )
}

export default function MonitorPanel() {
  const { events, connected, clearEvents } = useWebSocket()

  return (
    <div className="flex flex-col h-full bg-gray-950">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-blue-400" />
          <span className="font-semibold text-sm">Live Monitor</span>
          <span className={`text-xs px-2 py-0.5 rounded-full ${connected ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400'}`}>
            {connected ? 'Connected' : 'Reconnecting…'}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">{events.length} events</span>
          <button onClick={clearEvents}
            className="p-1.5 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-gray-200 transition-colors">
            <Trash2 size={14} />
          </button>
          {connected ? <Wifi size={14} className="text-green-400" /> : <WifiOff size={14} className="text-red-400" />}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {events.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-8">
            <Activity size={32} className="text-gray-700 mb-3" />
            <p className="text-gray-500 text-sm">No events yet</p>
            <p className="text-gray-600 text-xs mt-1">Events appear here in real-time as agents execute</p>
          </div>
        ) : (
          <div className="p-2">
            {events.map((event, i) => <EventRow key={i} event={event} />)}
          </div>
        )}
      </div>
    </div>
  )
}
