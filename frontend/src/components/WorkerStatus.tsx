import type { Worker } from '../types'

const STATUS_META: Record<string, { label: string; className: string }> = {
  online: { label: 'online', className: 'badge--green' },
  offline: { label: 'offline', className: 'badge--faint' },
  dead: { label: 'dead', className: 'badge--red' },
}

export function WorkerStatus({ workers }: { workers: Worker[] }) {
  if (workers.length === 0) {
    return <div className="empty-state">No workers have registered yet.</div>
  }
  return (
    <div className="worker-grid">
      {workers.map((w) => {
        const meta = STATUS_META[w.status] ?? { label: w.status, className: 'badge--faint' }
        return (
          <div className={`worker-card worker-card--${w.status}`} key={w.id}>
            <div className="worker-card-top">
              <span className="worker-name">{w.name}</span>
              <span className={`badge ${meta.className}`}>{meta.label}</span>
            </div>
            <div className="worker-card-meta">
              <span>capacity {w.capacity}</span>
              <span className="mono">{w.id.slice(0, 8)}</span>
            </div>
            <div className="worker-card-heartbeat">
              last heartbeat {new Date(w.last_heartbeat_at).toLocaleTimeString()}
            </div>
          </div>
        )
      })}
    </div>
  )
}
