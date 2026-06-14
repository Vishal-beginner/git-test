import { useEffect, useState } from 'react'
import { Plus, GitBranch, Play, Trash2, Pencil, LayoutTemplate, ArrowLeft } from 'lucide-react'
import { workflowsApi, agentsApi, executionsApi } from '../api/client'
import WorkflowCanvas from '../components/WorkflowBuilder/WorkflowCanvas'
import type { Agent, Workflow, WorkflowEdge, WorkflowNode, WorkflowTemplate } from '../types'

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([])
  const [selected, setSelected] = useState<Workflow | null>(null)
  const [showNew, setShowNew] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [toast, setToast] = useState('')

  const load = () => {
    workflowsApi.list().then(setWorkflows).catch(() => {})
    agentsApi.list().then(setAgents).catch(() => {})
    workflowsApi.templates().then(setTemplates).catch(() => {})
  }

  useEffect(() => { load() }, [])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  const createWorkflow = async (fromTemplate?: WorkflowTemplate) => {
    const name = fromTemplate ? `${fromTemplate.name} (copy)` : newName
    if (!name) return
    const wf = await workflowsApi.create({
      name,
      description: fromTemplate?.description ?? newDesc,
      nodes: fromTemplate?.nodes ?? [],
      edges: fromTemplate?.edges ?? [],
      template_id: fromTemplate?.id ?? null,
    })
    setWorkflows(w => [wf, ...w])
    setSelected(wf)
    setShowNew(false)
    setNewName('')
    setNewDesc('')
    showToast('Workflow created')
  }

  const handleSave = async (nodes: WorkflowNode[], edges: WorkflowEdge[]) => {
    if (!selected) return
    const updated = await workflowsApi.update(selected.id, { nodes, edges })
    setWorkflows(ws => ws.map(w => w.id === updated.id ? updated : w))
    setSelected(updated)
    showToast('Workflow saved')
  }

  const handleRun = async (inputMessage: string) => {
    if (!selected) return
    await executionsApi.create({ workflow_id: selected.id, input_data: { message: inputMessage } })
    showToast('Workflow execution started — check Live Monitor')
  }

  const deleteWorkflow = async (id: string) => {
    if (!confirm('Delete this workflow?')) return
    await workflowsApi.delete(id)
    setWorkflows(ws => ws.filter(w => w.id !== id))
    if (selected?.id === id) setSelected(null)
  }

  if (selected) {
    return (
      <div className="flex flex-col h-screen">
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800 bg-gray-900">
          <button onClick={() => setSelected(null)} className="flex items-center gap-1 text-sm text-gray-400 hover:text-white">
            <ArrowLeft size={16} /> Back
          </button>
          <div className="h-4 w-px bg-gray-700" />
          <div>
            <span className="font-semibold">{selected.name}</span>
            <span className={`ml-2 text-xs px-2 py-0.5 rounded-full ${
              selected.status === 'active' ? 'bg-green-900/50 text-green-400' : 'bg-gray-800 text-gray-400'
            }`}>{selected.status}</span>
          </div>
        </div>
        <div className="flex-1 overflow-hidden">
          <WorkflowCanvas
            workflow={selected}
            agents={agents}
            onSave={handleSave}
            onRun={handleRun}
          />
        </div>
        {toast && (
          <div className="fixed bottom-4 right-4 bg-green-800 text-green-100 px-4 py-2 rounded-xl text-sm shadow-lg">
            {toast}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Workflows</h1>
          <p className="text-gray-400 text-sm mt-1">{workflows.length} workflow{workflows.length !== 1 ? 's' : ''}</p>
        </div>
        <button onClick={() => setShowNew(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-medium">
          <Plus size={16} /> New Workflow
        </button>
      </div>

      {/* Templates */}
      <div className="mb-6">
        <h2 className="text-sm font-medium text-gray-400 mb-3 flex items-center gap-2">
          <LayoutTemplate size={14} /> Templates
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {templates.map(t => (
            <div key={t.id} className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-700 transition-colors">
              <h3 className="font-medium text-sm mb-1">{t.name}</h3>
              <p className="text-xs text-gray-500 mb-3">{t.description}</p>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-600">{t.nodes.length} nodes · {t.edges.length} edges</span>
                <button onClick={() => createWorkflow(t)}
                  className="text-xs px-3 py-1 bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 rounded-lg transition-colors">
                  Use template
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Existing workflows */}
      {workflows.length > 0 && (
        <div>
          <h2 className="text-sm font-medium text-gray-400 mb-3 flex items-center gap-2">
            <GitBranch size={14} /> My Workflows
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {workflows.map(wf => (
              <div key={wf.id} className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-700 transition-colors">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <GitBranch size={14} className="text-purple-400" />
                    <span className="font-medium text-sm">{wf.name}</span>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    wf.status === 'active' ? 'bg-green-900/50 text-green-400' : 'bg-gray-800 text-gray-400'
                  }`}>{wf.status}</span>
                </div>
                {wf.description && <p className="text-xs text-gray-500 mb-3">{wf.description}</p>}
                <p className="text-xs text-gray-600 mb-3">
                  {wf.nodes.length} nodes · {wf.edges.length} edges
                </p>
                <div className="flex gap-2">
                  <button onClick={() => setSelected(wf)}
                    className="flex-1 flex items-center justify-center gap-1 text-xs py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg">
                    <Pencil size={12} /> Edit
                  </button>
                  <button onClick={() => deleteWorkflow(wf.id)}
                    className="p-1.5 bg-gray-800 hover:bg-red-900/50 text-gray-400 hover:text-red-400 rounded-lg transition-colors">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Create dialog */}
      {showNew && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-96">
            <h3 className="font-semibold mb-4">New Workflow</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Name *</label>
                <input value={newName} onChange={e => setNewName(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                  placeholder="My Workflow" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Description</label>
                <textarea value={newDesc} onChange={e => setNewDesc(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:border-blue-500"
                  rows={2} />
              </div>
            </div>
            <div className="flex gap-3 mt-4">
              <button onClick={() => setShowNew(false)}
                className="flex-1 py-2 border border-gray-700 text-gray-300 rounded-lg text-sm">Cancel</button>
              <button onClick={() => createWorkflow()}
                className="flex-1 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium">Create</button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className="fixed bottom-4 right-4 bg-green-800 text-green-100 px-4 py-2 rounded-xl text-sm shadow-lg">
          {toast}
        </div>
      )}
    </div>
  )
}
