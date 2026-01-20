"""
HTTP API wrapper for the Accessibility MCP Server.

This provides a REST API that can be called from ECS Fargate containers
(MorphMind/AgentLab) without requiring MCP protocol support.

Endpoints:
- GET /health - Health check
- GET /tools - List all available tools
- POST /tools/{tool_name} - Execute a specific tool
- POST /batch - Execute multiple tools in sequence
"""

import asyncio
import json
import os
import tempfile
import shutil
import base64
from pathlib import Path
from typing import Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# Import the MCP server components
from src.mcp_server import call_tool, list_tools, run_verapdf
from src.validator import calculate_morphmind_score


# ============================================
# Request/Response Models
# ============================================

class ToolRequest(BaseModel):
    arguments: dict[str, Any] = {}


class BatchRequest(BaseModel):
    tools: list[dict[str, Any]]  # [{"name": "tool_name", "arguments": {...}}, ...]


class ToolResponse(BaseModel):
    success: bool
    tool_name: str
    result: Any
    error: Optional[str] = None


# ============================================
# File Management for Remote Execution
# ============================================

# Temporary directory for uploaded files
UPLOAD_DIR = Path(tempfile.gettempdir()) / "accessibility-mcp-uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Output directory for processed files
OUTPUT_DIR = Path(tempfile.gettempdir()) / "accessibility-mcp-outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


def cleanup_old_files():
    """Clean up files older than 1 hour."""
    import time
    current_time = time.time()
    for dir_path in [UPLOAD_DIR, OUTPUT_DIR]:
        for file_path in dir_path.iterdir():
            if file_path.is_file():
                file_age = current_time - file_path.stat().st_mtime
                if file_age > 3600:  # 1 hour
                    file_path.unlink(missing_ok=True)


# ============================================
# FastAPI Application
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    cleanup_old_files()
    yield
    # Shutdown
    pass


app = FastAPI(
    title="Accessibility MCP HTTP API",
    description="REST API for PDF and LaTeX accessibility enhancement tools",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for cross-origin requests from MorphMind
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# Health & Discovery Endpoints
# ============================================

@app.get("/health")
async def health_check():
    """Health check endpoint for load balancers."""
    return {"status": "healthy", "service": "accessibility-mcp"}


@app.get("/tools")
async def get_tools():
    """List all available tools with their schemas."""
    tools = await list_tools()
    return {
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema,
            }
            for tool in tools
        ]
    }


@app.get("/tools/{tool_name}")
async def get_tool_info(tool_name: str):
    """Get information about a specific tool."""
    tools = await list_tools()
    for tool in tools:
        if tool.name == tool_name:
            return {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema,
            }
    raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")


# ============================================
# Tool Execution Endpoints
# ============================================

def resolve_file_path(value: str) -> str:
    """
    Resolve a file_id or path to an actual file path.
    Handles: file_id, full path, or @file_id placeholder.
    """
    if not value or not isinstance(value, str):
        return value

    # Remove @ prefix if present (agent placeholder syntax)
    if value.startswith("@"):
        value = value[1:]

    # Check for unresolved placeholder strings - return helpful error
    placeholder_patterns = ["file_id", "output_file", "pdf_path", "input_file"]
    if value.lower() in placeholder_patterns:
        raise ValueError(
            f"Received placeholder '{value}' instead of actual file path. "
            f"Please use the actual file_path returned from /upload or output_path from previous tool calls. "
            f"Available files in uploads: {list(UPLOAD_DIR.iterdir()) if UPLOAD_DIR.exists() else []}"
        )

    # If it's already an absolute path that exists, use it
    if value.startswith("/") and Path(value).exists():
        return value

    # Check if it's a file_id in our upload directory
    upload_path = UPLOAD_DIR / value
    if upload_path.exists():
        return str(upload_path)

    # Check output directory too
    output_path = OUTPUT_DIR / value
    if output_path.exists():
        return str(output_path)

    # Return as-is if nothing found (let the tool handle the error)
    return value


