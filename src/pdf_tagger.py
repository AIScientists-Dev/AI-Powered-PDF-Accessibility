"""
PDF Tagger - Detect and create PDF structure tags for accessibility.

This module handles:
1. Detecting if a PDF already has structure tags (tagged PDF)
2. Creating basic structure tags for untagged PDFs using pikepdf
3. Adding XMP metadata for PDF/UA compliance
4. Detecting and tagging headings (H1, H2, H3)
5. Adding page structure (Tabs key for annotations)
6. Adding link annotation alt-text
"""

import pikepdf
from pikepdf import Name, Array, Dictionary, String, Stream, parse_content_stream, unparse_content_stream
from pathlib import Path
from typing import Optional, List, Tuple
from datetime import datetime
import fitz  # PyMuPDF for text extraction
import re


def is_tagged_pdf(pdf_path: str) -> bool:
    """Check if PDF has structure tags (MarkInfo/Marked)."""
    with pikepdf.open(pdf_path) as pdf:
        # Check for MarkInfo dictionary with Marked=true
        if Name.MarkInfo in pdf.Root:
            mark_info = pdf.Root.MarkInfo
            if Name.Marked in mark_info:
                return bool(mark_info.Marked)

        # Also check for StructTreeRoot existence
        if Name.StructTreeRoot in pdf.Root:
            return True

    return False


def get_pdf_info(pdf_path: str) -> dict:
    """Get basic PDF information including tag status."""
    info = {
        "path": pdf_path,
        "is_tagged": False,
        "has_struct_tree": False,
        "page_count": 0,
        "has_lang": False,
        "has_title": False,
    }

    with pikepdf.open(pdf_path) as pdf:
        info["page_count"] = len(pdf.pages)
        info["is_tagged"] = is_tagged_pdf(pdf_path)
        info["has_struct_tree"] = Name.StructTreeRoot in pdf.Root

        # Check for language
        if Name.Lang in pdf.Root:
            info["has_lang"] = True
            info["lang"] = str(pdf.Root.Lang)

        # Check for title in metadata
        if pdf.docinfo and Name.Title in pdf.docinfo:
            info["has_title"] = True
            info["title"] = str(pdf.docinfo.Title)

    return info


def create_basic_structure(
    pdf_path: str,
    output_path: Optional[str] = None,
    title: Optional[str] = None,
    lang: str = "en-US",
) -> str:
    """
    Create basic PDF/UA structure for an untagged PDF.

    This adds:
    - MarkInfo with Marked=true
    - Basic StructTreeRoot
    - Language attribute
    - ViewerPreferences for accessibility

    Args:
        pdf_path: Path to input PDF
        output_path: Path for output PDF (default: input_tagged.pdf)
        title: Document title (default: extracted from PDF or filename)
        lang: Document language (default: en-US)

    Returns path to the output PDF.
    """
    if output_path is None:
        p = Path(pdf_path)
        output_path = str(p.parent / f"{p.stem}_tagged{p.suffix}")

    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        # 1. Set MarkInfo
        pdf.Root.MarkInfo = Dictionary({
            "/Marked": True,
            "/Suspects": False,  # No suspect tags
        })

        # 2. Set language
        pdf.Root.Lang = lang

        # 3. Set ViewerPreferences for accessibility
        if Name.ViewerPreferences not in pdf.Root:
            pdf.Root.ViewerPreferences = Dictionary()
        pdf.Root.ViewerPreferences[Name.DisplayDocTitle] = True

        # 4. Create StructTreeRoot if it doesn't exist
        if Name.StructTreeRoot not in pdf.Root:
            # Create basic structure tree
            parent_tree = Dictionary({
                "/Type": Name.ParentTree,
                "/Nums": Array([]),
            })
            struct_tree = Dictionary({
                "/Type": Name.StructTreeRoot,
                "/K": Array([]),  # Children array
                "/ParentTree": parent_tree,
            })
            pdf.Root.StructTreeRoot = struct_tree

        # 5. Ensure metadata exists
        if not pdf.docinfo:
            pdf.docinfo = Dictionary()

        # Set title
        if title:
            pdf.docinfo[Name.Title] = title
        elif Name.Title not in pdf.docinfo or not pdf.docinfo.Title:
            # Try to extract title from first page text
            extracted_title = extract_title_from_pdf(pdf_path)
            if extracted_title:
                pdf.docinfo[Name.Title] = extracted_title
            else:
                pdf.docinfo[Name.Title] = Path(pdf_path).stem

        pdf.save(output_path)

    return output_path


