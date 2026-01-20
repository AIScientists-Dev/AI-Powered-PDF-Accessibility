#!/usr/bin/env python3
"""
CLI Tool for PDF Accessibility.

Standalone command-line interface that doesn't require MCP.

Usage:
    python cli.py analyze <pdf_path>
    python cli.py make-accessible <pdf_path> [--output <output_path>]
    python cli.py extract-figures <pdf_path> [--save-to <dir>]
    python cli.py validate <pdf_path>
"""

import click
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


@click.group()
def cli():
    """PDF Accessibility Tool - Make PDFs accessible with AI-generated alt-text."""
    pass


@cli.command()
@click.argument("pdf_path", type=click.Path(exists=True))
def analyze(pdf_path: str):
    """Analyze a PDF for accessibility status."""
    from src.pdf_tagger import get_pdf_info
    from src.figure_extractor import extract_figures, get_figures_summary
    from src.tag_injector import get_existing_alt_texts
    from src.validator import quick_accessibility_check

    console.print(f"\n[bold]Analyzing:[/bold] {pdf_path}\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Getting PDF info...", total=None)

        info = get_pdf_info(pdf_path)
        progress.update(task, description="Extracting figures...")

        figures = extract_figures(pdf_path)
        summary = get_figures_summary(figures)
        progress.update(task, description="Checking existing alt-texts...")

        existing_alts = get_existing_alt_texts(pdf_path)
        progress.update(task, description="Running validation...")

        validation = quick_accessibility_check(pdf_path)

    # Display results
    table = Table(title="PDF Information")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Pages", str(info["page_count"]))
    table.add_row("Tagged", "Yes ✓" if info["is_tagged"] else "No ✗")
    table.add_row("Has Structure Tree", "Yes ✓" if info["has_struct_tree"] else "No ✗")
    table.add_row("Language Set", info.get("lang", "No ✗") if info["has_lang"] else "No ✗")
    table.add_row("Title", info.get("title", "No ✗")[:50] if info["has_title"] else "No ✗")
    table.add_row("Figures Found", str(summary["count"]))
    table.add_row("Figures with Alt-text", str(len([a for a in existing_alts if a.get("alt_text")])))

    console.print(table)

    # Validation results
    console.print("\n[bold]Validation Results:[/bold]")
    for check in validation["passed"]:
        console.print(f"  [green]✓[/green] {check}")
    for issue in validation["issues"]:
        console.print(f"  [red]✗[/red] {issue}")

    # Recommendations
    console.print("\n[bold]Recommendations:[/bold]")
    if not info["is_tagged"]:
        console.print("  → Add structure tags: [cyan]python cli.py add-tags <pdf>[/cyan]")
    if summary["count"] > len([a for a in existing_alts if a.get("alt_text")]):
        console.print("  → Generate alt-text: [cyan]python cli.py make-accessible <pdf>[/cyan]")
    if validation["likely_valid"]:
        console.print("  [green]PDF appears to meet basic accessibility requirements![/green]")


@cli.command()
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--output", "-o", help="Output file path")
@click.option("--doc-type", default="academic paper", help="Document type for AI context")
def make_accessible(pdf_path: str, output: str, doc_type: str):
    """Make a PDF accessible by adding structure tags and alt-text."""
    from src.pdf_tagger import is_tagged_pdf, create_basic_structure
    from src.figure_extractor import extract_figures, extract_figure_context
    from src.ai_describer import generate_alt_text
    from src.tag_injector import inject_alt_text
    from src.validator import quick_accessibility_check

    console.print(f"\n[bold]Making accessible:[/bold] {pdf_path}\n")

    working_path = pdf_path

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Checking structure tags...", total=None)

        # Step 1: Add structure if needed
        if not is_tagged_pdf(pdf_path):
            progress.update(task, description="Adding structure tags...")
            working_path = create_basic_structure(pdf_path)
            console.print("  [green]✓[/green] Added structure tags")

        # Step 2: Extract figures
        progress.update(task, description="Extracting figures...")
        figures = extract_figures(working_path)
        console.print(f"  [green]✓[/green] Found {len(figures)} figures")

        # Step 3: Generate alt-text
        figures_with_alt = []
        for i, fig in enumerate(figures):
            progress.update(task, description=f"Generating alt-text for figure {i+1}/{len(figures)}...")
            context = extract_figure_context(working_path, fig)
            alt_text = generate_alt_text(fig.image_data, context, doc_type)
            figures_with_alt.append((fig, alt_text))
            console.print(f"  [green]✓[/green] Figure {i+1}: {alt_text[:60]}...")

        # Step 4: Inject alt-text
        if figures_with_alt:
            progress.update(task, description="Injecting alt-text into PDF...")
            output_path = inject_alt_text(working_path, figures_with_alt, output)
        else:
            output_path = working_path if not output else output
            if output and output != working_path:
                import shutil
                shutil.copy(working_path, output)

        # Step 5: Validate
        progress.update(task, description="Validating result...")
        validation = quick_accessibility_check(output_path)

    console.print(f"\n[bold green]Success![/bold green] Output: {output_path}")
    console.print(f"Validation: {'✓ Passed' if validation['likely_valid'] else '⚠ Check issues above'}")


