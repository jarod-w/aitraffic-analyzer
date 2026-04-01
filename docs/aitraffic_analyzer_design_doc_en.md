# Shadow AI Traffic Analyzer — System Design Document

> **Project Codename**: PRISM  
> **Version**: v1.0  
> **Date**: 2026-04-01  
> **Author**: AI Applications Product Division  
> **Status**: Initial Design

---

## 1. Project Background & Objectives

### 1.1 Problem Statement

"Shadow AI" refers to the unauthorized use of third-party AI services (e.g., ChatGPT, DeepSeek, Claude, Gemini, Copilot) by employees within an organization, bypassing IT department approval and security audits. This behavior poses risks of sensitive data leakage, regulatory non-compliance, and security audit blind spots.

### 1.2 Project Goal

Build an **AI Traffic Profiling and Analysis Platform (PRISM)** capable of active probing, passive capture, and deep inspection of all AI-related network traffic. The platform generates analysis reports containing complete raw HTTP request/response packets, providing full visibility for security teams.

### 1.3 Core Capabilities Overview

| Capability | Description |
|------------|-------------|
| Active Capture | Given a URL, automatically interact with the web page and capture all network traffic |
| PCAP Analysis | Import pcap/pcapng files and extract AI-related traffic |
| Stream Reassembly | WebSocket / SSE long-lived connection packet reassembly and reconstruction |
| Scripted Interaction | Support for Playwright/Puppeteer custom interaction scripts |
| Metadata Identification | Automatic extraction of User-Agent, API Version, Model Name, and other metadata |
| MITM Decryption | Built-in man-in-the-middle proxy with TLS decryption and certificate export |
| Report Generation | Output structured raw packet documents (per the reference format in the attachment) |

---

## 2. System Architecture

### 2.1 High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        PRISM Web Console                        │
│              (React + TypeScript Frontend UI)                    │
└────────────────────────────┬────────────────────────────────────┘
                             │ REST / WebSocket
┌────────────────────────────▼────────────────────────────────────┐
│                     PRISM Core Engine                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ Task     │  │ Report   │  │ Auth     │  │ Config         │  │
│  │ Scheduler│  │ Generator│  │ Manager  │  │ Manager        │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────────────┘  │
│       │              │             │                              │
│  ┌────▼──────────────▼─────────────▼─────────────────────────┐  │
│  │              Pipeline Orchestrator                         │  │
│  └──┬─────────┬──────────┬──────────┬──────────┬────────────┘  │
│     │         │          │          │          │                 │
│  ┌──▼───┐ ┌──▼────┐ ┌───▼───┐ ┌───▼────┐ ┌──▼──────────┐     │
│  │Active│ │ PCAP  │ │Stream │ │Metadata│ │ MITM Proxy  │     │
│  │Probe │ │Parser │ │Reasm. │ │Extract │ │ Module      │     │
│  │Module│ │Module │ │Module │ │Engine  │ │(mitmproxy)  │     │
│  └──┬───┘ └──┬────┘ └───┬───┘ └───┬────┘ └──┬──────────┘     │
│     │        │          │         │          │                  │
│  ┌──▼────────▼──────────▼─────────▼──────────▼──────────────┐  │
│  │            AI Traffic Signature Database                   │  │
│  │  (Domain Rules / URI Patterns / Header Fingerprints /     │  │
│  │   Payload Signatures)                                     │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │                                          │
   ┌─────▼──────┐                           ┌──────▼──────┐
   │ Playwright  │                           │  Storage    │
   │ / Puppeteer │                           │ (SQLite /   │
   │  Browser    │                           │  PostgreSQL)│
   └─────────────┘                           └─────────────┘
```

### 2.2 Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Backend Framework | Python 3.12 + FastAPI | Async high-performance, rich ecosystem |
| Browser Automation | Playwright (Python) | Multi-browser support, native CDP integration |
| MITM Proxy | mitmproxy 11.x (Python API) | Mature, programmable, TLS decryption support |
| PCAP Parsing | Scapy + dpkt | Flexible packet parsing and reassembly |
| Stream Protocol Parsing | Custom module (based on httptools + wsproto) | WebSocket / SSE dedicated reassembly |
| Storage Layer | SQLite (standalone) / PostgreSQL (multi-user) | Scales with deployment size |
| Frontend | React 18 + TypeScript + TailwindCSS | Modern SPA management interface |
| Report Generation | Jinja2 template engine + python-docx | Multi-format output (Markdown / DOCX / JSON) |

---

## 3. Detailed Module Design

### 3.1 Module 1: Active Probe & Capture (Active Probe Module)

#### 3.1.1 Functional Description

The user provides one or more URLs (optionally with authentication credentials). The system automatically launches a browser instance, routes traffic through the MITM Proxy for page navigation and interaction, and captures all HTTP/HTTPS traffic simultaneously.

#### 3.1.2 Workflow

```
User inputs URL + Credentials
        │
        ▼
