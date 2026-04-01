# Shadow AI Traffic Analyzer — 系统设计文档

> **项目代号**: PRISM  
> **版本**: v1.0  
> **日期**: 2026-04-01  
> **作者**: AI 应用产品部  
> **状态**: 初始设计

---

## 1. 项目背景与目标

### 1.1 问题定义

"Shadow AI" 是指组织内部员工在未经 IT 部门审批或安全审计的情况下，私自使用第三方 AI 服务（如 ChatGPT、DeepSeek、Claude、Gemini、Copilot 等）的行为。这种行为可能导致敏感数据泄露、合规风险以及安全审计盲区。

### 1.2 项目目标

构建一套 **AI 流量特征分析平台（PRISM）**，能够主动探测、被动抓取和深度解析所有与 AI 服务相关的网络流量，生成包含完整 HTTP 请求/响应原始报文的分析报告，为安全团队提供可见性。

### 1.3 核心能力一览

| 能力 | 描述 |
|------|------|
| 主动抓包 | 给定 URL，自动操作网页并捕获所有网络流量 |
| PCAP 分析 | 导入 pcap/pcapng 文件，提取 AI 相关流量 |
| 流式重组 | WebSocket / SSE 长连接报文重组与还原 |
| 脚本交互 | 支持 Playwright/Puppeteer 自定义交互脚本 |
| 元数据识别 | 自动提取 User-Agent、API Version、Model Name 等 |
| MITM 解密 | 内置中间人代理，TLS 解密与证书导出 |
| 报告生成 | 输出结构化原始报文文档（参考附件格式） |

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        PRISM Web Console                        │
│              (React + TypeScript 前端管理界面)                    │
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
│  │  (域名规则 / URI Pattern / Header指纹 / Payload特征)       │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │                                          │
   ┌─────▼──────┐                           ┌──────▼──────┐
   │ Playwright  │                           │  Storage    │
   │ / Puppeteer │                           │ (SQLite /   │
   │  Browser    │                           │  PostgreSQL)│
   └─────────────┘                           └─────────────┘
```

### 2.2 技术选型

| 层级 | 技术 | 理由 |
|------|------|------|
| 后端框架 | Python 3.12 + FastAPI | 异步高性能，生态丰富 |
| 浏览器自动化 | Playwright (Python) | 多浏览器支持、CDP 原生集成 |
| MITM 代理 | mitmproxy 11.x (Python API) | 成熟、可编程、支持 TLS 解密 |
| PCAP 解析 | Scapy + dpkt | 灵活的报文解析与重组 |
| 流协议解析 | 自研模块 (基于 httptools + wsproto) | WebSocket / SSE 专用重组 |
| 存储层 | SQLite (单机) / PostgreSQL (多用户) | 按部署规模选择 |
| 前端 | React 18 + TypeScript + TailwindCSS | 现代 SPA 管理界面 |
| 报告生成 | Jinja2 模板引擎 + python-docx | 多格式输出 (Markdown / DOCX / JSON) |

---

## 3. 模块详细设计

### 3.1 模块一：主动探测与抓包 (Active Probe Module)

#### 3.1.1 功能描述

用户提供一个或多个 URL（可附带认证信息），系统自动启动浏览器实例，通过 MITM Proxy 代理进行页面访问和交互操作，同时捕获所有 HTTP/HTTPS 流量。

#### 3.1.2 工作流程

```
用户输入 URL + 凭据
        │
        ▼
