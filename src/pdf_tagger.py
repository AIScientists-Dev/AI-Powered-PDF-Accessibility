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
from pikepdf import Name, Array, Dictionary, String, Stream
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
    fix_links: bool = True,
) -> dict:
    """
    Create comprehensive PDF/UA structure including all accessibility features.

    This is an enhanced version of create_basic_structure that also:
    - Adds XMP metadata stream
    - Adds Tabs key to pages with annotations
    - Optionally tags headings
    - Optionally fixes link annotations

    Args:
        pdf_path: Path to input PDF
        output_path: Optional output path
        title: Document title
        author: Document author
        lang: Document language
        tag_headings: Whether to detect and tag headings
        fix_links: Whether to add alt-text to links

    Returns:
        Dict with output_path and statistics
    """
    if output_path is None:
        p = Path(pdf_path)
        output_path = str(p.parent / f"{p.stem}_full_structure{p.suffix}")

    result = {
        "output_path": output_path,
        "xmp_added": False,
        "tabs_pages_modified": 0,
        "headings_tagged": 0,
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

    # 4. Tag headings (if requested)
    if tag_headings:
        headings = detect_headings(output_path)
        if headings:
            add_heading_tags(output_path, headings, output_path)
            result["headings_tagged"] = len(headings)
            result["headings"] = [
                {"level": h["level"], "text": h["text"][:50], "page": h["page"]}
                for h in headings[:10]  # Only include first 10 in result
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
