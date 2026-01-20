"""
Accessibility Education & Advocacy Module.

Provides curated educational content about PDF accessibility,
the challenges people face, and how AI agents can help.
"""

ACCESSIBILITY_GUIDE = {
    "what_is_accessibility": {
        "title": "What is PDF Accessibility?",
        "content": """
## What is PDF Accessibility?

PDF accessibility ensures that documents can be read and understood by everyone, including people who:

- **Use screen readers** (blind or visually impaired users)
- **Have cognitive disabilities** (need clear structure and navigation)
- **Have motor impairments** (rely on keyboard navigation)
- **Are in situational limitations** (noisy environment, small screen)

### The Standard: PDF/UA (ISO 14289)

PDF/UA (Universal Accessibility) is the international standard that defines how PDFs should be structured for accessibility. Key requirements include:

1. **Tagged Structure** - All content must be tagged (headings, paragraphs, lists, tables)
2. **Reading Order** - Content must flow logically for screen readers
3. **Alternative Text** - Images and figures need descriptive alt-text
4. **Language Specification** - Document language must be declared
5. **Navigation Aids** - Bookmarks, table of contents for long documents

### Why It Matters

- **1 billion+ people** worldwide have disabilities (WHO)
- **Legal requirements** in many countries (ADA, Section 508, EU Directive)
- **Better for everyone** - accessible documents are more searchable, mobile-friendly, and future-proof
"""
    },

    "common_struggles": {
        "title": "Common Accessibility Challenges",
        "content": """
## Why PDF Accessibility is Hard

### The Problem

Most PDFs are created without accessibility in mind. Common issues include:

| Issue | Impact | Frequency |
|-------|--------|-----------|
| Missing alt-text on images | Screen readers say "image" with no context | 90%+ of PDFs |
| No document structure tags | Content reads as jumbled text | 80%+ of PDFs |
| Incorrect reading order | Sentences read out of sequence | 70%+ of PDFs |
| Missing language declaration | Screen readers use wrong pronunciation | 60%+ of PDFs |
| Inaccessible tables | Data relationships lost | Common |
| No bookmarks in long docs | No way to navigate | Very common |

### Why It's Been Difficult to Fix

1. **Manual Process** - Traditional remediation requires clicking through every element
2. **Expertise Required** - Need to understand PDF/UA standard deeply
3. **Time Consuming** - A 50-page document can take hours to remediate
4. **Expensive** - Professional remediation costs $5-50+ per page
5. **Scale Problem** - Organizations have thousands of legacy PDFs

### The Human Cost

> "When I encounter an inaccessible PDF, I either have to ask someone to read it to me, or simply give up. It's frustrating to be excluded from information that others take for granted."
> — Screen reader user

### What People Actually Need

- **Automated detection** of accessibility issues
- **AI-powered alt-text** generation for figures
- **Batch processing** for document libraries
- **Clear remediation guidance** when manual review is needed
- **Validation** to confirm compliance
"""
    },

    "how_we_help": {
        "title": "How AI Agents Transform Accessibility",
        "content": """
## How AI Agents Are Changing the Game

### The AI-Powered Approach

Instead of manual remediation, AI agents can:

1. **Analyze documents instantly** - Detect all accessibility issues in seconds
2. **Generate alt-text automatically** - Describe figures, charts, and images using vision AI
3. **Apply structure tags** - Add proper heading hierarchy, lists, and semantic markup
4. **Fix common issues** - Language tags, reading order, link descriptions
5. **Validate compliance** - Check against PDF/UA standard with detailed scoring

### What This Agent Does

This accessibility agent provides **23 specialized tools** that work together:

**Analysis & Validation**
- `validate_pdfua` - Full PDF/UA validation with MorphMind Accessibility Score (0-100)
- `analyze_pdf` - Document structure analysis
- `detect_headings` - Heading hierarchy detection

**Automated Remediation**
- `make_accessible` - One-click full remediation pipeline
- `add_full_structure` - Comprehensive structure tagging
- `generate_alt_text` - AI-powered image descriptions
- `fix_link_alt_texts` - Link accessibility fixes

**The Result**

| Metric | Before | After |
|--------|--------|-------|
| Typical remediation time | 2-4 hours | 2-4 minutes |
| Alt-text generation | Manual writing | AI-generated |
| Structure tagging | Click-by-click | Automated |
| Validation | Separate tool | Integrated |
| Cost per document | $50-500 | Minimal |

### Built on Open Standards

- **MCP (Model Context Protocol)** - Anthropic's standard for AI tool integration
- **veraPDF** - Industry-standard PDF/UA validation
- **PDF/UA (ISO 14289)** - International accessibility standard
"""
    },

    "getting_started": {
        "title": "Getting Started with Accessibility Remediation",
        "content": """
## Quick Start Guide

### For End Users (via MorphMind AgentLab)

The easiest way to use these tools is through [MorphMind AgentLab](https://morphmind.ai), where this agent is available as a ready-to-use accessibility assistant.

1. **Upload your PDF** - Drag and drop any document
2. **Run analysis** - Get instant accessibility score and issues
3. **Auto-remediate** - One click to fix most issues automatically
4. **Download result** - Get your accessible PDF

### For Developers

**Option 1: Use the HTTP API**
```python
import requests

# Upload and remediate
resp = requests.post("http://your-server:8080/upload",
    files={"file": open("doc.pdf", "rb")})
file_id = resp.json()["file_id"]

resp = requests.post("http://your-server:8080/agent/make-accessible",
    json={"arguments": {"pdf_path": file_id}})
print(f"Accessible PDF: {resp.json()['output_file']}")
```

**Option 2: Run Locally**
```bash
git clone https://github.com/AIScientists-Dev/Accessibility-Agent-Backend
cd Accessibility-Agent-Backend
pip install -r requirements.txt
python -m uvicorn http_server:app --port 8080
```

### Understanding Your Score

| Score | Grade | Meaning |
|-------|-------|---------|
| 90-100 | A | Excellent - PDF/UA compliant or nearly so |
| 80-89 | B | Good - Minor issues, generally accessible |
| 70-79 | C | Fair - Some barriers, needs attention |
| 60-69 | D | Poor - Significant accessibility barriers |
| 0-59 | F | Failing - Major remediation needed |

### What Gets Fixed Automatically

- Document language declaration
- Basic structure tags (headings, paragraphs)
- Alt-text for figures (AI-generated)
- Link alt-text
- XMP metadata
- Reading order (basic)

### What May Need Manual Review

- Complex tables
- Mathematical equations
- Form fields
- Color contrast issues
- Cognitive accessibility concerns
"""
    },

    "about_project": {
        "title": "About This Project",
        "content": """
## About Accessibility-Agent-Backend

### Open Source

This project is **open source under the MIT License**. We believe accessibility tools should be accessible themselves.

**Repository**: [github.com/AIScientists-Dev/Accessibility-Agent-Backend](https://github.com/AIScientists-Dev/Accessibility-Agent-Backend)

### Built With

- **MCP (Model Context Protocol)** - For standardized AI tool integration
- **FastAPI** - High-performance Python web framework
- **veraPDF** - Industry-standard PDF validation
- **Google Gemini** - Vision AI for alt-text generation
- **pikepdf & PyMuPDF** - PDF manipulation

### The Team

Developed by [AIScientists](https://aiscientists.dev) in collaboration with the [MorphMind](https://morphmind.ai) team.

### MorphMind AgentLab

This agent demonstrates the power of MorphMind AgentLab - a platform where anyone can build, deploy, and share AI agents without writing complex code.

The entire PDF Accessibility Remediator agent was built using AgentLab's visual tools, connecting to this backend via simple HTTP calls. What would traditionally require a team of developers can now be created by a single person in hours.

**Try it yourself**: [morphmind.ai](https://morphmind.ai)

### Contributing

We welcome contributions! Areas where help is needed:

- Additional language support
- Table remediation improvements
- LaTeX accessibility enhancements
- Documentation and tutorials
- Testing with diverse PDF types

### License

MIT License - Use freely, contribute back if you can.
"""
    }
}


