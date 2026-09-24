from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import io
import zipfile
import httpx
import pandas as pd

SEC_ARCHIVES = "https://www.sec.gov/files/dera/data/financial-statement-data-sets"

@dataclass(frozen=True)
class Quarter:
    year: int
    quarter: int
    def __post_init__(self):
        if self.year < 2009 or self.quarter not in {1,2,3,4}:
            raise ValueError("SEC FSDS supports year >= 2009 and quarter 1-4")
    @property
    def slug(self): return f"{self.year}q{self.quarter}"
    @property
    def url(self): return f"{SEC_ARCHIVES}/{self.slug}.zip"

class SecFinancialStatementDatasetClient:
    def __init__(self,user_agent: str):
        if "@" not in user_agent:
            raise ValueError("Use an identifiable SEC User-Agent containing a contact email.")
        self.headers={"User-Agent":user_agent,"Accept-Encoding":"gzip, deflate"}
    def download(self,quarter: Quarter,cache_dir: Path)->Path:
        cache_dir.mkdir(parents=True,exist_ok=True)
        destination=cache_dir/f"{quarter.slug}.zip"
        if destination.exists() and destination.stat().st_size>0:return destination
        with httpx.stream("GET",quarter.url,headers=self.headers,timeout=120) as response:
            response.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in response.iter_bytes():handle.write(chunk)
        return destination

def read_table(archive: Path,table: str,usecols: list[str]|None=None)->pd.DataFrame:
    member=f"{table.lower()}.txt"
    with zipfile.ZipFile(archive) as zf:
        with zf.open(member) as raw:
            return pd.read_csv(raw,sep="\t",low_memory=False,usecols=usecols)

def read_table_bytes(data: bytes,table: str)->pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        with zf.open(f"{table.lower()}.txt") as raw:
            return pd.read_csv(raw,sep="\t",low_memory=False)
