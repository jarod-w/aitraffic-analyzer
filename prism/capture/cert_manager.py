"""CA certificate management for the MITM proxy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from prism.config import settings


class CertManager:
    """
    Manages the PRISM root CA certificate used by mitmproxy for TLS interception.

    mitmproxy auto-generates its CA on first run under ~/.mitmproxy/.
    This manager exposes paths and export helpers.
    """

    @property
    def mitmproxy_ca_dir(self) -> Path:
        return Path.home() / ".mitmproxy"

    @property
    def ca_cert_path(self) -> Path:
        return self.mitmproxy_ca_dir / "mitmproxy-ca-cert.pem"

    @property
    def ca_key_path(self) -> Path:
        return self.mitmproxy_ca_dir / "mitmproxy-ca.pem"

    @property
    def ca_cert_der_path(self) -> Path:
        return self.mitmproxy_ca_dir / "mitmproxy-ca-cert.cer"

    @property
    def ca_cert_p12_path(self) -> Path:
        return self.mitmproxy_ca_dir / "mitmproxy-ca-cert.p12"

    def ensure_ca(self):
        """
        Ensure the mitmproxy CA exists.
        mitmproxy creates it automatically on first start.
        We trigger a dry-run if needed.
        """
        if not self.ca_cert_path.exists():
            self._generate_ca()

    def _generate_ca(self):
        """Run a short mitmproxy invocation to generate the CA."""
        import mitmproxy.certs as mcerts
        from mitmproxy.options import Options
        from mitmproxy.proxy.server import DummyServer

        opts = Options()
        # Just instantiate to trigger cert generation
        try:
            from mitmproxy.master import Master
            master = Master(opts)
            # CA is generated as side-effect of option loading
        except Exception:
            pass  # If it fails the CA file probably already exists

    def ca_cert_pem(self) -> bytes:
        """Return raw PEM bytes of the CA certificate."""
        self.ensure_ca()
        return self.ca_cert_path.read_bytes()

    def export_path(self, fmt: str = "pem") -> Path:
        """Return path to the CA cert in the requested format."""
        self.ensure_ca()
        if fmt == "pem":
            return self.ca_cert_path
        if fmt == "cer":
            return self.ca_cert_der_path
        if fmt == "p12":
            return self.ca_cert_p12_path
        return self.ca_cert_path

    def install_command(self) -> str:
        """Return the OS-specific command to trust the PRISM CA."""
        cert = str(self.ca_cert_path)
        platform = sys.platform
        if platform == "darwin":
            return (
                f"sudo security add-trusted-cert -d -r trustRoot "
                f"-k /Library/Keychains/System.keychain {cert}"
            )
        if platform.startswith("linux"):
            return (
                f"sudo cp {cert} /usr/local/share/ca-certificates/prism-ca.crt "
                f"&& sudo update-ca-certificates"
            )
        if platform == "win32":
            return f'certutil -addstore -f ROOT "{cert}"'
        return f"# Install {cert} as a trusted root CA for your OS"
