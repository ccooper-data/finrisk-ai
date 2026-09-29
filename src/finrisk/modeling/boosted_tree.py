from __future__ import annotations
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.impute import SimpleImputer
from finrisk.modeling.baseline import FEATURES, TemporalSplit, temporal_split
from finrisk.modeling.probability_evidence import cohort_input_evidence, probability_evidence
from finrisk.modeling import observation_identity
from finrisk.modeling.run_environment import run_environment
from finrisk.labels import load_modelling_cohort

def _metrics(y,p):
    return {"rows":int(len(y)),"positives":int(np.sum(y)),"prevalence":float(np.mean(y)),
            "pr_auc":float(average_precision_score(y,p)),"roc_auc":float(roc_auc_score(y,p)),
            "brier":float(brier_score_loss(y,p))}

def train_boosted_tree(
    frame: pd.DataFrame, split: TemporalSplit = TemporalSplit(), *,
    calibration_out_dir: Path | None = None,
):
    train,val,test=temporal_split(frame,split)
    features=[c for c in FEATURES if c in frame.columns]
    imputer=SimpleImputer(strategy="median",add_indicator=True)
    x_train=imputer.fit_transform(train[features])
    y_train=train["distress_12m"].astype(int).to_numpy()
    # Preserve ranking pressure on the rare class without altering the held-out population.
    prevalence=float(y_train.mean())
    positive_weight=(1.0-prevalence)/prevalence
    weights=np.where(y_train==1,positive_weight,1.0)
    model=HistGradientBoostingClassifier(
        learning_rate=0.05,max_iter=300,max_leaf_nodes=31,min_samples_leaf=40,
        l2_regularization=1.0,early_stopping=True,validation_fraction=0.15,
        n_iter_no_change=25,random_state=42,
    )
    model.fit(x_train,y_train,sample_weight=weights)
    results={};predictions={}
    for name,part in [("train",train),("validation",val),("test",test)]:
        p=model.predict_proba(imputer.transform(part[features]))[:,1]
        predictions[name]=p
        results[name]=_metrics(part["distress_12m"].astype(int).to_numpy(),p)
    # This path predicts in partition row order, so partition rows are the
    # aligned identifier source. The sequence models cannot do this; see
    # modeling.sequences.
    results["test"]["calibration"] = probability_evidence(
        val["distress_12m"].to_numpy(), predictions["validation"],
        test["distress_12m"].to_numpy(), predictions["test"],
        method="platt", artifact_dir=calibration_out_dir,
        validation_identifiers=observation_identity.identifiers_from_frame(val),
        test_identifiers=observation_identity.identifiers_from_frame(test),
        validation_reuse={
            "checkpoint_selection_uses_validation": False,
            "internal_early_stopping_partition": "carved from train by validation_fraction",
            "calibration_uses_validation": True,
            "independent_calibration_holdout": False,
            "optimism_quantified": False,
        },
    )
    config={"features":features,"train_end":split.train_end,"validation_end":split.validation_end,
            "positive_weight":positive_weight,"iterations":int(model.n_iter_)}
    return model,imputer,results,config

def run_boosted_tree(cohort_path:Path,out_dir:Path):
    provenance=cohort_input_evidence(cohort_path)
    frame=load_modelling_cohort(cohort_path)
    model,imputer,metrics,config=train_boosted_tree(frame,calibration_out_dir=out_dir)
    out_dir.mkdir(parents=True,exist_ok=True)
    evidence={"model":"hist_gradient_boosting","metrics":metrics,"config":config,"input":provenance,"environment":run_environment(sequence_preprocessing=False)}
    joblib.dump({"model":model,"imputer":imputer},out_dir/"boosted_tree_model.joblib")
    (out_dir/"boosted_tree_metrics.json").write_text(json.dumps(evidence,indent=2,sort_keys=True,allow_nan=False))
    return evidence
