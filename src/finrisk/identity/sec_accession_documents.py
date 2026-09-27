from __future__ import annotations
import re
from pathlib import PurePosixPath

TEXT_EXT={".htm",".html",".txt"}
EXHIBIT_NAME_RE=re.compile(r"(?:^|[-_])ex(?:hibit)?[-_]?(2|4)(?:[._-]|$)",re.I)

def select_accession_documents(documents:list[dict],primary_document:str|None=None,max_documents:int=8)->list[dict]:
    chosen=[];seen=set()
    def add(d,reason):
        if d["name"] in seen:return
        x=dict(d);x["selection_reason"]=reason;chosen.append(x);seen.add(d["name"])
    if primary_document:
        for d in documents:
            if d["name"]==primary_document:add(d,"primary_filing")
    for d in documents:
        name=d["name"];suffix=PurePosixPath(name).suffix.lower()
        if suffix not in TEXT_EXT:continue
        if EXHIBIT_NAME_RE.search(name):add(d,"priority_exhibit_filename")
        if len(chosen)>=max_documents:break
    return chosen[:max_documents]

def validate_selected_urls(selected:list[dict],base_url:str)->None:
    prefix=base_url.rstrip("/")+"/"
    for d in selected:
        if not str(d["url"]).startswith(prefix):raise ValueError("Document escaped accession boundary")
