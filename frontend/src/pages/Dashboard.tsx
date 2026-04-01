import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, TaskStatus } from '../api/client'

const STATUS_COLOR: Record<string, string> = {
  pending: 'bg-yellow-800 text-yellow-200',
  running: 'bg-blue-800 text-blue-200',
  completed: 'bg-green-800 text-green-200',
  failed: 'bg-red-800 text-red-200',
}

export default function Dashboard() {
  const [tasks, setTasks] = useState<TaskStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Fetch recent tasks — poll every 5s while any running
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    const fetchTasks = async () => {
      try {
        // No list endpoint yet — we store visited task IDs in localStorage
        const ids: string[] = JSON.parse(localStorage.getItem('prism_tasks') || '[]')
        if (!ids.length) {
          setLoading(false)
          return
        }
        const results = await Promise.allSettled(ids.map((id) => api.getTask(id)))
        const fetched = results
          .filter((r): r is PromiseFulfilledResult<TaskStatus> => r.status === 'fulfilled')
          .map((r) => r.value)
          .sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
          )
        setTasks(fetched)
        setError('')

        const anyRunning = fetched.some((t) => t.status === 'running' || t.status === 'pending')
        if (anyRunning) {
          timer = setTimeout(fetchTasks, 3000)
        }
      } catch (e: unknown) {
        setError(String(e))
      } finally {
        setLoading(false)
      }
    }

    fetchTasks()
    return () => clearTimeout(timer)
  }, [])

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Task Dashboard</h1>
        <Link
          to="/new"
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded font-medium text-sm"
        >
          + New Task
        </Link>
      </div>

      {loading && <p className="text-gray-400">Loading...</p>}
      {error && <p className="text-red-400">{error}</p>}

      {!loading && tasks.length === 0 && (
        <div className="text-center py-20 text-gray-500">
          <p className="text-lg">No tasks yet.</p>
          <p className="text-sm mt-1">
            <Link to="/new" className="text-indigo-400 hover:underline">
              Create your first task
            </Link>{' '}
            to start capturing AI traffic.
          </p>
        </div>
      )}

      {tasks.length > 0 && (
        <div className="space-y-3">
          {tasks.map((task) => (
            <Link
              key={task.task_id}
              to={`/tasks/${task.task_id}`}
              className="block bg-gray-900 border border-gray-800 rounded-lg p-4 hover:border-indigo-600 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs text-gray-500 font-mono">{task.task_id}</span>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-white font-medium capitalize">{task.type.replace('_', ' ')}</span>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLOR[task.status] ?? 'bg-gray-700 text-gray-300'}`}
                    >
                      {task.status}
                    </span>
                    {task.record_count > 0 && (
                      <span className="text-xs text-indigo-400">
                        {task.record_count} AI request{task.record_count !== 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-xs text-gray-500">
                    {new Date(task.created_at).toLocaleString()}
                  </p>
                  {task.error_message && (
                    <p className="text-xs text-red-400 mt-1 max-w-xs truncate">
                      {task.error_message}
                    </p>
                  )}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
