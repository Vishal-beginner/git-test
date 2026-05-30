import { useState } from 'react'
import { X, Send, Loader2 } from 'lucide-react'
import { executionsApi } from '../../api/client'
import type { Agent } from '../../types'

interface Props {
  agent: Agent
  onClose: () => void
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export default function ChatModal({ agent, onClose }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  const send = async () => {
    if (!input.trim() || loading) return
    const userMsg = input.trim()
    setInput('')
    setMessages(m => [...m, { role: 'user', content: userMsg }])
    setLoading(true)

    try {
      const exec = await executionsApi.create({
        agent_id: agent.id,
        input_data: { message: userMsg },
      })

      // Poll for completion
      let attempts = 0
      const poll = async (): Promise<void> => {
        const updated = await executionsApi.get(exec.id)
        if (updated.status === 'completed') {
          const output = (updated.output_data as Record<string, string>).output ?? 'Done.'
          setMessages(m => [...m, { role: 'assistant', content: output }])
        } else if (updated.status === 'failed') {
          setMessages(m => [...m, { role: 'assistant', content: `Error: ${updated.error}` }])
        } else if (attempts++ < 30) {
          await new Promise(r => setTimeout(r, 1000))
          return poll()
        } else {
          setMessages(m => [...m, { role: 'assistant', content: 'Timed out waiting for response.' }])
        }
      }

      await poll()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to send message'
      setMessages(m => [...m, { role: 'assistant', content: `Error: ${msg}` }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-lg flex flex-col" style={{ height: '70vh' }}>
        <div className="flex items-center justify-between p-4 border-b border-gray-800">
          <div>
            <h2 className="font-semibold">{agent.name}</h2>
            <p className="text-xs text-gray-500">{agent.model}</p>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-gray-800 rounded-lg"><X size={18} /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3 scrollbar-thin">
          {messages.length === 0 && (
            <p className="text-center text-gray-600 text-sm mt-8">
              Start a conversation with <span className="text-gray-400">{agent.name}</span>
            </p>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-xs lg:max-w-sm px-4 py-2.5 rounded-2xl text-sm whitespace-pre-wrap ${
                m.role === 'user'
                  ? 'bg-blue-600 text-white rounded-br-sm'
                  : 'bg-gray-800 text-gray-100 rounded-bl-sm'
              }`}>
                {m.content}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-gray-800 px-4 py-2.5 rounded-2xl rounded-bl-sm">
                <Loader2 size={16} className="animate-spin text-gray-400" />
              </div>
            </div>
          )}
        </div>

        <div className="p-4 border-t border-gray-800">
          <div className="flex gap-2">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
              placeholder="Type a message…"
              className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500"
              disabled={loading}
            />
            <button
              onClick={send} disabled={loading || !input.trim()}
              className="p-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-xl transition-colors"
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
