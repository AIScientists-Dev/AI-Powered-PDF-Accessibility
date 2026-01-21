<p align="center">
  <img src="https://img.shields.io/badge/MCP-Model%20Context%20Protocol-blue?style=for-the-badge" alt="MCP">
  <img src="https://img.shields.io/badge/PDF%2FUA-ISO%2014289-green?style=for-the-badge" alt="PDF/UA">
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="MIT License">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python" alt="Python">
</p>

<h1 align="center">AI-Powered PDF Accessibility</h1>

<p align="center">
  <b>AI-powered PDF accessibility remediation with MorphMind Accessibility Score</b>
</p>

<p align="center">
  Transform inaccessible PDFs into PDF/UA compliant documents in minutes, not hours.<br>
  Built on MCP (Model Context Protocol) for seamless AI agent integration.
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-features">Features</a> •
  <a href="#-api-reference">API Reference</a> •
  <a href="#-deployment">Deployment</a> •
  <a href="#-contributing">Contributing</a>
</p>

---

## About

This project was developed in collaboration with **[MorphMind](https://morphmind.ai)**.

**Try it now — no setup required:** [agentlab.morphmind.ai](https://agentlab.morphmind.ai) (Free trial available)

---

## 🚀 Quick Start

### Option 1: Use via MorphMind AgentLab (Recommended)

The easiest way — no setup required:

1. Visit [agentlab.morphmind.ai](https://agentlab.morphmind.ai)
2. Find the **PDF Accessibility Remediator** agent
3. Upload your PDF and get instant results

**Free trial available** — start remediating PDFs in seconds.

### Option 2: Local Development

```bash
# Clone the repository
git clone https://github.com/AIScientists-Dev/AI-Powered-PDF-Accessibility.git
cd AI-Powered-PDF-Accessibility

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install veraPDF (required for validation)
# macOS:
brew install verapdf
# Linux: Download from https://verapdf.org/software/

# Set up environment
echo "GEMINI_API_KEY=your_api_key_here" > .env

# Run the server
python -m uvicorn http_server:app --host 0.0.0.0 --port 8080

# Test it
curl http://localhost:8080/health
```

---

## ✨ Features

### 🎯 MorphMind Accessibility Score

Get an instant **0-100 score** based on PDF/UA compliance, with letter grades and actionable insights.

```json
{
  "score": 82,
  "grade": "B",
  "issues_by_severity": {
    "critical": 0,
    "serious": 3,
    "moderate": 1
  }
}
```

### 🤖 AI-Powered Alt-Text

Automatically generate descriptive alt-text for images and figures using Google Gemini vision AI.

### 📋 25 Specialized Tools

| Category | Tools |
|----------|-------|
| **Analysis** | `analyze_pdf`, `validate_pdfua`, `validate_pdfa`, `detect_headings` |
| **Remediation** | `make_accessible`, `add_full_structure`, `add_alt_text`, `fix_link_alt_texts` |
| **Figures** | `extract_figures`, `generate_alt_text`, `get_link_annotations` |
| **LaTeX** | `analyze_latex`, `prepare_latex`, `make_latex_accessible` |
| **Education** | `get_accessibility_tutorial` |

### 🏗️ Built on Standards

- **MCP** (Model Context Protocol) - Open standard for AI tool integration
- **PDF/UA** (ISO 14289) - International PDF accessibility standard
- **veraPDF** - Industry-standard validation engine
- **WCAG 2.1** - Web Content Accessibility Guidelines alignment

---

## 📖 API Reference

### Agent-Optimized Endpoints

These endpoints return clean, structured JSON designed for AI agent consumption:

#### `POST /agent/validate`

Validate PDF against PDF/UA with MorphMind Score.

```bash
curl -X POST http://localhost:8080/agent/validate \
  -H "Content-Type: application/json" \
  -d '{"arguments": {"pdf_path": "/path/to/file.pdf"}}'
```

**Response:**
```json
{
  "success": true,
  "score": 82,
  "grade": "B",
  "compliant": false,
  "summary": {
    "passed_rules": 100,
    "failed_rules": 4
  },
  "issues_by_severity": {
    "critical": 0,
    "serious": 3,
    "moderate": 1,
    "minor": 0
  },
  "failures": [
    {
      "clause": "7.1",
      "test_number": "10",
      "description": "DisplayDocTitle key missing"
    }
  ]
}
```

#### `POST /agent/make-accessible`

Full remediation pipeline with AI alt-text generation.

```bash
curl -X POST http://localhost:8080/agent/make-accessible \
  -H "Content-Type: application/json" \
  -d '{"arguments": {"pdf_path": "file_id", "document_type": "technical report"}}'
```

**Response:**
```json
{
  "success": true,
  "output_file": "abc123_document_accessible.pdf",
  "figures_processed": 3,
  "structure_enhancements": {
    "headings_tagged": 15,
    "links_fixed": 8,
    "xmp_metadata_added": true
  }
}
```

### Standard Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/tools` | GET | List all available tools |
| `/tools/{name}` | POST | Execute any tool by name |
| `/upload` | POST | Upload PDF file, returns `file_id` |
| `/download/{file_id}` | GET | Download processed file |
| `/batch` | POST | Execute multiple tools in sequence |

---

## 🏛️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Your Application                         │
│                  (AgentLab, MCP Clients, etc.)                  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Accessibility Agent Backend                   │
│  ┌─────────────────────────┐  ┌─────────────────────────────┐  │
│  │  HTTP API (Port 8080)   │  │  MCP Transport (Port 8081)  │  │
│  │  • /agent/validate      │  │  • Streamable HTTP          │  │
│  │  • /agent/make-accessible│  │  • API Key authenticated    │  │
│  │  • /upload, /download   │  │                             │  │
│  └───────────┬─────────────┘  └───────────┬─────────────────┘  │
│              │                            │                     │
│              └──────────┬─────────────────┘                     │
│                         ▼                                       │
│              ┌─────────────────────────┐                       │
│              │   src/mcp_server.py     │                       │
│              │   25 Accessibility Tools │                       │
│              └───────────┬─────────────┘                       │
│                          │                                      │
│    ┌─────────────────────┼─────────────────────┐               │
│    ▼                     ▼                     ▼               │
│ ┌──────────┐      ┌────────────┐      ┌────────────┐          │
│ │ veraPDF  │      │  Gemini AI │      │  pikepdf   │          │
│ │Validation│      │  Alt-text  │      │PDF Editing │          │
│ └──────────┘      └────────────┘      └────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚢 Deployment

### Self-Hosted Deployment

Deploy on any cloud provider (AWS, GCP, Azure) or on-premises:

```bash
# Clone and setup
git clone https://github.com/AIScientists-Dev/AI-Powered-PDF-Accessibility.git
cd AI-Powered-PDF-Accessibility

# Configure environment
cp .env.example .env
# Edit .env with your GEMINI_API_KEY

# Run with systemd (see deploy/ folder for service files)
./deploy/update-ec2.sh
```

**CI/CD:** Push to `main` triggers GitHub Actions deployment.

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GEMINI_API_KEY` | Google Gemini API key for alt-text generation | Yes |
| `PORT` | HTTP server port (default: 8080) | No |
| `HOST` | Bind address (default: 0.0.0.0) | No |
| `MCP_API_KEYS` | Comma-separated API keys for MCP transport | No |

---

## 🤝 Contributing

We welcome contributions! This project is open source under the MIT License.

### Areas Where Help is Needed

- 🌍 **Internationalization** - Support for more languages
- 📊 **Table remediation** - Improve complex table handling
- 📐 **Math accessibility** - Better equation support
- 🧪 **Testing** - More diverse PDF test cases
- 📚 **Documentation** - Tutorials and guides

### Development Setup

```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/AI-Powered-PDF-Accessibility.git

# Install dev dependencies
pip install -r requirements.txt
pip install pytest black flake8

# Run tests
pytest

# Format code
black .
```

---

## 📊 Why Accessibility Matters

- **1 billion+ people** worldwide have disabilities (WHO)
- **90%+ of PDFs** lack proper accessibility features
- **Legal requirements** in most countries (ADA, Section 508, EU Directive)
- **2-4 hours** → **2-4 minutes**: Time savings with AI automation

### Built-in Educational Content

Ask the agent about accessibility:
```bash
curl -X POST http://localhost:8080/tools/get_accessibility_tutorial \
  -H "Content-Type: application/json" \
  -d '{"arguments": {"topic": "what_is_accessibility"}}'
```

Topics available:
- `what_is_accessibility` - Introduction to PDF accessibility
- `common_struggles` - Challenges people face
- `how_we_help` - How AI agents solve these problems
- `getting_started` - Quick start guide
- `about_project` - About this project

---

## 📜 License

MIT License - Use freely, contribute back if you can.

---

## 🔗 Links

- **Try it now**: [agentlab.morphmind.ai](https://agentlab.morphmind.ai) — Free trial available
- **MorphMind**: [morphmind.ai](https://morphmind.ai)
- **MCP Specification**: [modelcontextprotocol.io](https://modelcontextprotocol.io)
- **veraPDF**: [verapdf.org](https://verapdf.org)
- **PDF/UA Standard**: [ISO 14289](https://www.iso.org/standard/64599.html)

---

<p align="center">
  Built with ❤️ by <a href="https://morphmind.ai">MorphMind</a>
</p>
