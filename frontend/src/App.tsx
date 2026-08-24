import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { Dashboard } from './pages/Dashboard'
import { ProjectDetail } from './pages/ProjectDetail'
import { JobDetail } from './pages/JobDetail'
import { Workers } from './pages/Workers'

export default function App() {
  return (
    <BrowserRouter>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark">▣</span>
            <span className="brand-name">forge</span>
          </div>
          <nav className="nav">
            <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? 'nav-link--active' : ''}`}>
              Projects
            </NavLink>
            <NavLink to="/workers" className={({ isActive }) => `nav-link ${isActive ? 'nav-link--active' : ''}`}>
              Workers
            </NavLink>
          </nav>
          <div className="sidebar-footer">
            <span className="sidebar-footer-line">at-least-once execution</span>
            <span className="sidebar-footer-line">AI is a suggestion, not a verdict</span>
          </div>
        </aside>
        <main className="main">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/projects/:projectId" element={<ProjectDetail />} />
            <Route path="/jobs/:jobId" element={<JobDetail />} />
            <Route path="/workers" element={<Workers />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