┌──────────────────────┐
│ 1. Start mitmproxy    │──── Generate & register CA certificate
│    Listen on port     │
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ 2. Launch Playwright  │──── Configure proxy to point to mitmproxy
│    browser instance   │──── Install CA cert into browser trust chain
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ 3. Page navigation    │──── Navigate to target URL
│    + Auto-login       │──── Execute login flow if credentials provided
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ 4. Interaction exec.  │──── Default: auto-detect AI interaction entry
│                      │──── Custom: execute user Playwright script
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ 5. Traffic capture    │──── mitmproxy addon real-time callback
│    & filtering        │──── AI traffic signature matching
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ 6. Packet recording   │──── Save complete raw request/response
│    + Report gen.      │──── Output per attachment format
└──────────────────────┘
```

#### 3.1.3 Input Parameter Design

```python
class ProbeTask(BaseModel):
    """Active probe task definition"""
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    
    # Target configuration
    urls: list[str]                          # Target URL list
    credentials: Optional[Credentials]       # Login credentials
    
    # Interaction configuration
    interaction_mode: Literal["auto", "script"] = "auto"
    playwright_script: Optional[str] = None  # Path to user-defined script
    
    # Capture configuration
    capture_timeout: int = 120               # Capture timeout (seconds)
    capture_body: bool = True                # Whether to save full request body
    max_body_size: int = 10 * 1024 * 1024    # Request body size limit (10MB)
    
    # Output configuration
    output_format: Literal["markdown", "docx", "json"] = "markdown"

class Credentials(BaseModel):
    """Authentication credentials"""
    auth_type: Literal["form", "basic", "bearer", "cookie"]
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    cookies: Optional[dict[str, str]] = None
    login_url: Optional[str] = None          # Login page URL (for form type)
    username_selector: Optional[str] = None  # Username input CSS selector
    password_selector: Optional[str] = None  # Password input CSS selector
    submit_selector: Optional[str] = None    # Submit button CSS selector
```

#### 3.1.4 Auto-Login Strategy

For sites requiring authentication, the system supports four login methods:

**Form-Based Login** — Suitable for traditional web login pages. The system uses Playwright to automatically locate form elements, fill in credentials, and submit. Users can specify input fields and button positions via CSS selectors, or use auto-detection mode (the system searches the page for common patterns such as `input[type=password]`).

**Basic Auth** — The system injects an `Authorization: Basic <base64>` header into all outgoing HTTP requests.

**Bearer Token** — The system injects an `Authorization: Bearer <token>` header into all requests. Suitable for scenarios with direct API key access.

**Cookie Injection** — The system directly sets specified cookies in the browser context. Suitable for scenarios where session cookies have already been obtained.

---

### 3.2 Module 2: PCAP File Parsing (PCAP Parser Module)

#### 3.2.1 Functional Description

The user uploads a pcap or pcapng file. The system extracts all HTTP/HTTPS traffic from it (HTTPS decryption requires a corresponding TLS key log via SSLKEYLOGFILE), identifies AI-related requests, and generates reports in the same format as active capture output.

#### 3.2.2 Processing Pipeline

```
PCAP File Upload
      │
      ▼
┌─────────────────────────┐
│ 1. Format validation     │──── Verify pcap/pcapng validity
│    Size limit: < 500MB   │──── Check file integrity
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ 2. TCP stream reassembly │──── Scapy/dpkt-based TCP stream reassembly
│                         │──── Handle out-of-order, retransmission, fragmentation
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ 3. TLS decryption (opt.) │──── Decrypt using SSLKEYLOGFILE
│                         │──── Or mark as [ENCRYPTED]
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ 4. HTTP protocol parsing │──── Parse HTTP/1.1, HTTP/2 frames
│                         │──── Extract request line, headers, body
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ 5. AI traffic identif.   │──── Match against signature database
│                         │──── Score and rank
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ 6. Report generation     │──── Output in raw packet format
│                         │──── Separate packet types with delimiters
└─────────────────────────┘
```

#### 3.2.3 Core Parsing Engine

```python
class PcapAnalyzer:
    """PCAP file analyzer"""
    
    def __init__(self, filepath: str, sslkeylog: Optional[str] = None):
        self.filepath = filepath
        self.sslkeylog = sslkeylog
        self.sessions: list[HTTPSession] = []
    
    def parse(self) -> list[AITrafficRecord]:
        """Main parsing entry point"""
        raw_packets = self._read_packets()                    # Read raw packets
        tcp_streams = self._reassemble_tcp(raw_packets)       # TCP stream reassembly
        
        if self.sslkeylog:
            tcp_streams = self._decrypt_tls(tcp_streams)      # TLS decryption
        
        http_sessions = self._parse_http(tcp_streams)         # HTTP parsing
        ai_records = self._identify_ai_traffic(http_sessions) # AI identification
        
        return ai_records
    
    def _reassemble_tcp(self, packets) -> list[TCPStream]:
        """TCP stream reassembly — handles out-of-order, retransmissions, FIN/RST"""
        streams = {}
        for pkt in packets:
            if not pkt.haslayer(TCP):
                continue
            flow_key = self._get_flow_key(pkt)
            if flow_key not in streams:
                streams[flow_key] = TCPStream(flow_key)
            streams[flow_key].add_packet(pkt)
        
        for stream in streams.values():
            stream.reassemble()  # Reassemble by sequence number
        
        return list(streams.values())
