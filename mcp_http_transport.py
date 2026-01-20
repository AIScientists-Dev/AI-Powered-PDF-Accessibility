"""
MCP Server with Streamable HTTP Transport.

This allows Claude Code users to connect to your MCP server remotely via:
  claude mcp add accessibility-mcp --transport http https://your-server.com/mcp

Security:
- Requires API key authentication via X-API-Key header
- Validates Origin header to prevent DNS rebinding
- Session management for stateful connections
"""

import asyncio
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

# Import the MCP server components
from src.mcp_server import server, list_tools, call_tool


# ============================================
# Configuration
# ============================================

# API Keys for authentication (in production, use database/secrets manager)
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
VALID_API_KEYS = set(os.environ.get("MCP_API_KEYS", "").split(",")) - {""}

# Allowed origins (for CORS and DNS rebinding protection)
ALLOWED_ORIGINS = os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",")

# Session management
sessions: dict[str, dict] = {}  # session_id -> {created_at, last_used, initialized}
SESSION_TIMEOUT = timedelta(hours=1)


# ============================================
# Authentication
# ============================================

async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
) -> str:
    """Verify API key from header."""
    # Check X-API-Key header
    if x_api_key and x_api_key in VALID_API_KEYS:
        return x_api_key

    # Check Authorization: Bearer <key>
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if token in VALID_API_KEYS:
            return token

    # If no API keys configured, allow all (for development)
    if not VALID_API_KEYS:
        return "dev-mode"

    raise HTTPException(
        status_code=401,
        detail="Invalid or missing API key. Provide X-API-Key header.",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def validate_origin(request: Request) -> None:
    """Validate Origin header to prevent DNS rebinding attacks."""
    origin = request.headers.get("origin")

    # If no allowed origins configured, skip validation (development mode)
    if not ALLOWED_ORIGINS or ALLOWED_ORIGINS == [""]:
        return

    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail=f"Origin {origin} not allowed"
        )


# ============================================
# Session Management
# ============================================

def create_session() -> str:
    """Create a new session and return session ID."""
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "created_at": datetime.utcnow(),
        "last_used": datetime.utcnow(),
        "initialized": False,
    }
    return session_id


def get_session(session_id: str) -> Optional[dict]:
    """Get session by ID, checking timeout."""
    if session_id not in sessions:
        return None

    session = sessions[session_id]
    if datetime.utcnow() - session["last_used"] > SESSION_TIMEOUT:
        del sessions[session_id]
        return None

    session["last_used"] = datetime.utcnow()
    return session


def cleanup_sessions():
    """Remove expired sessions."""
    now = datetime.utcnow()
    expired = [
        sid for sid, s in sessions.items()
        if now - s["last_used"] > SESSION_TIMEOUT
    ]
    for sid in expired:
        del sessions[sid]


# ============================================
# FastAPI Application
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    print("MCP HTTP Transport Server starting...")
    if not VALID_API_KEYS:
        print("WARNING: No API keys configured. Running in development mode.")
    yield
    # Shutdown
    sessions.clear()


app = FastAPI(
    title="Accessibility MCP Server",
    description="MCP Server with Streamable HTTP Transport for Claude Code",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS != [""] else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)


# ============================================
# MCP Streamable HTTP Endpoints
# ============================================

@app.get("/mcp")
async def mcp_get(
    request: Request,
    mcp_session_id: Optional[str] = Header(None, alias="Mcp-Session-Id"),
    api_key: str = Depends(verify_api_key),
):
    """
    GET /mcp - Open SSE stream for server-initiated messages.

    Used by clients to receive server notifications and requests.
    """
    validate_origin(request)

    # Verify session exists
    if mcp_session_id:
        session = get_session(mcp_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

    # Return SSE stream (for now, just acknowledge - extend for server push)
    async def event_stream():
        # Keep connection alive with periodic pings
        while True:
            yield f"event: ping\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat()})}\n\n"
            await asyncio.sleep(30)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/mcp")
async def mcp_post(
    request: Request,
    mcp_session_id: Optional[str] = Header(None, alias="Mcp-Session-Id"),
    api_key: str = Depends(verify_api_key),
):
    """
    POST /mcp - Handle JSON-RPC messages from client.

    This is the main MCP communication endpoint.
    """
    validate_origin(request)
    cleanup_sessions()

    # Parse JSON-RPC request
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Handle batch or single request
    is_batch = isinstance(body, list)
    requests = body if is_batch else [body]

    responses = []
    new_session_id = None

    for req in requests:
        method = req.get("method")
        params = req.get("params", {})
        req_id = req.get("id")

        # Handle initialization
        if method == "initialize":
            # Create new session
            new_session_id = create_session()
            sessions[new_session_id]["initialized"] = True

            # Return server capabilities
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "accessibility-mcp",
                        "version": "1.0.0",
                    },
                }
            }
            responses.append(response)

        # Handle initialized notification
        elif method == "notifications/initialized":
            # No response needed for notifications
            pass

        # Handle tools/list
        elif method == "tools/list":
            tools = await list_tools()
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": tool.inputSchema,
                        }
                        for tool in tools
                    ]
                }
            }
            responses.append(response)

        # Handle tools/call
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            try:
                result = await call_tool(tool_name, arguments)

                # Extract content from result
                content = []
                if result:
                    for item in result:
                        if hasattr(item, 'text'):
                            content.append({
                                "type": "text",
                                "text": item.text,
                            })

                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": content,
                        "isError": False,
                    }
                }
            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": str(e)}],
                        "isError": True,
                    }
                }

            responses.append(response)

        # Handle ping
        elif method == "ping":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {}
            }
            responses.append(response)

        # Unknown method
        elif req_id is not None:  # Only respond to requests, not notifications
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                }
            }
            responses.append(response)

    # Build response
    if not responses:
        # No response needed (all notifications)
        return Response(status_code=202)

    result = responses if is_batch else responses[0]

    # Include session ID in response header if new session created
    headers = {}
    if new_session_id:
        headers["Mcp-Session-Id"] = new_session_id

    return JSONResponse(content=result, headers=headers)


@app.delete("/mcp")
async def mcp_delete(
    request: Request,
    mcp_session_id: str = Header(..., alias="Mcp-Session-Id"),
    api_key: str = Depends(verify_api_key),
):
    """
    DELETE /mcp - Terminate a session.
    """
    validate_origin(request)

    if mcp_session_id in sessions:
        del sessions[mcp_session_id]
        return Response(status_code=204)

    raise HTTPException(status_code=404, detail="Session not found")


# ============================================
# Health & Info Endpoints
# ============================================

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "accessibility-mcp-http"}


@app.get("/")
async def root():
    """Root endpoint with usage information."""
    return {
        "service": "Accessibility MCP Server",
        "transport": "Streamable HTTP",
        "mcp_endpoint": "/mcp",
        "usage": {
            "claude_code": "claude mcp add accessibility --transport http <url>/mcp --header 'X-API-Key: <your-key>'",
            "docs": "https://modelcontextprotocol.io/specification/2025-03-26/basic/transports",
        }
    }


# ============================================
# Main Entry Point
# ============================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("MCP_PORT", 8081))
    host = os.environ.get("MCP_HOST", "0.0.0.0")

    print(f"Starting MCP HTTP Transport on {host}:{port}")
    print(f"MCP endpoint: http://{host}:{port}/mcp")

    uvicorn.run(app, host=host, port=port)
