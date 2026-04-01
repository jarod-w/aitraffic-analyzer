# PRISM — Shadow AI Traffic Analyzer

> Actively probe, passively capture, and deeply inspect all AI-related network traffic in your organization.

PRISM is an **AI Traffic Profiling and Analysis Platform** that gives security teams full visibility into Shadow AI usage — employees using unauthorized AI services (ChatGPT, DeepSeek, Claude, Gemini, Copilot, etc.) outside IT approval. It intercepts and analyzes both active browsing sessions and historical packet captures, then generates structured reports containing complete raw HTTP request/response packets.

---

## Features

| Capability | Description |
|---|---|
| **Active Probe** | Given a URL, launches a browser, routes traffic through a built-in MITM proxy, and captures all AI-related requests automatically |
| **PCAP Analysis** | Import `.pcap`/`.pcapng` files and extract AI traffic via TCP reassembly + HTTP parsing |
| **TLS Decryption** | Built-in mitmproxy integration with CA certificate export for HTTPS interception |
| **SSE Reassembly** | Parses `text/event-stream` responses and aggregates streaming token output into complete text |
| **WebSocket Capture** | Intercepts and reassembles WebSocket frame conversations (e.g., OpenAI Realtime API) |
| **Metadata Extraction** | Automatically extracts provider, model name, API version, client version, auth type, file uploads, and custom headers |
| **25+ Providers** | Built-in signatures for OpenAI, Anthropic, DeepSeek, Gemini, Copilot, Azure OpenAI, AWS Bedrock, and more |
| **Custom Scripts** | Playwright-based interaction scripts with the `PrismPage` extended API |
| **Multi-format Reports** | Output as Markdown, DOCX, or JSON with configurable secret redaction |
| **Real-time Dashboard** | React web console with live WebSocket feed as traffic is captured |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              PRISM Web Console (React)               │
└──────────────────────┬──────────────────────────────┘
                       │ REST / WebSocket
┌──────────────────────▼──────────────────────────────┐
│                  FastAPI Core Engine                  │
│  Task Scheduler  │  Report Generator  │  Config Mgr  │
│  ───────────────────────────────────────────────────  │
│  Active Probe  │ PCAP Parser │ Stream Reassembly      │
│  (Playwright)  │ (Scapy/dpkt)│ (SSE + WebSocket)     │
│  ───────────────────────────────────────────────────  │
│         AI Traffic Signature Database                 │
│  (domain rules / URI patterns / payload signatures)   │
└──────────────────────────────────────────────────────┘
         │                              │
   ┌─────▼──────┐               ┌───────▼──────┐
   │  mitmproxy  │               │   SQLite /    │
   │  (port 8080)│               │  PostgreSQL   │
   └─────────────┘               └──────────────┘
```

**Tech stack:**

| Layer | Technology |
|---|---|
| Backend | Python 3.12 + FastAPI + uvicorn |
| MITM Proxy | mitmproxy 11.x |
| Browser Automation | Playwright (Chromium) |
| PCAP Parsing | Scapy + dpkt |
| Stream Parsing | wsproto + httptools |
| Database | SQLite (default) / PostgreSQL |
| Frontend | React 18 + TypeScript + TailwindCSS + Vite |
| Reports | Jinja2 + python-docx |

---

## Quick Start (Docker — recommended)

### Prerequisites

- Docker + Docker Compose
- Ports `3000` (web UI) and `8080` (MITM proxy) available

### 1. Clone and start

```bash
git clone https://github.com/your-org/aitraffic-analyzer.git
cd aitraffic-analyzer
cp .env.example .env

docker compose up -d
```

Open **http://localhost:3000** in your browser.

### 2. Trust the CA certificate

For the MITM proxy to decrypt HTTPS traffic, install the generated CA certificate on the target device/browser.

Download the cert:
```bash
curl -o prism-ca.pem http://localhost:3000/api/v1/certs/ca.pem
```

Install on **macOS:**
```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain prism-ca.pem
```

Install on **Ubuntu/Debian:**
```bash
sudo cp prism-ca.pem /usr/local/share/ca-certificates/prism-ca.crt
sudo update-ca-certificates
```

Install on **Windows (run as Administrator):**
```cmd
certutil -addstore -f ROOT prism-ca.pem
```

Or use the API to get the OS-specific command:
```bash
curl http://localhost:3000/api/v1/certs/install-command
```

### 3. Create your first task

**Via the web UI:**
1. Click **New Task**
2. Select **Active Probe**, enter a target URL (e.g. `https://chat.deepseek.com`)
3. Click **Start Probe** — traffic appears in real time on the Task Detail page