┌──────────────────┐
│ 1. 启动 mitmproxy │──── 生成并注册 CA 证书
│    监听端口       │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 2. 启动 Playwright│──── 配置 proxy 指向 mitmproxy
│    浏览器实例     │──── 安装 CA 证书到浏览器信任链
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 3. 页面导航      │──── 访问目标 URL
│    + 自动登录     │──── 如有凭据则执行登录流程
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 4. 交互执行      │──── 默认: 自动探测 AI 交互入口
│                  │──── 自定义: 执行用户 Playwright 脚本
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 5. 流量捕获与过滤 │──── mitmproxy addon 实时回调
│                  │──── AI 流量签名匹配
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 6. 报文记录      │──── 原始请求/响应完整保存
│    + 报告生成     │──── 按附件格式输出
└──────────────────┘
```

#### 3.1.3 输入参数设计

```python
class ProbeTask(BaseModel):
    """主动探测任务定义"""
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    
    # 目标配置
    urls: list[str]                          # 目标 URL 列表
    credentials: Optional[Credentials]       # 登录凭据
    
    # 交互配置
    interaction_mode: Literal["auto", "script"] = "auto"
    playwright_script: Optional[str] = None  # 用户自定义脚本路径
    
    # 抓包配置
    capture_timeout: int = 120               # 抓包超时 (秒)
    capture_body: bool = True                # 是否保存完整请求体
    max_body_size: int = 10 * 1024 * 1024    # 请求体大小上限 (10MB)
    
    # 输出配置
    output_format: Literal["markdown", "docx", "json"] = "markdown"

class Credentials(BaseModel):
    """认证信息"""
    auth_type: Literal["form", "basic", "bearer", "cookie"]
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    cookies: Optional[dict[str, str]] = None
    login_url: Optional[str] = None          # 登录页面 URL (form 类型)
    username_selector: Optional[str] = None  # 用户名输入框 CSS 选择器
    password_selector: Optional[str] = None  # 密码输入框 CSS 选择器
    submit_selector: Optional[str] = None    # 提交按钮 CSS 选择器
```

#### 3.1.4 自动登录策略

对于需要认证的站点，系统支持四种登录方式：

**Form 表单登录** — 适用于传统 Web 登录页面。系统通过 Playwright 自动定位表单元素填入凭据并提交。用户可通过 CSS 选择器指定具体的输入框和按钮位置，也可以使用自动检测模式（系统在页面中寻找 `input[type=password]` 等常见模式）。

**Basic Auth** — 系统在所有请求的 HTTP Header 中注入 `Authorization: Basic <base64>` 头部。

**Bearer Token** — 系统在所有请求中注入 `Authorization: Bearer <token>` 头部，适用于 API Key 直接访问的场景。

**Cookie 注入** — 系统在浏览器上下文中直接设置指定 Cookie，适用于已获取会话 Cookie 的场景。

---

### 3.2 模块二：PCAP 文件解析 (PCAP Parser Module)

#### 3.2.1 功能描述

用户上传 pcap 或 pcapng 文件，系统从中提取所有 HTTP/HTTPS 流量（对于 HTTPS 需提供对应的 TLS 密钥日志 SSLKEYLOGFILE），识别 AI 相关请求，并生成与主动抓包一致格式的报告。

#### 3.2.2 处理流程

```
PCAP 文件上传
      │
      ▼
