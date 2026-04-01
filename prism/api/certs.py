"""Certificate management API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from prism.capture.cert_manager import CertManager

router = APIRouter(prefix="/api/v1/certs", tags=["certs"])
cert_manager = CertManager()


@router.get("/ca.pem")
async def download_ca_pem():
    """Download the PRISM root CA certificate in PEM format."""
    try:
        pem_bytes = cert_manager.ca_cert_pem()
    except FileNotFoundError:
        raise HTTPException(
            404,
            "CA certificate not yet generated. Start a probe task to initialize mitmproxy.",
        )
    return Response(
        content=pem_bytes,
        media_type="application/x-pem-file",
        headers={"Content-Disposition": 'attachment; filename="prism-ca.pem"'},
    )


@router.get("/install-command")
async def get_install_command():
    """Return the OS-specific command to trust the PRISM CA."""
    return {"command": cert_manager.install_command()}
