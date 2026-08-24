import { useEffect, useRef } from 'react'
import { useLiveLogs } from '../hooks/useWebSocket'

export function LiveLogs({ attemptId }: { attemptId: string | null }) {
  const logText = useLiveLogs(attemptId)
  const scrollRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logText])

  if (!attemptId) {
    return <div className="terminal terminal--empty">select an attempt to view its log</div>
  }

  return (
    <div className="terminal">
      <div className="terminal-bar">
        <span className="terminal-dot" />
        <span className="terminal-dot" />
        <span className="terminal-dot" />
        <span className="terminal-title">attempt {attemptId.slice(0, 8)} — live log</span>
      </div>
      <pre className="terminal-body" ref={scrollRef}>
        {logText || 'waiting for output…'}
      </pre>
    </div>
  )
}
