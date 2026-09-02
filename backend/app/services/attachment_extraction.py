import io,re,time
from dataclasses import dataclass,field
from typing import Protocol
from PIL import Image,ImageEnhance,ImageOps,UnidentifiedImageError
from pypdf import PdfReader
import pytesseract
import pypdfium2 as pdfium
from app.config import settings

ALLOWED={".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".pdf":"application/pdf",".txt":"text/plain",".log":"text/plain"}
DECLARED_COMPAT={"image/png":{"image/png"},"image/jpeg":{"image/jpeg","image/jpg"},"application/pdf":{"application/pdf"},"text/plain":{"text/plain","application/octet-stream","text/x-log"}}
class AttachmentValidationError(ValueError):
    def __init__(self,code:str,message:str):super().__init__(message);self.code=code

@dataclass
class AttachmentExtractionResult:
    status:str; method:str|None=None; raw_text:str=""; sanitized_text:str=""; ocr_confidence:float|None=None; page_count:int|None=None; character_count:int=0; truncated:bool=False; duration_ms:int=0; warnings:list[str]=field(default_factory=list); error_code:str|None=None; error_summary:str|None=None

class AttachmentExtractor(Protocol):
    def extract(self,data:bytes,mime_type:str)->AttachmentExtractionResult:...

def detect_mime(data:bytes)->str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):return "image/png"
    if data.startswith(b"\xff\xd8\xff"):return "image/jpeg"
    if data.startswith(b"%PDF-"):return "application/pdf"
    sample=data[:4096]
    if b"\x00" not in sample:
        try: sample.decode("utf-8"); return "text/plain"
        except UnicodeDecodeError:
            try: sample.decode("cp1252"); return "text/plain"
            except UnicodeDecodeError: pass
    return "application/octet-stream"

def validate_upload(filename:str,declared_mime:str|None,data:bytes)->tuple[str,str]:
    if not data:raise AttachmentValidationError("empty_file","Attachment is empty")
    if len(data)>settings.attachment_max_bytes:raise AttachmentValidationError("file_too_large","Attachment exceeds configured size limit")
    if not filename or len(filename)>255 or "\x00" in filename or any(ord(c)<32 for c in filename):raise AttachmentValidationError("invalid_filename","Invalid filename")
    if "/" in filename or "\\" in filename or filename in {".",".."}:raise AttachmentValidationError("path_traversal","Invalid filename")
    suffixes=[x.lower() for x in __import__("pathlib").Path(filename).suffixes]; extension=suffixes[-1] if suffixes else ""
    if extension not in ALLOWED:raise AttachmentValidationError("unsupported_extension","Unsupported attachment type")
    if len(suffixes)>1 and any(x in {".exe",".dll",".js",".html",".zip",".rar"} for x in suffixes):raise AttachmentValidationError("multiple_extension","Unsafe multiple-extension filename")
    detected=detect_mime(data)
    if detected!=ALLOWED[extension]:raise AttachmentValidationError("mime_mismatch","File content does not match its extension")
    if declared_mime and declared_mime.lower() not in DECLARED_COMPAT[detected]:raise AttachmentValidationError("mime_mismatch","Declared content type does not match file content")
    if detected.startswith("image/"):
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify(); pixels=image.width*image.height
                if pixels>settings.attachment_max_image_pixels:raise AttachmentValidationError("image_too_large","Image dimensions exceed configured limit")
        except UnidentifiedImageError:raise AttachmentValidationError("corrupt_image","Image is corrupted")
    if detected=="application/pdf":
        try:
            count=len(PdfReader(io.BytesIO(data)).pages)
            if count>settings.attachment_max_pdf_pages:raise AttachmentValidationError("too_many_pages","PDF page limit exceeded")
        except AttachmentValidationError:raise
        except Exception:raise AttachmentValidationError("corrupt_pdf","PDF is corrupted")
    return extension,detected

def sanitize_extracted_text(text:str)->tuple[str,bool,list[str]]:
    text=text.replace("\x00","").replace("\r\n","\n").replace("\r","\n")
    text="".join(c for c in text if c in "\n\t" or ord(c)>=32)
    lines=[line[:2000] for line in text.splitlines()]; warnings=[]
    if any(len(line)>2000 for line in text.splitlines()):warnings.append("long_lines_truncated")
    cleaned="\n".join(lines); cleaned=re.sub(r"(.)\1{200,}",lambda m:m.group(1)*200,cleaned)
    truncated=len(cleaned)>settings.attachment_max_extracted_chars
    return cleaned[:settings.attachment_max_extracted_chars],truncated,warnings

class LocalAttachmentExtractor:
    def extract(self,data:bytes,mime_type:str)->AttachmentExtractionResult:
        started=time.monotonic(); warnings=[]; confidence=None; pages=None
        try:
            if mime_type=="text/plain": raw=self._decode_text(data); method="text"
            elif mime_type.startswith("image/"): raw,confidence=self._ocr_image(data); method="ocr";pages=1
            else:
                reader=PdfReader(io.BytesIO(data));pages=len(reader.pages); native="\n\n".join((p.extract_text() or "") for p in reader.pages)
                if len(native.strip())>=40:raw=native;method="native_pdf"
                else:
                    document=pdfium.PdfDocument(data); texts=[];scores=[]
                    for page in document:
                        buffer=io.BytesIO(); page.render(scale=2).to_pil().save(buffer,format="PNG")
                        text,score=self._ocr_image(buffer.getvalue());texts.append(text)
                        if score is not None:scores.append(score)
                    raw="\n\n".join(texts);confidence=sum(scores)/len(scores) if scores else None;method="ocr_pdf"
            sanitized,truncated,sanitize_warnings=sanitize_extracted_text(raw);warnings+=sanitize_warnings
            return AttachmentExtractionResult(status="ready" if sanitized.strip() else "empty",method=method,raw_text=raw,sanitized_text=sanitized,ocr_confidence=confidence,page_count=pages,character_count=len(sanitized),truncated=truncated,duration_ms=round((time.monotonic()-started)*1000),warnings=warnings)
        except Exception as exc:return AttachmentExtractionResult(status="failed",duration_ms=round((time.monotonic()-started)*1000),error_code="extraction_failed",error_summary=type(exc).__name__)
    def _decode_text(self,data:bytes)->str:
        if b"\x00" in data[:4096]:raise ValueError("binary_text")
        for encoding in ("utf-8-sig","utf-16","cp1252"):
            try:return data.decode(encoding)
            except UnicodeDecodeError:continue
        raise ValueError("unsupported_encoding")
    def _ocr_image(self,data:bytes)->tuple[str,float|None]:
        image=ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("L")
        if image.width*image.height>12_000_000:image.thumbnail((4000,3000))
        image=ImageEnhance.Contrast(image).enhance(1.3)
        output=pytesseract.image_to_data(image,output_type=pytesseract.Output.DICT)
        words=[];scores=[]
        for text,score in zip(output["text"],output["conf"]):
            if text.strip():words.append(text.strip());
            try:
                value=float(score)
                if value>=0:scores.append(value)
            except (TypeError,ValueError):pass
        return " ".join(words),(sum(scores)/len(scores)/100 if scores else None)

extractor=LocalAttachmentExtractor()
