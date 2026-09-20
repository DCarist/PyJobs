from __future__ import annotations

import datetime
import io
import logging
import os
import re
from pathlib import Path

import docx
import docx2pdf
import pymupdf

logger = logging.getLogger(__name__)


def extract_text_from_pdf(source: str | Path | bytes) -> str:
    """Extracts plain text from a PDF document using PyMuPDF."""
    text_chunks: list[str] = []
    doc = None
    try:
        if isinstance(source, bytes):
            doc = pymupdf.open(stream=source, filetype="pdf")
        else:
            doc = pymupdf.open(str(source))

        for page in doc:
            page_text = page.get_text("text")
            if page_text:
                text_chunks.append(page_text.strip())
    except Exception as e:
        logger.warning("Failed to extract text from PDF: %s", e)
    finally:
        if doc is not None:
            doc.close()

    return "\n\n".join(chunk for chunk in text_chunks if chunk)


def extract_text_from_docx(source: str | Path | bytes) -> str:
    """Extracts plain text from a Word (.docx) document using python-docx."""
    text_chunks: list[str] = []
    try:
        if isinstance(source, bytes):
            doc_file = io.BytesIO(source)
            doc = docx.Document(doc_file)
        else:
            doc = docx.Document(str(source))

        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if text:
                text_chunks.append(text)

        for table in doc.tables:
            for row in table.rows:
                row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_cells:
                    text_chunks.append(" | ".join(row_cells))
    except Exception as e:
        logger.warning("Failed to extract text from DOCX: %s", e)

    return "\n\n".join(text_chunks)


def extract_text(source: str | Path | bytes, file_type: str) -> str:
    """Extracts plain text from either a PDF or DOCX file."""
    normalized_type = file_type.lower().lstrip(".")
    if normalized_type == "pdf":
        return extract_text_from_pdf(source)
    if normalized_type in ("docx", "doc"):
        return extract_text_from_docx(source)
    return ""


