export interface Project {
  id: string
  name: string
  repo_url: string
  default_branch: string
  pipeline_yaml: string
  webhook_token: string
  created_at: string
}

export interface JobAttempt {
  id: string
  attempt_number: number
  status: string
  worker_id: string | null
  started_at: string | null
  finished_at: string | null
  exit_code: number | null
  failed_step: string | null
  is_permanent_failure: boolean
}

export interface Job {
  id: string
  project_id: string
  commit_sha: string
  branch: string
  trigger: string
  status: string
  priority: number
  created_at: string
  updated_at: string
  attempts: JobAttempt[]
}

export interface Worker {
  id: string
  name: string
  status: string
  capacity: number
  last_heartbeat_at: string
  registered_at: string
}

export interface AIAnalysis {
  status: string
  provider: string | null
  model: string | null
  failure_category: string | null
  root_cause: string | null
  explanation: string | null
  suggested_fix: string | null
  confidence: number | null
  error_message: string | null
  created_at: string
  completed_at: string | null
}
