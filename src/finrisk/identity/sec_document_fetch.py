from __future__ import annotations
import hashlib,re
import httpx

MAX_DOCUMENT_BYTES=8_000_000
TAG_RE=re.compile(r"<[^>]+>")
SPACE_RE=re.compile(r"\s+")

def fetch_document(url:str,user_agent:str,accession_base_url:str,client:httpx.Client|None=None)->tuple[str,dict]:
    prefix=accession_base_url.rstrip("/")+"/"
    if not url.startswith(prefix):raise ValueError("Document URL escaped accession boundary")
    own=client is None
    client=client or httpx.Client(headers={"User-Agent":user_agent,"Accept-Encoding":"gzip, deflate"},timeout=60)
    try:
        r=client.get(url);r.raise_for_status()
        if len(r.content)>MAX_DOCUMENT_BYTES:raise ValueError(f"SEC document exceeds {MAX_DOCUMENT_BYTES} bytes")
        raw=r.content
        text=r.text
        if url.lower().endswith((".htm",".html")):
            text=SPACE_RE.sub(" ",TAG_RE.sub(" ",text)).strip()
        evidence={"url":url,"http_status":r.status_code,"bytes":len(raw),
                  "sha256":hashlib.sha256(raw).hexdigest(),"text_chars":len(text)}
        return text,evidence
    finally:
        if own:client.close()
