const BASE = '/api/v1'

export interface TaskStatus {
  task_id: string
  type: string
  status: string
  record_count: number
  created_at: string
  completed_at?: string
  error_message?: string
}

export interface RecordSummary {
  id: string
  task_id: string
  sequence: number
  provider: string
  service_type: string
  confidence: number
  method: string
  url: string
  response_status?: number
  stream_type?: string
  timestamp: string
}

export interface RecordDetail extends RecordSummary {
  request_headers: Record<string, string>
  request_body?: string
  response_headers?: Record<string, string>
  response_body?: string
  raw_request: string
  raw_response?: string
  metadata: {
    provider: string
    model_name?: string
    api_version?: string
    user_agent: string
    client_version?: string
    app_version?: string
    platform?: string
    auth_type: string
    is_streaming: boolean
    thinking_enabled?: boolean
    file_upload?: { filename: string; size: number; content_type: string }
    custom_headers: Record<string, string>
  }
  stream_events?: Array<{ event_type: string; data: string; id?: string }>
  aggregated_response?: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${msg}`)
  }
  return res.json()
}

export const api = {
  createProbeTask: (body: {
    urls: string[]
    interaction_mode?: string
    capture_timeout?: number
    output_format?: string
    playwright_script?: string
  }) =>
    request<TaskStatus>('/tasks/probe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  uploadPcap: (formData: FormData) =>
    request<TaskStatus>('/tasks/pcap', { method: 'POST', body: formData }),

  getTask: (id: string) => request<TaskStatus>(`/tasks/${id}`),

  getTaskRecords: (id: string) => request<RecordSummary[]>(`/tasks/${id}/records`),

  getRecord: (id: string) => request<RecordDetail>(`/records/${id}`),

  reportUrl: (taskId: string, fmt: string) =>
    `${BASE}/tasks/${taskId}/report?format=${fmt}`,

  caInstallCmd: () => request<{ command: string }>('/certs/install-command'),
}

export function createLiveFeed(
  taskId: string,
  onMessage: (msg: unknown) => void,
): () => void {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/api/v1/tasks/${taskId}/live`)
  ws.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data))
    } catch {
      /* ignore */
    }
  }
  return () => ws.close()
}