def extract_title_from_pdf(pdf_path: str) -> Optional[str]:
    """Extract potential title from first page of PDF using PyMuPDF."""
    try:
        doc = fitz.open(pdf_path)
        if len(doc) > 0:
            page = doc[0]
            blocks = page.get_text("dict")["blocks"]

            # Find the largest text on first page (likely title)
            max_size = 0
            title_text = None

            for block in blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            if span["size"] > max_size and len(span["text"].strip()) > 3:
                                max_size = span["size"]
                                title_text = span["text"].strip()

            doc.close()
            return title_text
    except Exception:
        pass
    return None


def add_document_structure(pdf_path: str, output_path: Optional[str] = None) -> str:
    """
    Enhanced structure tagging - adds Document element with paragraphs.

    This creates a more complete structure tree with:
    - Document as root element
    - Basic paragraph structure from text blocks
    """
    if output_path is None:
        p = Path(pdf_path)
        output_path = str(p.parent / f"{p.stem}_structured{p.suffix}")

    # First ensure basic structure exists
    temp_path = create_basic_structure(pdf_path)

    with pikepdf.open(temp_path, allow_overwriting_input=True) as pdf:
        struct_tree = pdf.Root.StructTreeRoot

        # Create Document element
        doc_elem = pdf.make_indirect(Dictionary({
            Name.Type: Name.StructElem,
            Name.S: Name.Document,
            Name.P: struct_tree,
            Name.K: Array([]),
        }))

        # Update StructTreeRoot to point to Document
        struct_tree.K = Array([doc_elem])

        pdf.save(output_path)

    # Clean up temp file if different from output
    if temp_path != output_path:
        Path(temp_path).unlink(missing_ok=True)

    return output_path


def add_xmp_metadata(
    pdf: pikepdf.Pdf,
    title: str,
    author: str = "",
    lang: str = "en-US",
    subject: str = "",
    keywords: str = "",
) -> None:
    """
    Add XMP metadata stream for PDF/UA compliance (Clause 7.1).

    This creates the required /Metadata entry in the catalog with
    proper XMP format including dc, xmp, and pdfuaid namespaces.
    """
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Escape XML special characters
    def escape_xml(s: str) -> str:
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace('"', "&quot;")
                 .replace("'", "&apos;"))

    title = escape_xml(title)
    author = escape_xml(author)
    subject = escape_xml(subject)
    keywords = escape_xml(keywords)

    xmp_content = f'''<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about=""
        xmlns:dc="http://purl.org/dc/elements/1.1/"
        xmlns:xmp="http://ns.adobe.com/xap/1.0/"
        xmlns:pdf="http://ns.adobe.com/pdf/1.3/"
        xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/">
      <dc:title>
        <rdf:Alt>
          <rdf:li xml:lang="x-default">{title}</rdf:li>
        </rdf:Alt>
      </dc:title>
      <dc:creator>
        <rdf:Seq>
          <rdf:li>{author}</rdf:li>
        </rdf:Seq>
      </dc:creator>
      <dc:language>
        <rdf:Bag>
          <rdf:li>{lang}</rdf:li>
        </rdf:Bag>
      </dc:language>
      <dc:subject>
        <rdf:Bag>
          <rdf:li>{subject}</rdf:li>
        </rdf:Bag>
      </dc:subject>
      <xmp:CreateDate>{now}</xmp:CreateDate>
      <xmp:ModifyDate>{now}</xmp:ModifyDate>
      <xmp:MetadataDate>{now}</xmp:MetadataDate>
      <pdf:Producer>accessibility-mcp</pdf:Producer>
      <pdf:Keywords>{keywords}</pdf:Keywords>
      <pdfuaid:part>1</pdfuaid:part>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>'''

    # Create metadata stream with proper type and subtype
    metadata_stream = Stream(pdf, xmp_content.encode('utf-8'))
    metadata_stream.Type = Name.Metadata
    metadata_stream.Subtype = Name.XML

    pdf.Root.Metadata = metadata_stream


def add_page_tabs_key(pdf: pikepdf.Pdf) -> int:
    """
    Add /Tabs /S key to pages with annotations (Clause 7.18.3).

    PDF/UA requires pages with annotations to have the Tabs key
    set to /S (structure order) for proper keyboard navigation.

    Returns the number of pages modified.
    """
    modified_count = 0

    for page in pdf.pages:
        # Check if page has annotations
        if Name.Annots in page:
            annots = page.Annots
            if annots and len(annots) > 0:
                # Add Tabs key if not present
                if Name.Tabs not in page:
                    page.Tabs = Name.S
                    modified_count += 1

    return modified_count