def resolve_arguments(arguments: dict) -> dict:
    """Resolve file paths in tool arguments."""
    resolved = {}
    path_keys = ["pdf_path", "latex_path", "image_path", "file_path", "output_path"]

    for key, value in arguments.items():
        if key in path_keys and isinstance(value, str):
            resolved[key] = resolve_file_path(value)
        else:
            resolved[key] = value

    return resolved


@app.post("/tools/{tool_name}")
async def execute_tool(tool_name: str, request: ToolRequest):
    """Execute a specific tool with the given arguments."""
    try:
        # Verify tool exists
        tools = await list_tools()
        tool_names = [t.name for t in tools]
        if tool_name not in tool_names:
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

        # Resolve file paths in arguments (convert file_id to full path)
        resolved_args = resolve_arguments(request.arguments)

        # Execute the tool
        result = await call_tool(tool_name, resolved_args)

        # Parse result from TextContent
        if result and hasattr(result[0], 'text'):
            try:
                parsed = json.loads(result[0].text)
                return ToolResponse(
                    success=True,
                    tool_name=tool_name,
                    result=parsed,
                )
            except json.JSONDecodeError:
                # Return as plain text if not JSON
                return ToolResponse(
                    success=True,
                    tool_name=tool_name,
                    result=result[0].text,
                )

        return ToolResponse(
            success=True,
            tool_name=tool_name,
            result=str(result),
        )

    except Exception as e:
        return ToolResponse(
            success=False,
            tool_name=tool_name,
            result=None,
            error=str(e),
        )


@app.post("/batch")
async def execute_batch(request: BatchRequest):
    """Execute multiple tools in sequence."""
    results = []
    for tool_spec in request.tools:
        tool_name = tool_spec.get("name")
        arguments = tool_spec.get("arguments", {})

        # Resolve file paths
        resolved_args = resolve_arguments(arguments)

        try:
            result = await call_tool(tool_name, resolved_args)
            if result and hasattr(result[0], 'text'):
                try:
                    parsed = json.loads(result[0].text)
                    results.append({
                        "tool": tool_name,
                        "success": True,
                        "result": parsed,
                    })
                except json.JSONDecodeError:
                    results.append({
                        "tool": tool_name,
                        "success": True,
                        "result": result[0].text,
                    })
            else:
                results.append({
                    "tool": tool_name,
                    "success": True,
                    "result": str(result),
                })
        except Exception as e:
            results.append({
                "tool": tool_name,
                "success": False,
                "error": str(e),
            })

    return {"results": results}


# ============================================
# Agent-Friendly Structured Endpoints
# ============================================
# These endpoints return structured JSON specifically designed for
# programmatic agent consumption (vs MCP text for human display)

