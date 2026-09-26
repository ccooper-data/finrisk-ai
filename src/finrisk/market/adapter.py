from __future__ import annotations
from abc import ABC,abstractmethod
from pathlib import Path
import pandas as pd
from finrisk.market.capabilities import ProviderCapabilities,assess_provider
from finrisk.market.quality import validate_price_history
from finrisk.market.security_master import validate_security_master

class GovernedMarketAdapter(ABC):
    @property
    @abstractmethod
    def capabilities(self)->ProviderCapabilities: ...
    @abstractmethod
    def fetch_security_master(self)->pd.DataFrame: ...
    @abstractmethod
    def fetch_prices(self,security_ids:list[str],start:str,end:str)->pd.DataFrame: ...
    def validate_capabilities(self):
        result=assess_provider(self.capabilities)
        if not result["eligible_for_historical_ablation"]:
            raise ValueError(f"Provider blocked: {result['blockers']}")
        return result
    def validated_security_master(self):
        df=self.fetch_security_master();evidence=validate_security_master(df);return df,evidence
    def validated_prices(self,security_ids,start,end):
        df=self.fetch_prices(security_ids,start,end);evidence=validate_price_history(df);return df,evidence
