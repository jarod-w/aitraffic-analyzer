import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, RecordSummary, TaskStatus, createLiveFeed } from '../api/client'
import RecordCard from '../components/RecordCard'

const STATUS_COLOR: Record<string, string> = {
  pending: 'text-yellow-400',
  running: 'text-blue-400',
  completed: 'text-green-400',
  failed: 'text-red-400',
}

export default function TaskDetail() {
  const { taskId } = useParams<{ taskId: string }>()
  const [task, setTask] = useState<TaskStatus | null>(null)
  const [records, setRecords] = useState<RecordSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const unsub = useRef<(() => void) | null>(null)

  useEffect(() => {
    if (!taskId) return
    let pollTimer: ReturnType<typeof setTimeout>

    const loadTask = async () => {
      try {
        const [t, recs] = await Promise.all([api.getTask(taskId), api.getTaskRecords(taskId)])
        setTask(t)
        setRecords(recs)

        if (t.status === 'running' || t.status === 'pending') {
          pollTimer = setTimeout(loadTask, 3000)
        }
      } catch (e: unknown) {
        setError(String(e))
      }
    }

    loadTask()

    // Subscribe to live feed
    unsub.current = createLiveFeed(taskId, (msg: unknown) => {
      const m = msg as { type: string; data?: unknown; record?: RecordSummary }
      if (m.type === 'new_record' && m.record) {
        setRecords((prev) => {
          if (prev.find((r) => r.id === m.record!.id)) return prev
          return [...prev, m.record!]
        })
      }
      if (m.type === 'task_update' && m.data) {
        const d = m.data as { status: string; record_count: number }
        setTask((prev) => prev ? { ...prev, status: d.status, record_count: d.record_count } : prev)
        if (d.status !== 'running' && d.status !== 'pending') {
          // Final state — do one last refresh
          loadTask()
        }
      }
    })

    return () => {
      clearTimeout(pollTimer)
      unsub.current?.()
    }
  }, [taskId])

  if (error) return <p className="text-red-400">{error}</p>
  if (!task) return <p className="text-gray-400">Loading...</p>

  return (
    <div className="max-w-6xl mx-auto">
      {/* Task header */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 mb-6">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs text-gray-500 font-mono mb-1">{task.task_id}</p>
            <h1 className="text-xl font-bold text-white capitalize">
              {task.type.replace('_', ' ')}
            </h1>
            <div className="flex items-center gap-3 mt-2 text-sm">
              <span className={`font-medium ${STATUS_COLOR[task.status] ?? 'text-gray-300'}`}>
                {task.status}
              </span>
              <span className="text-gray-500">
                {task.record_count} AI request{task.record_count !== 1 ? 's' : ''} captured
              </span>
            </div>
            {task.error_message && (
              <p className="text-red-400 text-sm mt-2">{task.error_message}</p>
            )}
          </div>

          {/* Report download buttons */}
          {task.status === 'completed' && task.record_count > 0 && (
            <div className="flex gap-2">
              {(['markdown', 'json', 'docx'] as const).map((fmt) => (
                <a
                  key={fmt}
                  href={api.reportUrl(task.task_id, fmt)}
                  download
                  className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded text-xs font-medium"
                >
                  .{fmt === 'markdown' ? 'md' : fmt}
                </a>
              ))}
            </div>
          )}
        </div>

        {task.status === 'running' && (
          <div className="mt-3 flex items-center gap-2 text-blue-400 text-sm">
            <span className="animate-pulse">●</span>
            <span>Capturing live traffic…</span>
          </div>
        )}
      </div>

      {/* Records grid */}
      {records.length === 0 ? (
        <p className="text-gray-500 text-center py-10">
          {task.status === 'running' || task.status === 'pending'
            ? 'Waiting for AI traffic…'
            : 'No AI traffic detected.'}
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Record list */}
          <div className="md:col-span-1 space-y-2 max-h-[70vh] overflow-y-auto pr-1">
            {records.map((rec) => (
              <button
                key={rec.id}
                onClick={() => setSelectedId(rec.id === selectedId ? null : rec.id)}
                className={`w-full text-left bg-gray-900 border rounded-lg p-3 hover:border-indigo-600 transition-colors ${
                  rec.id === selectedId ? 'border-indigo-600' : 'border-gray-800'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-semibold text-indigo-300">{rec.provider}</span>
                  <span className="text-xs text-gray-500">#{rec.sequence}</span>
                </div>
                <p className="text-xs text-gray-400 truncate">{rec.url}</p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-gray-500">{rec.service_type}</span>
                  {rec.stream_type && (
                    <span className="text-xs bg-purple-900 text-purple-200 px-1.5 py-0.5 rounded">
                      {rec.stream_type.toUpperCase()}
                    </span>
                  )}
                  <span className="text-xs text-gray-600 ml-auto">
                    {(rec.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              </button>
            ))}
          </div>

          {/* Record detail */}
          <div className="md:col-span-2">
            {selectedId ? (
              <RecordCard recordId={selectedId} />
            ) : (
              <div className="bg-gray-900 border border-gray-800 rounded-lg h-full flex items-center justify-center text-gray-500 text-sm min-h-[200px]">
                Select a record to view details
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
