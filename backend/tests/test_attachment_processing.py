import io
import pytest
from PIL import Image
from pypdf import PdfWriter
from app.services.attachment_extraction import AttachmentValidationError,LocalAttachmentExtractor,sanitize_extracted_text,validate_upload

def png_bytes():
    out=io.BytesIO();Image.new("RGB",(80,30),"white").save(out,"PNG");return out.getvalue()
def pdf_bytes():
    out=io.BytesIO();writer=PdfWriter();writer.add_blank_page(100,100);writer.write(out);return out.getvalue()

@pytest.mark.parametrize("name,mime,data",[("screen.png","image/png",png_bytes()),("screen.jpg","image/jpeg",(lambda o:(Image.new("RGB",(10,10)).save(o,"JPEG"),o.getvalue())[1])(io.BytesIO())),("doc.pdf","application/pdf",pdf_bytes()),("error.txt","text/plain",b"VPN failed\ncode 691"),("vpn.log","text/plain",b"AUTH ERROR 691\nretry rejected")])
def test_supported_uploads(name,mime,data):
    extension,detected=validate_upload(name,mime,data);assert extension and detected

@pytest.mark.parametrize("name,mime,data,code",[("run.exe","application/octet-stream",b"MZabc","unsupported_extension"),("fake.pdf","application/pdf",b"plain text","mime_mismatch"),("empty.txt","text/plain",b"","empty_file"),("../secret.txt","text/plain",b"safe","path_traversal"),("report.pdf.exe","application/octet-stream",b"MZ","unsupported_extension"),("binary.txt","text/plain",b"abc\x00def","mime_mismatch"),("broken.pdf","application/pdf",b"%PDF-broken","corrupt_pdf")])
def test_rejected_uploads(name,mime,data,code):
    with pytest.raises(AttachmentValidationError) as exc:validate_upload(name,mime,data)
    assert exc.value.code==code

def test_text_and_log_extraction_preserves_formatting():
    result=LocalAttachmentExtractor().extract(b"VPN ERROR 691\r\nuser rejected\r\n","text/plain")
    assert result.status=="ready" and result.method=="text" and "VPN ERROR 691\nuser rejected" in result.sanitized_text
    assert result.ocr_confidence is None

def test_image_ocr_returns_real_structured_confidence(monkeypatch):
    monkeypatch.setattr("pytesseract.image_to_data",lambda *a,**k:{"text":["VPN","failed"],"conf":["90","80"]})
    result=LocalAttachmentExtractor().extract(png_bytes(),"image/png")
    assert result.method=="ocr" and result.sanitized_text=="VPN failed" and result.ocr_confidence==pytest.approx(.85)

def test_native_pdf_metadata_and_empty_scanned_fallback(monkeypatch):
    monkeypatch.setattr(LocalAttachmentExtractor,"_ocr_image",lambda *a:("",None))
    result=LocalAttachmentExtractor().extract(pdf_bytes(),"application/pdf")
    assert result.page_count==1 and result.method=="ocr_pdf" and result.status=="empty"

def test_sanitization_and_truncation(monkeypatch):
    from app.services import attachment_extraction as module
    monkeypatch.setattr(module.settings,"attachment_max_extracted_chars",20)
    text,truncated,warnings=sanitize_extracted_text("ERROR\x00\n"+"x"*3000)
    assert "\x00" not in text and truncated and "long_lines_truncated" in warnings