┌─────────────────────┐
│ 1. 格式校验          │──── 验证 pcap/pcapng 有效性
│    大小限制: < 500MB  │──── 检查文件完整性
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 2. TCP 流重组        │──── 基于 Scapy/dpkt 重组 TCP 流
│                     │──── 处理乱序、重传、分片
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 3. TLS 解密 (可选)   │──── 使用 SSLKEYLOGFILE 解密
│                     │──── 或标记为 [ENCRYPTED]
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 4. HTTP 协议解析     │──── 解析 HTTP/1.1、HTTP/2 帧
│                     │──── 提取请求行、头部、Body
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 5. AI 流量识别       │──── 匹配签名数据库
│                     │──── 评分排序
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 6. 报告生成          │──── 按原始报文格式输出
│                     │──── 多类型报文用分隔符隔开
└─────────────────────┘
```

#### 3.2.3 核心解析引擎

```python
class PcapAnalyzer:
    """PCAP 文件分析器"""
    
    def __init__(self, filepath: str, sslkeylog: Optional[str] = None):
        self.filepath = filepath
        self.sslkeylog = sslkeylog
        self.sessions: list[HTTPSession] = []
    
    def parse(self) -> list[AITrafficRecord]:
        """主解析入口"""
        raw_packets = self._read_packets()           # 读取原始包
        tcp_streams = self._reassemble_tcp(raw_packets)  # TCP 流重组
        
        if self.sslkeylog:
            tcp_streams = self._decrypt_tls(tcp_streams)  # TLS 解密
        
        http_sessions = self._parse_http(tcp_streams)     # HTTP 解析
        ai_records = self._identify_ai_traffic(http_sessions)  # AI 识别
        
        return ai_records
    
    def _reassemble_tcp(self, packets) -> list[TCPStream]:
        """TCP 流重组 — 处理乱序、重传、FIN/RST"""
        streams = {}
        for pkt in packets:
            if not pkt.haslayer(TCP):
                continue
            flow_key = self._get_flow_key(pkt)
            if flow_key not in streams:
                streams[flow_key] = TCPStream(flow_key)
            streams[flow_key].add_packet(pkt)
        
        for stream in streams.values():
            stream.reassemble()  # 按序号重组
        
        return list(streams.values())
```

#### 3.2.4 HTTP/2 支持

PCAP 中的 HTTP/2 流量需要特殊处理。系统使用 `h2` 库进行 HTTP/2 帧解码，将多路复用的流还原为独立的请求-响应对。对于 HPACK 压缩的头部，系统维护独立的解码上下文进行还原。

---

### 3.3 模块三：流式协议重组 (Stream Reassembly Module)

#### 3.3.1 设计目标

现代 AI 服务普遍使用 WebSocket 或 Server-Sent Events (SSE) 进行流式响应。本模块负责将这些长连接中的分片消息重组为完整的逻辑单元。

#### 3.3.2 WebSocket 重组

```python
class WebSocketReassembler:
    """WebSocket 消息重组器"""
    
    def __init__(self):
        self.fragments: dict[str, list[WSFrame]] = {}
        self.messages: list[WSMessage] = []
    
    def feed_frame(self, conn_id: str, frame: WSFrame):
        """逐帧输入"""
        if conn_id not in self.fragments:
            self.fragments[conn_id] = []
        
        self.fragments[conn_id].append(frame)
        
        if frame.fin:  # FIN 位表示消息结束
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
        """获取完整对话序列"""
        return [m for m in self.messages if m.conn_id == conn_id]
```

#### 3.3.3 SSE 重组

SSE（Server-Sent Events）是 AI 流式输出最常见的协议。系统将原始的 `text/event-stream` 数据流按 `\n\n` 分割为独立事件，解析 `event`、`data`、`id`、`retry` 字段，并将同一请求的所有 SSE 事件聚合为一条完整记录。

```python
class SSEReassembler:
    """SSE 事件流重组器"""
    
    def parse_stream(self, raw_body: bytes) -> list[SSEEvent]:
        """解析 SSE 流"""
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
        """将流式 token 聚合为完整回复文本"""
        full_text = ""
        for event in events:
            try:
                payload = json.loads(event.data)
                # 兼容 OpenAI / DeepSeek / Anthropic 等格式
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

#### 3.3.4 输出格式

对于流式报文，在输出报告中采用以下结构：

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

... 更多帧 ...

========== [SSE Session] ==========
Request:
  POST https://api.deepseek.com/v1/chat/completions HTTP/1.1
  ...headers...
  {"model": "deepseek-chat", "stream": true, ...}

Aggregated Response (32 events, 1.8s):
  "这是完整的聚合后回复内容..."

Raw Events:
  data: {"choices":[{"delta":{"content":"这"}}]}
  data: {"choices":[{"delta":{"content":"是"}}]}
  ...
