from pathlib import Path
from uuid import UUID,uuid4
from app.config import settings

class LocalAttachmentStorage:
    def __init__(self,root:str|None=None): self.root=Path(root or settings.attachment_storage_root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
    def _path(self,key:str)->Path:
        path=(self.root/key).resolve()
        if self.root not in path.parents: raise ValueError("Invalid storage key")
        return path
    def save(self,tenant_id:UUID,data:bytes,extension:str)->str:
        key=f"{tenant_id}/{uuid4().hex}{extension}"; path=self._path(key); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data); return key
    def read(self,key:str)->bytes:return self._path(key).read_bytes()
    def exists(self,key:str)->bool:return self._path(key).is_file()
    def delete(self,key:str)->None:self._path(key).unlink(missing_ok=True)
    def metadata(self,key:str)->dict:return {"size":self._path(key).stat().st_size}

storage=LocalAttachmentStorage()