```

#### 3.2.4 HTTP/2 Support

HTTP/2 traffic within PCAPs requires special handling. The system uses the `h2` library for HTTP/2 frame decoding, reconstituting multiplexed streams into individual request-response pairs. For HPACK-compressed headers, the system maintains a separate decoding context for restoration.

---

### 3.3 Module 3: Stream Protocol Reassembly (Stream Reassembly Module)

#### 3.3.1 Design Objective

Modern AI services widely use WebSocket or Server-Sent Events (SSE) for streaming responses. This module is responsible for reassembling fragmented messages from these long-lived connections into complete logical units.

#### 3.3.2 WebSocket Reassembly

```python
class WebSocketReassembler:
    """WebSocket message reassembler"""
    
    def __init__(self):
        self.fragments: dict[str, list[WSFrame]] = {}
        self.messages: list[WSMessage] = []
    
    def feed_frame(self, conn_id: str, frame: WSFrame):
        """Feed frames one at a time"""
        if conn_id not in self.fragments:
            self.fragments[conn_id] = []
        
        self.fragments[conn_id].append(frame)
        
        if frame.fin:  # FIN bit indicates end of message
            payload = b"".join(
                f.payload for f in self.fragments[conn_id]
            )
            msg = WSMessage(
                conn_id=conn_id,
                opcode=self.fragments[conn_id][0].opcode,
                payload=payload,
                timestamp_start=self.fragments[conn_id][0].timestamp,
                timestamp_end=frame.timestamp,
                direction=frame.direction,  # client→server / server→client
            )
            self.messages.append(msg)
            self.fragments[conn_id] = []
    
    def get_conversation(self, conn_id: str) -> list[WSMessage]:
        """Retrieve the complete conversation sequence"""
        return [m for m in self.messages if m.conn_id == conn_id]
```

#### 3.3.3 SSE Reassembly

SSE (Server-Sent Events) is the most common protocol for AI streaming output. The system splits the raw `text/event-stream` data by `\n\n` into individual events, parses the `event`, `data`, `id`, and `retry` fields, and aggregates all SSE events from the same request into a single complete record.

```python
class SSEReassembler:
    """SSE event stream reassembler"""
    
    def parse_stream(self, raw_body: bytes) -> list[SSEEvent]:
        """Parse SSE stream"""
        events = []
        current = SSEEvent()
        
        for line in raw_body.decode("utf-8", errors="replace").split("\n"):
            if line == "":
                if current.data:
                    events.append(current)
                current = SSEEvent()
            elif line.startswith("data: "):
                current.data += line[6:]
            elif line.startswith("event: "):
                current.event_type = line[7:]
            elif line.startswith("id: "):
                current.event_id = line[4:]
        
        return events
    
    def aggregate_completion(self, events: list[SSEEvent]) -> str:
        """Aggregate streaming tokens into a complete response text"""
        full_text = ""
        for event in events:
            try:
                payload = json.loads(event.data)
                # Compatible with OpenAI / DeepSeek / Anthropic formats
                delta = (
                    payload.get("choices", [{}])[0]
                           .get("delta", {})
                           .get("content", "")
                )
                if not delta:
                    delta = payload.get("delta", {}).get("text", "")
                full_text += delta
            except (json.JSONDecodeError, IndexError, KeyError):
                continue
        return full_text
```

#### 3.3.4 Output Format

For streaming packets, the output report adopts the following structure:

```
========== [WebSocket Session] ==========
Connection ID: ws-3a7f2b
Upgrade Request:
  GET wss://api.openai.com/v1/realtime HTTP/1.1
  ...headers...

--- Frame #1 (Client → Server) [2026-04-01 10:23:01.123] ---
{"type": "session.update", "session": {"model": "gpt-4o-realtime"}}

--- Frame #2 (Server → Client) [2026-04-01 10:23:01.456] ---
{"type": "session.created", "session": {...}}

... more frames ...