**Via API:**
```bash
curl -X POST http://localhost:3000/api/v1/tasks/probe \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://chat.deepseek.com"],
    "interaction_mode": "auto",
    "capture_timeout": 120,
    "output_format": "markdown"
  }'
```

**Analyze a PCAP file:**
```bash
curl -X POST http://localhost:3000/api/v1/tasks/pcap \
  -F "file=@capture.pcap" \
  -F "output_format=markdown"
```

---

## Local Development

### Backend

```bash
# Python 3.12+ required
pip install -e ".[dev]"
playwright install chromium

# Run with hot-reload
PRISM_DEBUG=true python -m prism.main
```

The API will be available at `http://localhost:3000`.

### Frontend

```bash
cd frontend
npm install
npm run dev       # Vite dev server at http://localhost:5173 (proxies /api to :3000)
```

Build for production:
```bash
cd frontend
npm run build     # outputs to frontend/dist/ — served by FastAPI automatically
```

---

## Configuration

All settings are controlled via environment variables (prefix `PRISM_`) or a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `PRISM_HOST` | `0.0.0.0` | FastAPI bind host |
| `PRISM_PORT` | `3000` | FastAPI bind port |
| `PRISM_DEBUG` | `false` | Enable debug logging + hot-reload |
| `PRISM_DB_PATH` | `/data/prism.db` | SQLite database path |
| `PRISM_DB_URL` | _(empty)_ | Full SQLAlchemy URL — overrides `PRISM_DB_PATH` (use for PostgreSQL) |
| `PRISM_MITM_HOST` | `127.0.0.1` | mitmproxy listen host |
| `PRISM_MITM_PORT` | `8080` | mitmproxy listen port |
| `PRISM_DATA_DIR` | `/data` | Root directory for all data |
| `PRISM_UPLOADS_DIR` | `/data/uploads` | PCAP upload staging directory |
| `SSLKEYLOGFILE` | _(empty)_ | Path to TLS key log file (NSS format, compatible with Wireshark) |
| `PRISM_REDACT_SECRETS` | `true` | Redact `Authorization` / `Cookie` headers and API keys in reports |
| `PRISM_DATA_RETENTION_DAYS` | `30` | Automatic data purge threshold |
| `PRISM_MAX_BODY_SIZE` | `10485760` | Max request/response body to capture (bytes) |
| `PRISM_MAX_PCAP_SIZE` | `524288000` | Max PCAP file upload size (bytes, default 500MB) |

### PostgreSQL (enterprise)

```env
PRISM_DB_URL=postgresql+asyncpg://prism:secret@db:5432/prism
```

Add `asyncpg` to your installation:
```bash
pip install -e ".[postgres]"
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/tasks/probe` | Create an active probe task |
| `POST` | `/api/v1/tasks/pcap` | Upload a PCAP file for analysis |
| `GET` | `/api/v1/tasks/{task_id}` | Get task status and record count |
| `GET` | `/api/v1/tasks/{task_id}/records` | List all captured AI records for a task |
| `GET` | `/api/v1/records/{record_id}` | Get full details for a single record |
| `GET` | `/api/v1/tasks/{task_id}/report` | Download report (`?format=markdown\|json\|docx`) |
| `WS` | `/api/v1/tasks/{task_id}/live` | WebSocket live feed of new records |
| `GET` | `/api/v1/certs/ca.pem` | Download the MITM root CA certificate |
| `GET` | `/api/v1/certs/install-command` | Get OS-specific CA install command |
| `GET` | `/api/v1/signatures` | View the current signature database |
| `PUT` | `/api/v1/signatures` | Hot-reload updated signature rules |
| `GET` | `/health` | Health check |

Interactive API docs are available at **http://localhost:3000/docs** (Swagger UI).

---

## Custom Playwright Scripts

For complex sites that need specific interactions, drop a Python file into the `scripts/` directory:

```python
# scripts/deepseek_probe.py
from prism.scripting import PrismPage

async def run(page: PrismPage):
    await page.goto("https://chat.deepseek.com")
    chat_input = await page.wait_for_selector("#chat-input")
    await chat_input.fill("Please write a quicksort algorithm in Python")
    await page.keyboard.press("Enter")

    # Wait for AI response to complete
    await page.prism.wait_for_ai_response(timeout=60000)

    # Annotate phases in the report
    page.prism.mark_phase("response_complete")
```

