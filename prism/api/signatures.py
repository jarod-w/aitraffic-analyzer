"""Signature database management API."""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from prism.identification.engine import get_signature_db
from prism.signatures import __file__ as _sig_pkg

SIGNATURES_DIR = Path(_sig_pkg).parent

router = APIRouter(prefix="/api/v1/signatures", tags=["signatures"])


@router.get("")
async def get_signatures():
    """Return the current AI traffic signature database."""
    db = get_signature_db()
    domains_path = SIGNATURES_DIR / "ai_domains.yaml"
    patterns_path = SIGNATURES_DIR / "ai_patterns.yaml"

    with open(domains_path) as f:
        domains = yaml.safe_load(f)
    with open(patterns_path) as f:
        patterns = yaml.safe_load(f)

    return {
        "domains": domains,
        "patterns": patterns,
    }


@router.put("")
async def update_signatures(body: dict):
    """
    Hot-reload signatures.
    Body: {"domains": {...}, "patterns": {...}} — partial updates supported.
    """
    db = get_signature_db()

    if "domains" in body:
        domains_path = SIGNATURES_DIR / "ai_domains.yaml"
        with open(domains_path, "w") as f:
            yaml.dump(body["domains"], f, allow_unicode=True)

    if "patterns" in body:
        patterns_path = SIGNATURES_DIR / "ai_patterns.yaml"
        with open(patterns_path, "w") as f:
            yaml.dump(body["patterns"], f, allow_unicode=True)

    db.reload()
    return {"status": "reloaded"}
