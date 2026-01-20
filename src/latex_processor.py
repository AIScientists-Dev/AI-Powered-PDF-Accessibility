"""
LaTeX Processor - Add accessibility preamble to LaTeX files.

This module:
1. Analyzes LaTeX files for accessibility issues
2. Injects the accessibility preamble (axessibility, hyperref, etc.)
3. Adds alt-text to figure environments
"""

import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass


# Accessibility preamble to inject
ACCESSIBILITY_PREAMBLE = r"""
% ============================================
% ACCESSIBILITY PREAMBLE (auto-generated)
% ============================================
\usepackage{accsupp}        % Actual text for copy/paste
\usepackage{axessibility}   % Tagged PDF structure
\usepackage[
    pdfa,
    pdfusetitle,
    bookmarks=true,
    bookmarksnumbered=true,
    colorlinks=true,
    linkcolor=blue,
    citecolor=blue,
    urlcolor=blue,
    pdfencoding=auto,
    pdflang={en-US}
]{hyperref}
\usepackage{pdfcomment}     % For tooltips/alt-text

% Set document metadata
\hypersetup{
    pdftitle={},
    pdfauthor={},
    pdfsubject={},
    pdfkeywords={}
}

% Macro for accessible figures with alt-text
\newcommand{\accessiblefigure}[3]{%
    % #1 = alt-text, #2 = includegraphics options, #3 = image path
    \pdftooltip{\includegraphics[#2]{#3}}{#1}%
}
% ============================================
"""

# Minimal preamble (if axessibility causes issues)
MINIMAL_PREAMBLE = r"""
% ============================================
% ACCESSIBILITY PREAMBLE (minimal)
% ============================================
\usepackage[
    pdfusetitle,
    bookmarks=true,
    colorlinks=true,
    pdflang={en-US}
]{hyperref}

\hypersetup{
    pdftitle={},
    pdfauthor={}
}
% ============================================
"""


@dataclass
class LaTeXFigure:
    """Represents a figure in a LaTeX file."""
    start_pos: int
    end_pos: int
    full_match: str
    image_path: str
    caption: Optional[str]
    label: Optional[str]
    has_alt_text: bool = False
    alt_text: Optional[str] = None


def analyze_latex(latex_content: str) -> Dict:
    """
    Analyze LaTeX content for accessibility features.

    Returns dict with analysis results.
    """
    results = {
        "has_hyperref": False,
        "has_axessibility": False,
        "has_accessibility_preamble": False,
        "has_pdflang": False,
        "has_pdftitle": False,
        "figures": [],
        "figures_with_alt": 0,
        "recommendations": [],
    }

    # Check for packages
    results["has_hyperref"] = bool(re.search(r'\\usepackage.*\{hyperref\}', latex_content))
    results["has_axessibility"] = bool(re.search(r'\\usepackage.*\{axessibility\}', latex_content))
    results["has_pdflang"] = bool(re.search(r'pdflang\s*=', latex_content))
    results["has_pdftitle"] = bool(re.search(r'pdftitle\s*=\s*\{[^}]+\}', latex_content))

    # Check for our accessibility preamble marker
    results["has_accessibility_preamble"] = "ACCESSIBILITY PREAMBLE" in latex_content

    # Find figures
    figures = find_figures(latex_content)
    results["figures"] = [
        {
            "image_path": f.image_path,
            "caption": f.caption[:50] + "..." if f.caption and len(f.caption) > 50 else f.caption,
            "has_alt_text": f.has_alt_text,
        }
        for f in figures
    ]
    results["figures_with_alt"] = sum(1 for f in figures if f.has_alt_text)

    # Generate recommendations
    if not results["has_accessibility_preamble"]:
        results["recommendations"].append("Add accessibility preamble with add_accessibility_preamble()")
    if not results["has_pdflang"]:
        results["recommendations"].append("Add pdflang to hyperref options")
    if not results["has_pdftitle"]:
        results["recommendations"].append("Set pdftitle in hypersetup")
    if results["figures"] and results["figures_with_alt"] < len(results["figures"]):
        results["recommendations"].append(
            f"Add alt-text to {len(results['figures']) - results['figures_with_alt']} figures"
        )

    return results