========== [SSE Session] ==========
Request:
  POST https://api.deepseek.com/v1/chat/completions HTTP/1.1
  ...headers...
  {"model": "deepseek-chat", "stream": true, ...}

Aggregated Response (32 events, 1.8s):
  "This is the complete aggregated response content..."

Raw Events:
  data: {"choices":[{"delta":{"content":"Hello"}}]}
  data: {"choices":[{"delta":{"content":" there"}}]}
  ...
```

---

### 3.4 Module 4: Custom Interaction Scripts (Script Engine)

#### 3.4.1 Design Rationale

Different AI services have vastly different interaction patterns — some require clicking specific buttons, some require typing a prompt and waiting, and others are direct API calls. Therefore, the system provides two modes: **auto-detection mode** and **custom script mode**.

#### 3.4.2 Auto-Detection Mode

The system includes a set of heuristic rules that, after page load, automatically attempt to identify the AI chat interface and execute interactions:

1. Detect text input fields on the page (textarea / contenteditable), prioritizing elements whose `placeholder` contains keywords like "Ask", "Message", "Prompt", or "Chat".
2. Fill the input field with a predefined probe text (e.g., "Hello, this is a test message") to trigger an AI request.
3. Wait for the response to complete (monitor SSE stream closure or DOM change stabilization).
4. Record the complete request-response traffic.

#### 3.4.3 Custom Script Mode

Users can write standard Playwright Python scripts to define complex interaction logic. The system provides an extended API:

```python
# Example user script: deepseek_probe.py
from prism.scripting import PrismPage

async def run(page: PrismPage):
    """
    PrismPage inherits from playwright.async_api.Page
    and provides additional PRISM-specific helper methods.
    """
    # Navigate to DeepSeek
    await page.goto("https://chat.deepseek.com")
    
    # Wait for chat input box
    chat_input = await page.wait_for_selector("#chat-input")
    
    # Send test message
    await chat_input.fill("Please write a quicksort algorithm in Python")
    await page.keyboard.press("Enter")
    
    # Wait for response to complete (PRISM extension method)
    await page.prism.wait_for_ai_response(timeout=60000)
    
    # File upload test
    file_input = await page.query_selector("input[type=file]")
    if file_input:
        await file_input.set_input_files("./test_document.docx")
        await page.prism.wait_for_upload_complete()
    
    # Mark the current phase
    page.prism.mark_phase("upload_test_complete")
```

#### 3.4.4 Script Sandbox & Security

User scripts run in an isolated process subject to the following constraints: execution timeout limit (default 5 minutes), read-only file system access (restricted to designated directories), no outbound network access (except through the MITM Proxy), and memory usage cap (default 512MB).

---

### 3.5 Module 5: AI Traffic Identification Engine (Identification Engine)

#### 3.5.1 Multi-Layer Identification Strategy

The identification engine employs a three-layer matching mechanism, each layer scored independently and combined via weighted aggregation:

**Layer 1: Domain / Host Matching (Weight: 40%)**

```yaml
# ai_domains.yaml — AI service domain signature database
providers:
  openai:
    domains:
      - "api.openai.com"
      - "chat.openai.com"
      - "chatgpt.com"
      - "*.oaiusercontent.com"
    confidence: 1.0
  
  anthropic:
    domains:
      - "api.anthropic.com"
      - "claude.ai"
      - "*.anthropic.com"
    confidence: 1.0
  
  deepseek:
    domains:
      - "api.deepseek.com"
      - "chat.deepseek.com"
    confidence: 1.0
  
  google_ai:
    domains:
      - "generativelanguage.googleapis.com"
      - "gemini.google.com"
      - "aistudio.google.com"
    confidence: 1.0
  
  # ... more providers (Mistral, Cohere, Perplexity, Baidu ERNIE, Alibaba Qwen,
  #                      ByteDance Doubao, etc.)
```

**Layer 2: URI Path + Header Feature Matching (Weight: 35%)**

```yaml
# ai_patterns.yaml
patterns:
  - name: "OpenAI Chat Completion"
    uri_regex: "/v1/chat/completions"
    headers:
      "authorization": "Bearer sk-.*"
    confidence: 0.95
  
  - name: "Anthropic Messages API"
    uri_regex: "/v1/messages"
    headers:
      "x-api-key": "sk-ant-.*"
      "anthropic-version": ".*"
    confidence: 0.95
  
  - name: "DeepSeek File Upload"
    uri_regex: "/api/v0/file/upload_file"
    headers:
      "x-client-platform": ".*"
      "x-app-version": ".*"
    confidence: 0.90
  
  - name: "Generic LLM Chat API"
    uri_regex: ".*/chat/completions|.*/generate|.*/v1/messages"
    body_contains: ["model", "messages", "prompt"]
    confidence: 0.70