def get_link_annotations(pdf_path: str) -> List[dict]:
    """
    Extract all link annotations from a PDF.

    Returns list of dicts with link info including page, rect, URI, and current alt-text.
    """
    links = []

    with pikepdf.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            if Name.Annots not in page:
                continue

            for annot_idx, annot in enumerate(page.Annots):
                # Check if it's a Link annotation
                if Name.Subtype in annot and annot.Subtype == Name.Link:
                    link_info = {
                        "page": page_num,
                        "index": annot_idx,
                        "rect": None,
                        "uri": None,
                        "has_contents": False,
                        "contents": None,
                    }

                    # Get rectangle
                    if Name.Rect in annot:
                        link_info["rect"] = [float(x) for x in annot.Rect]

                    # Get URI if present
                    if Name.A in annot:
                        action = annot.A
                        if Name.URI in action:
                            link_info["uri"] = str(action.URI)
                        elif Name.S in action and action.S == Name.URI:
                            if Name.URI in action:
                                link_info["uri"] = str(action.URI)

                    # Check for existing Contents (alt-text)
                    if Name.Contents in annot:
                        link_info["has_contents"] = True
                        link_info["contents"] = str(annot.Contents)

                    links.append(link_info)

    return links


def add_link_alt_texts(
    pdf_path: str,
    output_path: Optional[str] = None,
    auto_generate: bool = True,
) -> Tuple[str, int]:
    """
    Add alt-text (Contents key) to link annotations (Clause 7.18.1, 7.18.5).

    PDF/UA requires link annotations to have either a Contents key
    or an Alt entry in the enclosing structure element.

    Args:
        pdf_path: Path to input PDF
        output_path: Optional output path
        auto_generate: If True, auto-generate alt-text from URI

    Returns:
        Tuple of (output_path, number of links modified)
    """
    if output_path is None:
        p = Path(pdf_path)
        output_path = str(p.parent / f"{p.stem}_links{p.suffix}")

    modified_count = 0

    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        for page in pdf.pages:
            if Name.Annots not in page:
                continue

            for annot in page.Annots:
                if Name.Subtype in annot and annot.Subtype == Name.Link:
                    # Skip if already has Contents
                    if Name.Contents in annot and annot.Contents:
                        continue

                    if auto_generate:
                        # Generate alt-text from URI or generic description
                        alt_text = "Link"

                        if Name.A in annot:
                            action = annot.A
                            if Name.URI in action:
                                uri = str(action.URI)
                                # Create descriptive alt-text from URI
                                if "mailto:" in uri:
                                    email = uri.replace("mailto:", "")
                                    alt_text = f"Email link to {email}"
                                elif "http" in uri:
                                    # Extract domain for description
                                    import urllib.parse
                                    try:
                                        parsed = urllib.parse.urlparse(uri)
                                        domain = parsed.netloc.replace("www.", "")
                                        path = parsed.path.strip("/")
                                        if path:
                                            alt_text = f"Link to {path} on {domain}"
                                        else:
                                            alt_text = f"Link to {domain}"
                                    except Exception:
                                        alt_text = f"Link to {uri[:50]}"
                                else:
                                    alt_text = f"Link: {uri[:50]}"

                        annot.Contents = String(alt_text)
                        modified_count += 1

        pdf.save(output_path)

    return output_path, modified_count


