import { useEffect, useState } from 'react'
import { Plus, Search, MessageSquare } from 'lucide-react'
import { agentsApi, channelsApi } from '../api/client'
import AgentCard from '../components/AgentManager/AgentCard'
import AgentForm from '../components/AgentManager/AgentForm'
import ChatModal from '../components/AgentManager/ChatModal'
import type { Agent } from '../types'

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [tools, setTools] = useState<Record<string, string>>({})
  const [search, setSearch] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editAgent, setEditAgent] = useState<Agent | null>(null)
  const [chatAgent, setChatAgent] = useState<Agent | null>(null)
  const [channelStatus, setChannelStatus] = useState<Record<string, unknown>>({})

  const load = () => {
    agentsApi.list().then(setAgents).catch(() => {})
    agentsApi.tools().then(setTools).catch(() => {})
    channelsApi.status().then(setChannelStatus).catch(() => {})
  }

  useEffect(() => { load() }, [])

  const filtered = agents.filter(a =>
    a.name.toLowerCase().includes(search.toLowerCase()) ||
    a.role.toLowerCase().includes(search.toLowerCase())
  )

  const handleSave = async (data: Partial<Agent>) => {
    try {
      if (editAgent) {
        await agentsApi.update(editAgent.id, data)
      } else {
        await agentsApi.create(data)
      }
      setShowForm(false)
      setEditAgent(null)
      load()
    } catch (e) {
      console.error(e)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this agent?')) return
    await agentsApi.delete(id)
    load()
  }

  const connectTelegram = async (agentId: string) => {
    try {
      await channelsApi.connectTelegram(agentId)
      alert('Agent connected to Telegram!')
      load()
    } catch (e) {
      alert('Failed to connect to Telegram. Make sure TELEGRAM_BOT_TOKEN is set.')
    }
  }

  const tg = (channelStatus as Record<string, Record<string, unknown>>)?.telegram

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Agents</h1>
          <p className="text-gray-400 text-sm mt-1">{agents.length} agent{agents.length !== 1 ? 's' : ''} configured</p>
        </div>
        <button
          onClick={() => { setEditAgent(null); setShowForm(true) }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-medium transition-colors"
        >
          <Plus size={16} /> New Agent
        </button>
      </div>

      {/* Telegram status banner */}
      {tg && (
        <div className={`mb-4 p-3 rounded-xl border text-sm flex items-center justify-between ${
          tg.running ? 'bg-green-900/20 border-green-800 text-green-300' : 'bg-gray-900 border-gray-800 text-gray-400'
        }`}>
          <div className="flex items-center gap-2">
            <MessageSquare size={14} />
            <span>Telegram: {tg.running ? 'Bot running' : tg.enabled ? 'Token set, bot not running' : 'Not configured (set TELEGRAM_BOT_TOKEN)'}</span>
            {tg.connected_agent && <span className="text-xs bg-green-900/50 px-2 py-0.5 rounded">Agent connected</span>}
          </div>
        </div>
      )}

      <div className="mb-4">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search agents…"
            className="w-full pl-9 pr-4 py-2 bg-gray-900 border border-gray-800 rounded-xl text-sm focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-gray-500 mb-2">No agents yet</p>
          <button onClick={() => setShowForm(true)} className="text-blue-400 text-sm hover:underline">Create your first agent</button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filtered.map(agent => (
            <div key={agent.id} className="relative group">
              <AgentCard
                agent={agent}
                onEdit={a => { setEditAgent(a); setShowForm(true) }}
                onDelete={handleDelete}
                onChat={setChatAgent}
              />
              {tg?.enabled && !agent.channels.some((c: {type: string}) => c.type === 'telegram') && (
                <button
                  onClick={() => connectTelegram(agent.id)}
                  className="absolute top-2 right-2 hidden group-hover:flex items-center gap-1 text-xs px-2 py-1 bg-blue-900/80 text-blue-300 rounded-lg"
                >
                  <MessageSquare size={10} /> Telegram
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {showForm && (
        <AgentForm
          agent={editAgent}
          availableTools={tools}
          onSave={handleSave}
          onClose={() => { setShowForm(false); setEditAgent(null) }}
        />
      )}

      {chatAgent && (
        <ChatModal agent={chatAgent} onClose={() => setChatAgent(null)} />
      )}
    </div>
  )
}