```

**Layer 3: Payload Semantic Analysis (Weight: 25%)**

The system performs JSON structure analysis on request bodies, detecting whether they contain typical field combinations of AI calls (e.g., `model` + `messages` + `temperature`, `prompt` + `max_tokens`, etc.), and attempts to extract specific model names.

#### 3.5.2 Automated Metadata Extraction

```python
class MetadataExtractor:
    """AI traffic metadata extractor"""
    
    def extract(self, request: HTTPRequest, response: HTTPResponse) -> AIMetadata:
        return AIMetadata(
            provider=self._identify_provider(request),
            model_name=self._extract_model(request, response),
            api_version=self._extract_api_version(request),
            user_agent=request.headers.get("User-Agent", ""),
            client_version=self._extract_client_version(request),
            auth_type=self._classify_auth(request),
            content_type=request.headers.get("Content-Type", ""),
            is_streaming=self._detect_streaming(request, response),
            thinking_enabled=self._detect_thinking(request),
            custom_headers=self._extract_custom_headers(request),
            timestamp=request.timestamp,
        )
    
    def _extract_model(self, req, resp) -> Optional[str]:
        """Extract model name from request or response"""
        # 1. Extract from request body
        if req.json_body and "model" in req.json_body:
            return req.json_body["model"]
        
        # 2. Extract from response body
        if resp.json_body and "model" in resp.json_body:
            return resp.json_body["model"]
        
        # 3. Extract from URL path (e.g., /models/gpt-4/completions)
        model_match = re.search(r"/models?/([a-zA-Z0-9\-_.]+)", req.url)
        if model_match:
            return model_match.group(1)
        
        # 4. Extract from custom headers
        for header in ["x-model", "x-model-id", "x-thinking-enabled"]:
            if header in req.headers:
                return req.headers[header]
        
        return None
    
    def _extract_custom_headers(self, req) -> dict:
        """Extract AI service-specific custom headers"""
        custom = {}
        ai_header_prefixes = [
            "x-api-", "x-client-", "x-app-", "x-model-",
            "x-ds-", "x-thinking-", "x-file-", "anthropic-",
            "openai-", "x-stainless-",
        ]
        for key, value in req.headers.items():
            if any(key.lower().startswith(p) for p in ai_header_prefixes):
                custom[key] = value
        return custom
```

---

### 3.6 Module 6: MITM Proxy Module (Decryption Layer)

#### 3.6.1 Architecture Design

The MITM Proxy module is built on `mitmproxy`'s Python API, operating as a transparent/forward proxy responsible for TLS decryption and traffic interception.

```python
class PrismAddon:
    """mitmproxy addon — PRISM core data collection layer"""
    
    def __init__(self, task_id: str, signature_db: SignatureDB):
        self.task_id = task_id
        self.sig_db = signature_db
        self.records: list[CapturedFlow] = []
    
    def request(self, flow: http.HTTPFlow):
        """Request interception callback"""
        flow.metadata["prism_task_id"] = self.task_id
        flow.metadata["capture_time"] = datetime.utcnow().isoformat()
    
    def response(self, flow: http.HTTPFlow):
        """Response interception callback — core collection point"""
        if not self.sig_db.is_ai_related(flow):
            return
        
        record = CapturedFlow(
            task_id=self.task_id,
            request=self._serialize_request(flow.request),
            response=self._serialize_response(flow.response),
            metadata=MetadataExtractor().extract(flow.request, flow.response),
            raw_request=self._dump_raw_request(flow),
            raw_response=self._dump_raw_response(flow),
        )
        self.records.append(record)
    
    def websocket_message(self, flow: http.HTTPFlow):
        """WebSocket message interception"""
        msg = flow.websocket.messages[-1]
        # Record each frame for subsequent reassembly
        self.ws_reassembler.feed_frame(
            conn_id=flow.id,
            frame=WSFrame(
                payload=msg.content,
                opcode=msg.type,
                direction="client" if msg.from_client else "server",
                timestamp=datetime.utcnow(),
                fin=True,  # mitmproxy has already completed frame reassembly
            )
        )
    
    def _dump_raw_request(self, flow) -> str:
        """Generate raw HTTP request packet (consistent with attachment format)"""
        req = flow.request
        lines = [f"{req.method} {req.url} {req.http_version}"]
        for k, v in req.headers.items():
            lines.append(f"{k}: {v}")
        lines.append("")
        
        body = req.get_content(limit=10 * 1024 * 1024)
        if body:
            lines.append(body.decode("utf-8", errors="replace"))
        
        return "\n".join(lines)
