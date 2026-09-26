from __future__ import annotations
import pandas as pd

def provider_probe_sample(identity:pd.DataFrame,n_distressed=50,n_nondistressed=50)->pd.DataFrame:
    x=identity.copy();dist=x[x["distress_observations"]>0].copy();healthy=x[x["distress_observations"].eq(0)].copy()
    # Prioritize the exact hard cases: distressed issuers without current tickers.
    hard=dist[~dist["has_current_ticker"]].sort_values(["distress_observations","observations"],ascending=False)
    d=hard.head(n_distressed)
    h=healthy.sort_values("observations",ascending=False).head(n_nondistressed)
    out=pd.concat([d,h],ignore_index=True);out["probe_group"]=["distressed_no_current_ticker"]*len(d)+["nondistressed"]*len(h)
    return out