def find_figures(latex_content: str) -> List[LaTeXFigure]:
    """Find all figure environments in LaTeX content."""
    figures = []

    # Pattern for figure environments
    figure_pattern = r'\\begin\{figure\}.*?\\end\{figure\}'

    for match in re.finditer(figure_pattern, latex_content, re.DOTALL):
        fig_content = match.group()

        # Extract image path
        img_match = re.search(r'\\includegraphics(?:\[.*?\])?\{([^}]+)\}', fig_content)
        image_path = img_match.group(1) if img_match else ""

        # Extract caption
        caption_match = re.search(r'\\caption\{([^}]+)\}', fig_content)
        caption = caption_match.group(1) if caption_match else None

        # Extract label
        label_match = re.search(r'\\label\{([^}]+)\}', fig_content)
        label = label_match.group(1) if label_match else None

        # Check for alt-text (pdftooltip or our accessiblefigure macro)
        has_alt = bool(re.search(r'\\pdftooltip|\\accessiblefigure', fig_content))

        figures.append(LaTeXFigure(
            start_pos=match.start(),
            end_pos=match.end(),
            full_match=fig_content,
            image_path=image_path,
            caption=caption,
            label=label,
            has_alt_text=has_alt,
        ))

    return figures


def find_preamble_insertion_point(latex_content: str) -> int:
    """Find the best position to insert the accessibility preamble."""
    # Look for \documentclass
    doc_class = re.search(r'\\documentclass.*?\n', latex_content)
    if doc_class:
        # Insert after documentclass
        return doc_class.end()

    # Fallback: beginning of file
    return 0


def find_begin_document(latex_content: str) -> int:
    """Find position of \\begin{document}."""
    match = re.search(r'\\begin\{document\}', latex_content)
    return match.start() if match else len(latex_content)


def add_accessibility_preamble(
    latex_content: str,
    title: str = "",
    author: str = "",
    lang: str = "en-US",
    minimal: bool = False,
) -> str:
    """
    Add accessibility preamble to LaTeX content.

    Args:
        latex_content: Original LaTeX content
        title: Document title for PDF metadata
        author: Document author for PDF metadata
        lang: Document language (default: en-US)
        minimal: Use minimal preamble (fewer packages)

    Returns:
        Modified LaTeX content with preamble
    """
    # Check if already has our preamble
    if "ACCESSIBILITY PREAMBLE" in latex_content:
        return latex_content

    # Choose preamble
    preamble = MINIMAL_PREAMBLE if minimal else ACCESSIBILITY_PREAMBLE

    # Customize preamble with metadata
    preamble = preamble.replace('pdflang={en-US}', f'pdflang={{{lang}}}')
    preamble = preamble.replace('pdftitle={}', f'pdftitle={{{title}}}')
    preamble = preamble.replace('pdfauthor={}', f'pdfauthor={{{author}}}')

    # Find insertion point (after \documentclass, before \begin{document})
    insert_pos = find_preamble_insertion_point(latex_content)

    # Check if hyperref already exists - if so, we need to be careful
    if re.search(r'\\usepackage.*\{hyperref\}', latex_content):
        # Remove hyperref from our preamble to avoid conflict
        preamble = re.sub(r'\\usepackage\[[\s\S]*?\]\{hyperref\}', '', preamble)
        preamble = preamble.replace('% For hyperref options below', '')

    # Insert preamble
    new_content = latex_content[:insert_pos] + preamble + latex_content[insert_pos:]

    return new_content


