"""
AI Describer - Generate alt-text for figures using Gemini API and OCR.

Uses:
- Google's Gemini Vision model to analyze images and generate descriptions
- Tesseract OCR to extract any text embedded in figures
- Combined approach for comprehensive accessibility
"""

import google.generativeai as genai
from pathlib import Path
from typing import Optional, List, Tuple
import base64
import os
import io
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# OCR imports (lazy loaded)
_pytesseract = None
_Image = None


def _load_ocr():
    """Lazy load OCR dependencies."""
    global _pytesseract, _Image
    if _pytesseract is None:
        try:
            import pytesseract
            from PIL import Image
            _pytesseract = pytesseract
            _Image = Image
        except ImportError:
            pass
    return _pytesseract, _Image


def extract_text_ocr(image_data: bytes) -> str:
    """
    Extract text from an image using Tesseract OCR.

    Args:
        image_data: Image bytes (PNG/JPEG)

    Returns:
        Extracted text string, or empty string if OCR fails/unavailable
    """
    pytesseract, Image = _load_ocr()
    if pytesseract is None:
        return ""

    try:
        img = Image.open(io.BytesIO(image_data))
        # Use Tesseract to extract text
        text = pytesseract.image_to_string(img, lang='eng')
        # Clean up the text
        text = ' '.join(text.split())  # Normalize whitespace
        return text.strip()
    except Exception as e:
        return ""


def extract_text_with_confidence(image_data: bytes) -> Tuple[str, float]:
    """
    Extract text from an image with confidence score.

    Uses multiple OCR strategies and returns the best result.

    Returns:
        Tuple of (extracted_text, average_confidence)
    """
    pytesseract, Image = _load_ocr()
    if pytesseract is None:
        return "", 0.0

    try:
        img = Image.open(io.BytesIO(image_data))

        # Try multiple PSM modes and pick the best result
        best_text = ""
        best_conf = 0.0

        # PSM modes to try:
        # 3 = Fully automatic (default)
        # 4 = Single column of text
        # 6 = Assume uniform block of text
        # 11 = Sparse text
        for psm in [6, 3, 4, 11]:
            try:
                config = f'--psm {psm}'
                data = pytesseract.image_to_data(
                    img, lang='eng',
                    output_type=pytesseract.Output.DICT,
                    config=config
                )

                texts = []
                confidences = []

                for i, word in enumerate(data['text']):
                    if word.strip():
                        conf = int(data['conf'][i])
                        if conf > 0:  # Valid confidence
                            texts.append(word)
                            confidences.append(conf)

                if texts:
                    text = ' '.join(texts)
                    avg_conf = sum(confidences) / len(confidences) / 100.0

                    # Keep the result with most text if confidence is reasonable
                    if len(text) > len(best_text) and avg_conf > 0.3:
                        best_text = text
                        best_conf = avg_conf
                    elif avg_conf > best_conf and len(text) > len(best_text) * 0.7:
                        best_text = text
                        best_conf = avg_conf
            except Exception:
                continue

        return best_text.strip(), best_conf
    except Exception:
        return "", 0.0


def configure_gemini(api_key: Optional[str] = None):
    """Configure the Gemini API with the provided key."""
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY not found. Set it in .env or pass directly.")
    genai.configure(api_key=key)


