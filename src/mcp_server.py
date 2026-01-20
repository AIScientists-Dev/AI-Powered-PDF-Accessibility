"""
MCP Server - Model Context Protocol server for PDF accessibility.

A unified MCP server that provides:
1. LaTeX processing (preamble injection, figure detection)
2. Figure extraction and AI alt-text generation
3. PDF structure tagging
4. veraPDF validation (PDF/UA and PDF/A)

This is the single MCP server for the accessibility-mcp project.
"""

import asyncio
import json
import subprocess
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Any
import base64

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent

from .pdf_tagger import (
    get_pdf_info, create_basic_structure, is_tagged_pdf,
    create_full_structure, add_xmp_metadata, add_page_tabs_key,
    get_link_annotations, add_link_alt_texts, detect_headings, add_heading_tags
)
from .figure_extractor import extract_figures, get_figures_summary, extract_figure_context
from .ai_describer import generate_alt_text, validate_alt_text
from .tag_injector import inject_alt_text, get_existing_alt_texts
from .validator import (
    quick_accessibility_check, parse_verapdf_for_score,
    format_morphmind_report, MorphMindScore
)
from .latex_processor import (
    analyze_latex, add_accessibility_preamble, find_figures as find_latex_figures,
    add_figure_alt_text as add_latex_alt_text, add_all_figure_alt_texts,
    extract_title_from_latex, extract_author_from_latex,
    check_figure_files, get_missing_figures_prompt, resolve_image_path
)
from .accessibility_guide import get_accessibility_tutorial, format_tutorial_for_display


# ============================================
# veraPDF integration
# ============================================

