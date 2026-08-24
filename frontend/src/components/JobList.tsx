import { Link } from 'react-router-dom'
import type { Job } from '../types'
import { PipelineRail } from './PipelineRail'

const STATUS_CLASS: Record<string, string> = {
  queued: 'badge--amber',
  running: 'badge--amber',
  succeeded: 'badge--green',
  failed: 'badge--red',
  errored: 'badge--violet',
  cancelled: 'badge--faint',
}

export function JobList({ jobs }: { jobs: Job[] }) {
  if (jobs.length === 0) {
    return <div className="empty-state">No jobs yet. Trigger one from a project page.</div>
  }
  return (
    <table className="job-table">
      <thead>
        <tr>
          <th>commit</th>
          <th>branch</th>
          <th>trigger</th>
          <th>attempts</th>
          <th>status</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.id}>
            <td>
              <Link to={`/jobs/${job.id}`} className="mono-link">
                {job.commit_sha.slice(0, 8)}
              </Link>
            </td>
            <td className="mono">{job.branch}</td>
            <td className="mono">{job.trigger}</td>
            <td><PipelineRail attempts={job.attempts} /></td>
            <td>
              <span className={`badge ${STATUS_CLASS[job.status] ?? 'badge--faint'}`}>
                {job.status}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