```

---

### 3.4 模块四：自定义交互脚本 (Script Engine)

#### 3.4.1 设计思路

不同 AI 服务的交互方式各异（有的需要点击特定按钮、有的需要输入 prompt 后等待、有的是 API 直接调用），因此系统提供两种模式：**自动探测模式**和**脚本自定义模式**。

#### 3.4.2 自动探测模式

系统内置一组启发式规则，在页面加载后自动尝试识别 AI 对话界面并执行交互：

1. 检测页面中的文本输入框（textarea / contenteditable），优先匹配 `placeholder` 包含 "Ask"、"Message"、"Prompt"、"Chat" 等关键词的元素。
2. 在输入框中填入预设的探测文本（如 "Hello, this is a test message"），触发 AI 请求。
3. 等待响应完成（监测 SSE 流关闭或 DOM 变化稳定）。
4. 记录完整的请求-响应流量。

#### 3.4.3 脚本自定义模式

用户可编写标准的 Playwright Python 脚本来定义复杂的交互逻辑。系统提供扩展 API：

```python
# 用户脚本示例: deepseek_probe.py
from prism.scripting import PrismPage

async def run(page: PrismPage):
    """
    PrismPage 继承自 playwright.async_api.Page,
    额外提供 prism 特有的辅助方法。
    """
    # 导航到 DeepSeek
    await page.goto("https://chat.deepseek.com")
    
    # 等待聊天输入框
    chat_input = await page.wait_for_selector("#chat-input")
    
    # 发送测试消息
    await chat_input.fill("请用 Python 写一个快速排序算法")
    await page.keyboard.press("Enter")
    
    # 等待回复完成 (prism 扩展方法)
    await page.prism.wait_for_ai_response(timeout=60000)
    
    # 上传文件测试
    file_input = await page.query_selector("input[type=file]")
    if file_input:
        await file_input.set_input_files("./test_document.docx")
        await page.prism.wait_for_upload_complete()
    
    # 标记当前阶段
    page.prism.mark_phase("upload_test_complete")
```

#### 3.4.4 脚本沙箱与安全

用户脚本在隔离的进程中运行，受以下约束：执行超时限制（默认 5 分钟）、禁止文件系统写操作（只读访问指定目录）、禁止网络出站（除通过 MITM Proxy 外）、内存使用上限（默认 512MB）。

---

### 3.5 模块五：AI 流量识别引擎 (Identification Engine)

#### 3.5.1 多层识别策略

识别引擎采用三层匹配机制，每层独立评分，最终加权汇总：

**第一层：域名/Host 匹配（权重 40%）**

```yaml
# ai_domains.yaml — AI 服务域名签名库
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
  
  # ... 更多厂商 (Mistral, Cohere, Perplexity, 百度文心, 通义千问, 豆包等)
```

**第二层：URI 路径 + Header 特征匹配（权重 35%）**

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

**第三层：Payload 语义分析（权重 25%）**

系统对请求体进行 JSON 结构分析，检测是否包含 AI 调用的典型字段组合（如 `model` + `messages` + `temperature`、`prompt` + `max_tokens` 等），并尝试提取具体的模型名称。

#### 3.5.2 元数据自动提取

```python
class MetadataExtractor:
    """AI 流量元数据提取器"""
    
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
        """从请求或响应中提取模型名称"""
        # 1. 从请求体中提取
        if req.json_body and "model" in req.json_body:
            return req.json_body["model"]
        
        # 2. 从响应体中提取
        if resp.json_body and "model" in resp.json_body:
            return resp.json_body["model"]
        
        # 3. 从 URL 路径中提取 (如 /models/gpt-4/completions)
        model_match = re.search(r"/models?/([a-zA-Z0-9\-_.]+)", req.url)
        if model_match:
            return model_match.group(1)
        
        # 4. 从自定义头部提取
        for header in ["x-model", "x-model-id", "x-thinking-enabled"]:
            if header in req.headers:
                return req.headers[header]
        
        return None
    
    def _extract_custom_headers(self, req) -> dict:
        """提取 AI 服务特有的自定义头部"""
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

### 3.6 模块六：MITM Proxy 模块 (Decryption Layer)

