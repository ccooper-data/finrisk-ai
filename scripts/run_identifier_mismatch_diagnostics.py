from pathlib import Path
import pandas as pd
from finrisk.identity.identifier_mismatch_diagnostics import write_mismatch_diagnostics

report=write_mismatch_diagnostics(
    pd.read_parquet("artifacts/source/intersection/tier_a_identifier_intersection.parquet"),
    Path("artifacts/identity/identifier-mismatch-diagnostics"),
)
print(report)