def add_figure_alt_text(
    latex_content: str,
    figure_index: int,
    alt_text: str,
) -> str:
    """
    Add alt-text to a specific figure.

    Args:
        latex_content: LaTeX content
        figure_index: 0-indexed figure number
        alt_text: Alt-text to add

    Returns:
        Modified LaTeX content
    """
    figures = find_figures(latex_content)

    if figure_index >= len(figures):
        raise ValueError(f"Figure index {figure_index} out of range (found {len(figures)} figures)")

    fig = figures[figure_index]

    # Find the \includegraphics command in this figure
    img_pattern = r'(\\includegraphics)(\[[^\]]*\])?\{([^}]+)\}'
    img_match = re.search(img_pattern, fig.full_match)

    if not img_match:
        raise ValueError(f"Could not find \\includegraphics in figure {figure_index}")

    # Replace with pdftooltip version
    options = img_match.group(2) or ""
    path = img_match.group(3)

    # Escape special characters in alt-text for LaTeX
    safe_alt = alt_text.replace('\\', '\\textbackslash ')
    safe_alt = safe_alt.replace('{', '\\{').replace('}', '\\}')
    safe_alt = safe_alt.replace('%', '\\%').replace('&', '\\&')
    safe_alt = safe_alt.replace('_', '\\_').replace('#', '\\#')

    new_includegraphics = f'\\pdftooltip{{\\includegraphics{options}{{{path}}}}}{{{safe_alt}}}'

    # Replace in the figure
    new_fig_content = fig.full_match[:img_match.start()] + new_includegraphics + fig.full_match[img_match.end():]

    # Replace in the full document
    new_content = latex_content[:fig.start_pos] + new_fig_content + latex_content[fig.end_pos:]

    return new_content


def add_all_figure_alt_texts(
    latex_content: str,
    alt_texts: List[str],
) -> str:
    """
    Add alt-text to all figures.

    Args:
        latex_content: LaTeX content
        alt_texts: List of alt-texts in figure order

    Returns:
        Modified LaTeX content
    """
    figures = find_figures(latex_content)

    if len(alt_texts) != len(figures):
        raise ValueError(f"Got {len(alt_texts)} alt-texts for {len(figures)} figures")

    # Work backwards to preserve positions
    for i in range(len(figures) - 1, -1, -1):
        latex_content = add_figure_alt_text(latex_content, i, alt_texts[i])

    return latex_content


def extract_title_from_latex(latex_content: str) -> Optional[str]:
    """Extract document title from LaTeX content."""
    match = re.search(r'\\title\{([^}]+)\}', latex_content)
    return match.group(1) if match else None


def extract_author_from_latex(latex_content: str) -> Optional[str]:
    """Extract author from LaTeX content."""
    match = re.search(r'\\author\{([^}]+)\}', latex_content)
    if match:
        # Clean up author (remove \and, affiliations, etc.)
        author = match.group(1)
        author = re.sub(r'\\and', ', ', author)
        author = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', '', author)  # Remove commands
        author = re.sub(r'\s+', ' ', author).strip()
        return author
    return None


# ============================================
# Figure file resolution
# ============================================

def get_all_image_paths(latex_content: str) -> List[str]:
    r"""
    Extract all image paths referenced in the LaTeX content.

    This finds all \\includegraphics commands, not just those in figure environments.
    """
    paths = []
    # Match \includegraphics with optional arguments
    pattern = r'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}'
    for match in re.finditer(pattern, latex_content):
        paths.append(match.group(1))
    return paths


def resolve_image_path(
    image_ref: str,
    base_dir: Path,
    search_dirs: Optional[List[str]] = None,
) -> Optional[Path]:
    r"""
    Resolve an image reference to an actual file path.

    LaTeX allows:
    - Relative paths: figures/chart.png
    - Paths without extension: figures/chart (LaTeX tries .pdf, .png, .jpg, etc.)
    - graphicspath directories

    Args:
        image_ref: The path as written in \\includegraphics{...}
        base_dir: The directory containing the .tex file
        search_dirs: Additional directories to search (from \\graphicspath)

    Returns:
        Path to the image file if found, None otherwise
    """
    # Common image extensions LaTeX supports
    extensions = ['', '.pdf', '.png', '.jpg', '.jpeg', '.eps', '.svg']

    # Directories to search
    dirs_to_search = [base_dir]
    if search_dirs:
        for d in search_dirs:
            search_path = base_dir / d
            if search_path.exists():
                dirs_to_search.append(search_path)

    # Also check common subdirectories
    for subdir in ['figures', 'images', 'img', 'figs', 'graphics']:
        subpath = base_dir / subdir
        if subpath.exists() and subpath not in dirs_to_search:
            dirs_to_search.append(subpath)

    # Try to find the file
    for search_dir in dirs_to_search:
        for ext in extensions:
            candidate = search_dir / f"{image_ref}{ext}"
            if candidate.exists() and candidate.is_file():
                return candidate

            # Also try without adding extension if image_ref already has one
            if ext == '' and '.' in image_ref:
                candidate = search_dir / image_ref
                if candidate.exists() and candidate.is_file():
                    return candidate

    return None


