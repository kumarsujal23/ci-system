import { useEffect, useRef, useState } from 'react'
import { wsUrl } from '../api/client'

export function useLiveLogs(attemptId: string | null) {
  const [logText, setLogText] = useState('')
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!attemptId) return
    setLogText('')
    const ws = new WebSocket(wsUrl(`/ws/attempts/${attemptId}/logs`))
    socketRef.current = ws
    ws.onmessage = (event) => {
      setLogText((prev) => prev + event.data)
    }
    ws.onerror = () => {
      // silently degrade - the dashboard still shows whatever was fetched
      // via REST; live tailing just stops.
    }
    return () => ws.close()
  }, [attemptId])

  return logText
}

export function useJobStatus(jobId: string | null, onMessage: (payload: any) => void) {
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  useEffect(() => {
    if (!jobId) return
    let ws: WebSocket
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let stopped = false

    function connect() {
      ws = new WebSocket(wsUrl(`/ws/jobs/${jobId}/status`))
      ws.onmessage = (event) => {
        try {
          onMessageRef.current(JSON.parse(event.data))
        } catch {
          // ignore malformed frames
        }
      }
      ws.onclose = (event) => {
        // Only reconnect on unexpected closes (not clean teardown from cleanup).
        if (!stopped && !event.wasClean) {
          reconnectTimer = setTimeout(connect, 2000)
        }
      }
      ws.onerror = () => {
        // onerror always precedes onclose; reconnect is handled there.
      }
    }

    connect()

    return () => {
      stopped = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [jobId])
}