def detect_headings(pdf_path: str) -> List[dict]:
    """
    Detect potential headings in a PDF based on font size analysis.

    Uses PyMuPDF to analyze text blocks and identify headings based on:
    - Font size relative to body text
    - Bold/weight characteristics
    - Position on page (often at top or after whitespace)

    Returns list of detected headings with level (1-3), text, page, and bbox.
    """
    headings = []

    doc = fitz.open(pdf_path)

    # First pass: collect all font sizes to determine thresholds
    all_font_sizes = []
    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        size = span["size"]
                        text = span["text"].strip()
                        if text and len(text) > 2:  # Ignore very short text
                            all_font_sizes.append(size)

    if not all_font_sizes:
        doc.close()
        return headings

    # Calculate font size thresholds
    all_font_sizes.sort()
    median_size = all_font_sizes[len(all_font_sizes) // 2]

    # Headings are typically larger than body text
    h1_threshold = median_size * 1.5  # 50% larger = H1
    h2_threshold = median_size * 1.25  # 25% larger = H2
    h3_threshold = median_size * 1.1   # 10% larger = H3

    # Second pass: identify headings
    for page_num, page in enumerate(doc):
        blocks = page.get_text("dict")["blocks"]

        for block in blocks:
            if "lines" not in block:
                continue

            for line in block["lines"]:
                # Combine spans in the line
                line_text = ""
                line_size = 0
                line_flags = 0

                for span in line["spans"]:
                    line_text += span["text"]
                    line_size = max(line_size, span["size"])
                    line_flags |= span["flags"]

                line_text = line_text.strip()

                # Skip empty or very long lines (likely paragraphs)
                if not line_text or len(line_text) > 200:
                    continue

                # Skip lines that look like page numbers or footnotes
                if line_text.isdigit() or line_text.startswith("["):
                    continue

                # Determine heading level
                is_bold = bool(line_flags & 2**4)  # Bold flag
                level = 0

                if line_size >= h1_threshold:
                    level = 1
                elif line_size >= h2_threshold or (line_size >= h3_threshold and is_bold):
                    level = 2
                elif line_size >= h3_threshold:
                    level = 3
                elif is_bold and line_size >= median_size:
                    # Bold text at normal size could be H3
                    level = 3

                if level > 0:
                    headings.append({
                        "level": level,
                        "text": line_text,
                        "page": page_num,
                        "bbox": list(block["bbox"]),
                        "font_size": line_size,
                        "is_bold": is_bold,
                    })

    doc.close()
    return headings


def detect_content_elements(pdf_path: str) -> List[dict]:
    """
    Detect all content elements in a PDF: headings, paragraphs, formulas/matrices.

    Uses heuristics based on:
    - Font size analysis for headings
    - Text length and structure for paragraphs
    - Mathematical symbols and bracket patterns for formulas

    Returns list of content elements with type, text, page, and bbox.
    """
    elements = []
    doc = fitz.open(pdf_path)

    # First pass: collect all font sizes to determine thresholds
    all_font_sizes = []
    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        size = span["size"]
                        text = span["text"].strip()
                        if text and len(text) > 2:
                            all_font_sizes.append(size)

    if not all_font_sizes:
        doc.close()
        return elements

    # Calculate thresholds
    all_font_sizes.sort()
    median_size = all_font_sizes[len(all_font_sizes) // 2]
    h1_threshold = median_size * 1.5
    h2_threshold = median_size * 1.25
    h3_threshold = median_size * 1.1

    # Mathematical/formula indicators
    # Include standard math symbols and Private Use Area (PUA) characters (U+E000-U+F8FF, U+F0000-U+FFFFD)
    # Many PDFs use PUA for custom bracket glyphs
    math_brackets = set(['[', ']', '(', ')', '{', '}', '⎡', '⎤', '⎣', '⎦', '⎧', '⎫', '⎨', '⎬', '⎩', '⎭',
                        '∑', '∏', '∫', '√', '∞', '≠', '≤', '≥', '±', '×', '÷', '·', '∈', '∉', '⊂', '⊃',
                        '∀', '∃', '∇', '∂', '≈', '≡', '∝', '→', '←', '↔', '⇒', '⇐', '⇔'])

    # Second pass: classify each block
    for page_num, page in enumerate(doc):
        blocks = page.get_text("dict")["blocks"]

        for block_idx, block in enumerate(blocks):
            if "lines" not in block:
                # Image block - skip for now (handled by figure_extractor)
                continue

            # Extract block text and properties
            block_text = ""
            max_size = 0
            block_flags = 0
            has_math_chars = False

            for line in block["lines"]:
                for span in line["spans"]:
                    span_text = span["text"]
                    block_text += span_text
                    max_size = max(max_size, span["size"])
                    block_flags |= span["flags"]
                    # Check for math characters (including PUA range)
                    for c in span_text:
                        if c in math_brackets:
                            has_math_chars = True
                            break
                        # Check PUA ranges: U+E000-U+F8FF (BMP PUA) and U+F0000-U+FFFFD (Supplementary PUA-A)
                        code = ord(c)
                        if (0xE000 <= code <= 0xF8FF) or (0xF0000 <= code <= 0xFFFFD):
                            has_math_chars = True
                            break
                block_text += " "

            block_text = block_text.strip()
            bbox = list(block["bbox"])

            # Skip empty blocks or page numbers
            if not block_text or (block_text.isdigit() and len(block_text) <= 3):
                continue

            # Classify the block
            is_bold = bool(block_flags & 2**4)
            element_type = None
            heading_level = 0

            # Check if it's a formula/matrix
            # Criteria: contains math brackets AND is short, or mostly numbers/symbols
            is_formula = False

            # Count alphabetic vs non-alphabetic characters to determine if it's prose or math
            alpha_count = sum(1 for c in block_text if c.isalpha())
            total_chars = len(block_text.replace(" ", ""))

            # If it has math chars but is mostly alphabetic text (>60%), it's probably prose with a symbol
            if has_math_chars:
                if total_chars > 0 and alpha_count / total_chars < 0.6:
                    # Mostly non-alphabetic (numbers, symbols) - likely formula
                    is_formula = True
                elif len(block_text) < 30:
                    # Short block with math chars is likely formula
                    is_formula = True

            # Also check for matrix/array patterns
            if not is_formula:
                if re.search(r'[\[\(⎡⎣]\s*[\d,.\s]+', block_text):
                    # Pattern like "[16,000 23" suggesting matrix
                    is_formula = True
                elif len(block_text) < 50 and re.match(r'^[\d\s,.\-\+\*\/\=\<\>]+$', block_text):
                    # Short block with mostly numbers and operators
                    is_formula = True

            if is_formula:
                element_type = "Formula"
            # Check if heading
            elif max_size >= h1_threshold and len(block_text) < 200:
                element_type = "H1"
                heading_level = 1
            elif max_size >= h2_threshold and len(block_text) < 200:
                element_type = "H2"
                heading_level = 2
            elif max_size >= h3_threshold and len(block_text) < 200:
                element_type = "H3"
                heading_level = 3
            elif is_bold and max_size >= median_size and len(block_text) < 100:
                element_type = "H3"
                heading_level = 3
            else:
                # Default to paragraph
                element_type = "P"

            elements.append({
                "type": element_type,
                "text": block_text[:500],  # Limit text length
                "page": page_num,
                "block_idx": block_idx,
                "bbox": bbox,
                "font_size": max_size,
                "heading_level": heading_level,
            })

    doc.close()
    return elements


def inject_mcids_into_form_xobject(
    pdf: pikepdf.Pdf,
    xobj: pikepdf.Object,
    page_elements: List[dict],
    page_height: float,
) -> Tuple[dict, int]:
    """
    Inject BDC/EMC marked content operators into a Form XObject's content stream.

    This wraps text segments with appropriate marked content tags based on
    the element bounding boxes from PyMuPDF.

    Args:
        pdf: The pikepdf PDF object
        xobj: The Form XObject to modify
        page_elements: List of elements for this page with bbox info
        page_height: Page height for coordinate transformation

    Returns:
        Tuple of (element_idx -> mcid mapping, total mcid count)
    """
    # Parse existing content stream
    existing_ops = list(parse_content_stream(xobj))

    # Get Form's transformation info
    form_bbox = [float(x) for x in xobj.BBox] if Name.BBox in xobj else [0, 0, 612, 792]

    # Build mapping of element index to MCID
    # Each element gets a unique MCID
    element_mcids = {i: i for i in range(len(page_elements))}

    # Convert page coordinates (PyMuPDF) to form coordinates
    # PyMuPDF uses top-left origin, PDF uses bottom-left
    def page_to_form_y(page_y):
        return page_height - page_y

    # Sort elements by their form-space Y coordinate (top to bottom in visual order)
    sorted_elems = sorted(enumerate(page_elements),
                          key=lambda x: -page_to_form_y(x[1]['bbox'][1]))

    # Track current position in form content
    new_ops = []
    current_y = None
    current_elem_idx = 0
    in_mcid = False
    last_tm_y = None

    for operands, operator in existing_ops:
        op = str(operator)

        # Track Y position from Tm (text matrix) operators
        if op == 'Tm' and len(operands) >= 6:
            new_y = float(operands[5])  # Y coordinate in form space

            # Check if we should start a new element's MCID based on Y position
            if last_tm_y is not None and abs(new_y - last_tm_y) > 5:
                # Significant Y change - might be a new element
                if in_mcid:
                    new_ops.append(([], pikepdf.Operator("EMC")))
                    in_mcid = False
                    current_elem_idx += 1

            if not in_mcid and current_elem_idx < len(page_elements):
                # Start new MCID
                elem = page_elements[current_elem_idx]
                struct_type = Name("/" + elem['type'])
                props = Dictionary({"/MCID": current_elem_idx})
                new_ops.append(([struct_type, props], pikepdf.Operator("BDC")))
                in_mcid = True

            last_tm_y = new_y

        new_ops.append((operands, operator))

    # Close any open MCID
    if in_mcid:
        new_ops.append(([], pikepdf.Operator("EMC")))

    # Update the XObject's content stream
    new_content = unparse_content_stream(new_ops)
    xobj.write(new_content)

    return element_mcids, len(page_elements)


def add_content_tags(
    pdf_path: str,
    elements: List[dict],
    output_path: Optional[str] = None,
    use_ai_formula_descriptions: bool = False,
    formula_descriptions: Optional[dict] = None,
) -> str:
    """
    Add structure elements for all detected content (headings, paragraphs, formulas).

    This function REPLACES any existing structure tree content with the new
    content-based tags. The original PDF may have Figure-only tags that don't
    properly represent the document structure.

    Args:
        pdf_path: Path to input PDF
        elements: List of element dicts from detect_content_elements()
        output_path: Optional output path
        use_ai_formula_descriptions: If True, use pre-generated AI descriptions for formulas
        formula_descriptions: Dict mapping (page, block_idx) to AI-generated descriptions

    Returns:
        Path to output PDF
    """
    if output_path is None:
        p = Path(pdf_path)
        output_path = str(p.parent / f"{p.stem}_content_tagged{p.suffix}")

    if formula_descriptions is None:
        formula_descriptions = {}

    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        # Create structure tree with per-element MCIDs
        # Each element gets its own MCID in the Form XObject content stream

        # Create Document element
        doc_elem = pdf.make_indirect(Dictionary({
            "/Type": Name.StructElem,
            "/S": Name.Document,
            "/K": Array([]),
        }))

        # Map element types to PDF structure element names
        type_name_map = {
            "H1": Name.H1,
            "H2": Name.H2,
            "H3": Name.H3,
            "P": Name.P,
            "Formula": Name.Formula,
        }

        # Group elements by page
        elements_by_page = {}
        for i, elem in enumerate(elements):
            page_num = elem["page"]
            if page_num not in elements_by_page:
                elements_by_page[page_num] = []
            elem["global_idx"] = i  # Track global index
            elements_by_page[page_num].append(elem)

        # Track structure elements for ParentTree
        parent_tree_entries = {}  # page_num -> list of struct_elem refs indexed by MCID

        # Process each page
        for page_num in sorted(elements_by_page.keys()):
            page_elements = elements_by_page[page_num]
            page = pdf.pages[page_num]
            page_ref = page.obj

            parent_tree_entries[page_num] = []

            # Get the Form XObject that contains the actual content
            xobj = None
            xobj_name = None
            if hasattr(page, 'Resources') and Name.XObject in page.Resources:
                for name in page.Resources.XObject.keys():
                    obj = page.Resources.XObject[name]
                    if obj.get('/Subtype') == Name.Form:
                        xobj = obj
                        xobj_name = name
                        break

            # Create structure elements for each content element
            struct_elems = []
            for elem_idx, elem in enumerate(page_elements):
                elem_type = elem["type"]
                struct_name = type_name_map.get(elem_type, Name.P)
                mcid = elem_idx  # MCID within this page

                # Create MCR (Marked Content Reference)
                mcr = Dictionary({
                    "/Type": Name.MCR,
                    "/Pg": page_ref,
                    "/MCID": mcid,
                })

                # Create structure element with MCR
                struct_elem = pdf.make_indirect(Dictionary({
                    "/Type": Name.StructElem,
                    "/S": struct_name,
                    "/P": doc_elem,
                    "/Pg": page_ref,
                    "/K": mcr,
                    "/A": Dictionary({
                        "/O": Name.Layout,
                        "/BBox": Array(elem["bbox"]),
                    }),
                }))

                # Add alt-text
                if elem_type == "Formula":
                    key = (elem["page"], elem["block_idx"])
                    if use_ai_formula_descriptions and key in formula_descriptions:
                        alt_text = formula_descriptions[key]
                    else:
                        alt_text = f"Mathematical formula: {elem['text'][:200]}"
                    struct_elem[Name.Alt] = String(alt_text)
                elif elem_type in ("H1", "H2", "H3"):
                    struct_elem[Name.Alt] = String(elem["text"][:200])

                doc_elem.K.append(struct_elem)
                struct_elems.append(struct_elem)
                parent_tree_entries[page_num].append(struct_elem)

            # Modify page content stream to add MCIDs
            # Replace the single /Figure BDC with multiple element BDCs
            existing_ops = list(parse_content_stream(page))
            new_page_ops = []

            # Track nesting to properly match Figure's EMC
            in_figure_block = False

            for operands, operator in existing_ops:
                op_name = str(operator)
                if op_name == "BDC" and len(operands) >= 1 and str(operands[0]) == "/Figure":
                    # Replace single Figure tag with multiple element tags
                    in_figure_block = True
                    for elem_idx, elem in enumerate(page_elements):
                        struct_name = type_name_map.get(elem["type"], Name.P)
                        props = Dictionary({"/MCID": elem_idx})
                        new_page_ops.append(([struct_name, props], pikepdf.Operator("BDC")))
                elif op_name == "EMC" and in_figure_block:
                    # Close all the element tags (only for the Figure block's EMC)
                    in_figure_block = False
                    for _ in page_elements:
                        new_page_ops.append(([], pikepdf.Operator("EMC")))
                else:
                    new_page_ops.append((operands, operator))

            # Update page content stream
            new_content = unparse_content_stream(new_page_ops)
            page.Contents = pdf.make_stream(new_content)
            page.StructParents = page_num

        # Build ParentTree
        nums_array = Array([])
        for page_num in sorted(parent_tree_entries.keys()):
            struct_refs = Array(parent_tree_entries[page_num])
            nums_array.append(page_num)
            nums_array.append(struct_refs)

        parent_tree = Dictionary({"/Nums": nums_array})

        # Create StructTreeRoot
        struct_tree = pdf.make_indirect(Dictionary({
            "/Type": Name.StructTreeRoot,
            "/K": Array([doc_elem]),
            "/ParentTree": parent_tree,
            "/ParentTreeNextKey": len(pdf.pages),
        }))

        doc_elem.P = struct_tree
        pdf.Root.StructTreeRoot = struct_tree

        pdf.save(output_path)

    return output_path


def generate_formula_descriptions(
    pdf_path: str,
    elements: List[dict],
    max_formulas: int = 50,
) -> dict:
    """
    Generate AI descriptions for formula elements by rendering and sending to Gemini.

    Args:
        pdf_path: Path to the PDF file
        elements: List of content elements from detect_content_elements()
        max_formulas: Maximum number of formulas to process (to limit API calls)

    Returns:
        Dict mapping (page, block_idx) to description string
    """
    from .ai_describer import describe_formula_from_pdf

    descriptions = {}
    formula_count = 0

    for elem in elements:
        if elem["type"] != "Formula":
            continue

        if formula_count >= max_formulas:
            break

        key = (elem["page"], elem["block_idx"])
        bbox = tuple(elem["bbox"])

        try:
            description = describe_formula_from_pdf(
                pdf_path=pdf_path,
                page_num=elem["page"],
                bbox=bbox,
            )
            descriptions[key] = description
            formula_count += 1
        except Exception as e:
            # Fallback on error
            descriptions[key] = f"Mathematical formula: {elem['text'][:100]}"

    return descriptions


def add_heading_tags(
    pdf_path: str,
    headings: List[dict],
    output_path: Optional[str] = None,
) -> str:
    """
    Add heading structure elements (H1, H2, H3) to the PDF structure tree.

    Args:
        pdf_path: Path to input PDF
        headings: List of heading dicts from detect_headings()
        output_path: Optional output path

    Returns:
        Path to output PDF
    """
    if output_path is None:
        p = Path(pdf_path)
        output_path = str(p.parent / f"{p.stem}_headings{p.suffix}")

    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        # Ensure structure tree exists
        if Name.StructTreeRoot not in pdf.Root:
            # Create basic structure first
            parent_tree = Dictionary({"/Nums": Array([])})
            pdf.Root.StructTreeRoot = Dictionary({
                "/Type": Name.StructTreeRoot,
                "/K": Array([]),
                "/ParentTree": parent_tree,
            })

        struct_tree = pdf.Root.StructTreeRoot

        # Get or create Document element
        doc_elem = None
        if Name.K in struct_tree:
            k = struct_tree.K
            if isinstance(k, Array) and len(k) > 0:
                first = k[0]
                if isinstance(first, Dictionary) and Name.S in first:
                    if first.S == Name.Document:
                        doc_elem = first

        if doc_elem is None:
            doc_elem = pdf.make_indirect(Dictionary({
                "/Type": Name.StructElem,
                "/S": Name.Document,
                "/P": struct_tree,
                "/K": Array([]),
            }))
            if Name.K not in struct_tree:
                struct_tree.K = Array([])
            if isinstance(struct_tree.K, Array):
                struct_tree.K.append(doc_elem)
            else:
                old_k = struct_tree.K
                struct_tree.K = Array([old_k, doc_elem])

        # Add heading elements
        heading_name_map = {
            1: Name.H1,
            2: Name.H2,
            3: Name.H3,
        }

        for heading in headings:
            level = heading["level"]
            heading_name = heading_name_map.get(level, Name.H)

            # Create heading element
            heading_elem = pdf.make_indirect(Dictionary({
                "/Type": Name.StructElem,
                "/S": heading_name,
                "/P": doc_elem,
                "/Alt": String(heading["text"]),  # Add alt-text as well
                "/A": Dictionary({
                    "/O": Name.Layout,
                    "/BBox": Array(heading["bbox"]),
                }),
            }))

            # Add to Document children
            if Name.K not in doc_elem:
                doc_elem.K = Array([])

            if isinstance(doc_elem.K, Array):
                doc_elem.K.append(heading_elem)
            else:
                old_k = doc_elem.K
                doc_elem.K = Array([old_k, heading_elem])

        pdf.save(output_path)

    return output_path


def create_full_structure(
    pdf_path: str,
    output_path: Optional[str] = None,
    title: Optional[str] = None,
    author: str = "",
    lang: str = "en-US",
    tag_headings: bool = True,
    tag_all_content: bool = True,
    fix_links: bool = True,
    use_ai_formula_descriptions: bool = False,
    max_ai_formulas: int = 50,
) -> dict:
    """
    Create comprehensive PDF/UA structure including all accessibility features.

    This is an enhanced version of create_basic_structure that also:
    - Adds XMP metadata stream
    - Adds Tabs key to pages with annotations
    - Tags all content elements (headings, paragraphs, formulas)
    - Optionally uses AI (Gemini Vision) to describe formulas
    - Optionally fixes link annotations

    Args:
        pdf_path: Path to input PDF
        output_path: Optional output path
        title: Document title
        author: Document author
        lang: Document language
        tag_headings: Whether to detect and tag headings (legacy, use tag_all_content)
        tag_all_content: Whether to tag all content (headings, paragraphs, formulas)
        fix_links: Whether to add alt-text to links
        use_ai_formula_descriptions: If True, use Gemini Vision API to generate human-readable
            descriptions for mathematical formulas (e.g., "A 3x3 matrix with values...").
            If False (default), formulas get raw extracted text which may contain
            unreadable characters. Requires GEMINI_API_KEY in environment.
        max_ai_formulas: Maximum number of formulas to process with AI (default: 50).
            Set higher to cover all formulas, or lower to reduce processing time.
            Formulas beyond this limit fall back to raw text extraction.

    Returns:
        Dict with output_path and statistics including:
        - output_path: Path to the generated PDF
        - headings_tagged: Number of H1/H2/H3 elements tagged
        - paragraphs_tagged: Number of P elements tagged
        - formulas_tagged: Number of Formula elements tagged
        - ai_formula_descriptions: Number of formulas described by AI (if enabled)
        - links_fixed: Number of link annotations with added alt-text
    """
    if output_path is None:
        p = Path(pdf_path)
        output_path = str(p.parent / f"{p.stem}_full_structure{p.suffix}")

    result = {
        "output_path": output_path,
        "xmp_added": False,
        "tabs_pages_modified": 0,
        "headings_tagged": 0,
        "paragraphs_tagged": 0,
        "formulas_tagged": 0,
        "links_fixed": 0,
    }

    # Extract title if not provided
    if not title:
        title = extract_title_from_pdf(pdf_path) or Path(pdf_path).stem

    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        # 1. Basic structure (MarkInfo, Lang, ViewerPreferences, StructTreeRoot)
        # MarkInfo
        pdf.Root.MarkInfo = Dictionary({
            "/Marked": True,
            "/Suspects": False,
        })

        # Language
        pdf.Root.Lang = lang

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

        # Set docinfo title
        if not pdf.docinfo:
            pdf.docinfo = Dictionary()
        pdf.docinfo[Name.Title] = title

        # 2. Add XMP metadata
        add_xmp_metadata(pdf, title=title, author=author, lang=lang)
        result["xmp_added"] = True

        # 3. Add Tabs key to pages with annotations
        result["tabs_pages_modified"] = add_page_tabs_key(pdf)

        pdf.save(output_path)

    # 4. Tag all content (headings, paragraphs, formulas) - NEW comprehensive approach
    if tag_all_content:
        elements = detect_content_elements(output_path)
        if elements:
            # Generate AI descriptions for formulas if requested
            formula_descriptions = {}
            if use_ai_formula_descriptions:
                formula_descriptions = generate_formula_descriptions(
                    pdf_path=output_path,
                    elements=elements,
                    max_formulas=max_ai_formulas,
                )
                result["ai_formula_descriptions"] = len(formula_descriptions)

            add_content_tags(
                output_path, elements, output_path,
                use_ai_formula_descriptions=use_ai_formula_descriptions,
                formula_descriptions=formula_descriptions,
            )

            # Count by type
            for elem in elements:
                if elem["type"] in ("H1", "H2", "H3"):
                    result["headings_tagged"] += 1
                elif elem["type"] == "P":
                    result["paragraphs_tagged"] += 1
                elif elem["type"] == "Formula":
                    result["formulas_tagged"] += 1

            # Include sample elements in result
            result["elements_sample"] = [
                {"type": e["type"], "text": e["text"][:50], "page": e["page"]}
                for e in elements[:15]
            ]
    elif tag_headings:
        # Legacy: only tag headings
        headings = detect_headings(output_path)
        if headings:
            add_heading_tags(output_path, headings, output_path)
            result["headings_tagged"] = len(headings)
            result["headings"] = [
                {"level": h["level"], "text": h["text"][:50], "page": h["page"]}
                for h in headings[:10]
            ]

    # 5. Fix link annotations (if requested)
    if fix_links:
        _, links_fixed = add_link_alt_texts(output_path, output_path)
        result["links_fixed"] = links_fixed

    return result


if __name__ == "__main__":
    # Test with a sample PDF
    import sys
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        print(f"Checking: {pdf_path}")
        info = get_pdf_info(pdf_path)
        print(f"Info: {info}")

        if not info["is_tagged"]:
            print("PDF is not tagged. Creating full structure...")
            result = create_full_structure(pdf_path)
            print(f"Created: {result['output_path']}")
            print(f"XMP added: {result['xmp_added']}")
            print(f"Tabs pages modified: {result['tabs_pages_modified']}")
            print(f"Headings tagged: {result['headings_tagged']}")
            print(f"Links fixed: {result['links_fixed']}")
            print(f"New info: {get_pdf_info(result['output_path'])}")
