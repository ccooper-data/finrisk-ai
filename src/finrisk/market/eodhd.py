from __future__ import annotations
import os
from datetime import datetime,timezone
import httpx,pandas as pd
from finrisk.market.adapter import GovernedMarketAdapter
from finrisk.market.capabilities import ProviderCapabilities

class EODHDProbeAdapter(GovernedMarketAdapter):
    base="https://eodhd.com/api"
    def __init__(self,token:str|None=None):
        self.token=token or os.environ.get("EODHD_API_TOKEN","")
        if not self.token:raise ValueError("EODHD_API_TOKEN is required")
    @property
    def capabilities(self):
        # Documentary claims must still be verified by the empirical probe.
        return ProviderCapabilities("EODHD",True,False,False,True,True,True,False)
    def _get(self,path,params=None):
        q={"api_token":self.token,"fmt":"json",**(params or {})}
        r=httpx.get(f"{self.base}/{path}",params=q,timeout=120);r.raise_for_status();return r.json()
    def fetch_security_master(self)->pd.DataFrame:
        rows=[]
        for delisted in [0,1]:
            data=self._get("exchange-symbol-list/US",{"delisted":delisted,"type":"common_stock"})
            for x in data:
                code=str(x.get("Code",""));isin=x.get("Isin")
                rows.append({"security_id":f"{code}.US","issuer_id":isin or code,"security_name":x.get("Name"),
                  "valid_from":None,"valid_to":None,"source":"EODHD",
                  "source_identifier":f"{code}.US","ticker":code,"isin":isin,"is_delisted":bool(delisted)})
        return pd.DataFrame(rows)
    def fetch_prices(self,security_ids:list[str],start:str,end:str)->pd.DataFrame:
        rows=[];retrieved=datetime.now(timezone.utc).isoformat()
        for sid in security_ids:
            for x in self._get(f"eod/{sid}",{"from":start,"to":end,"period":"d"}):
                rows.append({"security_id":sid,"date":x["date"],"close":x.get("adjusted_close",x.get("close")),
                             "volume":x.get("volume",0),"source":"EODHD","retrieved_at":retrieved})
        return pd.DataFrame(rows)
