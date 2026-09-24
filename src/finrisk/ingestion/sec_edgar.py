from __future__ import annotations
import time
from pathlib import Path
import httpx
BASE="https://data.sec.gov/api/xbrl/companyfacts"
class SecEdgarClient:
    def __init__(self,user_agent:str,min_interval:float=0.12):
        if "@" not in user_agent:raise ValueError("Use an identifiable SEC User-Agent containing a contact email.")
        self.headers={"User-Agent":user_agent,"Accept-Encoding":"gzip, deflate"};self.min_interval=min_interval;self._last=0.0
    def company_facts(self,cik:str)->dict:
        cik10=str(cik).zfill(10);elapsed=time.monotonic()-self._last
        if elapsed<self.min_interval:time.sleep(self.min_interval-elapsed)
        with httpx.Client(timeout=30,headers=self.headers) as client:
            r=client.get(f"{BASE}/CIK{cik10}.json");self._last=time.monotonic();r.raise_for_status();return r.json()
    def save_company_facts(self,cik:str,output:Path)->Path:
        import json
        data=self.company_facts(cik);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(data,indent=2));return output