def generate_alt_text(
    image_data: bytes,
    context: str = "",
    document_type: str = "academic paper",
    api_key: Optional[str] = None,
    include_ocr: bool = True,
) -> str:
    """
    Generate alt-text for an image using Gemini Vision and optional OCR.

    Args:
        image_data: Image bytes (PNG/JPEG)
        context: Optional context about the image (caption, surrounding text)
        document_type: Type of document for context (e.g., "academic paper", "textbook")
        api_key: Optional API key (uses env var if not provided)
        include_ocr: Whether to extract and include OCR text (default: True)

    Returns:
        Generated alt-text string
    """
    configure_gemini(api_key)

    # Extract OCR text if enabled
    ocr_text = ""
    if include_ocr:
        ocr_text, confidence = extract_text_with_confidence(image_data)
        if ocr_text and confidence > 0.5:  # Only use if reasonably confident
            ocr_text = ocr_text[:500]  # Limit length

    # Use Gemini 2.0 Flash (supports vision)
    model = genai.GenerativeModel("gemini-2.0-flash")

    # Build the prompt for accessible alt-text
    ocr_section = ""
    if ocr_text:
        ocr_section = f"""
Text extracted from the image via OCR:
\"\"\"{ocr_text}\"\"\"

Please incorporate this text into your description where relevant."""

    prompt = f"""You are an expert at writing accessible alt-text for images in {document_type}s.

Generate a concise but descriptive alt-text for this image that would help a blind or visually impaired reader understand:
1. What type of figure this is (graph, diagram, photo, chart, etc.)
2. The key information or data being conveyed
3. Any important trends, relationships, or conclusions visible

Guidelines for alt-text:
- Be concise but informative (aim for 1-3 sentences)
- Don't start with "Image of" or "Picture of" - just describe the content
- For graphs/charts: describe the type, axes, and main trends
- For diagrams: describe the structure and key components
- For photos: describe the subject and relevant details
- Include specific numbers/data if they're important to understanding
- If there is text in the image, include the key text content
{ocr_section}
{f"Context from the document: {context}" if context else ""}

Respond with ONLY the alt-text, no additional commentary or formatting."""

    # Create the image part
    image_part = {
        "mime_type": "image/png",
        "data": base64.b64encode(image_data).decode("utf-8"),
    }

    try:
        response = model.generate_content([prompt, image_part])
        alt_text = response.text.strip()

        # Clean up any potential quotes or extra formatting
        alt_text = alt_text.strip('"\'')

        return alt_text

    except Exception as e:
        return f"[Alt-text generation failed: {str(e)}]"


def generate_alt_text_with_ocr(
    image_data: bytes,
    context: str = "",
    document_type: str = "academic paper",
    api_key: Optional[str] = None,
) -> dict:
    """
    Generate alt-text with separate OCR text extraction.

    Returns dict with:
    - alt_text: The generated description
    - ocr_text: Raw OCR extracted text
    - ocr_confidence: OCR confidence score (0-1)
    """
    # Extract OCR
    ocr_text, confidence = extract_text_with_confidence(image_data)

    # Generate alt-text (OCR already included in the function)
    alt_text = generate_alt_text(
        image_data=image_data,
        context=context,
        document_type=document_type,
        api_key=api_key,
        include_ocr=True,
    )

    return {
        "alt_text": alt_text,
        "ocr_text": ocr_text,
        "ocr_confidence": confidence,
    }


def generate_alt_texts_batch(
    images: List[dict],
    api_key: Optional[str] = None,
) -> List[str]:
    """
    Generate alt-text for multiple images.

    Args:
        images: List of dicts with 'image_data' and optional 'context'
        api_key: Optional API key

    Returns:
        List of alt-text strings in the same order
    """
    results = []
    for img in images:
        alt_text = generate_alt_text(
            image_data=img["image_data"],
            context=img.get("context", ""),
            api_key=api_key,
        )
        results.append(alt_text)
    return results


def generate_formula_description(
    image_data: bytes,
    context: str = "",
    api_key: Optional[str] = None,
) -> str:
    """
    Generate a human-readable description of a mathematical formula/equation.

    This is specialized for math content - matrices, equations, integrals, etc.
    The description is optimized for screen reader users.

    Args:
        image_data: Image bytes of the rendered formula region (PNG)
        context: Optional context about the formula (surrounding text)
        api_key: Optional API key (uses env var if not provided)

    Returns:
        Human-readable description of the formula
    """
    configure_gemini(api_key)

    # Use Gemini 2.0 Flash (supports vision)
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""You are an expert at describing mathematical formulas for blind and visually impaired users.

Describe this mathematical content in plain English that a screen reader user can understand.

Guidelines:
- For MATRICES: State the dimensions (e.g., "3 by 2 matrix"), then read the values row by row
  Example: "A 3 by 2 matrix. Row 1: 16,000 and 23. Row 2: 33,000 and 47. Row 3: 21,000 and 35."
- For EQUATIONS: Read left to right, spell out operations
  Example: "x equals negative b plus or minus the square root of b squared minus 4ac, all over 2a"
