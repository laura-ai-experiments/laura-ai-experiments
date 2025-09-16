# main.py — FastMCP version (async tools; returns plain values)
import os, base64
from typing import Any, Optional, Tuple, List

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com")
DEFAULT_OWNER = os.getenv("GITHUB_DEFAULT_OWNER", "laura-ai-experiments")
DEFAULT_REPO  = os.getenv("GITHUB_DEFAULT_REPO", "ml-exercises-private")

if not GITHUB_TOKEN:
    raise SystemExit("Missing GITHUB_TOKEN in .env")

mcp = FastMCP("github-reader-mcp")

# Runtime defaults (can be changed via set_target_repo)
current_owner = DEFAULT_OWNER
current_repo  = DEFAULT_REPO

def _eff(owner: Optional[str], repo: Optional[str]) -> Tuple[str, str]:
    return (owner or current_owner, repo or current_repo)

def _hdrs() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def _b64(s: str) -> str:
    return base64.b64decode(s).decode("utf-8", errors="replace")

class GHError(Exception): ...

async def gh_get(client: httpx.AsyncClient, path: str, params: Optional[dict] = None) -> Any:
    url = path if path.startswith("http") else f"{GITHUB_API_URL.rstrip('/')}/{path.lstrip('/')}"
    r = await client.get(url, headers=_hdrs(), params=params, timeout=30)
    if r.status_code in (401, 403, 404):
        try:
            msg = r.json().get("message", "")
        except Exception:
            msg = r.text
        raise GHError(f"{r.status_code}: {msg or 'GitHub API error'}")
    r.raise_for_status()
    return r.json() if r.content else None

# -------------------- Tools --------------------

@mcp.tool()
def set_target_repo(owner: str, repo: str) -> str:
    """Set default owner/repo for subsequent calls."""
    global current_owner, current_repo
    current_owner, current_repo = owner, repo
    return f"Defaults set to {current_owner}/{current_repo}"

@mcp.tool()
async def gh_repo_info(owner: Optional[str] = None, repo: Optional[str] = None) -> str:
    """Get basic information about the repository."""
    owner, repo = _eff(owner, repo)
    async with httpx.AsyncClient() as client:
        data = await gh_get(client, f"repos/{owner}/{repo}")
    out = [
        f"Repository: {owner}/{repo}",
        f"Visibility: {data.get('visibility')} (private={data.get('private')})",
        f"Default branch: {data.get('default_branch')}",
        f"Description: {data.get('description') or '(none)'}",
    ]
    return "\n".join(out)

@mcp.tool()
async def gh_list_dir(
    path: str = "",
    ref: Optional[str] = None,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    """List items at a path in the repo (files/folders)."""
    owner, repo = _eff(owner, repo)
    params = {"ref": ref} if ref else None
    async with httpx.AsyncClient() as client:
        data = await gh_get(client, f"repos/{owner}/{repo}/contents/{path}", params)
    if isinstance(data, dict) and data.get("type") == "file":
        return f"{path} is a file ({data.get('size')} bytes)."
    lines: List[str] = []
    for item in data:
        kind, name, size = item.get("type"), item.get("name"), item.get("size")
        lines.append(f"{kind:6} {name} {'' if size is None else f'({size}B)'}")
    return "\n".join(lines) if lines else "(empty)"

@mcp.tool()
async def gh_get_text_file(
    path: str,
    ref: Optional[str] = None,
    max_chars: int = 10000,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    """Fetch a text file and return (truncated) content."""
    owner, repo = _eff(owner, repo)
    params = {"ref": ref} if ref else None
    async with httpx.AsyncClient() as client:
        d = await gh_get(client, f"repos/{owner}/{repo}/contents/{path}", params)
    if d.get("type") != "file":
        return f"Not a file: {path}"
    if d.get("encoding") == "base64":
        return _b64(d["content"])[:max_chars]
    return str(d.get("content"))[:max_chars]

@mcp.tool()
async def gh_search_code(
    query: str,
    limit: int = 10,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    """Search code within the repo using GitHub's search API."""
    owner, repo = _eff(owner, repo)
    q = f"{query} repo:{owner}/{repo}"
    params = {"q": q, "per_page": min(limit, 100)}
    async with httpx.AsyncClient() as client:
        data = await gh_get(client, "search/code", params)
    items = data.get("items", [])[:limit]
    if not items:
        return "(no results)"
    return "\n".join(f"{it['repository']['full_name']}:{it['path']} ({it['sha'][:7]})" for it in items)

@mcp.tool()
async def health_check() -> str:
    """Quick token/repo check: lists root names (up to 20)."""
    owner, repo = current_owner, current_repo
    async with httpx.AsyncClient() as client:
        data = await gh_get(client, f"repos/{owner}/{repo}/contents/")
    names = [it.get("name") for it in (data if isinstance(data, list) else [])][:20]
    return "OK: " + ", ".join(names) if names else "OK (empty root)"

if __name__ == "__main__":
    print(f"Starting github-reader-mcp with defaults {current_owner}/{current_repo}")
    mcp.run()