```

#### 3.6.2 Certificate Management & Export

```python
class CertManager:
    """CA certificate management"""
    
    CERT_DIR = Path.home() / ".prism" / "certs"
    
    def generate_ca(self) -> tuple[Path, Path]:
        """Generate PRISM root CA certificate"""
        # Uses mitmproxy's built-in certificate generation capability
        # Outputs PEM-formatted CA certificate and private key
        ca_cert = self.CERT_DIR / "prism-ca-cert.pem"
        ca_key = self.CERT_DIR / "prism-ca-key.pem"
        return ca_cert, ca_key
    
    def export_for_browser(self, format: str = "pem") -> Path:
        """Export browser-installable CA certificate"""
        # Supports PEM (Linux/macOS), DER (Windows), P12 (universal)
        ...
    
    def export_for_system(self, os_type: str) -> str:
        """Return system-level certificate installation command"""
        commands = {
            "macos": "sudo security add-trusted-cert -d -r trustRoot "
                     "-k /Library/Keychains/System.keychain {cert}",
            "ubuntu": "sudo cp {cert} /usr/local/share/ca-certificates/ "
                      "&& sudo update-ca-certificates",
            "windows": "certutil -addstore -f ROOT {cert}",
        }
        return commands.get(os_type, "")
```

#### 3.6.3 TLS Key Logging

The system supports exporting TLS session keys via the `SSLKEYLOGFILE` environment variable, enabling offline decryption verification with external tools such as Wireshark.

---

### 3.7 Module 7: Report Generation (Report Generator)

#### 3.7.1 Output Format Definition

The system follows the format of the attached sample to generate analysis reports containing complete raw HTTP packets. When multiple types of AI traffic are present, clear delimiters are used to separate them:

```
╔══════════════════════════════════════════════════════════════════╗
║  PRISM AI Traffic Analysis Report                               ║
║  Task ID: probe-2026-04-01-a3f7                                 ║
║  Generated: 2026-04-01T14:23:00Z                                ║
║  Total AI Requests Captured: 5                                  ║
╚══════════════════════════════════════════════════════════════════╝

══════════════════════════════════════════════════════════════════
 Record #1 — DeepSeek File Upload
 Provider: DeepSeek | Model: N/A (file upload)
 Type: HTTP POST | Confidence: 0.95
══════════════════════════════════════════════════════════════════

