import { useEffect, useState } from 'react'
import { Clock, CheckCircle, XCircle, Loader2, RefreshCw, MessageSquare } from 'lucide-react'
import { executionsApi } from '../api/client'
import MonitorPanel from '../components/LiveMonitor/MonitorPanel'
import type { Execution, Message } from '../types'

export default function MonitorPage() {
  const [executions, setExecutions] = useState<Execution[]>([])
  const [selectedExec, setSelectedExec] = useState<Execution | null>(null)
  const [messages, setMessages] = useState<Message[]>([])

  const loadExecutions = () => {
    executionsApi.list().then(setExecutions).catch(() => {})
  }

  useEffect(() => { loadExecutions() }, [])

  useEffect(() => {
    if (!selectedExec) return
    executionsApi.messages(selectedExec.id).then(setMessages).catch(() => {})
  }, [selectedExec])

  const StatusIcon = ({ status }: { status: string }) => {
    if (status === 'completed') return <CheckCircle size={14} className="text-green-400" />
    if (status === 'failed') return <XCircle size={14} className="text-red-400" />
    if (status === 'running') return <Loader2 size={14} className="text-yellow-400 animate-spin" />
    return <Clock size={14} className="text-gray-500" />
  }

  const duration = (ex: Execution) => {
    if (!ex.started_at) return '—'
    const end = ex.completed_at ? new Date(ex.completed_at) : new Date()
    const ms = end.getTime() - new Date(ex.started_at).getTime()
    return `${(ms / 1000).toFixed(1)}s`
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Execution history sidebar */}
      <div className="w-72 border-r border-gray-800 flex flex-col bg-gray-900">
        <div className="flex items-center justify-between p-3 border-b border-gray-800">
          <span className="text-sm font-medium">Executions</span>
          <button onClick={loadExecutions} className="p-1.5 hover:bg-gray-800 rounded-lg">
            <RefreshCw size={13} className="text-gray-400" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-thin">
          {executions.length === 0 ? (
            <p className="text-center text-gray-600 text-xs p-4">No executions yet</p>
          ) : (
            executions.map(ex => (
              <button
                key={ex.id}
                onClick={() => setSelectedExec(ex)}
                className={`w-full text-left px-3 py-2.5 border-b border-gray-800 hover:bg-gray-800 transition-colors ${
                  selectedExec?.id === ex.id ? 'bg-gray-800' : ''
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5">
                    <StatusIcon status={ex.status} />
                    <span className="text-xs text-gray-300 font-mono">{ex.id.slice(0, 8)}</span>
                  </div>
                  <span className="text-xs text-gray-600">{duration(ex)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500">
                    {ex.workflow_id ? 'workflow' : 'single agent'}
                  </span>
                  <span className="text-xs text-gray-600">{ex.total_tokens} tok</span>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Main area: execution detail + live monitor */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {selectedExec ? (
          <div className="flex-1 flex flex-col overflow-hidden">
            <div className="p-4 border-b border-gray-800 bg-gray-900">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <StatusIcon status={selectedExec.status} />
                  <div>
                    <p className="font-mono text-sm">{selectedExec.id}</p>
                    <p className="text-xs text-gray-500">
                      {selectedExec.status} · {selectedExec.total_tokens} tokens · ${selectedExec.total_cost.toFixed(5)}
                    </p>
                  </div>
                </div>
                <button onClick={() => setSelectedExec(null)} className="text-xs text-gray-500 hover:text-gray-300">
                  ✕ Close
                </button>
              </div>
              {selectedExec.error && (
                <div className="mt-2 p-2 bg-red-900/20 border border-red-800 rounded text-xs text-red-300">
                  {selectedExec.error}
                </div>
              )}
              {(selectedExec.output_data as Record<string, string>)?.output && (
                <div className="mt-2 p-2 bg-green-900/10 border border-green-900/50 rounded text-xs text-green-300">
                  <strong>Output:</strong> {(selectedExec.output_data as Record<string, string>).output}
                </div>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-4 scrollbar-thin">
              {messages.length === 0 ? (
                <p className="text-gray-600 text-xs text-center mt-4">No messages for this execution</p>
              ) : (
                <div className="space-y-2">
                  {messages.map(msg => (
                    <div key={msg.id} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                      <div className="flex items-center gap-2 mb-1">
                        <MessageSquare size={12} className="text-gray-500" />
                        <span className="text-xs text-blue-400">{msg.from_agent_name}</span>
                        <span className="text-xs text-gray-600">→</span>
                        <span className="text-xs text-gray-400">{msg.to_agent_name}</span>
                        {msg.channel !== 'internal' && (
                          <span className="text-xs bg-purple-900/50 text-purple-400 px-1.5 rounded">{msg.channel}</span>
                        )}
                        <span className="ml-auto text-xs text-gray-600">{msg.tokens_used} tok</span>
                      </div>
                      <p className="text-xs text-gray-300 whitespace-pre-wrap">{msg.content}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex-1 overflow-hidden">
            <MonitorPanel />
          </div>
        )}
      </div>
    </div>
  )
}
