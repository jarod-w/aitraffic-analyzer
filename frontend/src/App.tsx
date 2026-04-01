import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import NewTask from './pages/NewTask'
import TaskDetail from './pages/TaskDetail'

function Nav() {
  const cls = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-2 rounded text-sm font-medium ${isActive ? 'bg-indigo-600 text-white' : 'text-gray-300 hover:text-white'}`
  return (
    <nav className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center gap-4">
      <span className="text-indigo-400 font-bold text-lg tracking-wide mr-4">PRISM</span>
      <NavLink to="/" end className={cls}>Dashboard</NavLink>
      <NavLink to="/new" className={cls}>New Task</NavLink>
    </nav>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col">
        <Nav />
        <main className="flex-1 p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/new" element={<NewTask />} />
            <Route path="/tasks/:taskId" element={<TaskDetail />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
