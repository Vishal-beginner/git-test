import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bot, GitBranch, Activity, Zap, TrendingUp, Clock, CheckCircle, XCircle } from 'lucide-react'
import { agentsApi, workflowsApi, executionsApi } from '../api/client'
import type { Agent, Workflow, Execution } from '../types'

export default function Dashboard() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [executions, setExecutions] = useState<Execution[]>([])

  useEffect(() => {
    Promise.all([agentsApi.list(), workflowsApi.list(), executionsApi.list()])
      .then(([a, w, e]) => { setAgents(a); setWorkflows(w); setExecutions(e) })
      .catch(() => {})
  }, [])

  const stats = [
    { label: 'Agents', value: agents.length, icon: Bot, color: 'text-blue-400', bg: 'bg-blue-900/30', to: '/agents' },
    { label: 'Workflows', value: workflows.length, icon: GitBranch, color: 'text-purple-400', bg: 'bg-purple-900/30', to: '/workflows' },
    { label: 'Executions', value: executions.length, icon: Zap, color: 'text-yellow-400', bg: 'bg-yellow-900/30', to: '/monitor' },
    { label: 'Active Agents', value: agents.filter(a => a.is_active).length, icon: TrendingUp, color: 'text-green-400', bg: 'bg-green-900/30', to: '/agents' },
  ]

  const totalTokens = executions.reduce((s, e) => s + (e.total_tokens || 0), 0)
  const totalCost = executions.reduce((s, e) => s + (e.total_cost || 0), 0)

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-gray-400 text-sm mt-1">AI Agent Orchestration Platform</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {stats.map(({ label, value, icon: Icon, color, bg, to }) => (
          <Link key={label} to={to}
            className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-700 transition-colors">
            <div className="flex items-center justify-between mb-2">
              <div className={`p-2 rounded-lg ${bg}`}>
                <Icon size={18} className={color} />
              </div>
              <span className="text-2xl font-bold text-white">{value}</span>
            </div>
            <p className="text-sm text-gray-400">{label}</p>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <Activity size={14} className="text-blue-400" />
            <span className="text-sm font-medium">Token Usage</span>
          </div>
          <p className="text-2xl font-bold">{totalTokens.toLocaleString()}</p>
          <p className="text-xs text-gray-500 mt-1">Total tokens consumed</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp size={14} className="text-green-400" />
            <span className="text-sm font-medium">Est. Cost</span>
          </div>
          <p className="text-2xl font-bold">${totalCost.toFixed(4)}</p>
          <p className="text-xs text-gray-500 mt-1">Estimated API cost</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle size={14} className="text-green-400" />
            <span className="text-sm font-medium">Success Rate</span>
          </div>
          <p className="text-2xl font-bold">
            {executions.length === 0 ? '—' :
              `${Math.round((executions.filter(e => e.status === 'completed').length / executions.length) * 100)}%`}
          </p>
          <p className="text-xs text-gray-500 mt-1">Execution success rate</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Recent Executions */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <h3 className="font-medium text-sm mb-3 flex items-center gap-2">
            <Clock size={14} className="text-gray-400" /> Recent Executions
          </h3>
          {executions.slice(0, 5).length === 0 ? (
            <p className="text-gray-600 text-xs">No executions yet</p>
          ) : (
            <div className="space-y-2">
              {executions.slice(0, 5).map(ex => (
                <div key={ex.id} className="flex items-center justify-between py-1.5 border-b border-gray-800">
                  <div className="flex items-center gap-2">
                    {ex.status === 'completed'
                      ? <CheckCircle size={12} className="text-green-400" />
                      : ex.status === 'failed'
                      ? <XCircle size={12} className="text-red-400" />
                      : <Clock size={12} className="text-yellow-400" />}
                    <span className="text-xs text-gray-300">{ex.id.slice(0, 8)}…</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-500">{ex.total_tokens} tok</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      ex.status === 'completed' ? 'bg-green-900/50 text-green-400' :
                      ex.status === 'failed' ? 'bg-red-900/50 text-red-400' :
                      ex.status === 'running' ? 'bg-yellow-900/50 text-yellow-400' :
                      'bg-gray-800 text-gray-400'
                    }`}>{ex.status}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Quick Actions */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <h3 className="font-medium text-sm mb-3">Quick Actions</h3>
          <div className="space-y-2">
            <Link to="/agents" className="flex items-center gap-3 p-3 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors">
              <Bot size={16} className="text-blue-400" />
              <div>
                <p className="text-sm font-medium">Create New Agent</p>
                <p className="text-xs text-gray-500">Configure personality, tools & memory</p>
              </div>
            </Link>
            <Link to="/workflows" className="flex items-center gap-3 p-3 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors">
              <GitBranch size={16} className="text-purple-400" />
              <div>
                <p className="text-sm font-medium">Build a Workflow</p>
                <p className="text-xs text-gray-500">Connect agents into pipelines</p>
              </div>
            </Link>
            <Link to="/monitor" className="flex items-center gap-3 p-3 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors">
              <Activity size={16} className="text-green-400" />
              <div>
                <p className="text-sm font-medium">Live Monitor</p>
                <p className="text-xs text-gray-500">Watch agents execute in real-time</p>
              </div>
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
