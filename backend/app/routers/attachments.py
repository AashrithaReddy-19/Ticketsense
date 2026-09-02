import asyncio,hashlib
from datetime import datetime,timezone
from fastapi import APIRouter,Depends,File,HTTPException,UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.core.rbac import has_permission,is_customer
from app.database import get_db
from app.dependencies import get_current_user
from app.models.ticket_attachment import TicketAttachment
from app.models.user import User
from app.services.attachment_extraction import AttachmentValidationError,extractor,validate_upload
from app.services.attachment_storage import storage
from app.services.ticket_visibility import get_visible_ticket

router=APIRouter(prefix="/api/tickets",tags=["attachments"])
async def parent(ticket_id,user,db):
    from uuid import UUID
    try:return await get_visible_ticket(db,user,UUID(str(ticket_id)))
    except ValueError:raise HTTPException(404,"Ticket not found")
def can_mutate(user:User,ticket)->bool:
    return (is_customer(user.role) and ticket.submitted_by==user.id) or has_permission(user.role,"ticket:update") or has_permission(user.role,"review:manage")
def public_meta(row:TicketAttachment,internal:bool)->dict:
    result={"id":row.id,"ticket_id":row.ticket_id,"original_filename":row.original_filename,"detected_mime_type":row.detected_mime_type,"file_extension":row.file_extension,"file_size_bytes":row.file_size_bytes,"status":row.status,"extraction_status":row.extraction_status,"created_at":row.created_at,"processed_at":row.processed_at}
    if internal:result.update({"extraction_method":row.extraction_method,"sanitized_text":row.sanitized_text,"ocr_confidence":row.ocr_confidence,"ocr_confidence_available":row.ocr_confidence_available,"page_count":row.page_count,"character_count":row.character_count,"truncated":row.truncated,"processing_duration_ms":row.processing_duration_ms,"warnings":row.warnings,"error_code":row.error_code,"error_summary":row.error_summary})
    return result
async def attachment_for(ticket_id,user,db):
    ticket=await parent(ticket_id,user,db);row=await db.scalar(select(TicketAttachment).where(TicketAttachment.ticket_id==ticket.id,TicketAttachment.tenant_id==user.tenant_id));return ticket,row

@router.post("/{ticket_id}/attachment",status_code=201)
async def upload_attachment(ticket_id:str,file:UploadFile=File(...),user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    ticket,existing=await attachment_for(ticket_id,user,db)
    if not can_mutate(user,ticket):raise HTTPException(403,"Attachment upload is not allowed")
    if existing:raise HTTPException(409,"Ticket already has an attachment; remove it before replacement")
    data=await file.read(settings.attachment_max_bytes+1)
    try:extension,detected=validate_upload(file.filename or "",file.content_type,data)
    except AttachmentValidationError as exc:raise HTTPException(422,{"code":exc.code,"message":str(exc)})
    key=storage.save(ticket.tenant_id,data,extension)
    try:
        row=TicketAttachment(ticket_id=ticket.id,tenant_id=ticket.tenant_id,original_filename=file.filename,storage_key=key,declared_mime_type=file.content_type,detected_mime_type=detected,file_extension=extension,file_size_bytes=len(data),sha256_checksum=hashlib.sha256(data).hexdigest(),status="uploaded",validation_status="valid",extraction_status="pending")
        db.add(row);await db.commit();await db.refresh(row);return public_meta(row,False)
    except Exception:
        storage.delete(key);await db.rollback();raise

@router.get("/{ticket_id}/attachment")
async def get_attachment(ticket_id:str,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    _,row=await attachment_for(ticket_id,user,db)
    if not row:raise HTTPException(404,"Attachment not found")
    return public_meta(row,has_permission(user.role,"ticket:internal_ai"))

@router.post("/{ticket_id}/attachment/process")
async def process_attachment(ticket_id:str,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    ticket,row=await attachment_for(ticket_id,user,db)
    if not row:raise HTTPException(404,"Attachment not found")
    if not (has_permission(user.role,"ticket:update") or has_permission(user.role,"review:manage")):raise HTTPException(403,"Attachment processing is not allowed")
    if row.extraction_status=="processing":raise HTTPException(409,"Attachment is already processing")
    row.status="processing";row.extraction_status="processing";await db.commit()
    try:result=await asyncio.wait_for(asyncio.to_thread(extractor.extract,storage.read(row.storage_key),row.detected_mime_type),settings.attachment_extraction_timeout_seconds)
    except TimeoutError:
        row.status="failed";row.extraction_status="failed";row.error_code="extraction_timeout";row.error_summary="Extraction timed out";await db.commit();return public_meta(row,True)
    row.extracted_text=result.raw_text;row.sanitized_text=result.sanitized_text;row.extraction_method=result.method;row.ocr_confidence=result.ocr_confidence;row.ocr_confidence_available=result.ocr_confidence is not None;row.page_count=result.page_count;row.character_count=result.character_count;row.truncated=result.truncated;row.processing_duration_ms=result.duration_ms;row.warnings=result.warnings;row.error_code=result.error_code;row.error_summary=result.error_summary;row.extraction_status=result.status;row.status="ready" if result.status in {"ready","empty"} else "failed";row.processed_at=datetime.now(timezone.utc);await db.commit();await db.refresh(row);return public_meta(row,True)

@router.get("/{ticket_id}/attachment/download")
async def download_attachment(ticket_id:str,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    _,row=await attachment_for(ticket_id,user,db)
    if not row or not storage.exists(row.storage_key):raise HTTPException(404,"Attachment not found")
    return Response(storage.read(row.storage_key),media_type=row.detected_mime_type,headers={"Content-Disposition":f'attachment; filename="attachment{row.file_extension}"',"X-Content-Type-Options":"nosniff"})

@router.delete("/{ticket_id}/attachment",status_code=204)
async def delete_attachment(ticket_id:str,user:User=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    ticket,row=await attachment_for(ticket_id,user,db)
    if not row:raise HTTPException(404,"Attachment not found")
    if not can_mutate(user,ticket) or ticket.status in {"resolved","closed"}:raise HTTPException(403,"Attachment removal is not allowed")
    await db.delete(row);await db.commit();storage.delete(row.storage_key);return Response(status_code=204)
