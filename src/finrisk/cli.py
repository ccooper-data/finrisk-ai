from pathlib import Path
import json
import typer
from finrisk.ingestion.sec_edgar import SecEdgarClient
from finrisk.features.fundamentals import point_in_time_fundamentals, risk_features
app = typer.Typer()

@app.command()
def fetch(cik: str, user_agent: str, out: Path = Path("data/raw/companyfacts.json")):
    path = SecEdgarClient(user_agent).save_company_facts(cik, out)
    typer.echo(path)

@app.command()
def features(source: Path, as_of: str):
    payload = json.loads(source.read_text())
    typer.echo(json.dumps(risk_features(point_in_time_fundamentals(payload, as_of)), indent=2))

@app.command("build-sec-cohort")
def build_sec_cohort(
    user_agent: str = typer.Option(..., envvar="SEC_USER_AGENT", help="Identifiable SEC User-Agent with contact email."),
    cache_dir: Path = typer.Option(Path("data/cache/sec")),
    out_dir: Path = typer.Option(Path("artifacts/sec-cohort")),
    start_year: int = typer.Option(2009),
    end_year: int = typer.Option(2026),
    end_quarter: int = typer.Option(2, min=1, max=4),
):
    from finrisk.cohort_builder import CohortBuildConfig
    from finrisk.real_run import execute_real_sec_build
    if "@" not in user_agent:
        raise typer.BadParameter("SEC_USER_AGENT must include a contact email")
    config=CohortBuildConfig(start_year=start_year,end_year=end_year,end_quarter=end_quarter)
    manifest=execute_real_sec_build(user_agent,cache_dir,out_dir,config)
    typer.echo(json.dumps(manifest,indent=2,default=str))

@app.command("audit-sec-cache")
def audit_sec_cache(
    cache_dir: Path = typer.Option(Path("data/cache/sec")),
    start_year: int = typer.Option(2009),
    end_year: int = typer.Option(2026),
    end_quarter: int = typer.Option(2, min=1, max=4),
):
    from finrisk.cohort_builder import CohortBuildConfig
    from finrisk.real_run import quarter_inventory
    config=CohortBuildConfig(start_year=start_year,end_year=end_year,end_quarter=end_quarter)
    typer.echo(quarter_inventory(cache_dir,config).to_string(index=False))


@app.command("train-baseline")
def train_baseline(
    cohort: Path = typer.Option(..., exists=True, help="Source-hashed SEC cohort Parquet."),
    out_dir: Path = typer.Option(Path("artifacts/modeling/baseline")),
):
    """Train and evaluate the chronological logistic-regression benchmark."""
    from finrisk.modeling.baseline import run_baseline
    evidence=run_baseline(cohort,out_dir)
    typer.echo(json.dumps(evidence,indent=2))


@app.command("train-boosted-tree")
def train_boosted_tree_command(
    cohort: Path = typer.Option(..., exists=True, help="Frozen source-hashed SEC cohort Parquet."),
    out_dir: Path = typer.Option(Path("artifacts/modeling/boosted-tree")),
):
    """Train the nonlinear tree benchmark on the frozen temporal population."""
    from finrisk.modeling.boosted_tree import run_boosted_tree
    evidence=run_boosted_tree(cohort,out_dir)
    typer.echo(json.dumps(evidence,indent=2))


@app.command("train-pytorch-mlp")
def train_pytorch_mlp_command(
    cohort: Path = typer.Option(..., exists=True),
    out_dir: Path = typer.Option(Path("artifacts/modeling/pytorch-mlp")),
):
    """Train the PyTorch MLP on the frozen temporal population."""
    from finrisk.modeling.pytorch_mlp import run_pytorch_mlp
    evidence=run_pytorch_mlp(cohort,out_dir)
    typer.echo(json.dumps(evidence,indent=2))


@app.command("train-tensorflow-mlp")
def train_tensorflow_mlp_command(
    cohort: Path = typer.Option(..., exists=True),
    out_dir: Path = typer.Option(Path("artifacts/modeling/tensorflow-mlp")),
):
    """Train the TensorFlow MLP on the frozen temporal population."""
    from finrisk.modeling.tensorflow_mlp import run_tensorflow_mlp
    evidence=run_tensorflow_mlp(cohort,out_dir)
    typer.echo(json.dumps(evidence,indent=2))


@app.command("train-pytorch-gru")
def train_pytorch_gru_command(
    cohort: Path = typer.Option(..., exists=True),
    out_dir: Path = typer.Option(Path("artifacts/modeling/pytorch-gru")),
):
    from finrisk.modeling.pytorch_gru import run_pytorch_gru
    evidence=run_pytorch_gru(cohort,out_dir)
    typer.echo(json.dumps(evidence,indent=2))
