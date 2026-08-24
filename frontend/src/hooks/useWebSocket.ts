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
  useEffect(() => {
    if (!jobId) return
    const ws = new WebSocket(wsUrl(`/ws/jobs/${jobId}/status`))
    ws.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data))
      } catch {
        // ignore malformed frames
      }
    }
    return () => ws.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])
}
