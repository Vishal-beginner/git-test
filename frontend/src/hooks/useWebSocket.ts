import { useEffect, useRef, useState, useCallback } from 'react'
import type { WSEvent } from '../types'

export function useWebSocket() {
  const [events, setEvents] = useState<WSEvent[]>([])
  const [connected, setConnected] = useState(false)
  const ws = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()

  const connect = useCallback(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/ws`
    const socket = new WebSocket(url)

    socket.onopen = () => setConnected(true)
    socket.onclose = () => {
      setConnected(false)
      reconnectTimer.current = setTimeout(connect, 3000)
    }
    socket.onerror = () => socket.close()
    socket.onmessage = (e) => {
      try {
        const event: WSEvent = JSON.parse(e.data)
        setEvents(prev => [event, ...prev].slice(0, 200))
      } catch { /* ignore malformed */ }
    }

    ws.current = socket
  }, [])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      ws.current?.close()
    }
  }, [connect])

  const clearEvents = useCallback(() => setEvents([]), [])

  return { events, connected, clearEvents }
}
