import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Worker } from '../types'
import { WorkerStatus } from '../components/WorkerStatus'

export function Workers() {
  const [workers, setWorkers] = useState<Worker[]>([])

  useEffect(() => {
    function refresh() {
      api.listWorkers().then(setWorkers)
    }
    refresh()
    const interval = setInterval(refresh, 3000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">fleet</span>
          <h1>Workers</h1>
        </div>
      </div>
      <WorkerStatus workers={workers} />
    </div>
  )
}
