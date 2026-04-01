"""PCAP file analyzer — TCP reassembly, HTTP/1.x parsing, AI traffic identification."""

from __future__ import annotations

import hashlib
import io
import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

from prism.config import settings
from prism.identification.engine import SignatureDB, get_signature_db
from prism.identification.metadata import MetadataExtractor
from prism.models import AITrafficRecord, AIMetadata
from prism.stream.sse import SSEReassembler

logger = logging.getLogger(__name__)

# TCP flags
TCP_FIN = 0x01
TCP_SYN = 0x02
TCP_RST = 0x04
TCP_ACK = 0x10


class TCPStream:
    """Represents a reassembled TCP byte stream for one direction."""

    def __init__(self):
        self._segments: list[tuple[int, bytes]] = []  # (seq, data)
        self._base_seq: Optional[int] = None
        self.data: bytes = b""

    def add_segment(self, seq: int, data: bytes):
        if not data:
            return
        if self._base_seq is None:
            self._base_seq = seq
        self._segments.append((seq, data))

    def reassemble(self):
        if not self._segments:
            return
        self._segments.sort(key=lambda x: x[0])
        buf = bytearray()
        expected = self._segments[0][0]
        for seq, data in self._segments:
            # Skip retransmissions
            if seq < expected:
                overlap = expected - seq
                if overlap < len(data):
                    data = data[overlap:]
                    seq = expected
                else:
                    continue
            # Fill gap with zeros (shouldn't happen with complete captures)
            if seq > expected:
                buf.extend(b"\x00" * (seq - expected))
            buf.extend(data)
            expected = seq + len(data)
        self.data = bytes(buf)


class TCPSessionKey:
    def __init__(self, src_ip, src_port, dst_ip, dst_port):
        # Normalize so client→server and server→client have the same base key
        self.forward = (src_ip, src_port, dst_ip, dst_port)
        self.reverse = (dst_ip, dst_port, src_ip, src_port)

    def __hash__(self):
        return hash(tuple(sorted([self.forward, self.reverse])))

    def __eq__(self, other):
        return hash(self) == hash(other)


class HTTPSession:
    """A parsed HTTP request + response pair."""

    def __init__(
        self,
        method: str,
        url: str,
        http_version: str,
        req_headers: dict[str, str],
        req_body: Optional[bytes],
        resp_status: Optional[int],
        resp_reason: str,
        resp_headers: dict[str, str],
        resp_body: Optional[bytes],
        timestamp: datetime,
    ):
        self.method = method
        self.url = url
        self.http_version = http_version
        self.req_headers = req_headers
        self.req_body = req_body
        self.resp_status = resp_status
        self.resp_reason = resp_reason
        self.resp_headers = resp_headers
        self.resp_body = resp_body
        self.timestamp = timestamp


