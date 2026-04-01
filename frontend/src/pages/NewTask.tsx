import { FormEvent, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'

function rememberTask(taskId: string) {
  const ids: string[] = JSON.parse(localStorage.getItem('prism_tasks') || '[]')
  if (!ids.includes(taskId)) {
    ids.unshift(taskId)
    localStorage.setItem('prism_tasks', JSON.stringify(ids.slice(0, 50)))
  }
}

export default function NewTask() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<'probe' | 'pcap'>('probe')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Probe form
  const [urls, setUrls] = useState('https://chat.deepseek.com')
  const [interactionMode, setInteractionMode] = useState<'auto' | 'script'>('auto')
  const [timeout, setTimeout] = useState(120)
  const [outputFmt, setOutputFmt] = useState('markdown')
  const [script, setScript] = useState('')

  // PCAP form
  const fileRef = useRef<HTMLInputElement>(null)

  const submitProbe = async (e: FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const task = await api.createProbeTask({
        urls: urls.split('\n').map((u) => u.trim()).filter(Boolean),
        interaction_mode: interactionMode,
        capture_timeout: timeout,
        output_format: outputFmt,
        playwright_script: script || undefined,
      })
      rememberTask(task.task_id)
      navigate(`/tasks/${task.task_id}`)
    } catch (e: unknown) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const submitPcap = async (e: FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    const file = fileRef.current?.files?.[0]
    if (!file) {
      setError('Please select a PCAP file')
      setLoading(false)
      return
    }
    const fd = new FormData()
    fd.append('file', file)
    fd.append('output_format', outputFmt)
    try {
      const task = await api.uploadPcap(fd)
      rememberTask(task.task_id)
      navigate(`/tasks/${task.task_id}`)
    } catch (e: unknown) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const inputCls = 'w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500'
  const labelCls = 'block text-sm text-gray-400 mb-1'

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-white mb-6">New Task</h1>

      {/* Mode selector */}
      <div className="flex gap-2 mb-6">
        {(['probe', 'pcap'] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
              mode === m
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:text-white'
            }`}
          >
            {m === 'probe' ? 'Active Probe' : 'PCAP Import'}
          </button>
        ))}
      </div>

      {mode === 'probe' && (
        <form onSubmit={submitProbe} className="space-y-5">
          <div>
            <label className={labelCls}>Target URLs (one per line)</label>
            <textarea
              className={`${inputCls} h-24 resize-none`}
              value={urls}
              onChange={(e) => setUrls(e.target.value)}
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelCls}>Interaction Mode</label>
              <select
                className={inputCls}
                value={interactionMode}
                onChange={(e) => setInteractionMode(e.target.value as 'auto' | 'script')}
              >
                <option value="auto">Auto-detect</option>
                <option value="script">Custom Script</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Capture Timeout (s)</label>
              <input
                type="number"
                className={inputCls}
                value={timeout}
                min={10}
                max={600}
                onChange={(e) => setTimeout(Number(e.target.value))}
              />
            </div>
          </div>

          {interactionMode === 'script' && (
            <div>
              <label className={labelCls}>Playwright Script Path (on server)</label>
              <input
                className={inputCls}
                value={script}
                onChange={(e) => setScript(e.target.value)}
                placeholder="/scripts/my_probe.py"
              />
            </div>
          )}

          <div>
            <label className={labelCls}>Report Format</label>
            <select
              className={inputCls}
              value={outputFmt}
              onChange={(e) => setOutputFmt(e.target.value)}
            >
              <option value="markdown">Markdown</option>
              <option value="json">JSON</option>
              <option value="docx">DOCX</option>
            </select>
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded font-medium text-sm"
          >
            {loading ? 'Starting...' : 'Start Probe'}
          </button>
        </form>
      )}

      {mode === 'pcap' && (
        <form onSubmit={submitPcap} className="space-y-5">
          <div>
            <label className={labelCls}>PCAP File (.pcap / .pcapng, max 500MB)</label>
            <input
              ref={fileRef}
              type="file"
              accept=".pcap,.pcapng"
              className="w-full text-sm text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded file:border-0 file:text-sm file:bg-indigo-700 file:text-white hover:file:bg-indigo-600"
            />
          </div>

          <div>
            <label className={labelCls}>Report Format</label>
            <select
              className={inputCls}
              value={outputFmt}
              onChange={(e) => setOutputFmt(e.target.value)}
            >
              <option value="markdown">Markdown</option>
              <option value="json">JSON</option>
              <option value="docx">DOCX</option>
            </select>
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded font-medium text-sm"
          >
            {loading ? 'Uploading...' : 'Analyze PCAP'}
          </button>
        </form>
      )}
    </div>
  )
}