@cli.command()
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--save-to", "-s", help="Directory to save extracted images")
def extract_figures(pdf_path: str, save_to: str):
    """Extract figures from a PDF."""
    from src.figure_extractor import extract_figures as do_extract, get_figures_summary, save_figures

    console.print(f"\n[bold]Extracting figures from:[/bold] {pdf_path}\n")

    figures = do_extract(pdf_path)
    summary = get_figures_summary(figures)

    if not figures:
        console.print("[yellow]No figures found in PDF[/yellow]")
        return

    table = Table(title=f"Found {len(figures)} Figures")
    table.add_column("Page", style="cyan")
    table.add_column("Index", style="cyan")
    table.add_column("Size")
    table.add_column("BBox")

    for fig_info in summary["figures"]:
        bbox = fig_info["bbox"]
        table.add_row(
            str(fig_info["page"]),
            str(fig_info["index"]),
            fig_info["size"],
            f"({bbox[0]:.0f}, {bbox[1]:.0f}, {bbox[2]:.0f}, {bbox[3]:.0f})",
        )

    console.print(table)

    if save_to:
        paths = save_figures(figures, save_to)
        console.print(f"\n[green]Saved {len(paths)} figures to {save_to}[/green]")
        for p in paths:
            console.print(f"  {p}")


@cli.command()
@click.argument("pdf_path", type=click.Path(exists=True))
def validate(pdf_path: str):
    """Validate PDF accessibility."""
    from src.validator import quick_accessibility_check

    console.print(f"\n[bold]Validating:[/bold] {pdf_path}\n")

    result = quick_accessibility_check(pdf_path)

    console.print("[bold]Checks Passed:[/bold]")
    for check in result["passed"]:
        console.print(f"  [green]✓[/green] {check}")

    if result["issues"]:
        console.print("\n[bold]Issues Found:[/bold]")
        for issue in result["issues"]:
            console.print(f"  [red]✗[/red] {issue}")

    status = "[green]LIKELY VALID[/green]" if result["likely_valid"] else "[red]NEEDS WORK[/red]"
    console.print(f"\n[bold]Overall Status:[/bold] {status}")


@cli.command()
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--output", "-o", help="Output file path")
def add_tags(pdf_path: str, output: str):
    """Add structure tags to an untagged PDF."""
    from src.pdf_tagger import create_basic_structure, get_pdf_info

    console.print(f"\n[bold]Adding tags to:[/bold] {pdf_path}\n")

    output_path = create_basic_structure(pdf_path, output)
    info = get_pdf_info(output_path)

    console.print(f"[green]✓[/green] Created tagged PDF: {output_path}")
    console.print(f"  Tagged: {info['is_tagged']}")
    console.print(f"  Language: {info.get('lang', 'N/A')}")
    console.print(f"  Title: {info.get('title', 'N/A')[:50]}")


# ============================================
# LaTeX Commands
# ============================================

@cli.command()
@click.argument("latex_path", type=click.Path(exists=True))
def analyze_latex(latex_path: str):
    """Analyze a LaTeX file for accessibility features."""
    from src.latex_processor import analyze_latex as do_analyze

    console.print(f"\n[bold]Analyzing LaTeX:[/bold] {latex_path}\n")

    content = Path(latex_path).read_text()
    analysis = do_analyze(content)

    table = Table(title="LaTeX Accessibility Analysis")
    table.add_column("Feature", style="cyan")
    table.add_column("Status", style="green")

    table.add_row("Has hyperref", "Yes ✓" if analysis["has_hyperref"] else "No ✗")
    table.add_row("Has axessibility", "Yes ✓" if analysis["has_axessibility"] else "No ✗")
    table.add_row("Has our preamble", "Yes ✓" if analysis["has_accessibility_preamble"] else "No ✗")
    table.add_row("Has pdflang", "Yes ✓" if analysis["has_pdflang"] else "No ✗")
    table.add_row("Has pdftitle", "Yes ✓" if analysis["has_pdftitle"] else "No ✗")
    table.add_row("Figures found", str(len(analysis["figures"])))
    table.add_row("Figures with alt-text", str(analysis["figures_with_alt"]))

    console.print(table)

    if analysis["figures"]:
        console.print("\n[bold]Figures:[/bold]")
        for i, fig in enumerate(analysis["figures"]):
            status = "[green]✓[/green]" if fig["has_alt_text"] else "[red]✗[/red]"
            caption = fig["caption"] or "(no caption)"
            console.print(f"  {i}. {status} {fig['image_path']} - {caption}")

    if analysis["recommendations"]:
        console.print("\n[bold]Recommendations:[/bold]")
        for rec in analysis["recommendations"]:
            console.print(f"  → {rec}")