Then create a task with:
```json
{
  "urls": ["https://chat.deepseek.com"],
  "interaction_mode": "script",
  "playwright_script": "/scripts/deepseek_probe.py"
}
```

---

## Signature Database

AI provider signatures live in `prism/signatures/` as YAML files and support hot-reload via `PUT /api/v1/signatures`.

**Covered providers (built-in):**

- General LLM: OpenAI, Anthropic, DeepSeek, Google Gemini, Mistral, Cohere, Perplexity, Groq, Together AI, Replicate
- Code Assistants: GitHub Copilot, Cursor
- Enterprise: Azure OpenAI, AWS Bedrock, GCP Vertex AI
- Image Generation: Midjourney, Stability AI
- China Domestic: Baidu ERNIE Bot, Alibaba Qwen, ByteDance Doubao, Zhipu AI, Moonshot (Kimi), MiniMax
- Generic patterns: any `/v1/chat/completions`, `/v1/messages`, `/v1/embeddings` endpoint

Add a custom provider by editing `prism/signatures/ai_domains.yaml`:
```yaml
providers:
  my_internal_llm:
    display_name: "Internal LLM Gateway"
    domains:
      - "llm.internal.corp.com"
    confidence: 1.0
```

---

## Deployment — Enterprise / Production

### Network tap mode (passive)

Deploy PRISM at a network gateway with port mirroring enabled. Feed captured traffic as PCAP files via the API — no browser automation needed.

### Forward proxy mode (active)

Configure enterprise devices to use PRISM's mitmproxy (`host:8080`) as their HTTP/HTTPS proxy. Deploy the CA certificate via MDM (Jamf, Intune, etc.) to all managed endpoints.

### Kubernetes (example)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prism
spec:
  replicas: 1
  selector:
    matchLabels:
      app: prism
  template:
    spec:
      containers:
        - name: prism
          image: your-registry/prism:1.0.0
          ports:
            - containerPort: 3000
            - containerPort: 8080
          env:
            - name: PRISM_DB_URL
              valueFrom:
                secretKeyRef:
                  name: prism-secrets
                  key: db-url
```

---

## Security & Compliance

> **Important:** PRISM intercepts and stores traffic that may contain sensitive user data. Before deployment:

- Obtain written approval from your Information Security and Legal teams
- Declare AI traffic monitoring in your employee Acceptable Use Policy (AUP)
- For traffic involving personal data, ensure compliance with applicable regulations (GDPR, PIPL, CCPA, etc.)
- Limit MITM certificate deployment to **enterprise-managed devices only**
- Enable `PRISM_REDACT_SECRETS=true` (default) to mask tokens and session cookies in stored reports
- Data is automatically purged after `PRISM_DATA_RETENTION_DAYS` days (default: 30)

---

## Project Structure

```
aitraffic-analyzer/
├── prism/
│   ├── main.py                  # FastAPI app entry point
│   ├── config.py                # Settings (env-driven)
│   ├── models.py                # Pydantic data models
│   ├── database.py              # Async SQLAlchemy ORM
│   ├── api/                     # REST + WebSocket routes
│   ├── capture/
│   │   ├── probe.py             # Active probe (Playwright + mitmproxy)
│   │   ├── mitm.py              # mitmproxy PrismAddon
│   │   └── cert_manager.py      # CA certificate management
│   ├── pcap/
│   │   └── analyzer.py          # PCAP → TCP reassembly → HTTP → AI ID
│   ├── stream/
│   │   ├── sse.py               # SSE event parser + token aggregator
│   │   └── websocket.py         # WebSocket frame reassembler
│   ├── identification/
│   │   ├── engine.py            # Three-layer weighted matching
│   │   └── metadata.py          # Metadata extractor
│   ├── scripting/
│   │   └── prism_page.py        # PrismPage Playwright extension
│   ├── report/
│   │   └── generator.py         # Markdown / DOCX / JSON output
│   └── signatures/
│       ├── ai_domains.yaml      # Provider domain rules
│       └── ai_patterns.yaml     # URI / header / payload patterns
├── frontend/                    # React 18 + TypeScript + TailwindCSS
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```

---

## License

See [LICENSE](LICENSE).