def get_accessibility_tutorial(topic: str = None) -> dict:
    """
    Get accessibility tutorial content.

    Args:
        topic: Specific topic to retrieve. Options:
            - "what_is_accessibility" - Introduction to PDF accessibility
            - "common_struggles" - Challenges people face
            - "how_we_help" - How AI agents solve these problems
            - "getting_started" - Quick start guide
            - "about_project" - About this project and MorphMind
            - None - Returns all topics

    Returns:
        Dictionary with title and content for requested topic(s)
    """
    if topic and topic in ACCESSIBILITY_GUIDE:
        return {
            "topic": topic,
            **ACCESSIBILITY_GUIDE[topic]
        }

    # Return overview with all topics
    return {
        "title": "PDF Accessibility Guide",
        "description": "Complete guide to PDF accessibility, challenges, and AI-powered solutions",
        "topics": list(ACCESSIBILITY_GUIDE.keys()),
        "sections": ACCESSIBILITY_GUIDE,
        "quick_summary": """
PDF accessibility ensures documents can be read by everyone, including people using screen readers.
Most PDFs lack proper structure and alt-text, creating barriers for millions of users.

This AI agent automates accessibility remediation - analyzing documents, generating alt-text,
and fixing structure issues in minutes instead of hours.

Get started at morphmind.ai or deploy your own instance from our open-source repository.
"""
    }


def format_tutorial_for_display(tutorial: dict) -> str:
    """Format tutorial content for display to user."""
    if "sections" in tutorial:
        # Full guide
        output = f"# {tutorial['title']}\n\n"
        output += f"{tutorial['quick_summary']}\n\n"
        output += "---\n\n"
        output += "## Available Topics\n\n"
        for key, section in tutorial["sections"].items():
            output += f"- **{section['title']}** (`{key}`)\n"
        output += "\n*Ask about a specific topic for detailed information.*"
        return output
    else:
        # Specific topic
        return tutorial["content"]