def convert_docx_to_pdf_pure_pymupdf(docx_path: Path, output_pdf_path: Path) -> bool:
    """Fallback generator that converts a DOCX to a clean formatted PDF using PyMuPDF."""
    try:
        doc = docx.Document(str(docx_path))
        pdf = pymupdf.open()

        # Target dimensions: US Letter (612 x 792 points), 0.75-inch margin (54 points)
        margin = 54
        page_width = 612
        page_height = 792
        usable_width = page_width - (margin * 2)

        current_page = pdf.new_page(width=page_width, height=page_height)
        y_cursor = margin

        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                y_cursor += 12
                continue

            # Check if heading or regular text
            is_heading = p.style and "Heading" in p.style.name
            font_size = 14 if is_heading else 10
            line_height = 18 if is_heading else 14

            # Estimate lines required
            approx_chars_per_line = max(20, int(usable_width / (font_size * 0.55)))
            line_count = max(1, (len(text) // approx_chars_per_line) + 1)
            block_height = line_count * line_height + 4

            # Check if block fits on current page
            if y_cursor + block_height > (page_height - margin):
                current_page = pdf.new_page(width=page_width, height=page_height)
                y_cursor = margin

            rect = pymupdf.Rect(margin, y_cursor, margin + usable_width, y_cursor + block_height)
            current_page.insert_textbox(
                rect,
                text,
                fontsize=font_size,
                fontname="helv",
                color=(0.1, 0.1, 0.1) if not is_heading else (0.15, 0.35, 0.75),
            )
            y_cursor += block_height

        # If no paragraphs were output, create a minimal page
        if len(pdf) == 0:
            current_page = pdf.new_page(width=page_width, height=page_height)
            current_page.insert_text((margin, margin + 20), "Resume Document", fontsize=14)

        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(str(output_pdf_path))
        pdf.close()
        return True
    except Exception as e:
        logger.error("PyMuPDF DOCX fallback conversion failed: %s", e)
        return False


def convert_docx_to_pdf(docx_path: str | Path, output_pdf_path: str | Path) -> bool:
    """Converts DOCX to PDF using Word COM (docx2pdf) if available, falling back to PyMuPDF."""
    docx_p = Path(docx_path)
    output_p = Path(output_pdf_path)
    output_p.parent.mkdir(parents=True, exist_ok=True)

    # In test mode, use the pure PyMuPDF generator directly for hermetic sub-second execution
    if os.environ.get("PYJOBS_TESTING"):
        return convert_docx_to_pdf_pure_pymupdf(docx_p, output_p)

    # 1. Try docx2pdf (native Word / LibreOffice automation)
    try:
        docx2pdf.convert(str(docx_p), str(output_p))
        if output_p.exists() and output_p.stat().st_size > 0:
            return True
    except Exception as e:
        logger.info("docx2pdf conversion unavailable or failed (%s), using PyMuPDF fallback", e)

    # 2. Pure Python fallback via PyMuPDF
    return convert_docx_to_pdf_pure_pymupdf(docx_p, output_p)


def sanitize_filename_component(name: str) -> str:
    """Sanitizes strings for safe inclusion in filenames across Windows, macOS, and Linux."""
    # Replace Windows-illegal characters: \ / : * ? " < > |
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name)
    # Collapse multiple spaces or underscores
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "Resume"


def generate_download_filename(
    pattern: str,
    date_format: str,
    candidate_name: str,
    resume_title: str,
    version_number: int,
    file_ext: str,
    retrieval_date: datetime.date | None = None,
    company: str | None = None,
    job_title: str | None = None,
) -> str:
    """Renders a customized, auto-dated filename for resume retrieval."""
    if retrieval_date is None:
        retrieval_date = datetime.date.today()

    clean_ext = file_ext.lstrip(".").lower() or "pdf"

    # Default date formatting
    try:
        formatted_date = retrieval_date.strftime(date_format or "%m-%d-%Y")
    except Exception:
        formatted_date = retrieval_date.strftime("%m-%d-%Y")

    name_val = candidate_name.strip() if candidate_name else ""
    title_val = resume_title.strip() if resume_title else "Resume"

    # If pattern has {name} but name_val is empty, fall back to title_val
    if "{name}" in pattern and not name_val:
        name_val = title_val

    token_map = {
        "{name}": name_val or "Resume",
        "{title}": title_val,
        "{date}": formatted_date,
        "{version}": f"v{version_number}",
        "{company}": company.strip() if company else "",
        "{job_title}": job_title.strip() if job_title else "",
        "{ext}": clean_ext,
    }

    result = pattern.strip() or "{name} {date}.{ext}"

    for token, val in token_map.items():
        if token != "{ext}":
            result = result.replace(token, sanitize_filename_component(val))

    # Handle extension replacement or append
    if "{ext}" in pattern:
        result = result.replace("{ext}", clean_ext)
    else:
        # If user template didn't include {ext}, append it
        result = f"{result.rstrip('.')}.{clean_ext}"

    # Strip illegal filename characters
    result = re.sub(r'[\\/:*?"<>|]+', "_", result)
    result = re.sub(r"\s+", " ", result).strip()

    return result


def score_resume_match(
    resume_title: str,
    resume_tags: str,
    job_title: str,
    job_description: str | None = None,
) -> float:
    """Calculates a keyword/tag relevance score (0.0 to 1.0) between a resume and a job."""
    if not job_title:
        return 0.0

    target_tokens = set(re.findall(r"\b[a-zA-Z0-9+#]{2,}\b", (job_title or "").lower()))
    if job_description:
        # Sample first 2000 chars of description for key skills
        desc_tokens = set(re.findall(r"\b[a-zA-Z0-9+#]{2,}\b", job_description[:2000].lower()))
        target_tokens.update(desc_tokens)

    # Resume tokens from title and comma-separated tags
    resume_text = f"{resume_title} {resume_tags.replace(',', ' ')}"
    resume_tokens = set(re.findall(r"\b[a-zA-Z0-9+#]{2,}\b", resume_text.lower()))

    # Filter out common stop words
    stop_words = {
        "and",
        "the",
        "for",
        "with",
        "job",
        "developer",
        "engineer",
        "senior",
        "lead",
        "role",
    }
    meaningful_resume_tokens = resume_tokens - stop_words
    if not meaningful_resume_tokens:
        meaningful_resume_tokens = resume_tokens

    if not meaningful_resume_tokens:
        return 0.0

    matches = meaningful_resume_tokens.intersection(target_tokens)
    return round(len(matches) / max(len(meaningful_resume_tokens), 1), 2)