def extract_graphicspath(latex_content: str) -> List[str]:
    r"""
    Extract directories from \\graphicspath command.

    \\graphicspath{{./figures/}{./images/}}
    """
    paths = []
    match = re.search(r'\\graphicspath\{(.*?)\}', latex_content, re.DOTALL)
    if match:
        # Extract individual paths from {{path1}{path2}}
        path_matches = re.findall(r'\{([^}]*)\}', match.group(1))
        paths.extend(path_matches)
    return paths


@dataclass
class FigureFileStatus:
    """Status of a figure's image file."""
    figure_index: int
    image_ref: str  # As written in LaTeX
    resolved_path: Optional[Path]  # Actual file path if found
    exists: bool
    caption: Optional[str]
    has_alt_text: bool


def check_figure_files(
    latex_content: str,
    latex_file_path: str,
) -> Dict:
    """
    Check which figure image files exist and which are missing.

    Args:
        latex_content: The LaTeX source
        latex_file_path: Path to the .tex file (for resolving relative paths)

    Returns:
        Dict with 'found', 'missing', and 'all' lists of FigureFileStatus
    """
    base_dir = Path(latex_file_path).parent
    graphicspath_dirs = extract_graphicspath(latex_content)

    figures = find_figures(latex_content)

    found = []
    missing = []
    all_figures = []

    for i, fig in enumerate(figures):
        resolved = resolve_image_path(fig.image_path, base_dir, graphicspath_dirs)

        status = FigureFileStatus(
            figure_index=i,
            image_ref=fig.image_path,
            resolved_path=resolved,
            exists=resolved is not None,
            caption=fig.caption,
            has_alt_text=fig.has_alt_text,
        )

        all_figures.append(status)
        if resolved:
            found.append(status)
        else:
            missing.append(status)

    return {
        "found": found,
        "missing": missing,
        "all": all_figures,
        "total": len(figures),
        "found_count": len(found),
        "missing_count": len(missing),
    }


def get_missing_figures_prompt(missing_figures: List[FigureFileStatus]) -> str:
    """
    Generate a user-friendly prompt asking for missing figure files.
    """
    if not missing_figures:
        return ""

    lines = [
        "The following figure images were not found:",
        ""
    ]

    for fig in missing_figures:
        caption_text = f' ("{fig.caption[:40]}...")' if fig.caption else ""
        lines.append(f"  {fig.figure_index + 1}. {fig.image_ref}{caption_text}")

    lines.extend([
        "",
        "Please provide these image files so I can generate alt-text descriptions.",
        "You can:",
        "  - Upload the image files",
        "  - Provide the correct path to the images",
        "  - Tell me the directory where your figures are stored",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    # Test with a simple LaTeX file
    test_latex = r"""
\documentclass{article}
\usepackage{graphicx}

\title{My Test Paper}
\author{John Doe}

\begin{document}
\maketitle

\begin{figure}
    \centering
    \includegraphics[width=0.8\textwidth]{figure1.png}
    \caption{This is figure 1}
    \label{fig:1}
\end{figure}

Some text here.

\begin{figure}
    \centering
    \includegraphics{figure2.pdf}
    \caption{This is figure 2}
\end{figure}

\end{document}
"""

    print("=== Analysis ===")
    analysis = analyze_latex(test_latex)
    print(f"Figures found: {len(analysis['figures'])}")
    print(f"Recommendations: {analysis['recommendations']}")

    print("\n=== Adding preamble ===")
    modified = add_accessibility_preamble(
        test_latex,
        title="My Test Paper",
        author="John Doe",
    )
    print(modified[:500])

    print("\n=== Adding alt-text ===")
    modified = add_figure_alt_text(modified, 0, "A bar chart showing sales data for Q1 2024")

    # Find the modified figure
    figs = find_figures(modified)
    print(f"Figure 0 now has alt-text: {figs[0].has_alt_text}")
