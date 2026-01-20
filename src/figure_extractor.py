"""
Figure Extractor - Extract images/figures from PDF with coordinates.

Uses PyMuPDF (fitz) to:
1. Find all images in the PDF
2. Extract image data and coordinates (bounding boxes)
3. Identify which images likely need alt-text
"""

import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from PIL import Image
import io


@dataclass
class ExtractedFigure:
    """Represents an extracted figure from a PDF."""
    page_num: int  # 0-indexed
    index: int  # Index on the page
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    width: int
    height: int
    image_data: bytes  # Raw image bytes (PNG format)
    xref: int  # PDF internal reference
    has_alt_text: bool = False
    alt_text: Optional[str] = None


def extract_figures(pdf_path: str, min_size: int = 50) -> List[ExtractedFigure]:
    """
    Extract all figures/images from a PDF.

    Args:
        pdf_path: Path to the PDF file
        min_size: Minimum width/height to consider (filters out tiny icons)

    Returns:
        List of ExtractedFigure objects
    """
    figures = []
    doc = fitz.open(pdf_path)

    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)

        for img_index, img_info in enumerate(image_list):
            xref = img_info[0]  # Image xref

            try:
                # Extract image
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue

                image_bytes = base_image["image"]
                width = base_image["width"]
                height = base_image["height"]

                # Skip tiny images (likely icons, bullets, etc.)
                if width < min_size or height < min_size:
                    continue

                # Convert to PNG for consistency
                img = Image.open(io.BytesIO(image_bytes))
                png_buffer = io.BytesIO()
                img.save(png_buffer, format="PNG")
                png_bytes = png_buffer.getvalue()

                # Get bounding box from page
                bbox = get_image_bbox(page, xref)

                figure = ExtractedFigure(
                    page_num=page_num,
                    index=img_index,
                    bbox=bbox,
                    width=width,
                    height=height,
                    image_data=png_bytes,
                    xref=xref,
                )
                figures.append(figure)

            except Exception as e:
                print(f"Warning: Could not extract image {xref} on page {page_num}: {e}")
                continue

    doc.close()
    return figures


def get_image_bbox(page: fitz.Page, xref: int) -> Tuple[float, float, float, float]:
    """Get the bounding box of an image on a page by its xref."""
    # Try to find the image in the page's image list with positions
    for img in page.get_images(full=True):
        if img[0] == xref:
            # Get image rectangles
            rects = page.get_image_rects(img)
            if rects:
                rect = rects[0]  # Use first occurrence
                return (rect.x0, rect.y0, rect.x1, rect.y1)

    # Fallback: return page bounds
    rect = page.rect
    return (rect.x0, rect.y0, rect.x1, rect.y1)


def save_figures(figures: List[ExtractedFigure], output_dir: str) -> List[str]:
    """
    Save extracted figures to files.

    Returns list of saved file paths.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    for fig in figures:
        filename = f"figure_p{fig.page_num + 1}_{fig.index}.png"
        filepath = output_path / filename
        filepath.write_bytes(fig.image_data)
        saved_paths.append(str(filepath))

    return saved_paths


def get_figures_summary(figures: List[ExtractedFigure]) -> Dict:
    """Get a summary of extracted figures."""
    if not figures:
        return {"count": 0, "pages": [], "figures": []}

    pages_with_figures = sorted(set(f.page_num + 1 for f in figures))

    return {
        "count": len(figures),
        "pages": pages_with_figures,
        "figures": [
            {
                "page": f.page_num + 1,
                "index": f.index,
                "size": f"{f.width}x{f.height}",
                "bbox": f.bbox,
                "has_alt_text": f.has_alt_text,
            }
            for f in figures
        ],
    }


def extract_figure_context(pdf_path: str, figure: ExtractedFigure, context_chars: int = 500) -> str:
    """
    Extract text context around a figure to help with alt-text generation.

    This gets text near the figure's bounding box that might be captions or descriptions.
    """
    doc = fitz.open(pdf_path)
    page = doc[figure.page_num]

    # Expand the bounding box to capture nearby text
    x0, y0, x1, y1 = figure.bbox
    margin = 50  # pixels

    # Search below the figure (common caption location)
    caption_rect = fitz.Rect(x0 - margin, y1, x1 + margin, y1 + 100)
    caption_text = page.get_text("text", clip=caption_rect).strip()

    # Search above the figure (sometimes captions are above)
    above_rect = fitz.Rect(x0 - margin, y0 - 100, x1 + margin, y0)
    above_text = page.get_text("text", clip=above_rect).strip()

    doc.close()

    # Combine context
    context_parts = []
    if caption_text:
        context_parts.append(f"Caption/text below: {caption_text[:context_chars]}")
    if above_text:
        context_parts.append(f"Text above: {above_text[:context_chars]}")

    return "\n".join(context_parts) if context_parts else ""


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        print(f"Extracting figures from: {pdf_path}")

        figures = extract_figures(pdf_path)
        summary = get_figures_summary(figures)
        print(f"Found {summary['count']} figures")

        for fig_info in summary["figures"]:
            print(f"  Page {fig_info['page']}: {fig_info['size']}")

        if figures:
            # Save to temp directory
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                paths = save_figures(figures, tmpdir)
                print(f"Saved figures to: {tmpdir}")
                for p in paths:
                    print(f"  {p}")
