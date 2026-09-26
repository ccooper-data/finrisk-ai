from __future__ import annotations
import json, random
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss
from finrisk.modeling.baseline import FEATURES, TemporalSplit, temporal_split

def _torch():
    import torch
    from torch import nn
    return torch,nn

def _metrics(y,p):
    return {"rows":int(len(y)),"positives":int(np.sum(y)),"prevalence":float(np.mean(y)),
            "pr_auc":float(average_precision_score(y,p)),"roc_auc":float(roc_auc_score(y,p)),
            "brier":float(brier_score_loss(y,p))}

def train_pytorch_mlp(frame:pd.DataFrame,split:TemporalSplit=TemporalSplit(),epochs:int=50,batch_size:int=4096):
    torch,nn=_torch(); seed=42
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    train,val,test=temporal_split(frame,split);features=[c for c in FEATURES if c in frame.columns]
    imputer=SimpleImputer(strategy="median",add_indicator=True)
    scaler=StandardScaler()
    xtr=scaler.fit_transform(imputer.fit_transform(train[features])).astype("float32")
    def transform(part):return scaler.transform(imputer.transform(part[features])).astype("float32")
    xval,xtest=transform(val),transform(test)
    ytr=train["distress_12m"].astype("float32").to_numpy();yval=val["distress_12m"].astype("float32").to_numpy()
    model=nn.Sequential(nn.Linear(xtr.shape[1],128),nn.BatchNorm1d(128),nn.ReLU(),nn.Dropout(.25),
                        nn.Linear(128,64),nn.ReLU(),nn.Dropout(.15),nn.Linear(64,1))
    pos=float(ytr.sum());neg=float(len(ytr)-pos);loss_fn=nn.BCEWithLogitsLoss(pos_weight=torch.tensor([neg/pos]))
    opt=torch.optim.AdamW(model.parameters(),lr=1e-3,weight_decay=1e-4)
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(opt,mode="max",factor=.5,patience=3)
    ds=torch.utils.data.TensorDataset(torch.from_numpy(xtr),torch.from_numpy(ytr))
    loader=torch.utils.data.DataLoader(ds,batch_size=batch_size,shuffle=True,generator=torch.Generator().manual_seed(seed))
    def predict(x):
        model.eval()
        with torch.no_grad():return torch.sigmoid(model(torch.from_numpy(x)).squeeze(1)).cpu().numpy()
    best=-1.;best_state=None;stale=0;history=[]
    for epoch in range(epochs):
        model.train();running=0.
        for xb,yb in loader:
            opt.zero_grad();logits=model(xb).squeeze(1);loss=loss_fn(logits,yb);loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),5.0);opt.step();running+=float(loss)*len(xb)
        vp=predict(xval);score=float(average_precision_score(yval,vp));scheduler.step(score)
        history.append({"epoch":epoch+1,"train_loss":running/len(ytr),"validation_pr_auc":score})
        if score>best+1e-5:
            best=score;best_state={k:v.detach().clone() for k,v in model.state_dict().items()};stale=0
        else: stale+=1
        if stale>=8:break
    model.load_state_dict(best_state)
    results={}
    for name,part,x in [("train",train,xtr),("validation",val,xval),("test",test,xtest)]:
        results[name]=_metrics(part["distress_12m"].astype(int).to_numpy(),predict(x))
    params=sum(p.numel() for p in model.parameters())
    config={"features":features,"train_end":split.train_end,"validation_end":split.validation_end,
            "epochs_ran":len(history),"best_validation_pr_auc":best,"parameters":int(params),"seed":seed}
    return model,results,config,history

def run_pytorch_mlp(cohort_path:Path,out_dir:Path):
    frame=pd.read_parquet(cohort_path);model,metrics,config,history=train_pytorch_mlp(frame)
    out_dir.mkdir(parents=True,exist_ok=True)
    evidence={"model":"pytorch_mlp","framework":"pytorch","metrics":metrics,"config":config,"history":history}
    (out_dir/"pytorch_mlp_metrics.json").write_text(json.dumps(evidence,indent=2,sort_keys=True))
    torch,_=_torch();torch.save(model.state_dict(),out_dir/"pytorch_mlp_state.pt")
    return evidence
