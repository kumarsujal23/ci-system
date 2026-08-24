import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Project } from '../types'

const DEFAULT_PIPELINE = `image: python:3.11-slim
timeout_seconds: 600
resources:
  memory: 512m
  cpus: 1.0
network: bridge
steps:
  - name: install
    run: pip install -r requirements.txt
  - name: test
    run: pytest -q
`

export function Dashboard() {
  const [projects, setProjects] = useState<Project[]>([])
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [pipelineYaml, setPipelineYaml] = useState(DEFAULT_PIPELINE)
  const [error, setError] = useState<string | null>(null)

  function refresh() {
    api.listProjects().then(setProjects)
  }

  useEffect(refresh, [])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await api.createProject({ name, repo_url: repoUrl, default_branch: 'main', pipeline_yaml: pipelineYaml })
      setShowForm(false)
      setName('')
      setRepoUrl('')
      setPipelineYaml(DEFAULT_PIPELINE)
      refresh()
    } catch (err: any) {
      setError(err.message)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">registered repositories</span>
          <h1>Projects</h1>
        </div>
        <button className="btn btn--primary" onClick={() => setShowForm((s) => !s)}>
          {showForm ? 'cancel' : '+ New project'}
        </button>
      </div>

      {showForm && (
        <form className="panel form" onSubmit={handleCreate}>
          <label>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label>
            Repository URL
            <input value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} required
                   placeholder="https://github.com/you/repo.git" />
          </label>
          <label>
            Pipeline (YAML)
            <textarea
              className="mono"
              rows={12}
              value={pipelineYaml}
              onChange={(e) => setPipelineYaml(e.target.value)}
            />
          </label>
          {error && <div className="form-error">{error}</div>}
          <button className="btn btn--primary" type="submit">Register project</button>
        </form>
      )}

      <div className="card-grid">
        {projects.map((p) => (
          <Link to={`/projects/${p.id}`} key={p.id} className="project-card">
            <span className="project-card-name">{p.name}</span>
            <span className="project-card-repo mono">{p.repo_url}</span>
            <span className="project-card-branch">default branch: {p.default_branch}</span>
          </Link>
        ))}
        {projects.length === 0 && !showForm && (
          <div className="empty-state">No projects registered yet. Create one to get started.</div>
        )}
      </div>
    </div>
  )
}