def find_verapdf() -> str:
    """Find veraPDF executable path."""
    paths = [
        "/opt/homebrew/bin/verapdf",
        "/usr/local/bin/verapdf",
        os.path.expanduser("~/bin/verapdf"),
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    try:
        result = subprocess.run(["which", "verapdf"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    raise FileNotFoundError("veraPDF not found. Please install it: brew install verapdf")


def parse_verapdf_xml(xml_content: str) -> dict[str, Any]:
    """Parse veraPDF XML output into structured JSON."""
    try:
        root = ET.fromstring(xml_content)
        result = {
            "compliant": False,
            "profile": None,
            "summary": {
                "passed_rules": 0,
                "failed_rules": 0,
                "passed_checks": 0,
                "failed_checks": 0,
            },
            "failures": [],
        }

        batch_summary = root.find(".//batchSummary")
        if batch_summary is not None:
            result["summary"]["total_jobs"] = int(batch_summary.get("totalJobs", "0"))
            result["summary"]["failed_to_parse"] = int(batch_summary.get("failedToParse", "0"))

        validation_report = root.find(".//validationReport")
        if validation_report is not None:
            result["compliant"] = validation_report.get("isCompliant", "false").lower() == "true"
            result["profile"] = validation_report.get("profileName", "Unknown")

            details = validation_report.find("details")
            if details is not None:
                result["summary"]["passed_rules"] = int(details.get("passedRules", 0))
                result["summary"]["failed_rules"] = int(details.get("failedRules", 0))
                result["summary"]["passed_checks"] = int(details.get("passedChecks", 0))
                result["summary"]["failed_checks"] = int(details.get("failedChecks", 0))

                for rule in details.findall(".//rule"):
                    if rule.get("status") == "failed":
                        failure = {
                            "clause": rule.get("clause", ""),
                            "test_number": rule.get("testNumber", ""),
                            "description": "",
                            "checks": [],
                        }
                        desc = rule.find("description")
                        if desc is not None and desc.text:
                            failure["description"] = desc.text.strip()
                        for check in rule.findall("check"):
                            if check.get("status") == "failed":
                                ctx = check.find("context")
                                failure["checks"].append({
                                    "context": ctx.text if ctx is not None else "",
                                })
                        result["failures"].append(failure)
        return result
    except ET.ParseError as e:
        return {"error": f"Failed to parse XML: {str(e)}", "raw_xml": xml_content[:2000]}


def run_verapdf(pdf_path: str, profile: str = "ua1") -> dict[str, Any]:
    """Run veraPDF validation on a PDF file."""
    verapdf_path = find_verapdf()
    valid_profiles = ["ua1", "ua2", "1a", "1b", "2a", "2b", "3a", "3b", "4", "4e", "4f"]
    if profile not in valid_profiles:
        return {"error": f"Invalid profile. Valid options: {', '.join(valid_profiles)}"}
    if not os.path.exists(pdf_path):
        return {"error": f"PDF file not found: {pdf_path}"}

    cmd = [verapdf_path, "--format", "xml", "--flavour", profile, pdf_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode not in [0, 1]:
            return {"error": f"veraPDF error: {result.stderr}", "returncode": result.returncode}
        parsed = parse_verapdf_xml(result.stdout)
        parsed["pdf_path"] = pdf_path
        parsed["profile_used"] = profile
        return parsed
    except subprocess.TimeoutExpired:
        return {"error": "Validation timed out (120s limit)"}
    except Exception as e:
        return {"error": f"Execution error: {str(e)}"}


# Create the MCP server
server = Server("accessibility-mcp")


@server.list_tools()
async def list_tools():
    """List available tools."""
    return [
        Tool(
            name="analyze_pdf",
            description="Analyze a PDF for accessibility status. Returns info about tags, structure, figures, and existing alt-text.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file",
                    },
                },
                "required": ["pdf_path"],
            },
        ),
        Tool(
            name="extract_figures",
            description="Extract all figures/images from a PDF. Returns figure metadata and can optionally save images to disk.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file",
                    },
                    "save_to": {
                        "type": "string",
                        "description": "Optional directory to save extracted images",
                    },
                    "include_context": {
                        "type": "boolean",
                        "description": "Include surrounding text context for each figure",
                        "default": True,
                    },
                },
                "required": ["pdf_path"],
            },
        ),
        Tool(
            name="generate_alt_text",
            description="Generate alt-text for a specific figure using AI. Can use image data or a saved image file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "Path to the image file",
                    },
                    "image_base64": {
                        "type": "string",
                        "description": "Base64-encoded image data (alternative to image_path)",
                    },
                    "context": {
                        "type": "string",
                        "description": "Context about the image (caption, surrounding text)",
                    },
                    "document_type": {
                        "type": "string",
                        "description": "Type of document (e.g., 'academic paper', 'textbook')",
                        "default": "academic paper",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="add_alt_text",
            description="Add alt-text to a specific figure in the PDF and save the result.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Path to the PDF file",
                    },
                    "page_num": {
                        "type": "integer",
                        "description": "Page number (0-indexed)",
                    },
                    "figure_index": {
                        "type": "integer",
                        "description": "Index of the figure on the page",
                    },
                    "alt_text": {
                        "type": "string",
                        "description": "The alt-text to add",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional output path (defaults to _accessible suffix)",
                    },
                },
                "required": ["pdf_path", "page_num", "figure_index", "alt_text"],
            },
        ),
        Tool(
            name="make_accessible",
            description="Full pipeline: analyze PDF, extract figures, generate alt-text, and create accessible PDF.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Path to the input PDF",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional output path",
                    },
                    "document_type": {
                        "type": "string",
                        "description": "Type of document for AI context",
                        "default": "academic paper",
                    },
                },
                "required": ["pdf_path"],
            },
        ),
        Tool(
            name="validate_accessibility",
            description="Quick accessibility validation check for a PDF.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Path to the PDF file",
                    },
                },
                "required": ["pdf_path"],
            },
        ),
        Tool(
            name="add_structure_tags",
            description="Add basic PDF/UA structure tags to an untagged PDF.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Path to the PDF file",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional output path",
                    },
                },
                "required": ["pdf_path"],
            },
        ),
        Tool(
            name="add_full_structure",
            description="Add comprehensive PDF/UA structure including XMP metadata, page tabs, headings, and link alt-text. This is an enhanced version of add_structure_tags that addresses more PDF/UA compliance issues.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Path to the PDF file",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional output path",
                    },
                    "title": {
                        "type": "string",
                        "description": "Document title (auto-detected if not provided)",
                    },
                    "author": {
                        "type": "string",
                        "description": "Document author",
                        "default": "",
                    },
                    "lang": {
                        "type": "string",
                        "description": "Document language code",
                        "default": "en-US",
                    },
                    "tag_headings": {
                        "type": "boolean",
                        "description": "Whether to detect and tag headings (H1, H2, H3)",
                        "default": True,
                    },
                    "fix_links": {
                        "type": "boolean",
                        "description": "Whether to add alt-text to link annotations",
                        "default": True,
                    },
                },
                "required": ["pdf_path"],
            },
        ),
        Tool(
            name="detect_headings",
            description="Detect potential headings in a PDF based on font size and formatting. Returns a list of detected headings with their level (H1, H2, H3), text, and location.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Path to the PDF file",
                    },
                },
                "required": ["pdf_path"],
            },
        ),
        Tool(
            name="tag_headings",
            description="Add heading structure elements (H1, H2, H3) to the PDF structure tree based on detected headings.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Path to the PDF file",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional output path",
                    },
                },
                "required": ["pdf_path"],
            },
        ),
        Tool(
            name="get_link_annotations",
            description="Get all link annotations from a PDF with their current alt-text status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Path to the PDF file",
                    },
                },
                "required": ["pdf_path"],
            },
        ),
        Tool(
            name="fix_link_alt_texts",
            description="Add alt-text (Contents key) to link annotations that are missing them. PDF/UA requires all links to have alternative text.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Path to the PDF file",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional output path",
                    },
                },
                "required": ["pdf_path"],
            },
        ),
        # LaTeX tools
        Tool(
            name="analyze_latex",
            description="Analyze a LaTeX file for accessibility features. Returns info about packages, figures, and recommendations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "latex_path": {
                        "type": "string",
                        "description": "Path to the .tex file",
                    },
                },
                "required": ["latex_path"],
            },
        ),
        Tool(
            name="prepare_latex",
            description="Add accessibility preamble to LaTeX file. This prepares the file for Overleaf compilation with proper PDF/UA tags.",
            inputSchema={
                "type": "object",
                "properties": {
                    "latex_path": {
                        "type": "string",
                        "description": "Path to the .tex file",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional output path (defaults to _accessible.tex suffix)",
                    },
                    "title": {
                        "type": "string",
                        "description": "Document title (auto-detected if not provided)",
                    },
                    "author": {
                        "type": "string",
                        "description": "Document author (auto-detected if not provided)",
                    },
                    "lang": {
                        "type": "string",
                        "description": "Document language code",
                        "default": "en-US",
                    },
                },
                "required": ["latex_path"],
            },
        ),
        Tool(
            name="add_latex_alt_text",
            description="Add alt-text to a specific figure in the LaTeX file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "latex_path": {
                        "type": "string",
                        "description": "Path to the .tex file",
                    },
                    "figure_index": {
                        "type": "integer",
                        "description": "0-indexed figure number",
                    },
                    "alt_text": {
                        "type": "string",
                        "description": "Alt-text to add",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional output path",
                    },
                },
                "required": ["latex_path", "figure_index", "alt_text"],
            },
        ),
        Tool(
            name="make_latex_accessible",
            description="Full pipeline for LaTeX: analyze, add preamble, extract figures from compiled PDF, generate alt-text, and update LaTeX with alt-texts. User should compile on Overleaf between steps.",
            inputSchema={
                "type": "object",
                "properties": {
                    "latex_path": {
                        "type": "string",
                        "description": "Path to the .tex file",
                    },
                    "pdf_path": {
                        "type": "string",
                        "description": "Path to the compiled PDF (from Overleaf)",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional output path for the modified .tex file",
                    },
                },
                "required": ["latex_path", "pdf_path"],
            },
        ),
        Tool(
            name="check_latex_figures",
            description="Check which figure image files exist locally and which are missing. Use this to identify files the user needs to upload.",
            inputSchema={
                "type": "object",
                "properties": {
                    "latex_path": {
                        "type": "string",
                        "description": "Path to the .tex file",
                    },
                },
                "required": ["latex_path"],
            },
        ),
        Tool(
            name="process_latex_figures",
            description="Process LaTeX file by reading local figure files directly (no PDF needed). Generates alt-text for each figure and updates the LaTeX. Use check_latex_figures first to see which files are available.",
            inputSchema={
                "type": "object",
                "properties": {
                    "latex_path": {
                        "type": "string",
                        "description": "Path to the .tex file",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional output path for the modified .tex file",
                    },
                    "figure_dir": {
                        "type": "string",
                        "description": "Optional directory where figure files are located (if not in standard locations)",
                    },
                },
                "required": ["latex_path"],
            },
        ),
        Tool(
            name="add_figure_file",
            description="Register a figure file location for a specific figure reference. Use this when the user provides the path to a missing figure.",
            inputSchema={
                "type": "object",
                "properties": {
                    "latex_path": {
                        "type": "string",
                        "description": "Path to the .tex file",
                    },
                    "figure_ref": {
                        "type": "string",
                        "description": "The figure reference as it appears in LaTeX (e.g., 'figures/chart')",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Actual path to the image file",
                    },
                },
                "required": ["latex_path", "figure_ref", "file_path"],
            },
        ),
        # veraPDF validation tools
        Tool(
            name="validate_pdfua",
            description="Validate a PDF against PDF/UA (Universal Accessibility) standard using veraPDF. Returns a MorphMind Accessibility Score (0-100) along with detailed compliance results. Checks document tagging, reading order, alt text, table markup, navigation aids, and language specification.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file to validate",
                    },
                    "profile": {
                        "type": "string",
                        "enum": ["ua1", "ua2"],
                        "default": "ua1",
                        "description": "PDF/UA version: ua1 (PDF/UA-1) or ua2 (PDF/UA-2)",
                    },
                },
                "required": ["pdf_path"],
            },
        ),
        Tool(
            name="validate_pdfa",
            description="Validate a PDF against PDF/A (archival) standard using veraPDF. Profiles: 1b/2b/3b for basic, 1a/2a/3a for tagged structure, 4 for latest.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file to validate",
                    },
                    "profile": {
                        "type": "string",
                        "enum": ["1a", "1b", "2a", "2b", "3a", "3b", "4", "4e", "4f"],
                        "default": "2b",
                        "description": "PDF/A profile to validate against",
                    },
                },
                "required": ["pdf_path"],
            },
        ),
        Tool(
            name="get_validation_profiles",
            description="List all available veraPDF validation profiles with descriptions.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="check_verapdf_installation",
            description="Check if veraPDF is properly installed and return version info.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        # Educational tool
        Tool(
            name="get_accessibility_tutorial",
            description="Get educational content about PDF accessibility, common challenges, and how AI agents help. Perfect for users who want to learn about accessibility or understand what this tool does. Topics: 'what_is_accessibility', 'common_struggles', 'how_we_help', 'getting_started', 'about_project'. Leave topic empty for overview.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Specific topic to learn about. Options: what_is_accessibility, common_struggles, how_we_help, getting_started, about_project. Leave empty for overview.",
                        "enum": ["what_is_accessibility", "common_struggles", "how_we_help", "getting_started", "about_project"],
                    },
                },
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""

    if name == "analyze_pdf":
        pdf_path = arguments["pdf_path"]

        # Get basic info
        info = get_pdf_info(pdf_path)

        # Get figures
        figures = extract_figures(pdf_path)
        figures_summary = get_figures_summary(figures)

        # Get existing alt-texts
        existing_alts = get_existing_alt_texts(pdf_path)

        # Quick validation
        validation = quick_accessibility_check(pdf_path)

        result = {
            "pdf_info": info,
            "figures": figures_summary,
            "existing_alt_texts": existing_alts,
            "validation": validation,
            "recommendations": [],
        }

        # Add recommendations
        if not info["is_tagged"]:
            result["recommendations"].append("Add structure tags using add_structure_tags tool")
        if figures_summary["count"] > len([a for a in existing_alts if a.get("alt_text")]):
            result["recommendations"].append("Generate alt-text for figures using make_accessible tool")
        if not info.get("has_lang"):
            result["recommendations"].append("Document needs language attribute")
        if not info.get("has_title"):
            result["recommendations"].append("Document needs title metadata")

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "extract_figures":
        pdf_path = arguments["pdf_path"]
        save_to = arguments.get("save_to")
        include_context = arguments.get("include_context", True)

        figures = extract_figures(pdf_path)
        summary = get_figures_summary(figures)

        # Add context if requested
        if include_context:
            for i, fig in enumerate(figures):
                context = extract_figure_context(pdf_path, fig)
                if i < len(summary["figures"]):
                    summary["figures"][i]["context"] = context

        # Save images if requested
        if save_to:
            from .figure_extractor import save_figures
            saved_paths = save_figures(figures, save_to)
            summary["saved_paths"] = saved_paths

        return [TextContent(type="text", text=json.dumps(summary, indent=2))]

    elif name == "generate_alt_text":
        image_path = arguments.get("image_path")
        image_base64 = arguments.get("image_base64")
        context = arguments.get("context", "")
        document_type = arguments.get("document_type", "academic paper")

        if image_path:
            image_data = Path(image_path).read_bytes()
        elif image_base64:
            image_data = base64.b64decode(image_base64)
        else:
            return [TextContent(type="text", text="Error: Must provide image_path or image_base64")]

        alt_text = generate_alt_text(image_data, context, document_type)
        validation = validate_alt_text(alt_text)

        result = {
            "alt_text": alt_text,
            "validation": validation,
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "add_alt_text":
        pdf_path = arguments["pdf_path"]
        page_num = arguments["page_num"]
        figure_index = arguments["figure_index"]
        alt_text = arguments["alt_text"]
        output_path = arguments.get("output_path")

        from .tag_injector import inject_single_alt_text
        output = inject_single_alt_text(pdf_path, page_num, figure_index, alt_text, output_path)

        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "output_path": output,
            "message": f"Added alt-text to figure on page {page_num + 1}",
        }, indent=2))]

    elif name == "make_accessible":
        pdf_path = arguments["pdf_path"]
        output_path = arguments.get("output_path")
        document_type = arguments.get("document_type", "academic paper")

        # Step 1: Create full structure (includes XMP, tabs, headings, links)
        structure_result = create_full_structure(
            pdf_path,
            output_path=None,  # Temp output
            tag_headings=True,
            fix_links=True,
        )
        working_path = structure_result["output_path"]

        # Step 2: Extract figures
        figures = extract_figures(working_path)

        # Step 3: Generate alt-text for each figure
        figures_with_alt = []
        for fig in figures:
            context = extract_figure_context(working_path, fig)
            alt_text = generate_alt_text(fig.image_data, context, document_type)
            figures_with_alt.append((fig, alt_text))

        # Step 4: Inject figure alt-text
        if figures_with_alt:
            output = inject_alt_text(working_path, figures_with_alt, output_path)
        else:
            # No figures, use the structured version
            if output_path:
                import shutil
                shutil.copy(working_path, output_path)
                output = output_path
            else:
                output = working_path

        # Step 5: Validate result
        validation = quick_accessibility_check(output)

        result = {
            "success": True,
            "output_path": output,
            "figures_processed": len(figures_with_alt),
            "alt_texts": [
                {"page": f.page_num + 1, "alt_text": alt[:100] + "..." if len(alt) > 100 else alt}
                for f, alt in figures_with_alt
            ],
            "structure_enhancements": {
                "xmp_metadata_added": structure_result.get("xmp_added", False),
                "tabs_pages_modified": structure_result.get("tabs_pages_modified", 0),
                "headings_tagged": structure_result.get("headings_tagged", 0),
                "links_fixed": structure_result.get("links_fixed", 0),
            },
            "validation": validation,
        }

        # Clean up intermediate file if different from output
        if working_path != output:
            try:
                Path(working_path).unlink(missing_ok=True)
            except Exception:
                pass

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "validate_accessibility":
        pdf_path = arguments["pdf_path"]
        result = quick_accessibility_check(pdf_path)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "add_structure_tags":
        pdf_path = arguments["pdf_path"]
        output_path = arguments.get("output_path")

        output = create_basic_structure(pdf_path, output_path)

        result = {
            "success": True,
            "output_path": output,
            "new_info": get_pdf_info(output),
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "add_full_structure":
        pdf_path = arguments["pdf_path"]
        output_path = arguments.get("output_path")
        title = arguments.get("title")
        author = arguments.get("author", "")
        lang = arguments.get("lang", "en-US")
        tag_headings = arguments.get("tag_headings", True)
        fix_links = arguments.get("fix_links", True)

        result = create_full_structure(
            pdf_path,
            output_path=output_path,
            title=title,
            author=author,
            lang=lang,
            tag_headings=tag_headings,
            fix_links=fix_links,
        )

        result["success"] = True
        result["new_info"] = get_pdf_info(result["output_path"])

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "detect_headings":
        pdf_path = arguments["pdf_path"]
        headings = detect_headings(pdf_path)

        result = {
            "pdf_path": pdf_path,
            "headings_count": len(headings),
            "headings": [
                {
                    "level": h["level"],
                    "text": h["text"][:100] + "..." if len(h["text"]) > 100 else h["text"],
                    "page": h["page"] + 1,  # 1-indexed for display
                    "font_size": round(h["font_size"], 1),
                    "is_bold": h["is_bold"],
                }
                for h in headings
            ],
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "tag_headings":
        pdf_path = arguments["pdf_path"]
        output_path = arguments.get("output_path")

        # First detect headings
        headings = detect_headings(pdf_path)

        if not headings:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "message": "No headings detected in the PDF",
            }, indent=2))]

        # Add heading tags
        output = add_heading_tags(pdf_path, headings, output_path)

        result = {
            "success": True,
            "output_path": output,
            "headings_tagged": len(headings),
            "headings": [
                {"level": h["level"], "text": h["text"][:50], "page": h["page"] + 1}
                for h in headings[:10]
            ],
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "get_link_annotations":
        pdf_path = arguments["pdf_path"]
        links = get_link_annotations(pdf_path)

        result = {
            "pdf_path": pdf_path,
            "total_links": len(links),
            "links_with_alt_text": len([l for l in links if l["has_contents"]]),
            "links_missing_alt_text": len([l for l in links if not l["has_contents"]]),
            "links": [
                {
                    "page": l["page"] + 1,
                    "uri": l["uri"][:80] + "..." if l["uri"] and len(l["uri"]) > 80 else l["uri"],
                    "has_alt_text": l["has_contents"],
                    "alt_text": l["contents"][:50] + "..." if l["contents"] and len(l["contents"]) > 50 else l["contents"],
                }
                for l in links
            ],
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "fix_link_alt_texts":
        pdf_path = arguments["pdf_path"]
        output_path = arguments.get("output_path")

        output, links_fixed = add_link_alt_texts(pdf_path, output_path)

        result = {
            "success": True,
            "output_path": output,
            "links_fixed": links_fixed,
            "message": f"Added alt-text to {links_fixed} link annotations",
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # LaTeX tools
    elif name == "analyze_latex":
        latex_path = arguments["latex_path"]
        content = Path(latex_path).read_text()
        analysis = analyze_latex(content)
        analysis["file_path"] = latex_path
        return [TextContent(type="text", text=json.dumps(analysis, indent=2))]

    elif name == "prepare_latex":
        latex_path = arguments["latex_path"]
        output_path = arguments.get("output_path")
        lang = arguments.get("lang", "en-US")

        content = Path(latex_path).read_text()

        # Auto-detect title/author if not provided
        title = arguments.get("title") or extract_title_from_latex(content) or Path(latex_path).stem
        author = arguments.get("author") or extract_author_from_latex(content) or ""

        # Add preamble
        modified = add_accessibility_preamble(content, title=title, author=author, lang=lang)

        # Write output
        if output_path is None:
            p = Path(latex_path)
            output_path = str(p.parent / f"{p.stem}_accessible{p.suffix}")

        Path(output_path).write_text(modified)

        result = {
            "success": True,
            "output_path": output_path,
            "title": title,
            "author": author,
            "lang": lang,
            "message": "LaTeX file prepared. Upload to Overleaf and compile, then use make_latex_accessible with the PDF.",
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "add_latex_alt_text":
        latex_path = arguments["latex_path"]
        figure_index = arguments["figure_index"]
        alt_text = arguments["alt_text"]
        output_path = arguments.get("output_path")

        content = Path(latex_path).read_text()
        modified = add_latex_alt_text(content, figure_index, alt_text)

        if output_path is None:
            output_path = latex_path  # Overwrite

        Path(output_path).write_text(modified)

        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "output_path": output_path,
            "message": f"Added alt-text to figure {figure_index}",
        }, indent=2))]

    elif name == "make_latex_accessible":
        latex_path = arguments["latex_path"]
        pdf_path = arguments["pdf_path"]
        output_path = arguments.get("output_path")

        latex_content = Path(latex_path).read_text()

        # Step 1: Ensure preamble is added
        if "ACCESSIBILITY PREAMBLE" not in latex_content:
            title = extract_title_from_latex(latex_content) or Path(latex_path).stem
            author = extract_author_from_latex(latex_content) or ""
            latex_content = add_accessibility_preamble(latex_content, title=title, author=author)

        # Step 2: Find figures in LaTeX
        latex_figures = find_latex_figures(latex_content)

        # Step 3: Extract figures from PDF and generate alt-text
        pdf_figures = extract_figures(pdf_path)
        alt_texts = []

        for i, pdf_fig in enumerate(pdf_figures):
            context = extract_figure_context(pdf_path, pdf_fig)
            # Also add LaTeX caption as context if available
            if i < len(latex_figures) and latex_figures[i].caption:
                context += f"\nCaption: {latex_figures[i].caption}"
            alt_text = generate_alt_text(pdf_fig.image_data, context)
            alt_texts.append(alt_text)

        # Step 4: Add alt-texts to LaTeX (if we have matching figures)
        if alt_texts and len(alt_texts) <= len(latex_figures):
            latex_content = add_all_figure_alt_texts(latex_content, alt_texts)

        # Step 5: Write output
        if output_path is None:
            p = Path(latex_path)
            output_path = str(p.parent / f"{p.stem}_accessible{p.suffix}")

        Path(output_path).write_text(latex_content)

        result = {
            "success": True,
            "output_path": output_path,
            "figures_in_latex": len(latex_figures),
            "figures_in_pdf": len(pdf_figures),
            "alt_texts_generated": len(alt_texts),
            "alt_texts": [
                {"figure": i, "alt_text": alt[:100] + "..." if len(alt) > 100 else alt}
                for i, alt in enumerate(alt_texts)
            ],
            "next_step": "Upload the modified LaTeX to Overleaf and recompile for the accessible PDF.",
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "check_latex_figures":
        latex_path = arguments["latex_path"]
        latex_content = Path(latex_path).read_text()

        file_status = check_figure_files(latex_content, latex_path)

        result = {
            "latex_path": latex_path,
            "total_figures": file_status["total"],
            "found_count": file_status["found_count"],
            "missing_count": file_status["missing_count"],
            "found": [
                {
                    "index": f.figure_index,
                    "ref": f.image_ref,
                    "path": str(f.resolved_path),
                    "caption": f.caption[:50] + "..." if f.caption and len(f.caption) > 50 else f.caption,
                    "has_alt_text": f.has_alt_text,
                }
                for f in file_status["found"]
            ],
            "missing": [
                {
                    "index": f.figure_index,
                    "ref": f.image_ref,
                    "caption": f.caption[:50] + "..." if f.caption and len(f.caption) > 50 else f.caption,
                }
                for f in file_status["missing"]
            ],
        }

        if file_status["missing"]:
            result["user_prompt"] = get_missing_figures_prompt(file_status["missing"])

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "process_latex_figures":
        latex_path = arguments["latex_path"]
        output_path = arguments.get("output_path")
        figure_dir = arguments.get("figure_dir")

        latex_content = Path(latex_path).read_text()
        base_dir = Path(latex_path).parent

        # Add figure_dir to search paths if provided
        extra_dirs = [figure_dir] if figure_dir else None

        # Step 1: Ensure preamble
        if "ACCESSIBILITY PREAMBLE" not in latex_content:
            title = extract_title_from_latex(latex_content) or Path(latex_path).stem
            author = extract_author_from_latex(latex_content) or ""
            latex_content = add_accessibility_preamble(latex_content, title=title, author=author)

        # Step 2: Find figures and check files
        file_status = check_figure_files(latex_content, latex_path)

        # Step 3: Generate alt-text for found figures
        alt_texts = []
        processed = []
        skipped = []

        for fig_status in file_status["all"]:
            if fig_status.resolved_path and fig_status.resolved_path.exists():
                # Read image and generate alt-text
                image_data = fig_status.resolved_path.read_bytes()
                context = f"Caption: {fig_status.caption}" if fig_status.caption else ""
                alt_text = generate_alt_text(image_data, context)
                alt_texts.append(alt_text)
                processed.append({
                    "index": fig_status.figure_index,
                    "ref": fig_status.image_ref,
                    "alt_text": alt_text[:100] + "..." if len(alt_text) > 100 else alt_text,
                })
            else:
                alt_texts.append(None)  # Placeholder
                skipped.append({
                    "index": fig_status.figure_index,
                    "ref": fig_status.image_ref,
                    "reason": "File not found",
                })

        # Step 4: Add alt-texts to LaTeX (only for found figures)
        latex_figures = find_latex_figures(latex_content)
        for i in range(len(latex_figures) - 1, -1, -1):
            if i < len(alt_texts) and alt_texts[i] is not None:
                latex_content = add_latex_alt_text(latex_content, i, alt_texts[i])

        # Step 5: Write output
        if output_path is None:
            p = Path(latex_path)
            output_path = str(p.parent / f"{p.stem}_accessible{p.suffix}")

        Path(output_path).write_text(latex_content)

        result = {
            "success": True,
            "output_path": output_path,
            "processed": processed,
            "skipped": skipped,
            "next_step": "Upload the modified LaTeX to Overleaf and compile to get the accessible PDF.",
        }

        if skipped:
            result["note"] = f"{len(skipped)} figures were skipped because their image files were not found. Use check_latex_figures to see details."

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "add_figure_file":
        # This is a helper for the agent to track user-provided file locations
        latex_path = arguments["latex_path"]
        figure_ref = arguments["figure_ref"]
        file_path = arguments["file_path"]

        # Verify the file exists
        if not Path(file_path).exists():
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"File not found: {file_path}",
            }, indent=2))]

        result = {
            "success": True,
            "figure_ref": figure_ref,
            "file_path": file_path,
            "file_exists": True,
            "message": f"Registered {figure_ref} -> {file_path}. You can now use process_latex_figures with figure_dir pointing to the directory containing this file.",
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # veraPDF validation tools
    elif name == "validate_pdfua":
        pdf_path = arguments.get("pdf_path")
        profile = arguments.get("profile", "ua1")

        result = run_verapdf(pdf_path, profile)

        if "error" in result:
            output = f"**Validation Error**\n{result['error']}"
        else:
            status = "COMPLIANT" if result["compliant"] else "NON-COMPLIANT"

            # Calculate MorphMind Accessibility Score
            failures_for_score = []
            for failure in result.get("failures", []):
                failures_for_score.append({
                    "clause": failure.get("clause", ""),
                    "test": failure.get("test_number"),
                    "message": failure.get("description", ""),
                    "count": len(failure.get("checks", [1])),
                })

            from .validator import calculate_morphmind_score
            morphmind = calculate_morphmind_score(
                passed_rules=result['summary']['passed_rules'],
                failed_rules=result['summary']['failed_rules'],
                passed_checks=result['summary']['passed_checks'],
                failed_checks=result['summary']['failed_checks'],
                failures=failures_for_score,
            )

            # Build output with MorphMind score prominently displayed
            output = f"""
╔══════════════════════════════════════════════════════════════╗
║             MorphMind Accessibility Score                    ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║          SCORE: {morphmind.score:3d}/100    GRADE: {morphmind.grade}                       ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

**PDF/UA Validation Result: {status}**

**Profile:** {result.get('profile', profile)}
**File:** {result.get('pdf_path', pdf_path)}

**Summary:**
- Passed Rules: {result['summary']['passed_rules']}
- Failed Rules: {result['summary']['failed_rules']}
- Passed Checks: {result['summary']['passed_checks']:,}
- Failed Checks: {result['summary']['failed_checks']:,}

**Issues by Severity:**
"""
            severity_icons = {"critical": "🔴", "serious": "🟠", "moderate": "🟡", "minor": "🟢"}
            for sev, count in morphmind.issues_by_severity.items():
                if count > 0:
                    icon = severity_icons.get(sev, "⚪")
                    output += f"- {icon} {sev.capitalize()}: {count}\n"

            if morphmind.category_scores:
                output += "\n**Category Breakdown:**\n"
                for cat, cat_score in morphmind.category_scores.items():
                    bar_len = cat_score // 10
                    bar = "█" * bar_len + "░" * (10 - bar_len)
                    output += f"- {cat.capitalize():12} [{bar}] {cat_score}%\n"

            if result["failures"]:
                output += "\n**Failures:**\n"
                for i, failure in enumerate(result["failures"][:20], 1):
                    output += f"\n{i}. **Clause {failure['clause']}** (Test {failure['test_number']})\n"
                    output += f"   {failure['description']}\n"
                    for check in failure['checks'][:3]:
                        if check['context']:
                            output += f"   - Context: `{check['context'][:100]}`\n"
                if len(result["failures"]) > 20:
                    output += f"\n... and {len(result['failures']) - 20} more failures"

            output += """

---
*Score provided by **MorphMind**. This weighted scoring methodology may differ
from other accessibility tools (UDOIT, SiteImprove, etc.). Use as a guide
alongside manual accessibility review.*
"""

        return [TextContent(type="text", text=output)]

    elif name == "validate_pdfa":
        pdf_path = arguments.get("pdf_path")
        profile = arguments.get("profile", "2b")

        result = run_verapdf(pdf_path, profile)

        if "error" in result:
            output = f"**Validation Error**\n{result['error']}"
        else:
            status = "COMPLIANT" if result["compliant"] else "NON-COMPLIANT"
            output = f"""**PDF/A Validation Result: {status}**

**Profile:** {result.get('profile', profile)}
**File:** {result.get('pdf_path', pdf_path)}

**Summary:**
- Passed Rules: {result['summary']['passed_rules']}
- Failed Rules: {result['summary']['failed_rules']}
- Passed Checks: {result['summary']['passed_checks']}
- Failed Checks: {result['summary']['failed_checks']}
"""
            if result["failures"]:
                output += "\n**Failures:**\n"
                for i, failure in enumerate(result["failures"][:20], 1):
                    output += f"\n{i}. **Clause {failure['clause']}** (Test {failure['test_number']})\n"
                    output += f"   {failure['description']}\n"

        return [TextContent(type="text", text=output)]

    elif name == "get_validation_profiles":
        profiles = """**Available veraPDF Validation Profiles**

**PDF/UA (Accessibility):**
| Profile | Standard | Description |
|---------|----------|-------------|
| `ua1` | PDF/UA-1 (ISO 14289-1) | Universal Accessibility standard |
| `ua2` | PDF/UA-2 | Updated accessibility standard |

**PDF/A (Archival):**
| Profile | Standard | Description |
|---------|----------|-------------|
| `1a` | PDF/A-1a | Level A conformance (tagged, Unicode) |
| `1b` | PDF/A-1b | Level B conformance (visual only) |
| `2a` | PDF/A-2a | Level A + JPEG2000, transparency |
| `2b` | PDF/A-2b | Level B + JPEG2000, transparency |
| `3a` | PDF/A-3a | Level A + embedded files |
| `3b` | PDF/A-3b | Level B + embedded files |
| `4` | PDF/A-4 | Latest version, modern features |
| `4e` | PDF/A-4e | Engineering documents |
| `4f` | PDF/A-4f | With embedded files |

**For accessibility checking, use `ua1` (PDF/UA-1).**
"""
        return [TextContent(type="text", text=profiles)]

    elif name == "check_verapdf_installation":
        try:
            verapdf_path = find_verapdf()
            result = subprocess.run(
                [verapdf_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            output = f"""**veraPDF Installation: OK**

**Path:** `{verapdf_path}`
**Version:**
```
{result.stdout.strip()}
```
"""
        except FileNotFoundError as e:
            output = f"**veraPDF Installation: NOT FOUND**\n\n{str(e)}"
        except Exception as e:
            output = f"**veraPDF Installation: ERROR**\n\n{str(e)}"

        return [TextContent(type="text", text=output)]

    elif name == "get_accessibility_tutorial":
        topic = arguments.get("topic")
        tutorial = get_accessibility_tutorial(topic)
        output = format_tutorial_for_display(tutorial)
        return [TextContent(type="text", text=output)]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
