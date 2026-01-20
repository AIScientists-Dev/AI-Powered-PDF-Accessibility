# Accessibility MCP Server

PDF and LaTeX accessibility enhancement tools powered by MCP (Model Context Protocol). Includes AI-generated alt-text, PDF/UA validation with MorphMind Accessibility Score, and automated remediation.

## Features

- **23 accessibility tools** for PDF and LaTeX documents
- **MorphMind Accessibility Score** (0-100) based on PDF/UA compliance
- **AI-powered alt-text generation** using Google Gemini
- **veraPDF validation** for PDF/UA-1, PDF/UA-2, and PDF/A standards
- **Automatic structure tagging** (headings, links, metadata)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    EC2 Server (c6i.2xlarge)                 │
│                                                             │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │  HTTP API (Port 8080)   │  │  MCP HTTP (Port 8081)   │  │
│  │  For AgentLab/Fargate   │  │  For Claude Code        │  │
│  │  (Internal VPC only)    │  │  (Future - not exposed) │  │
│  └───────────┬─────────────┘  └───────────┬─────────────┘  │
│              │                            │                 │
│              └──────────┬─────────────────┘                 │
│                         │                                   │
│              ┌──────────▼──────────┐                       │
│              │   src/mcp_server.py │                       │
│              │   (Tool Implementations)                    │
│              └─────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

## Endpoints

### Agent-Friendly Endpoints (Recommended)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/agent/validate` | POST | PDF/UA validation with structured JSON response |
| `/agent/make-accessible` | POST | Full remediation pipeline with `output_file` for chaining |

### Standard Tool Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/tools` | GET | List all available tools |
| `/tools/{name}` | POST | Execute any tool |
| `/upload` | POST | Upload PDF/LaTeX file |
| `/download/{file_id}` | GET | Download processed file |

## Quick Start

### For AgentLab Integration

```python
import requests

BACKEND_URL = "http://172.31.15.119:8080"

# 1. Upload PDF
with open("document.pdf", "rb") as f:
    resp = requests.post(f"{BACKEND_URL}/upload", files={"file": f})
file_id = resp.json()["file_id"]

# 2. Validate (get score)
resp = requests.post(f"{BACKEND_URL}/agent/validate",
    json={"arguments": {"pdf_path": file_id}})
result = resp.json()
print(f"Score: {result['score']}/100, Grade: {result['grade']}")

# 3. Make accessible
resp = requests.post(f"{BACKEND_URL}/agent/make-accessible",
    json={"arguments": {"pdf_path": file_id, "document_type": "technical report"}})
output_file = resp.json()["output_file"]

# 4. Validate again
resp = requests.post(f"{BACKEND_URL}/agent/validate",
    json={"arguments": {"pdf_path": output_file}})
print(f"New Score: {resp.json()['score']}/100")
```

### Response Examples

**`/agent/validate` response:**
```json
{
  "success": true,
  "score": 82,
  "grade": "B",
  "compliant": false,
  "summary": {
    "passed_rules": 100,
    "failed_rules": 4,
    "passed_checks": 19460,
    "failed_checks": 4
  },
  "issues_by_severity": {
    "critical": 0,
    "serious": 3,
    "moderate": 1,
    "minor": 0
  },
  "failures": [...]
}
```

**`/agent/make-accessible` response:**
```json
{
  "success": true,
  "output_file": "abc123_document_accessible.pdf",
  "output_path": "/tmp/.../abc123_document_accessible.pdf",
  "figures_processed": 3,
  "alt_texts": [...],
  "structure_enhancements": {
    "xmp_metadata_added": true,
    "headings_tagged": 15,
    "links_fixed": 8
  }
}
```

## Available Tools

### PDF Analysis & Validation
- `analyze_pdf` - Analyze accessibility status
- `validate_pdfua` - PDF/UA validation with MorphMind Score
- `validate_pdfa` - PDF/A validation
- `validate_accessibility` - Quick accessibility check

### PDF Remediation
- `make_accessible` - Full pipeline (structure + alt-text)
- `add_structure_tags` - Basic structure tagging
- `add_full_structure` - Comprehensive structure (metadata, headings, links)
- `add_alt_text` - Add alt-text to specific figure
- `fix_link_alt_texts` - Add alt-text to links

### Figure Processing
- `extract_figures` - Extract all figures from PDF
- `generate_alt_text` - AI-generated alt-text for image
- `detect_headings` - Detect heading hierarchy
- `get_link_annotations` - List all links

### LaTeX Support
- `analyze_latex` - Analyze LaTeX for accessibility
- `prepare_latex` - Add accessibility preamble
- `make_latex_accessible` - Full LaTeX pipeline
- `add_latex_alt_text` - Add alt-text to LaTeX figure

## Deployment

### Prerequisites
- AWS CLI configured
- EC2 instance running (i-0e875c3fc07d73dca)
- SSH deploy key configured

### Deploy Updates
```bash
./deploy/update-ec2.sh
```

### GitHub Actions (CI/CD)
Push to `main` triggers automatic deployment. Requires GitHub secrets:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

## Infrastructure

| Component | Value |
|-----------|-------|
| EC2 Instance | i-0e875c3fc07d73dca |
| Instance Type | c6i.2xlarge |
| Private IP | 172.31.15.119 |
| Port | 8080 |
| VPC | Default VPC (vpc-09dff21e271372a41) |
| Region | us-east-1 |

## Security

- HTTP API (8080) restricted to VPC CIDR only
- No public SSH access (use SSM)
- MCP HTTP (8081) not exposed (future use)
- Gemini API key stored in `/home/mcpuser/app/.env`

## Future: MCP for Claude Code

The `mcp_http_transport.py` implements MCP Streamable HTTP transport for future public access. Not currently deployed. When enabled, Claude Code users can connect with:

```bash
claude mcp add accessibility --transport http https://your-domain/mcp \
    --header "X-API-Key: <key>"
```

## Dependencies

- Python 3.11
- FastAPI + Uvicorn
- pikepdf, PyMuPDF
- google-generativeai (Gemini)
- veraPDF 1.26+

## License

MIT
