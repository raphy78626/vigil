"""Auth API: /api/auth/*."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from testai.auth import list_saved as list_auth, save_auth_data, get_auth_for_url, _domain_from_url

router = APIRouter()


@router.get("/api/auth")
async def list_auth_states():
    """List all saved auth states (one per domain)."""
    return list_auth()


@router.get("/api/auth/check")
async def check_auth(url: str = ""):
    """Check if auth.json exists for a given URL's domain."""
    if not url:
        return {"has_auth": False, "domain": ""}
    domain = _domain_from_url(url)
    path = get_auth_for_url(url)
    return {"has_auth": path is not None, "domain": domain, "path": path}


@router.post("/api/auth/upload")
async def upload_auth(file: UploadFile = File(...), domain: str = ""):
    """Upload an auth.json for a specific domain."""
    if not domain:
        raise HTTPException(status_code=400, detail="domain query param required")
    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    path = save_auth_data(domain, data)
    return {"ok": True, "domain": domain, "path": path}


@router.post("/api/auth/generate")
async def generate_auth(url: str = ""):
    """Launch browser for interactive login. User closes browser = auth saved."""
    if not url:
        raise HTTPException(status_code=400, detail="url query param required")
    from testai.auth import generate_auth_interactive

    loop = asyncio.get_event_loop()
    path = await loop.run_in_executor(None, generate_auth_interactive, url)
    domain = _domain_from_url(url)
    return {"ok": True, "domain": domain, "path": path}


@router.get("/api/auth/download/{domain}")
async def download_auth(domain: str):
    """Download the saved auth.json for a domain."""
    from testai.auth import _auth_path

    p = _auth_path(domain)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"No auth for {domain}")
    return FileResponse(
        path=str(p),
        filename=f"{domain}-auth.json",
        media_type="application/json",
    )


@router.delete("/api/auth/{domain}")
async def delete_auth(domain: str):
    """Delete saved auth state for a domain."""
    from testai.auth import _auth_path

    p = _auth_path(domain)
    if p.exists():
        p.unlink()
        return {"ok": True, "domain": domain}
    raise HTTPException(status_code=404, detail="No auth state for this domain")
