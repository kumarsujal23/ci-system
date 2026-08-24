import type { JobAttempt } from '../types'

const STATUS_COLOR: Record<string, string> = {
  leased: 'var(--signal-amber)',
  running: 'var(--signal-amber)',
  succeeded: 'var(--signal-green)',
  failed: 'var(--signal-red)',
  infra_error: 'var(--signal-violet)',
  cancelled: 'var(--ink-faint)',
}

const STATUS_LABEL: Record<string, string> = {
  leased: 'leased',
  running: 'running',
  succeeded: 'passed',
  failed: 'failed',
  infra_error: 'infra error',
  cancelled: 'cancelled',
}

/** The rail is the system's signature visual: each attempt is a node in a
 * causal chain. Infra-error nodes are diamonds (they were requeued —
 * recoverable), failed nodes are squares (permanent, terminal, real
 * signal). This distinction is the whole point of the fault-tolerance
 * story, so the shape itself carries that meaning rather than color alone. */
export function PipelineRail({ attempts }: { attempts: JobAttempt[] }) {
  return (
    <div className="rail">
      {attempts.map((a, i) => (
        <div className="rail-node-group" key={a.id}>
          {i > 0 && <div className="rail-connector" />}
          <div
            className={`rail-node rail-node--${a.is_permanent_failure ? 'square' : a.status === 'succeeded' ? 'circle' : 'diamond'}`}
            style={{ ['--node-color' as any]: STATUS_COLOR[a.status] ?? 'var(--ink-faint)' }}
            title={`attempt ${a.attempt_number}: ${STATUS_LABEL[a.status] ?? a.status}`}
          >
            <span className="rail-node-number">{a.attempt_number}</span>
          </div>
          <span className="rail-node-label">{STATUS_LABEL[a.status] ?? a.status}</span>
        </div>
      ))}
    </div>
  )
}
