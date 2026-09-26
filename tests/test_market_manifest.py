from pathlib import Path
from finrisk.market.manifest import hash_file,market_ingestion_manifest

def test_market_manifest_hashes_exact_files(tmp_path:Path):
    s=tmp_path/"s.csv";p=tmp_path/"p.csv";s.write_text("security");p.write_text("prices")
    m=market_ingestion_manifest("x","2026-01-01",s,p)
    assert m["files"]["security_master"]["bytes"]==8
    assert len(m["files"]["prices"]["sha256"])==64
