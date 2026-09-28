from __future__ import annotations
import json,random
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss
from finrisk.modeling.sequences import build_sequence_arrays
from finrisk.modeling.baseline import TemporalSplit
from finrisk.modeling.probability_evidence import cohort_input_evidence, probability_evidence
from finrisk.modeling import observation_identity
from finrisk.modeling.run_environment import run_environment

def _torch():
    import torch
    from torch import nn
    return torch,nn

def _metrics(y,p):
    return {"rows":int(len(y)),"positives":int(y.sum()),"prevalence":float(y.mean()),
            "pr_auc":float(average_precision_score(y,p)),"roc_auc":float(roc_auc_score(y,p)),
            "brier":float(brier_score_loss(y,p))}

def train_pytorch_gru(
    frame, epochs=40, batch_size=2048, *, calibration_out_dir: Path | None = None,
    seed: int = 42, validation_only: bool = False,
):
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    if type(validation_only) is not bool:
        raise ValueError("validation_only must be a boolean")
    for name, value in (("epochs", epochs), ("batch_size", batch_size)):
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    seed = int(seed)
    if validation_only:
        # Filter before sequence construction: held-out labels/features never reach it.
        dates = pd.to_datetime(frame["filed"], errors="raise")
        if dates.isna().any():
            raise ValueError("filing dates must be present")
        frame = frame.loc[dates <= pd.Timestamp(TemporalSplit().validation_end)].copy()
    torch,nn=_torch();random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    seq,y,masks,lengths,meta,identifiers=build_sequence_arrays(frame)
    if validation_only and np.any(masks["test"]):
        raise ValueError("validation-only sequence construction returned test rows")
    class GRUModel(nn.Module):
        def __init__(self,n_features):
            super().__init__();self.gru=nn.GRU(n_features,96,num_layers=2,batch_first=True,dropout=.2)
            self.head=nn.Sequential(nn.LayerNorm(96),nn.Linear(96,48),nn.ReLU(),nn.Dropout(.2),nn.Linear(48,1))
        def forward(self,x):
            _,h=self.gru(x);return self.head(h[-1]).squeeze(1)
    model=GRUModel(seq.shape[2]);tr=np.where(masks["train"])[0];va=np.where(masks["validation"])[0]
    pos=float(y[tr].sum());neg=float(len(tr)-pos);loss_fn=nn.BCEWithLogitsLoss(pos_weight=torch.tensor(neg/pos))
    opt=torch.optim.AdamW(model.parameters(),lr=8e-4,weight_decay=2e-4)
    ds=torch.utils.data.TensorDataset(torch.from_numpy(seq[tr]),torch.from_numpy(y[tr]))
    loader=torch.utils.data.DataLoader(ds,batch_size=batch_size,shuffle=True,generator=torch.Generator().manual_seed(seed))
    def predict(indices):
        model.eval();out=[]
        with torch.no_grad():
            for start in range(0,len(indices),8192):
                xb=torch.from_numpy(seq[indices[start:start+8192]])
                out.append(torch.sigmoid(model(xb)).numpy())
        return np.concatenate(out)
    best=-1.;state=None;stale=0;history=[]
    for epoch in range(epochs):
        model.train();total=0.
        for xb,yb in loader:
            opt.zero_grad();loss=loss_fn(model(xb),yb);loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);opt.step();total+=float(loss)*len(xb)
        vp=predict(va);score=float(average_precision_score(y[va],vp))
        history.append({"epoch":epoch+1,"train_loss":total/len(tr),"validation_pr_auc":score})
        if score>best+1e-5:best=score;state={k:v.detach().clone() for k,v in model.state_dict().items()};stale=0
        else:stale+=1
        if stale>=7:break
    model.load_state_dict(state);metrics={};predictions={}
    evaluation_masks = ({name: masks[name] for name in ("train", "validation")}
                        if validation_only else masks)
    for name,mask in evaluation_masks.items():
        idx=np.where(mask)[0];predictions[name]=predict(idx)
        metrics[name]=_metrics(y[idx].astype(int),predictions[name])
    # Identifiers come from the sequence builder, masked with the same boolean
    # masks used to select predictions -- never copied from the source frame,
    # whose row order the builder does not preserve.
    def _ids(mask):
        return {f:np.asarray(identifiers[f])[mask]
                for f in observation_identity.IDENTIFIER_FIELDS}
    if validation_only:
        if calibration_out_dir is not None:
            destination = Path(calibration_out_dir)
            destination.mkdir(parents=True, exist_ok=True)
            arrays = {"y_validation": y[masks["validation"]],
                      "p_validation": predictions["validation"]}
            arrays.update({f"validation_{field}": np.asarray(values, dtype=str)
                           for field, values in _ids(masks["validation"]).items()})
            np.savez_compressed(destination / "validation_predictions.npz", **arrays)
        config = {**meta, "parameters": sum(p.numel() for p in model.parameters()),
                  "epochs_ran": len(history), "best_validation_pr_auc": best, "seed": seed,
                  "evaluation_scope": "validation_only", "test_evaluated": False,
                  "calibration_fitted": False,
                  "validation_reused_for_checkpoint_selection": True}
        return model, metrics, config, history
    metrics["test"]["calibration"] = probability_evidence(
        y[masks["validation"]], predictions["validation"],
        y[masks["test"]], predictions["test"],
        method="platt", artifact_dir=calibration_out_dir,
        validation_identifiers=_ids(masks["validation"]),
        test_identifiers=_ids(masks["test"]),
        validation_reuse={
            "checkpoint_selection_uses_validation": True,
            "checkpoint_selection_metric": "validation average_precision",
            "calibration_uses_validation": True,
            "independent_calibration_holdout": False,
            "shared_partition": "checkpoint selection and calibration use the same validation rows",
            "optimism_quantified": False,
        },
    )
    config={**meta,"parameters":sum(p.numel() for p in model.parameters()),"epochs_ran":len(history),
            "best_validation_pr_auc":best,"seed":seed}
    return model,metrics,config,history

def run_pytorch_gru(cohort_path:Path,out_dir:Path):
    provenance=cohort_input_evidence(cohort_path)
    model,metrics,config,history=train_pytorch_gru(pd.read_parquet(cohort_path),calibration_out_dir=out_dir)
    out_dir.mkdir(parents=True,exist_ok=True)
    evidence={"model":"pytorch_gru","framework":"pytorch","metrics":metrics,"config":config,"history":history,"input":provenance,"environment":run_environment(sequence_preprocessing=True)}
    (out_dir/"pytorch_gru_metrics.json").write_text(json.dumps(evidence,indent=2,sort_keys=True,allow_nan=False))
    torch,_=_torch();torch.save(model.state_dict(),out_dir/"pytorch_gru_state.pt");return evidence
