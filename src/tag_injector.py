"""
Tag Injector - Inject alt-text and structure tags into PDF.

This module handles:
1. Adding alt-text to existing figure tags
2. Creating Figure structure elements with alt-text for untagged figures
3. Updating the PDF structure tree
"""

import pikepdf
from pikepdf import Name, Array, Dictionary, String
from pathlib import Path
from typing import Optional, List, Tuple
import fitz  # PyMuPDF for coordinate mapping

from .figure_extractor import ExtractedFigure


def inject_alt_text(
    pdf_path: str,
    figures_with_alt: List[Tuple[ExtractedFigure, str]],
    output_path: Optional[str] = None,
) -> str:
    """
    Inject alt-text into PDF for the given figures.

    Args:
        pdf_path: Path to the input PDF
        figures_with_alt: List of (ExtractedFigure, alt_text) tuples
        output_path: Optional output path (defaults to _accessible suffix)

    Returns:
        Path to the output PDF
    """
    if output_path is None:
        p = Path(pdf_path)
        output_path = str(p.parent / f"{p.stem}_accessible{p.suffix}")

    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        # Ensure basic structure exists
        ensure_basic_structure(pdf)

        # Get or create the structure tree
        struct_tree = pdf.Root.StructTreeRoot

        # Get the document element (or create one)
        doc_elem = get_or_create_document_element(pdf, struct_tree)

        # Add each figure with alt-text
        for figure, alt_text in figures_with_alt:
            add_figure_element(pdf, doc_elem, figure, alt_text)

        pdf.save(output_path)

    return output_path


def ensure_basic_structure(pdf: pikepdf.Pdf):
    """Ensure the PDF has basic accessibility structure."""
    # MarkInfo
    if Name.MarkInfo not in pdf.Root:
        pdf.Root.MarkInfo = Dictionary({
            "/Marked": True,
            "/Suspects": False,
        })
    else:
        pdf.Root.MarkInfo[Name.Marked] = True

    # Language
    if Name.Lang not in pdf.Root:
        pdf.Root.Lang = "en-US"

    # ViewerPreferences
    if Name.ViewerPreferences not in pdf.Root:
        pdf.Root.ViewerPreferences = Dictionary()
    pdf.Root.ViewerPreferences[Name.DisplayDocTitle] = True

    # StructTreeRoot
    if Name.StructTreeRoot not in pdf.Root:
        parent_tree = Dictionary({"/Nums": Array([])})
        pdf.Root.StructTreeRoot = Dictionary({
            "/Type": Name.StructTreeRoot,
            "/K": Array([]),
            "/ParentTree": parent_tree,
        })


def get_or_create_document_element(pdf: pikepdf.Pdf, struct_tree) -> pikepdf.Object:
    """Get existing Document element or create one."""
    # Check if K already has a Document element
    if Name.K in struct_tree:
        k = struct_tree.K
        if isinstance(k, Array) and len(k) > 0:
            first = k[0]
            if isinstance(first, Dictionary) and Name.S in first:
                if first.S == Name.Document:
                    return first

        # If K is a single element (not array)
        if isinstance(k, Dictionary) and Name.S in k:
            if k.S == Name.Document:
                return k

    # Create Document element
    doc_elem = pdf.make_indirect(Dictionary({
        "/Type": Name.StructElem,
        "/S": Name.Document,
        "/P": struct_tree,
        "/K": Array([]),
    }))

    # Add to struct tree
    if Name.K not in struct_tree:
        struct_tree.K = Array([])

    if isinstance(struct_tree.K, Array):
        struct_tree.K.append(doc_elem)
    else:
        # K was a single element, convert to array
        old_k = struct_tree.K
        struct_tree.K = Array([old_k, doc_elem])

    return doc_elem


def add_figure_element(
    pdf: pikepdf.Pdf,
    parent: pikepdf.Object,
    figure: ExtractedFigure,
    alt_text: str,
):
    """
    Add a Figure structure element with alt-text.

    This creates a Figure element in the structure tree with the
    Alt attribute containing the description.
    """
    # Create the Figure structure element
    attr_dict = Dictionary({
        "/O": Name.Layout,
        "/BBox": Array([
            figure.bbox[0],
            figure.bbox[1],
            figure.bbox[2],
            figure.bbox[3],
        ]),
    })
    fig_elem = pdf.make_indirect(Dictionary({
        "/Type": Name.StructElem,
        "/S": Name.Figure,
        "/P": parent,
        "/Alt": String(alt_text),  # The alt-text!
        "/A": attr_dict,
    }))

    # Add to parent's children
    if Name.K not in parent:
        parent.K = Array([])

    if isinstance(parent.K, Array):
        parent.K.append(fig_elem)
    else:
        old_k = parent.K
        parent.K = Array([old_k, fig_elem])

    return fig_elem


def inject_single_alt_text(
    pdf_path: str,
    page_num: int,
    image_index: int,
    alt_text: str,
    output_path: Optional[str] = None,
) -> str:
    """
    Convenience function to inject alt-text for a single figure.

    Args:
        pdf_path: Path to PDF
        page_num: 0-indexed page number
        image_index: Index of image on the page
        alt_text: The alt-text to add
        output_path: Optional output path

    Returns:
        Path to output PDF
    """
    from .figure_extractor import extract_figures

    # Find the specific figure
    figures = extract_figures(pdf_path)
    target_fig = None

    for fig in figures:
        if fig.page_num == page_num and fig.index == image_index:
            target_fig = fig
            break

    if target_fig is None:
        raise ValueError(f"Figure not found at page {page_num}, index {image_index}")

    return inject_alt_text(pdf_path, [(target_fig, alt_text)], output_path)


def get_existing_alt_texts(pdf_path: str) -> List[dict]:
    """
    Get any existing alt-texts from the PDF structure.

    Returns list of dicts with figure info and alt-text.
    """
    results = []

    with pikepdf.open(pdf_path) as pdf:
        if Name.StructTreeRoot not in pdf.Root:
            return results

        struct_tree = pdf.Root.StructTreeRoot
        _traverse_for_figures(struct_tree, results)

    return results


def _traverse_for_figures(elem, results: list, depth: int = 0):
    """Recursively traverse structure tree looking for Figure elements."""
    if depth > 50:  # Prevent infinite recursion
        return

    if not isinstance(elem, Dictionary):
        return

    # Check if this is a Figure element
    if Name.S in elem and elem.S == Name.Figure:
        fig_info = {"type": "Figure"}

        if Name.Alt in elem:
            fig_info["alt_text"] = str(elem.Alt)

        if Name.A in elem and Name.BBox in elem.A:
            bbox = elem.A.BBox
            fig_info["bbox"] = [float(x) for x in bbox]

        results.append(fig_info)

    # Traverse children
    if Name.K in elem:
        k = elem.K
        if isinstance(k, Array):
            for child in k:
                _traverse_for_figures(child, results, depth + 1)
        elif isinstance(k, Dictionary):
            _traverse_for_figures(k, results, depth + 1)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 2:
        pdf_path = sys.argv[1]
        alt_text = sys.argv[2]

        print(f"Injecting alt-text into: {pdf_path}")

        # Get figures
        from figure_extractor import extract_figures
        figures = extract_figures(pdf_path)

        if figures:
            # Add alt-text to first figure as a test
            output = inject_alt_text(pdf_path, [(figures[0], alt_text)])
            print(f"Created: {output}")

            # Verify
            existing = get_existing_alt_texts(output)
            print(f"Existing alt-texts: {existing}")
        else:
            print("No figures found in PDF")
