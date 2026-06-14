import { useCallback, useState } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  addEdge, useNodesState, useEdgesState,
  type Node, type Edge, type Connection,
  BackgroundVariant, MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import AgentNode from './AgentNode'
import type { Agent, Workflow, WorkflowNode, WorkflowEdge } from '../../types'
import { Plus, Save, Play } from 'lucide-react'

const nodeTypes = { agentNode: AgentNode }

interface Props {
  workflow: Workflow
  agents: Agent[]
  onSave: (nodes: WorkflowNode[], edges: WorkflowEdge[]) => void
  onRun: (inputMessage: string) => void
}

function toFlowNode(n: WorkflowNode, agents: Agent[]): Node {
  const agent = agents.find(a => a.id === n.agent_id)
  return {
    id: n.id,
    type: 'agentNode',
    position: n.position,
    data: {
      label: n.label || agent?.name || 'Agent',
      agentName: agent?.name,
      role: agent?.role,
      hasAgent: !!agent,
      agentId: n.agent_id,
    },
  }
}

function toFlowEdge(e: WorkflowEdge): Edge {
  return {
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.label || e.condition || '',
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: '#4b5563' },
    labelStyle: { fill: '#9ca3af', fontSize: 10 },
  }
}

export default function WorkflowCanvas({ workflow, agents, onSave, onRun }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState(workflow.nodes.map(n => toFlowNode(n, agents)))
  const [edges, setEdges, onEdgesChange] = useEdgesState(workflow.edges.map(toFlowEdge))
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [runInput, setRunInput] = useState('')
  const [showRunDialog, setShowRunDialog] = useState(false)

  const onConnect = useCallback((params: Connection) => {
    setEdges(eds => addEdge({
      ...params,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: '#4b5563' },
    }, eds))
  }, [setEdges])

  const addNode = () => {
    const id = `node_${Date.now()}`
    const newNode: Node = {
      id,
      type: 'agentNode',
      position: { x: 200 + nodes.length * 50, y: 200 },
      data: { label: 'New Agent', hasAgent: false },
    }
    setNodes(ns => [...ns, newNode])
  }

  const handleSave = () => {
    const wfNodes: WorkflowNode[] = nodes.map(n => ({
      id: n.id,
      agent_id: (n.data.agentId as string) ?? null,
      label: n.data.label as string,
      position: n.position,
      config: {},
    }))
    const wfEdges: WorkflowEdge[] = edges.map(e => ({
      id: e.id,
      source: e.source,
      target: e.target,
      condition: typeof e.label === 'string' ? e.label : 'always',
      label: typeof e.label === 'string' ? e.label : '',
    }))
    onSave(wfNodes, wfEdges)
  }

  const assignAgent = (nodeId: string, agentId: string) => {
    const agent = agents.find(a => a.id === agentId)
    setNodes(ns => ns.map(n => n.id === nodeId
      ? { ...n, data: { ...n.data, agentId, agentName: agent?.name, role: agent?.role, hasAgent: true } }
      : n
    ))
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 p-3 border-b border-gray-800 bg-gray-900">
        <button onClick={addNode}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg">
          <Plus size={13} /> Add Node
        </button>
        <button onClick={handleSave}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg">
          <Save size={13} /> Save
        </button>
        <button onClick={() => setShowRunDialog(true)}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white rounded-lg">
          <Play size={13} /> Run
        </button>
        {selectedNode && (
          <div className="ml-4 flex items-center gap-2">
            <span className="text-xs text-gray-400">Assign agent to node:</span>
            <select
              onChange={e => { if (e.target.value) assignAgent(selectedNode, e.target.value); e.target.value = '' }}
              className="text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1"
              defaultValue=""
            >
              <option value="">Select agent…</option>
              {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </div>
        )}
      </div>

      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          onNodeClick={(_, node) => setSelectedNode(node.id)}
          onPaneClick={() => setSelectedNode(null)}
          fitView
        >
          <Background variant={BackgroundVariant.Dots} color="#1f2937" gap={20} />
          <Controls />
          <MiniMap nodeColor="#374151" maskColor="#0f172a80" />
        </ReactFlow>
      </div>

      {showRunDialog && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-96">
            <h3 className="font-semibold mb-3">Run Workflow</h3>
            <textarea
              value={runInput} onChange={e => setRunInput(e.target.value)}
              placeholder="Initial message / task for the workflow…"
              rows={4}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:border-blue-500 mb-4"
            />
            <div className="flex gap-3">
              <button onClick={() => setShowRunDialog(false)}
                className="flex-1 py-2 border border-gray-700 text-gray-300 rounded-lg text-sm">Cancel</button>
              <button
                onClick={() => { onRun(runInput); setShowRunDialog(false) }}
                className="flex-1 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium">
                Run
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
