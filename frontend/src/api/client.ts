import type { Project, Job, Worker, AIAnalysis } from '../types'

const BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (res.status === 204) return undefined as T
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json()
}

export const api = {
  listProjects: () => request<Project[]>('/projects'),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (payload: { name: string; repo_url: string; default_branch: string; pipeline_yaml: string }) =>
    request<Project>('/projects', { method: 'POST', body: JSON.stringify(payload) }),
  updatePipeline: (id: string, pipeline_yaml: string) =>
    request<Project>(`/projects/${id}/pipeline`, { method: 'PUT', body: JSON.stringify({ pipeline_yaml }) }),

  listJobs: () => request<Job[]>('/jobs'),
  listProjectJobs: (projectId: string) => request<Job[]>(`/projects/${projectId}/jobs`),
  getJob: (id: string) => request<Job>(`/jobs/${id}`),
  triggerJob: (projectId: string, payload: { commit_sha: string; branch?: string; priority?: number }) =>
    request<Job>(`/projects/${projectId}/jobs`, { method: 'POST', body: JSON.stringify(payload) }),

  listWorkers: () => request<Worker[]>('/workers'),

  getAnalysis: (attemptId: string) => request<AIAnalysis>(`/attempts/${attemptId}/analysis`).catch(() => null),
  triggerAnalysis: (attemptId: string) =>
    request<AIAnalysis>(`/attempts/${attemptId}/analyze`, { method: 'POST' }),
}

export function wsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${path}`
}