POST https://chat.deepseek.com/api/v0/file/upload_file HTTP/1.1
Host: chat.deepseek.com
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) ...
Accept: */*
x-thinking-enabled: 0
x-file-size: 52060
x-ds-pow-response: eyJhbGdvcml0aG0iOiJEZWVwU2Vla0hhc2hWMSIs...
x-client-platform: web
x-client-version: 1.7.1
x-app-version: 20241129.1
Authorization: Bearer [REDACTED]
Content-Type: multipart/form-data; boundary=----geckoform...
Content-Length: 52343
Origin: https://chat.deepseek.com
Cookie: [REDACTED]

------geckoformboundary3dfa3c2814503fcc4c97d39789c52621
Content-Disposition: form-data; name="file"; filename="DOCX_TestPage.docx"
Content-Type: application/vnd.openxmlformats-officedocument...

[BINARY DATA: 52060 bytes, SHA256: a3f7b2c1...]
------geckoformboundary3dfa3c2814503fcc4c97d39789c52621--

── Extracted Metadata ──────────────────────────────────────────
  Provider     : DeepSeek
  User-Agent   : Mozilla/5.0 (Windows NT 10.0; Win64; x64; ...)
  Client Ver.  : 1.7.1
  App Ver.     : 20241129.1
  Platform     : web
  Auth Type    : Bearer Token
  File Name    : DOCX_TestPage.docx
  File Size    : 52,060 bytes
  Thinking     : Disabled

════════════════════════════════════════════════════════════════
 Record #2 — DeepSeek Chat Completion (SSE)
 Provider: DeepSeek | Model: deepseek-chat
 Type: SSE Stream | Confidence: 0.98
════════════════════════════════════════════════════════════════

POST https://chat.deepseek.com/api/v0/chat/completion HTTP/1.1
...full request headers and body...

── SSE Response Stream (42 events, 3.2s) ──
data: {"choices":[{"delta":{"content":"Hello"}}]}
data: {"choices":[{"delta":{"content":" there"}}]}
...
data: [DONE]

── Aggregated Response ──
Hello there! How can I help you?

── Extracted Metadata ──────────────────────────────────────────
  Provider     : DeepSeek
  Model        : deepseek-chat
  Streaming    : Yes (SSE)
  ...
```

#### 3.7.2 Sensitive Information Handling

By default, the report generator redacts the following fields:

- Bearer Token in `Authorization` headers → `[REDACTED]`
- Session information in `Cookie` headers → `[REDACTED]`
- Binary request bodies → `[BINARY DATA: {size} bytes, SHA256: {hash}]`
- API Keys → only the first 8 characters retained + `...`

Users can disable redaction via the `--no-redact` flag for internal security analysis.

---

## 4. AI Traffic Signature Database

### 4.1 Coverage

The built-in signature database covers the following AI service providers (continuously updated):

| Category | Provider | Key Domains / Signatures |
|----------|----------|--------------------------|
| General LLM | OpenAI | api.openai.com, chatgpt.com |
| General LLM | Anthropic | api.anthropic.com, claude.ai |
| General LLM | Google | generativelanguage.googleapis.com, gemini.google.com |
| General LLM | DeepSeek | api.deepseek.com, chat.deepseek.com |
| General LLM | Mistral | api.mistral.ai |
| Code Assistant | GitHub Copilot | copilot-proxy.githubusercontent.com |
| Code Assistant | Cursor | api2.cursor.sh |
| Enterprise Platform | Azure OpenAI | *.openai.azure.com |
| Enterprise Platform | AWS Bedrock | bedrock-runtime.*.amazonaws.com |
| Enterprise Platform | GCP Vertex AI | *.aiplatform.googleapis.com |
| Image Generation | Midjourney | *.midjourney.com |
| Image Generation | Stability AI | api.stability.ai |
| China Domestic | Baidu ERNIE Bot | aip.baidubce.com, yiyan.baidu.com |
| China Domestic | Alibaba Qwen | dashscope.aliyuncs.com |
| China Domestic | ByteDance Doubao | *.volcengine.com |
| China Domestic | Zhipu AI | open.bigmodel.cn |

### 4.2 Signature Update Mechanism

The signature database is independently maintained as YAML files with hot-reload support. Update sources include community contributions (GitHub PRs), automated crawlers (periodic scanning of AI service API documentation changes), and user-defined custom rule supplements.

---

## 5. Data Model

### 5.1 Core Entities

```python
class CaptureTask(BaseModel):
    """Capture task"""
    id: str
    type: Literal["active_probe", "pcap_import"]
    status: Literal["pending", "running", "completed", "failed"]
    config: ProbeTask | PcapImportConfig
    created_at: datetime
    completed_at: Optional[datetime]
    record_count: int = 0
    error_message: Optional[str] = None

class AITrafficRecord(BaseModel):
    """AI traffic record"""
    id: str
    task_id: str
    sequence: int                              # Sequence number within the same task
    provider: str                              # AI service provider
    service_type: str                          # chat / completion / embedding / upload / image
    confidence: float                          # Identification confidence 0~1
    
    # Raw packets
    raw_request: str                           # Raw HTTP request text
    raw_response: Optional[str]                # Raw HTTP response text
    
    # Structured data
    method: str
    url: str
    request_headers: dict[str, str]
    request_body: Optional[str]
    response_status: Optional[int]
    response_headers: Optional[dict[str, str]]
    response_body: Optional[str]
    
    # Metadata
    metadata: AIMetadata
    
    # Streaming data
    stream_type: Optional[Literal["sse", "websocket"]] = None
    stream_events: Optional[list[dict]] = None
    aggregated_response: Optional[str] = None
    
    timestamp: datetime

class AIMetadata(BaseModel):
    """AI traffic metadata"""
    provider: str
    model_name: Optional[str]
    api_version: Optional[str]
    user_agent: str
    client_version: Optional[str]
    app_version: Optional[str]
    platform: Optional[str]
    auth_type: str
    is_streaming: bool
    thinking_enabled: Optional[bool]
    file_upload: Optional[FileUploadInfo]
    custom_headers: dict[str, str]
```

---

## 6. API Interface Design

### 6.1 Core REST API

```
POST   /api/v1/tasks/probe          — Create active probe task
POST   /api/v1/tasks/pcap           — Upload PCAP and create analysis task
GET    /api/v1/tasks/{task_id}       — Query task status
GET    /api/v1/tasks/{task_id}/records  — Get AI traffic record list
GET    /api/v1/records/{record_id}   — Get single record details
GET    /api/v1/tasks/{task_id}/report  — Download report (format=md|docx|json)
POST   /api/v1/scripts/validate      — Validate Playwright script syntax
GET    /api/v1/certs/ca.pem          — Download CA certificate
GET    /api/v1/signatures            — View current signature database
PUT    /api/v1/signatures            — Update signature rules
WS     /api/v1/tasks/{task_id}/live  — Real-time traffic push (WebSocket)
```

### 6.2 Real-Time Traffic Push

During task execution, the frontend can receive newly captured AI traffic records in real-time via the WebSocket interface:

```json
{
  "type": "new_record",
  "task_id": "probe-2026-04-01-a3f7",
  "record": {
    "id": "rec-001",
    "provider": "DeepSeek",
    "url": "https://chat.deepseek.com/api/v0/file/upload_file",
    "method": "POST",
    "confidence": 0.95,
    "metadata": { "file_name": "DOCX_TestPage.docx", "file_size": 52060 }
  }
}
```

---

## 7. Deployment Architecture

### 7.1 Standalone Deployment (Recommended for Getting Started)

```
┌──────────────────────────────────┐
│         Docker Compose           │
│  ┌────────────┐ ┌─────────────┐ │
│  │ PRISM Core │ │ mitmproxy   │ │
│  │ (FastAPI)  │ │ (port 8080) │ │
│  │ port 3000  │ └─────────────┘ │
│  └────────────┘                  │
│  ┌────────────┐ ┌─────────────┐ │
│  │ Playwright  │ │ SQLite DB   │ │
│  │ Chromium   │ │ /data/prism │ │
│  └────────────┘ └─────────────┘ │
└──────────────────────────────────┘
```

```yaml
# docker-compose.yml
version: "3.9"
services:
  prism:
    build: .
    ports:
      - "3000:3000"    # Web UI + API
      - "8080:8080"    # MITM Proxy
    volumes:
      - ./data:/data
      - ./scripts:/scripts:ro
      - ./certs:/certs
    environment:
      - PRISM_DB_PATH=/data/prism.db
      - SSLKEYLOGFILE=/data/sslkeys.log
```

### 7.2 Enterprise Deployment

In enterprise environments, PRISM can be deployed as a network tap device for passive traffic collection via port mirroring, or as a forward proxy at the gateway egress point. In this mode, it is recommended to use PostgreSQL for storage, Kubernetes for orchestration, and Syslog/Webhook integration with enterprise SIEM systems.

---

## 8. Security & Compliance

### 8.1 Platform Security

The system processes data containing sensitive authentication credentials and user privacy content. Strict data security measures are required: encryption at rest (AES-256-GCM), access control (RBAC), audit logging (all operations traceable), and automatic expiration (data purged after 30 days by default).

### 8.2 Compliance Recommendations

Before deployment, confirm the following compliance requirements are met: obtain written approval from the Information Security team and Legal department; explicitly declare AI traffic monitoring in the employee Acceptable Use Policy (AUP); for traffic involving personal data, comply with applicable regional privacy regulations (e.g., GDPR, PIPL, CCPA); and limit the MITM certificate deployment scope to enterprise-managed devices only.

---

## 9. Project Milestones

| Phase | Timeline | Deliverables |
|-------|----------|-------------|
| M1 — Foundation | Weeks 1–3 | Core engine, mitmproxy integration, Playwright driver, basic report generation |
| M2 — PCAP Support | Weeks 4–5 | PCAP parsing, TCP reassembly, HTTP protocol parsing |
| M3 — Stream Protocols | Weeks 6–7 | WebSocket / SSE reassembly, streaming packet output |
| M4 — Identification Engine | Weeks 8–9 | Signature database, three-layer matching, metadata extraction |
| M5 — Script Engine | Week 10 | Playwright script sandbox, PrismPage API |
| M6 — Web Console | Weeks 11–12 | React frontend, real-time traffic dashboard, report download |
| M7 — Enterprise Features | Weeks 13–16 | PostgreSQL, RBAC, SIEM integration, tap deployment mode |

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| AI providers change API domains or endpoints | Signature invalidation, missed detections | Hot-reload signature updates + community-driven maintenance |
| HTTPS Certificate Pinning | Unable to MITM decrypt | Fall back to traffic metadata analysis (domain, connection duration, data volume) |
| Oversized PCAP files causing memory overflow | System crash | Streaming parsing + 500MB limit + chunked processing |
| Malicious user scripts | System abuse | Process sandbox + resource quotas + audit logging |
| Privacy compliance complaints | Legal risk | Pre-deployment legal approval + AUP update + data minimization collection |

---

## Appendix A: Output Sample Reference

The DeepSeek file upload packet in the attachment serves as a typical output unit for this system. The system will add structured delimiters, metadata extraction summaries, and sensitive information redaction on top of this base format.

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| Shadow AI | Unauthorized use of AI services not approved by the enterprise |
| MITM | Man-In-The-Middle proxy used for decrypting TLS traffic |
| SSE | Server-Sent Events, an HTTP-based server push streaming protocol |
| SSLKEYLOGFILE | TLS session key log file in NSS Key Log format |
| PCAP | Packet Capture, a network packet capture file format |
| CDP | Chrome DevTools Protocol, the Chrome browser debugging protocol |
| AUP | Acceptable Use Policy, an enterprise employee usage policy |
| RBAC | Role-Based Access Control |
| SIEM | Security Information and Event Management |
| PIPL | Personal Information Protection Law (China) |
