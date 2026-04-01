import { useEffect, useState } from 'react'
import { api, RecordDetail } from '../api/client'

type Tab = 'request' | 'response' | 'metadata' | 'stream'

export default function RecordCard({ recordId }: { recordId: string }) {
  const [record, setRecord] = useState<RecordDetail | null>(null)
  const [tab, setTab] = useState<Tab>('request')
  const [error, setError] = useState('')

  useEffect(() => {
    setRecord(null)
    setError('')
    api.getRecord(recordId)
      .then(setRecord)
      .catch((e) => setError(String(e)))
  }, [recordId])

  if (error) return <div className="text-red-400 text-sm p-4">{error}</div>
  if (!record) return <div className="text-gray-500 text-sm p-4">Loading…</div>

  const tabs: Tab[] = ['request', 'response', 'metadata']
  if (record.stream_type) tabs.push('stream')

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <div>
          <span className="text-indigo-300 font-semibold text-sm">{record.provider}</span>
          <span className="text-gray-500 text-xs ml-2">{record.service_type}</span>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <span className="font-mono">{record.method}</span>
          {record.response_status && (
            <span
              className={`px-1.5 py-0.5 rounded ${
                record.response_status < 300
                  ? 'bg-green-900 text-green-300'
                  : 'bg-red-900 text-red-300'
              }`}
            >
              {record.response_status}
            </span>
          )}
          {record.stream_type && (
            <span className="bg-purple-900 text-purple-200 px-1.5 py-0.5 rounded">
              {record.stream_type.toUpperCase()}
            </span>
          )}
        </div>
      </div>

      {/* URL */}
      <div className="px-4 py-2 bg-gray-950 text-xs font-mono text-gray-400 truncate">
        {record.url}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-800">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-xs font-medium capitalize transition-colors ${
              tab === t
                ? 'border-b-2 border-indigo-500 text-white'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-4 max-h-[50vh] overflow-y-auto">
        {tab === 'request' && (
          <pre className="text-xs text-gray-300 whitespace-pre-wrap break-all">
            {record.raw_request || '(empty)'}
          </pre>
        )}

        {tab === 'response' && (
          <pre className="text-xs text-gray-300 whitespace-pre-wrap break-all">
            {record.raw_response || '(empty)'}
          </pre>
        )}

        {tab === 'metadata' && (
          <table className="text-xs w-full">
            <tbody>
              {Object.entries({
                Provider: record.metadata.provider,
                Model: record.metadata.model_name ?? '—',
                'API Version': record.metadata.api_version ?? '—',
                'User-Agent': record.metadata.user_agent || '—',
                'Client Version': record.metadata.client_version ?? '—',
                Platform: record.metadata.platform ?? '—',
                'Auth Type': record.metadata.auth_type,
                Streaming: record.metadata.is_streaming ? 'Yes' : 'No',
                Thinking:
                  record.metadata.thinking_enabled == null
                    ? '—'
                    : record.metadata.thinking_enabled
                    ? 'Enabled'
                    : 'Disabled',
                ...(record.metadata.file_upload
                  ? {
                      'File Name': record.metadata.file_upload.filename,
                      'File Size': `${record.metadata.file_upload.size.toLocaleString()} bytes`,
                    }
                  : {}),
              }).map(([k, v]) => (
                <tr key={k} className="border-b border-gray-800">
                  <td className="py-1.5 pr-4 text-gray-500 w-36">{k}</td>
                  <td className="py-1.5 text-gray-200 break-all">{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tab === 'stream' && record.stream_type === 'sse' && (
          <div className="space-y-3">
            {record.aggregated_response && (
              <div>
                <p className="text-xs text-gray-500 mb-1">Aggregated Response</p>
                <div className="bg-gray-950 rounded p-3 text-sm text-gray-200 whitespace-pre-wrap">
                  {record.aggregated_response}
                </div>
              </div>
            )}
            <div>
              <p className="text-xs text-gray-500 mb-1">
                Raw Events ({record.stream_events?.length ?? 0})
              </p>
              <pre className="text-xs text-gray-400 whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
                {record.stream_events?.map((e) => `data: ${e.data}`).join('\n') ?? ''}
              </pre>
            </div>
          </div>
        )}

        {tab === 'stream' && record.stream_type === 'websocket' && (
          <div className="space-y-2">
            {record.stream_events?.map((frame, i) => (
              <div key={i} className="border border-gray-800 rounded p-2">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`text-xs px-1.5 py-0.5 rounded ${
                      frame.direction === 'client'
                        ? 'bg-blue-900 text-blue-300'
                        : 'bg-green-900 text-green-300'
                    }`}
                  >
                    {frame.direction === 'client' ? 'Client → Server' : 'Server → Client'}
                  </span>
                  <span className="text-xs text-gray-500">#{i + 1}</span>
                </div>
                <pre className="text-xs text-gray-300 whitespace-pre-wrap break-all">
                  {frame.payload}
                </pre>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