@cli.command()
@click.argument("latex_path", type=click.Path(exists=True))
@click.option("--output", "-o", help="Output file path")
@click.option("--title", "-t", help="Document title")
@click.option("--author", "-a", help="Document author")
@click.option("--lang", "-l", default="en-US", help="Document language")
def prepare_latex(latex_path: str, output: str, title: str, author: str, lang: str):
    """Add accessibility preamble to a LaTeX file."""
    from src.latex_processor import (
        add_accessibility_preamble, extract_title_from_latex, extract_author_from_latex
    )

    console.print(f"\n[bold]Preparing LaTeX:[/bold] {latex_path}\n")

    content = Path(latex_path).read_text()

    # Auto-detect if not provided
    title = title or extract_title_from_latex(content) or Path(latex_path).stem
    author = author or extract_author_from_latex(content) or ""

    modified = add_accessibility_preamble(content, title=title, author=author, lang=lang)

    if output is None:
        p = Path(latex_path)
        output = str(p.parent / f"{p.stem}_accessible{p.suffix}")

    Path(output).write_text(modified)

    console.print(f"[green]✓[/green] Created: {output}")
    console.print(f"  Title: {title}")
    console.print(f"  Author: {author}")
    console.print(f"  Language: {lang}")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Upload to Overleaf")
    console.print("  2. Compile the PDF")
    console.print("  3. Download the PDF")
    console.print(f"  4. Run: [cyan]python cli.py make-latex-accessible {latex_path} <pdf_path>[/cyan]")


@cli.command()
@click.argument("latex_path", type=click.Path(exists=True))
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--output", "-o", help="Output LaTeX file path")
def make_latex_accessible(latex_path: str, pdf_path: str, output: str):
    """Full pipeline: prepare LaTeX, extract figures from PDF, generate alt-text."""
    from src.latex_processor import (
        add_accessibility_preamble, find_figures as find_latex_figures,
        add_all_figure_alt_texts, extract_title_from_latex, extract_author_from_latex
    )
    from src.figure_extractor import extract_figures, extract_figure_context
    from src.ai_describer import generate_alt_text

    console.print(f"\n[bold]Making LaTeX accessible:[/bold]")
    console.print(f"  LaTeX: {latex_path}")
    console.print(f"  PDF:   {pdf_path}\n")

    latex_content = Path(latex_path).read_text()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Checking preamble...", total=None)

        # Step 1: Add preamble if needed
        if "ACCESSIBILITY PREAMBLE" not in latex_content:
            progress.update(task, description="Adding accessibility preamble...")
            title = extract_title_from_latex(latex_content) or Path(latex_path).stem
            author = extract_author_from_latex(latex_content) or ""
            latex_content = add_accessibility_preamble(latex_content, title=title, author=author)
            console.print("  [green]✓[/green] Added accessibility preamble")

        # Step 2: Find figures in LaTeX
        progress.update(task, description="Finding figures in LaTeX...")
        latex_figures = find_latex_figures(latex_content)
        console.print(f"  [green]✓[/green] Found {len(latex_figures)} figures in LaTeX")

        # Step 3: Extract figures from PDF
        progress.update(task, description="Extracting figures from PDF...")
        pdf_figures = extract_figures(pdf_path)
        console.print(f"  [green]✓[/green] Extracted {len(pdf_figures)} figures from PDF")

        # Step 4: Generate alt-text for each figure
        alt_texts = []
        for i, pdf_fig in enumerate(pdf_figures):
            progress.update(task, description=f"Generating alt-text {i+1}/{len(pdf_figures)}...")
            context = extract_figure_context(pdf_path, pdf_fig)
            if i < len(latex_figures) and latex_figures[i].caption:
                context += f"\nCaption: {latex_figures[i].caption}"
            alt_text = generate_alt_text(pdf_fig.image_data, context)
            alt_texts.append(alt_text)
            console.print(f"  [green]✓[/green] Figure {i+1}: {alt_text[:50]}...")

        # Step 5: Add alt-texts to LaTeX
        if alt_texts and len(alt_texts) <= len(latex_figures):
            progress.update(task, description="Adding alt-texts to LaTeX...")
            latex_content = add_all_figure_alt_texts(latex_content, alt_texts)

    # Write output
    if output is None:
        p = Path(latex_path)
        output = str(p.parent / f"{p.stem}_accessible{p.suffix}")

    Path(output).write_text(latex_content)

    console.print(f"\n[bold green]Success![/bold green] Output: {output}")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Upload the modified LaTeX to Overleaf")
    console.print("  2. Recompile to get the accessible PDF")
    console.print(f"  3. Validate: [cyan]python cli.py validate <new_pdf>[/cyan]")