@app.post("/agent/validate")
async def agent_validate_pdfua(request: ToolRequest):
    """
    Agent-friendly PDF/UA validation that returns structured JSON.

    Returns:
        - score: MorphMind Accessibility Score (0-100)
        - grade: Letter grade (A-F)
        - compliant: Boolean PDF/UA compliance
        - summary: Pass/fail counts
        - failures: List of specific failures with clause info
        - issues_by_severity: Breakdown by critical/serious/moderate/minor
    """
    try:
        pdf_path = request.arguments.get("pdf_path")
        profile = request.arguments.get("profile", "ua1")

        # Resolve file path
        pdf_path = resolve_file_path(pdf_path)

        # Run veraPDF directly for structured result
        result = run_verapdf(pdf_path, profile)

        if "error" in result:
            return {
                "success": False,
                "error": result["error"]
            }

        # Calculate MorphMind score
        failures_for_score = []
        for failure in result.get("failures", []):
            failures_for_score.append({
                "clause": failure.get("clause", ""),
                "test": failure.get("test_number"),
                "message": failure.get("description", ""),
                "count": len(failure.get("checks", [1])),
            })

        morphmind = calculate_morphmind_score(
            passed_rules=result['summary']['passed_rules'],
            failed_rules=result['summary']['failed_rules'],
            passed_checks=result['summary']['passed_checks'],
            failed_checks=result['summary']['failed_checks'],
            failures=failures_for_score,
        )

        return {
            "success": True,
            "score": morphmind.score,
            "grade": morphmind.grade,
            "compliant": result["compliant"],
            "profile": result.get("profile", profile),
            "summary": result["summary"],
            "issues_by_severity": morphmind.issues_by_severity,
            "category_scores": morphmind.category_scores,
            "failures": [
                {
                    "clause": f.get("clause"),
                    "test_number": f.get("test_number"),
                    "description": f.get("description"),
                    "check_count": len(f.get("checks", [])),
                }
                for f in result.get("failures", [])[:20]  # Limit to 20
            ],
            "total_failures": len(result.get("failures", [])),
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@app.post("/agent/make-accessible")
async def agent_make_accessible(request: ToolRequest):
    """
    Agent-friendly make_accessible that returns structured JSON with output_file.

    Returns:
        - output_file: The file_id of the processed PDF (can be used directly in subsequent calls)
        - output_path: Full path to the processed PDF
        - figures_processed: Number of figures with alt-text added
        - structure_enhancements: What was added (headings, links, metadata)
    """
    try:
        resolved_args = resolve_arguments(request.arguments)

        # Execute the tool
        result = await call_tool("make_accessible", resolved_args)

        if result and hasattr(result[0], 'text'):
            parsed = json.loads(result[0].text)

            # Extract file_id from output_path for easy reuse
            output_path = parsed.get("output_path", "")
            output_file = Path(output_path).name if output_path else None

            return {
                "success": parsed.get("success", True),
                "output_file": output_file,  # Just the filename for easy use
                "output_path": output_path,   # Full path if needed
                "figures_processed": parsed.get("figures_processed", 0),
                "alt_texts": parsed.get("alt_texts", []),
                "structure_enhancements": parsed.get("structure_enhancements", {}),
                "validation": parsed.get("validation", {}),
            }

        return {"success": False, "error": "No result from make_accessible"}

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================
# File Upload & Download Endpoints
# ============================================

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload a file (PDF, LaTeX, image) for processing.
    Returns a file_id that can be used in tool arguments.
    """
    # Generate unique filename
    file_id = f"{os.urandom(8).hex()}_{file.filename}"
    file_path = UPLOAD_DIR / file_id

    # Save uploaded file
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    return {
        "file_id": file_id,
        "file_path": str(file_path),
        "size": file_path.stat().st_size,
        "message": f"Use '{file_path}' as the path in tool arguments",
    }


@app.get("/download/{file_id}")
async def download_file(file_id: str):
    """Download a processed file by its ID."""
    # Check both upload and output directories
    for dir_path in [OUTPUT_DIR, UPLOAD_DIR]:
        file_path = dir_path / file_id
        if file_path.exists():
            return FileResponse(
                path=file_path,
                filename=file_id,
                media_type="application/octet-stream",
            )

    raise HTTPException(status_code=404, detail=f"File '{file_id}' not found")


@app.post("/process-pdf")
async def process_pdf(
    file: UploadFile = File(...),
    operation: str = Form("make_accessible"),
    document_type: str = Form("academic paper"),
):
    """
    Convenience endpoint: Upload a PDF and process it in one request.

    Operations:
    - analyze: Analyze accessibility status
    - make_accessible: Full accessibility pipeline
    - validate_pdfua: PDF/UA validation
    - add_structure_tags: Add basic structure
    - add_full_structure: Add comprehensive structure
    """
    # Save uploaded file
    file_id = f"{os.urandom(8).hex()}_{file.filename}"
    input_path = UPLOAD_DIR / file_id

    with open(input_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Determine output path
    output_id = f"{os.urandom(8).hex()}_accessible_{file.filename}"
    output_path = OUTPUT_DIR / output_id

    # Build arguments based on operation
    if operation == "analyze":
        arguments = {"pdf_path": str(input_path)}
    elif operation == "make_accessible":
        arguments = {
            "pdf_path": str(input_path),
            "output_path": str(output_path),
            "document_type": document_type,
        }
    elif operation == "validate_pdfua":
        arguments = {"pdf_path": str(input_path), "profile": "ua1"}
    elif operation == "add_structure_tags":
        arguments = {"pdf_path": str(input_path), "output_path": str(output_path)}
    elif operation == "add_full_structure":
        arguments = {"pdf_path": str(input_path), "output_path": str(output_path)}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown operation: {operation}")

    # Execute tool
    try:
        result = await call_tool(operation, arguments)

        if result and hasattr(result[0], 'text'):
            try:
                parsed = json.loads(result[0].text)
            except json.JSONDecodeError:
                parsed = {"raw_result": result[0].text}
        else:
            parsed = {"raw_result": str(result)}

        # Add download info if output file exists
        if output_path.exists():
            parsed["download_url"] = f"/download/{output_id}"
            parsed["output_file_id"] = output_id

        return {
            "success": True,
            "operation": operation,
            "input_file": file_id,
            "result": parsed,
        }

    except Exception as e:
        return {
            "success": False,
            "operation": operation,
            "error": str(e),
        }


@app.post("/process-latex")
async def process_latex(
    tex_file: UploadFile = File(...),
    pdf_file: Optional[UploadFile] = File(None),
    operation: str = Form("prepare_latex"),
):
    """
    Convenience endpoint for LaTeX processing.

    Operations:
    - analyze_latex: Analyze LaTeX for accessibility
    - prepare_latex: Add accessibility preamble
    - make_latex_accessible: Full pipeline (requires PDF)
    """
    # Save LaTeX file
    tex_id = f"{os.urandom(8).hex()}_{tex_file.filename}"
    tex_path = UPLOAD_DIR / tex_id

    with open(tex_path, "wb") as f:
        content = await tex_file.read()
        f.write(content)

    # Save PDF if provided
    pdf_path = None
    if pdf_file:
        pdf_id = f"{os.urandom(8).hex()}_{pdf_file.filename}"
        pdf_path = UPLOAD_DIR / pdf_id
        with open(pdf_path, "wb") as f:
            content = await pdf_file.read()
            f.write(content)

    # Output path
    output_id = f"{os.urandom(8).hex()}_accessible_{tex_file.filename}"
    output_path = OUTPUT_DIR / output_id

    # Build arguments
    if operation == "analyze_latex":
        arguments = {"latex_path": str(tex_path)}
    elif operation == "prepare_latex":
        arguments = {"latex_path": str(tex_path), "output_path": str(output_path)}
    elif operation == "make_latex_accessible":
        if not pdf_path:
            raise HTTPException(
                status_code=400,
                detail="make_latex_accessible requires a compiled PDF file"
            )
        arguments = {
            "latex_path": str(tex_path),
            "pdf_path": str(pdf_path),
            "output_path": str(output_path),
        }
    else:
        raise HTTPException(status_code=400, detail=f"Unknown operation: {operation}")

    # Execute
    try:
        result = await call_tool(operation, arguments)

        if result and hasattr(result[0], 'text'):
            try:
                parsed = json.loads(result[0].text)
            except json.JSONDecodeError:
                parsed = {"raw_result": result[0].text}
        else:
            parsed = {"raw_result": str(result)}

        if output_path.exists():
            parsed["download_url"] = f"/download/{output_id}"
            parsed["output_file_id"] = output_id

        return {
            "success": True,
            "operation": operation,
            "result": parsed,
        }

    except Exception as e:
        return {
            "success": False,
            "operation": operation,
            "error": str(e),
        }


# ============================================
# Agent Customization Endpoints
# ============================================

@app.get("/openapi-tools")
async def get_openapi_tools():
    """
    Get tool definitions in OpenAI/Anthropic function calling format.
    This can be used by MorphMind agents to discover and use these tools.
    """
    tools = await list_tools()

    # Convert to OpenAI function format
    openai_format = []
    for tool in tools:
        openai_format.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema,
            }
        })

    # Also provide Anthropic format
    anthropic_format = []
    for tool in tools:
        anthropic_format.append({
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema,
        })

    return {
        "openai_format": openai_format,
        "anthropic_format": anthropic_format,
        "mcp_format": [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            }
            for tool in tools
        ],
    }


# ============================================
# Main Entry Point
# ============================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    uvicorn.run(app, host=host, port=port)
