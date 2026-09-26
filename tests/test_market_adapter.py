import pandas as pd,pytest
from finrisk.market.adapter import GovernedMarketAdapter
from finrisk.market.capabilities import ProviderCapabilities

class Bad(GovernedMarketAdapter):
    @property
    def capabilities(self):return ProviderCapabilities("bad",False,False,False,False,True,True,False)
    def fetch_security_master(self):return pd.DataFrame()
    def fetch_prices(self,security_ids,start,end):return pd.DataFrame()

def test_adapter_blocks_ineligible_provider_before_ingestion():
    with pytest.raises(ValueError):Bad().validate_capabilities()