@cli.command()
@click.argument("latex_path", type=click.Path(exists=True))
def check_figures(latex_path: str):
    """Check which figure files exist locally and which are missing."""
    from src.latex_processor import check_figure_files, get_missing_figures_prompt

    console.print(f"\n[bold]Checking figures in:[/bold] {latex_path}\n")

    latex_content = Path(latex_path).read_text()
    status = check_figure_files(latex_content, latex_path)

    # Summary
    console.print(f"Total figures: {status['total']}")
    console.print(f"Found: [green]{status['found_count']}[/green]")
    console.print(f"Missing: [red]{status['missing_count']}[/red]\n")

    # Found files
    if status["found"]:
        table = Table(title="Found Figures")
        table.add_column("#", style="cyan")
        table.add_column("Reference")
        table.add_column("Path")
        table.add_column("Caption")

        for fig in status["found"]:
            caption = fig.caption[:30] + "..." if fig.caption and len(fig.caption) > 30 else (fig.caption or "-")
            table.add_row(
                str(fig.figure_index),
                fig.image_ref,
                str(fig.resolved_path),
                caption,
            )
        console.print(table)

    # Missing files
    if status["missing"]:
        console.print("\n[bold red]Missing Figures:[/bold red]")
        for fig in status["missing"]:
            caption = f' ("{fig.caption[:40]}...")' if fig.caption else ""
            console.print(f"  [red]✗[/red] {fig.figure_index}. {fig.image_ref}{caption}")

        console.print("\n[bold]To process these figures:[/bold]")
        console.print("  1. Upload/provide the missing image files")
        console.print("  2. Place them in a 'figures/' directory or specify --figure-dir")
        console.print(f"  3. Run: [cyan]python cli.py process-figures {latex_path}[/cyan]")


@cli.command()
@click.argument("latex_path", type=click.Path(exists=True))
@click.option("--output", "-o", help="Output LaTeX file path")
@click.option("--figure-dir", "-d", help="Directory containing figure files")
def process_figures(latex_path: str, output: str, figure_dir: str):
    """Process LaTeX by reading figure files directly (no PDF needed)."""
    from src.latex_processor import (
        check_figure_files, add_accessibility_preamble, find_figures as find_latex_figures,
        add_figure_alt_text, extract_title_from_latex, extract_author_from_latex
    )
    from src.ai_describer import generate_alt_text

    console.print(f"\n[bold]Processing figures from:[/bold] {latex_path}\n")

    latex_content = Path(latex_path).read_text()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Checking files...", total=None)

        # Step 1: Add preamble if needed
        if "ACCESSIBILITY PREAMBLE" not in latex_content:
            progress.update(task, description="Adding accessibility preamble...")
            title = extract_title_from_latex(latex_content) or Path(latex_path).stem
            author = extract_author_from_latex(latex_content) or ""
            latex_content = add_accessibility_preamble(latex_content, title=title, author=author)
            console.print("  [green]✓[/green] Added accessibility preamble")

        # Step 2: Check figure files
        progress.update(task, description="Finding figure files...")
        status = check_figure_files(latex_content, latex_path)
        console.print(f"  [green]✓[/green] Found {status['found_count']}/{status['total']} figure files")

        # Step 3: Generate alt-text for each found figure
        processed = []
        skipped = []

        for fig in status["all"]:
            if fig.resolved_path and fig.resolved_path.exists():
                progress.update(task, description=f"Processing figure {fig.figure_index + 1}...")
                image_data = fig.resolved_path.read_bytes()
                context = f"Caption: {fig.caption}" if fig.caption else ""
                alt_text = generate_alt_text(image_data, context)

                # Add alt-text to this figure
                latex_content = add_figure_alt_text(latex_content, fig.figure_index, alt_text)
                processed.append((fig.figure_index, fig.image_ref, alt_text))
                console.print(f"  [green]✓[/green] Figure {fig.figure_index + 1}: {alt_text[:50]}...")
            else:
                skipped.append((fig.figure_index, fig.image_ref))

    # Write output
    if output is None:
        p = Path(latex_path)
        output = str(p.parent / f"{p.stem}_accessible{p.suffix}")

    Path(output).write_text(latex_content)

    console.print(f"\n[bold green]Success![/bold green] Output: {output}")
    console.print(f"  Processed: {len(processed)} figures")

    if skipped:
        console.print(f"  [yellow]Skipped: {len(skipped)} figures (files not found)[/yellow]")
        for idx, ref in skipped:
            console.print(f"    - Figure {idx + 1}: {ref}")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Upload the modified LaTeX to Overleaf")
    console.print("  2. Compile to get the accessible PDF")


if __name__ == "__main__":
    cli()
