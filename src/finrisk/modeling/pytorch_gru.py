from __future__ import annotations
import json,random
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss
from finrisk.modeling.sequences import build_sequence_arrays

def _torch():
    import torch
    from torch import nn
    return torch,nn

def _metrics(y,p):
    return {"rows":int(len(y)),"positives":int(y.sum()),"prevalence":float(y.mean()),
            "pr_auc":float(average_precision_score(y,p)),"roc_auc":float(roc_auc_score(y,p)),
            "brier":float(brier_score_loss(y,p))}

def train_pytorch_gru(frame,epochs=40,batch_size=2048):
    torch,nn=_torch();seed=42;random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    seq,y,masks,lengths,meta=build_sequence_arrays(frame)
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
    model.load_state_dict(state);metrics={}
    for name,mask in masks.items():
        idx=np.where(mask)[0];metrics[name]=_metrics(y[idx].astype(int),predict(idx))
    config={**meta,"parameters":sum(p.numel() for p in model.parameters()),"epochs_ran":len(history),
            "best_validation_pr_auc":best,"seed":seed}
    return model,metrics,config,history

def run_pytorch_gru(cohort_path:Path,out_dir:Path):
    model,metrics,config,history=train_pytorch_gru(pd.read_parquet(cohort_path));out_dir.mkdir(parents=True,exist_ok=True)
    evidence={"model":"pytorch_gru","framework":"pytorch","metrics":metrics,"config":config,"history":history}
    (out_dir/"pytorch_gru_metrics.json").write_text(json.dumps(evidence,indent=2,sort_keys=True))
    torch,_=_torch();torch.save(model.state_dict(),out_dir/"pytorch_gru_state.pt");return evidence
