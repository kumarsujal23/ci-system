import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Project, Job } from '../types'
import { JobList } from '../components/JobList'

export function ProjectDetail() {
  const { projectId } = useParams()
  const [project, setProject] = useState<Project | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [commitSha, setCommitSha] = useState('HEAD')
  const [triggering, setTriggering] = useState(false)

  function refresh() {
    if (!projectId) return
    api.getProject(projectId).then(setProject)
    api.listProjectJobs(projectId).then(setJobs)
  }

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 4000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  async function handleTrigger() {
    if (!projectId) return
    setTriggering(true)
    try {
      await api.triggerJob(projectId, { commit_sha: commitSha })
      refresh()
    } finally {
      setTriggering(false)
    }
  }

  if (!project) return <div className="page">loading…</div>

  const webhookUrl = `${window.location.origin}/api/webhooks/github/${project.id}?token=${project.webhook_token}`

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">{project.repo_url}</span>
          <h1>{project.name}</h1>
        </div>
        <div className="trigger-form">
          <input
            className="mono"
            value={commitSha}
            onChange={(e) => setCommitSha(e.target.value)}
            placeholder="commit sha"
          />
          <button className="btn btn--primary" onClick={handleTrigger} disabled={triggering}>
            {triggering ? 'queuing…' : 'Trigger build'}
          </button>
        </div>
      </div>

      <div className="panel">
        <span className="eyebrow">webhook url (push events)</span>
        <code className="mono webhook-url">{webhookUrl}</code>
      </div>

      <div className="panel">
        <span className="eyebrow">pipeline configuration</span>
        <pre className="mono pipeline-yaml">{project.pipeline_yaml}</pre>
      </div>

      <div className="panel">
        <span className="eyebrow">recent jobs</span>
        <JobList jobs={jobs} />
      </div>
    </div>
  )
}