class PcapAnalyzer:
    """
    Analyzes a PCAP/PCAPNG file and extracts AI-related HTTP sessions.

    Args:
        filepath: Path to the PCAP file.
        task_id: Task ID to attach to generated records.
        sslkeylog: Optional path to an SSLKEYLOGFILE for TLS decryption.
    """

    def __init__(self, filepath: str, task_id: str, sslkeylog: Optional[str] = None):
        self.filepath = filepath
        self.task_id = task_id
        self.sslkeylog = sslkeylog
        self.sig_db = get_signature_db()
        self.metadata_extractor = MetadataExtractor()
        self.sse_reassembler = SSEReassembler()

    def parse(self) -> list[AITrafficRecord]:
        """Main entry point — returns AI traffic records."""
        try:
            import scapy.all as scapy
        except ImportError:
            raise RuntimeError("scapy is required for PCAP analysis: pip install scapy")

        logger.info("Reading PCAP: %s", self.filepath)
        packets = scapy.rdpcap(self.filepath)
        tcp_streams = self._reassemble_tcp(packets)
        http_sessions = self._parse_http_sessions(tcp_streams)
        return self._identify_ai_traffic(http_sessions)

    # ------------------------------------------------------------------
    # TCP reassembly
    # ------------------------------------------------------------------

    def _reassemble_tcp(self, packets) -> list[tuple[bytes, bytes, str, str, int, int, datetime]]:
        """
        Reassemble TCP streams.
        Returns list of (client_data, server_data, src_ip, dst_ip, src_port, dst_port, timestamp).
        """
        try:
            from scapy.layers.inet import IP, TCP
        except ImportError:
            from scapy.all import IP, TCP

        # flow_key -> {client: TCPStream, server: TCPStream, timestamp: datetime}
        flows: dict[tuple, dict] = defaultdict(lambda: {
            "client": TCPStream(),
            "server": TCPStream(),
            "timestamp": datetime.utcnow(),
            "src_ip": "",
            "dst_ip": "",
            "src_port": 0,
            "dst_port": 0,
        })

        for pkt in packets:
            if not (pkt.haslayer(IP) and pkt.haslayer(TCP)):
                continue

            ip = pkt[IP]
            tcp = pkt[TCP]

            if not tcp.payload:
                continue

            src = (ip.src, tcp.sport)
            dst = (ip.dst, tcp.dport)
            # Use canonical key (smaller tuple first)
            if src < dst:
                key = (src, dst)
                direction = "client"
            else:
                key = (dst, src)
                direction = "server"

            flow = flows[key]
            if not flow["src_ip"]:
                flow["src_ip"] = ip.src
                flow["dst_ip"] = ip.dst
                flow["src_port"] = tcp.sport
                flow["dst_port"] = tcp.dport
                if hasattr(pkt, "time"):
                    flow["timestamp"] = datetime.utcfromtimestamp(float(pkt.time))

            payload = bytes(tcp.payload)
            flow[direction].add_segment(tcp.seq, payload)

        result = []
        for key, flow in flows.items():
            flow["client"].reassemble()
            flow["server"].reassemble()
            if flow["client"].data or flow["server"].data:
                result.append((
                    flow["client"].data,
                    flow["server"].data,
                    flow["src_ip"],
                    flow["dst_ip"],
                    flow["src_port"],
                    flow["dst_port"],
                    flow["timestamp"],
                ))
        return result

    # ------------------------------------------------------------------
    # HTTP parsing
    # ------------------------------------------------------------------

    def _parse_http_sessions(
        self, streams: list[tuple]
    ) -> list[HTTPSession]:
        sessions = []
        for client_data, server_data, src_ip, dst_ip, src_port, dst_port, ts in streams:
            # Only look at likely HTTP/HTTPS ports
            if dst_port not in (80, 443, 8080, 8443, 3000, 8000, 8001) and src_port not in (80, 443):
                continue

            parsed = self._parse_http_pair(client_data, server_data, dst_ip, dst_port, ts)
            sessions.extend(parsed)
        return sessions

    def _parse_http_pair(
        self, req_data: bytes, resp_data: bytes, host: str, port: int, ts: datetime
    ) -> list[HTTPSession]:
        """Parse one or more HTTP request/response pairs from raw TCP data."""
        sessions = []
        try:
            import dpkt
        except ImportError:
            raise RuntimeError("dpkt is required: pip install dpkt")

        if not req_data:
            return sessions

        try:
            req_io = io.BytesIO(req_data)
            resp_io = io.BytesIO(resp_data) if resp_data else None

            while True:
                req_start = req_io.tell()
                try:
                    req = dpkt.http.Request(req_io)
                except (dpkt.UnpackError, dpkt.NeedData, StopIteration, Exception):
                    break

                # Build URL
                req_headers = {k.decode(): v.decode() for k, v in req.headers.items()}
                host_hdr = req_headers.get("host", host)
                scheme = "https" if port in (443, 8443) else "http"
                url = f"{scheme}://{host_hdr}{req.uri.decode()}"
                method = req.method.decode()

                # Parse response
                resp_status = None
                resp_reason = ""
                resp_headers: dict[str, str] = {}
                resp_body = b""

                if resp_io:
                    try:
                        resp = dpkt.http.Response(resp_io)
                        resp_status = resp.status
                        resp_reason = resp.reason.decode() if isinstance(resp.reason, bytes) else resp.reason
                        resp_headers = {k.decode(): v.decode() for k, v in resp.headers.items()}
                        resp_body = resp.body
                    except Exception:
                        pass

                session = HTTPSession(
                    method=method,
                    url=url,
                    http_version=f"HTTP/{req.version}",
                    req_headers=req_headers,
                    req_body=req.body if req.body else None,
                    resp_status=resp_status,
                    resp_reason=resp_reason,
                    resp_headers=resp_headers,
                    resp_body=resp_body if resp_body else None,
                    timestamp=ts,
                )
                sessions.append(session)

        except Exception as e:
            logger.debug("HTTP parse error: %s", e)

        return sessions

    # ------------------------------------------------------------------
    # AI identification
    # ------------------------------------------------------------------

    def _identify_ai_traffic(self, sessions: list[HTTPSession]) -> list[AITrafficRecord]:
        records = []
        seq = 0

        for session in sessions:
            parsed = urlparse(session.url)
            host = parsed.netloc.split(":")[0]
            path = parsed.path

            match = self.sig_db.identify(
                host=host,
                path=path,
                headers=session.req_headers,
                body=session.req_body,
            )
            if not match.is_ai:
                continue

            seq += 1
            raw_req = self._format_raw_request(session)
            raw_resp = self._format_raw_response(session)

            # SSE
            stream_type = None
            stream_events = None
            aggregated = None
            if session.resp_body and "text/event-stream" in session.resp_headers.get("content-type", ""):
                stream_type = "sse"
                events = self.sse_reassembler.parse_stream(session.resp_body)
                stream_events = self.sse_reassembler.to_dict_list(events)
                aggregated = self.sse_reassembler.aggregate_completion(events)

            meta = self.metadata_extractor.extract(
                provider=self.sig_db.provider_display_name(match.provider),
                method=session.method,
                url=session.url,
                request_headers=session.req_headers,
                request_body=session.req_body,
                response_headers=session.resp_headers,
                response_body=session.resp_body,
                timestamp=session.timestamp,
            )

            record = AITrafficRecord(
                id=f"rec-{uuid4().hex[:12]}",
                task_id=self.task_id,
                sequence=seq,
                provider=self.sig_db.provider_display_name(match.provider),
                service_type=match.service_type,
                confidence=match.confidence,
                method=session.method,
                url=session.url,
                request_headers=session.req_headers,
                request_body=self._body_str(session.req_body, session.req_headers),
                response_status=session.resp_status,
                response_headers=session.resp_headers,
                response_body=self._body_str(session.resp_body, session.resp_headers),
                raw_request=raw_req,
                raw_response=raw_resp,
                metadata=meta,
                stream_type=stream_type,
                stream_events=stream_events,
                aggregated_response=aggregated,
                timestamp=session.timestamp,
            )
            records.append(record)

        return records

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_raw_request(self, s: HTTPSession) -> str:
        lines = [f"{s.method} {s.url} {s.http_version}"]
        for k, v in s.req_headers.items():
            if k.lower() in ("authorization", "cookie") and settings.redact_secrets:
                lines.append(f"{k}: [REDACTED]")
            else:
                lines.append(f"{k}: {v}")
        lines.append("")
        if s.req_body:
            lines.append(self._body_str(s.req_body, s.req_headers))
        return "\n".join(lines)

    def _format_raw_response(self, s: HTTPSession) -> str:
        if s.resp_status is None:
            return ""
        lines = [f"{s.http_version} {s.resp_status} {s.resp_reason}"]
        for k, v in s.resp_headers.items():
            lines.append(f"{k}: {v}")
        lines.append("")
        if s.resp_body:
            lines.append(self._body_str(s.resp_body, s.resp_headers))
        return "\n".join(lines)

    def _body_str(self, body: Optional[bytes], headers: dict) -> str:
        if not body:
            return ""
        ct = headers.get("content-type", "")
        if "application/octet-stream" in ct or "multipart/form-data" in ct:
            sha = hashlib.sha256(body).hexdigest()
            return f"[BINARY DATA: {len(body)} bytes, SHA256: {sha}]"
        try:
            return body.decode("utf-8", errors="replace")
        except Exception:
            sha = hashlib.sha256(body).hexdigest()
            return f"[BINARY DATA: {len(body)} bytes, SHA256: {sha}]"
