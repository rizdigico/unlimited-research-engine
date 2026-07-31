from research.extract import extract_content, extract_metadata, extract_pdf_text, truncate


def test_extract_content_from_html():
    html = "<html><head><title>Doc Title</title></head><body><article><h1>Heading</h1><p>Some real body content here.</p></article></body></html>"
    md = extract_content(html, "markdown", "https://example.com")
    assert md.strip() != ""
    assert "Heading" in md


def test_extract_content_empty_html():
    assert extract_content("") == ""
    assert extract_content("   ") == ""


def test_extract_metadata_title():
    html = "<html><head><title>My Page</title></head><body><p>hi</p></body></html>"
    meta = extract_metadata(html)
    assert meta.get("title") == "My Page"


def test_extract_metadata_no_title():
    meta = extract_metadata("<html><body></body></html>")
    assert "title" not in meta or not meta.get("title")


def test_truncate():
    text = "x" * 1000
    assert len(truncate(text, 100)) == 100
    assert truncate(text, 0) == text
    assert truncate(text, 5000) == text


def test_extract_pdf_text_blank_page():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    import io

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    text = extract_pdf_text(buf.read())
    assert isinstance(text, str)


def test_extract_pdf_text_garbage_raises():
    import pytest

    with pytest.raises(Exception):
        extract_pdf_text(b"this is definitely not a pdf file")