#### 3.6.1 架构设计

MITM Proxy 模块基于 `mitmproxy` 的 Python API 构建，作为透明/正向代理运行，负责 TLS 解密和流量拦截。

```python
class PrismAddon:
    """mitmproxy 插件 — PRISM 核心数据采集层"""
    
    def __init__(self, task_id: str, signature_db: SignatureDB):
        self.task_id = task_id
        self.sig_db = signature_db
        self.records: list[CapturedFlow] = []
    
    def request(self, flow: http.HTTPFlow):
        """请求拦截回调"""
        flow.metadata["prism_task_id"] = self.task_id
        flow.metadata["capture_time"] = datetime.utcnow().isoformat()
    
    def response(self, flow: http.HTTPFlow):
        """响应拦截回调 — 核心采集点"""
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
        """WebSocket 消息拦截"""
        msg = flow.websocket.messages[-1]
        # 记录每一帧用于后续重组
        self.ws_reassembler.feed_frame(
            conn_id=flow.id,
            frame=WSFrame(
                payload=msg.content,
                opcode=msg.type,
                direction="client" if msg.from_client else "server",
                timestamp=datetime.utcnow(),
                fin=True,  # mitmproxy 已完成帧重组
            )
        )
    
    def _dump_raw_request(self, flow) -> str:
        """生成原始 HTTP 请求报文（与附件格式一致）"""
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

#### 3.6.2 证书管理与导出

```python
class CertManager:
    """CA 证书管理"""
    
    CERT_DIR = Path.home() / ".prism" / "certs"
    
    def generate_ca(self) -> tuple[Path, Path]:
        """生成 PRISM 根 CA 证书"""
        # 使用 mitmproxy 内置的证书生成能力
        # 输出 PEM 格式的 CA 证书和私钥
        ca_cert = self.CERT_DIR / "prism-ca-cert.pem"
        ca_key = self.CERT_DIR / "prism-ca-key.pem"
        return ca_cert, ca_key
    
    def export_for_browser(self, format: str = "pem") -> Path:
        """导出浏览器可安装的 CA 证书"""
        # 支持 PEM (Linux/macOS), DER (Windows), P12 (通用)
        ...
    
    def export_for_system(self, os_type: str) -> str:
        """返回系统级证书安装命令"""
        commands = {
            "macos": "sudo security add-trusted-cert -d -r trustRoot "
                     "-k /Library/Keychains/System.keychain {cert}",
            "ubuntu": "sudo cp {cert} /usr/local/share/ca-certificates/ "
                      "&& sudo update-ca-certificates",
            "windows": "certutil -addstore -f ROOT {cert}",
        }
        return commands.get(os_type, "")
```

#### 3.6.3 TLS 密钥日志

系统支持通过设置 `SSLKEYLOGFILE` 环境变量导出 TLS 会话密钥，供 Wireshark 等外部工具进行离线解密验证。

---

### 3.7 模块七：报告生成 (Report Generator)

#### 3.7.1 输出格式定义

系统参照附件样本格式，生成包含完整 HTTP 原始报文的分析报告。当存在多种类型的 AI 流量时，使用明确的分隔符区隔：

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
...完整请求头和请求体...

── SSE Response Stream (42 events, 3.2s) ──
data: {"choices":[{"delta":{"content":"你"}}]}
data: {"choices":[{"delta":{"content":"好"}}]}
...
data: [DONE]

── Aggregated Response ──
你好！有什么可以帮助你的吗？

── Extracted Metadata ──────────────────────────────────────────
  Provider     : DeepSeek
  Model        : deepseek-chat
  Streaming    : Yes (SSE)
  ...
```

#### 3.7.2 敏感信息处理

报告生成时默认对以下字段进行脱敏：

- `Authorization` 头部中的 Bearer Token → `[REDACTED]`
- `Cookie` 头部中的会话信息 → `[REDACTED]`
- 二进制请求体 → `[BINARY DATA: {size} bytes, SHA256: {hash}]`
- API Key → 仅保留前 8 位 + `...`

