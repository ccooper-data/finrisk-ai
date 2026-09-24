# Running the real SEC cohort

1. Create a repository secret named `SEC_USER_AGENT`. Its value must identify the project/operator and include a real contact email.
2. Open **Actions → Build real SEC cohort → Run workflow**.
3. Run `smoke` first. It builds 2025 Q1-Q4 through the complete parsing and labeling path.
4. Inspect `run_manifest.json`, `quarter_inventory.csv`, the cohort Parquet, and distress-event Parquet.
5. If the smoke run is valid, run `full`, targeting 2009 through 2026 Q2.
6. Preserve the GitHub run ID with any reported result; source ZIP SHA-256 hashes are recorded in the evidence.

Do not publish model metrics from a failed or partial evidence package.
