from __future__ import annotations
import httpx

def eodhd_access_preflight(token:str)->dict:
    if not token:raise ValueError("EODHD_API_TOKEN is required")
    user=httpx.get("https://eodhd.com/api/user",params={"api_token":token,"fmt":"json"},timeout=60)
    user.raise_for_status();payload=user.json()
    # One active + one delisted exchange-list call proves discovery access without per-security price calls.
    checks={}
    for name,delisted in [("active_us",0),("delisted_us",1)]:
        r=httpx.get("https://eodhd.com/api/exchange-symbol-list/US",
            params={"api_token":token,"fmt":"json","type":"common_stock","delisted":delisted},timeout=120)
        checks[name]={"status_code":r.status_code,"ok":r.is_success,
                      "rows":len(r.json()) if r.is_success and isinstance(r.json(),list) else None}
    return {"user":payload,"discovery_checks":checks,
            "ready_for_discovery":all(x["ok"] for x in checks.values())}