用户可通过 `--no-redact` 参数关闭脱敏，用于内部安全分析。

---

## 4. AI 流量签名数据库

### 4.1 覆盖范围

系统内置的签名库覆盖以下 AI 服务提供商（持续更新）：

| 分类 | 服务商 | 关键域名 / 特征 |
|------|--------|-----------------|
| 通用大模型 | OpenAI | api.openai.com, chatgpt.com |
| 通用大模型 | Anthropic | api.anthropic.com, claude.ai |
| 通用大模型 | Google | generativelanguage.googleapis.com, gemini.google.com |
| 通用大模型 | DeepSeek | api.deepseek.com, chat.deepseek.com |
| 通用大模型 | Mistral | api.mistral.ai |
| 代码助手 | GitHub Copilot | copilot-proxy.githubusercontent.com |
| 代码助手 | Cursor | api2.cursor.sh |
| 企业平台 | Azure OpenAI | *.openai.azure.com |
| 企业平台 | AWS Bedrock | bedrock-runtime.*.amazonaws.com |
| 企业平台 | GCP Vertex AI | *.aiplatform.googleapis.com |
| 图像生成 | Midjourney | *.midjourney.com |
| 图像生成 | Stability AI | api.stability.ai |
| 国内厂商 | 百度文心一言 | aip.baidubce.com, yiyan.baidu.com |
| 国内厂商 | 阿里通义千问 | dashscope.aliyuncs.com |
| 国内厂商 | 字节豆包 | *.volcengine.com |
| 国内厂商 | 智谱 AI | open.bigmodel.cn |

### 4.2 签名更新机制

签名数据库以 YAML 文件形式独立维护，支持热加载。更新来源包括社区贡献（GitHub PR）、自动爬虫发现（定期扫描 AI 服务 API 文档变更）以及用户自定义规则补充。

---

## 5. 数据模型

### 5.1 核心实体