- For INTEGRALS: Describe the integral sign, limits, and integrand
  Example: "The integral from 0 to infinity of e to the negative x squared dx"
- For SUMMATIONS: Describe the sigma notation and terms
  Example: "The sum from i equals 1 to n of x sub i"
- For FRACTIONS: Use "over" or "divided by"
- For SUBSCRIPTS/SUPERSCRIPTS: Use "sub" and "to the power of" or "squared"/"cubed"
- For GREEK LETTERS: Name them (alpha, beta, gamma, etc.)

Be concise but complete. Include all values and symbols.
{f"Context from document: {context}" if context else ""}

Respond with ONLY the description, no additional commentary."""

    # Create the image part
    image_part = {
        "mime_type": "image/png",
        "data": base64.b64encode(image_data).decode("utf-8"),
    }

    try:
        response = model.generate_content([prompt, image_part])
        description = response.text.strip()
        description = description.strip('"\'')
        return description

    except Exception as e:
        return f"[Formula description failed: {str(e)}]"


def render_pdf_region(
    pdf_path: str,
    page_num: int,
    bbox: tuple,
    scale: float = 2.0,
) -> bytes:
    """
    Render a specific region of a PDF page as a PNG image.

    Args:
        pdf_path: Path to the PDF file
        page_num: Page number (0-indexed)
        bbox: Bounding box tuple (x0, y0, x1, y1)
        scale: Scale factor for rendering (default 2.0 for clarity)

    Returns:
        PNG image bytes of the rendered region
    """
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    page = doc[page_num]

    # Create a clip rectangle from the bounding box
    x0, y0, x1, y1 = bbox
    clip_rect = fitz.Rect(x0, y0, x1, y1)

    # Create a transformation matrix for scaling
    mat = fitz.Matrix(scale, scale)

    # Render just the clipped region
    pix = page.get_pixmap(matrix=mat, clip=clip_rect)

    # Convert to PNG bytes
    png_bytes = pix.tobytes("png")

    doc.close()
    return png_bytes


def describe_formula_from_pdf(
    pdf_path: str,
    page_num: int,
    bbox: tuple,
    context: str = "",
    api_key: Optional[str] = None,
) -> str:
    """
    Render a formula region from a PDF and generate a human-readable description.

    This combines rendering and AI description in one call.

    Args:
        pdf_path: Path to the PDF file
        page_num: Page number (0-indexed)
        bbox: Bounding box of the formula (x0, y0, x1, y1)
        context: Optional context about the formula
        api_key: Optional API key

    Returns:
        Human-readable description of the formula
    """
    # Render the formula region as an image
    image_data = render_pdf_region(pdf_path, page_num, bbox, scale=2.0)

    # Generate description using Gemini Vision
    description = generate_formula_description(
        image_data=image_data,
        context=context,
        api_key=api_key,
    )

    return description


def validate_alt_text(alt_text: str) -> dict:
    """
    Validate alt-text quality based on accessibility guidelines.

    Returns dict with 'valid' boolean and 'issues' list.
    """
    issues = []

    if not alt_text or alt_text.startswith("["):
        return {"valid": False, "issues": ["Alt-text is missing or failed to generate"]}

    # Check length
    if len(alt_text) < 10:
        issues.append("Alt-text may be too short to be descriptive")
    if len(alt_text) > 500:
        issues.append("Alt-text may be too long; consider being more concise")

    # Check for bad patterns
    bad_starts = ["image of", "picture of", "photo of", "figure showing"]
    if any(alt_text.lower().startswith(pat) for pat in bad_starts):
        issues.append("Alt-text should not start with 'Image of' or similar phrases")

    # Check for placeholder text
    placeholder_patterns = ["placeholder", "todo", "insert", "add description"]
    if any(pat in alt_text.lower() for pat in placeholder_patterns):
        issues.append("Alt-text appears to contain placeholder text")

    return {"valid": len(issues) == 0, "issues": issues}


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        print(f"Generating alt-text for: {image_path}")

        image_data = Path(image_path).read_bytes()
        alt_text = generate_alt_text(image_data)
        print(f"\nGenerated alt-text:\n{alt_text}")

        validation = validate_alt_text(alt_text)
        print(f"\nValidation: {validation}")
