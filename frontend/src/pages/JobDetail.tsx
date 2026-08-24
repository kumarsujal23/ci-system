import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Job, JobAttempt } from '../types'
import { PipelineRail } from '../components/PipelineRail'
import { LiveLogs } from '../components/LiveLogs'
import { AIAnalysisPanel } from '../components/AIAnalysisPanel'
import { useJobStatus } from '../hooks/useWebSocket'

export function JobDetail() {
  const { jobId } = useParams()
  const [job, setJob] = useState<Job | null>(null)
  const [selectedAttempt, setSelectedAttempt] = useState<JobAttempt | null>(null)

  function refresh() {
    if (!jobId) return
    api.getJob(jobId).then((j) => {
      setJob(j)
      setSelectedAttempt((prev) => {
        if (prev) {
          const stillThere = j.attempts.find((a) => a.id === prev.id)
          if (stillThere) return stillThere
        }
        return j.attempts[j.attempts.length - 1] ?? null
      })
    })
  }

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  useJobStatus(jobId ?? null, () => refresh())

  if (!job) return <div className="page">loading…</div>

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">job</span>
          <h1 className="mono">{job.commit_sha.slice(0, 12)}</h1>
        </div>
        <span className={`badge badge--${statusClass(job.status)}`}>{job.status}</span>
      </div>

      <div className="panel">
        <span className="eyebrow">attempt history</span>
        <PipelineRail attempts={job.attempts} />
      </div>

      <div className="attempt-tabs">
        {job.attempts.map((a) => (
          <button
            key={a.id}
            className={`attempt-tab ${selectedAttempt?.id === a.id ? 'attempt-tab--active' : ''}`}
            onClick={() => setSelectedAttempt(a)}
          >
            #{a.attempt_number} · {a.status}
          </button>
        ))}
      </div>

      <div className="job-detail-grid">
        <LiveLogs attemptId={selectedAttempt?.id ?? null} />
        {selectedAttempt && (
          <AIAnalysisPanel
            attemptId={selectedAttempt.id}
            canAnalyze={selectedAttempt.status === 'failed' || selectedAttempt.status === 'infra_error'}
          />
        )}
      </div>
    </div>
  )
}

function statusClass(status: string) {
  if (status === 'succeeded') return 'green'
  if (status === 'failed') return 'red'
  if (status === 'errored') return 'violet'
  if (status === 'queued' || status === 'running') return 'amber'
  return 'faint'
}