```python
class CaptureTask(BaseModel):
    """捕获任务"""
    id: str
    type: Literal["active_probe", "pcap_import"]
    status: Literal["pending", "running", "completed", "failed"]
    config: ProbeTask | PcapImportConfig
    created_at: datetime
    completed_at: Optional[datetime]
    record_count: int = 0
    error_message: Optional[str] = None

class AITrafficRecord(BaseModel):
    """AI 流量记录"""
    id: str
    task_id: str
    sequence: int                              # 同一任务内的序号
    provider: str                              # AI 服务提供商
    service_type: str                          # chat / completion / embedding / upload / image
    confidence: float                          # 识别置信度 0~1
    
    # 原始报文
    raw_request: str                           # 原始 HTTP 请求文本
    raw_response: Optional[str]                # 原始 HTTP 响应文本
    
    # 结构化数据
    method: str
    url: str
    request_headers: dict[str, str]
    request_body: Optional[str]
    response_status: Optional[int]
    response_headers: Optional[dict[str, str]]
    response_body: Optional[str]
    
    # 元数据
    metadata: AIMetadata
    
    # 流式数据
    stream_type: Optional[Literal["sse", "websocket"]] = None
    stream_events: Optional[list[dict]] = None
    aggregated_response: Optional[str] = None
    
    timestamp: datetime

class AIMetadata(BaseModel):
    """AI 流量元数据"""
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

## 6. API 接口设计

### 6.1 核心 REST API

```
POST   /api/v1/tasks/probe          — 创建主动探测任务
POST   /api/v1/tasks/pcap           — 上传 PCAP 并创建分析任务
GET    /api/v1/tasks/{task_id}       — 查询任务状态
GET    /api/v1/tasks/{task_id}/records  — 获取 AI 流量记录列表
GET    /api/v1/records/{record_id}   — 获取单条记录详情
GET    /api/v1/tasks/{task_id}/report  — 下载报告 (format=md|docx|json)
POST   /api/v1/scripts/validate      — 验证 Playwright 脚本语法
GET    /api/v1/certs/ca.pem          — 下载 CA 证书
GET    /api/v1/signatures            — 查看当前签名库
PUT    /api/v1/signatures            — 更新签名规则
WS     /api/v1/tasks/{task_id}/live  — 实时流量推送 (WebSocket)
```

### 6.2 实时流量推送

任务执行过程中，前端可通过 WebSocket 接口实时接收新捕获的 AI 流量记录：

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

## 7. 部署架构

### 7.1 单机部署（推荐入门）

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

### 7.2 企业部署

企业环境中可将 PRISM 部署为网络旁路设备，通过端口镜像被动采集流量，或作为正向代理部署在网关出口处。此模式下推荐使用 PostgreSQL 存储、Kubernetes 编排、以及与企业 SIEM 系统的 Syslog/Webhook 集成。

---

## 8. 安全与合规

### 8.1 自身安全

系统处理的数据包含敏感认证信息和用户隐私内容，需严格保障数据安全：存储加密（AES-256-GCM）、访问控制（RBAC）、审计日志（所有操作可追溯）、自动过期（数据默认 30 天后清除）。

### 8.2 合规建议

部署前需确认以下合规要求已满足：获得信息安全团队与法务部门的书面审批；在员工可接受使用政策 (AUP) 中明确声明 AI 流量监控；对于涉及个人数据的流量，遵循所在地区的隐私保护法规（如 GDPR、个人信息保护法等）；MITM 证书的部署范围限定在企业管控设备内。

---

## 9. 项目里程碑

| 阶段 | 周期 | 交付内容 |
|------|------|----------|
| M1 — 基础框架 | 第 1–3 周 | 核心引擎、mitmproxy 集成、Playwright 驱动、基础报告生成 |
| M2 — PCAP 支持 | 第 4–5 周 | PCAP 解析、TCP 重组、HTTP 协议解析 |
| M3 — 流式协议 | 第 6–7 周 | WebSocket / SSE 重组、流式报文输出 |
| M4 — 识别引擎 | 第 8–9 周 | 签名数据库、三层匹配、元数据提取 |
| M5 — 脚本引擎 | 第 10 周 | Playwright 脚本沙箱、PrismPage API |
| M6 — Web 管理台 | 第 11–12 周 | React 前端、实时流量面板、报告下载 |
| M7 — 企业功能 | 第 13–16 周 | PostgreSQL、RBAC、SIEM 集成、旁路部署模式 |

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| AI 服务商更换 API 域名或接口 | 签名失效，漏报 | 签名热更新 + 社区协作维护 |
| HTTPS 证书固定 (Certificate Pinning) | 无法 MITM 解密 | 降级为流量元数据分析（域名、连接时长、数据量） |
| PCAP 文件过大导致内存溢出 | 系统崩溃 | 流式解析 + 500MB 上限 + 分块处理 |
| 用户脚本恶意行为 | 系统被滥用 | 进程沙箱 + 资源配额 + 审计日志 |
| 隐私合规投诉 | 法律风险 | 部署前法务审批 + AUP 更新 + 数据最小化采集 |

---

## 附录 A：输出样本参考

附件中的 DeepSeek 文件上传报文即为本系统的典型输出单元。系统会在此基础上增加结构化分隔、元数据提取摘要和敏感信息脱敏处理。

## 附录 B：术语表

| 术语 | 定义 |
|------|------|
| Shadow AI | 未经企业审批的 AI 服务使用行为 |
| MITM | Man-In-The-Middle，中间人代理，用于解密 TLS 流量 |
| SSE | Server-Sent Events，服务端推送的 HTTP 流式协议 |
| SSLKEYLOGFILE | NSS Key Log 格式的 TLS 密钥日志文件 |
| PCAP | Packet Capture，网络抓包文件格式 |
| CDP | Chrome DevTools Protocol，Chrome 浏览器调试协议 |
