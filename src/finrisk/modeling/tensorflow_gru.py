from __future__ import annotations
import json,os,random
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss
from finrisk.modeling.sequences import build_sequence_arrays

def _tf():
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL","2")
    import tensorflow as tf
    return tf

def _metrics(y,p):
    return {"rows":int(len(y)),"positives":int(y.sum()),"prevalence":float(y.mean()),
            "pr_auc":float(average_precision_score(y,p)),"roc_auc":float(roc_auc_score(y,p)),
            "brier":float(brier_score_loss(y,p))}

def train_tensorflow_gru(frame,epochs=40,batch_size=2048):
    tf=_tf();seed=42;random.seed(seed);np.random.seed(seed);tf.keras.utils.set_random_seed(seed)
    try:tf.config.experimental.enable_op_determinism()
    except Exception:pass
    seq,y,masks,lengths,meta=build_sequence_arrays(frame)
    inp=tf.keras.Input(shape=(seq.shape[1],seq.shape[2]))
    x=tf.keras.layers.GRU(96,return_sequences=True,dropout=.2)(inp)
    x=tf.keras.layers.GRU(96,dropout=.2)(x)
    x=tf.keras.layers.LayerNormalization()(x)
    x=tf.keras.layers.Dense(48,activation="relu")(x);x=tf.keras.layers.Dropout(.2)(x)
    out=tf.keras.layers.Dense(1,activation="sigmoid")(x);model=tf.keras.Model(inp,out)
    model.compile(optimizer=tf.keras.optimizers.AdamW(learning_rate=8e-4,weight_decay=2e-4),
                  loss="binary_crossentropy",metrics=[tf.keras.metrics.AUC(curve="PR",name="pr_auc")])
    tr=np.where(masks["train"])[0];va=np.where(masks["validation"])[0]
    pos=float(y[tr].sum());neg=float(len(tr)-pos);weights={0:1.,1:neg/pos}
    callbacks=[tf.keras.callbacks.EarlyStopping(monitor="val_pr_auc",mode="max",patience=7,min_delta=1e-5,restore_best_weights=True)]
    hist=model.fit(seq[tr],y[tr],validation_data=(seq[va],y[va]),epochs=epochs,batch_size=batch_size,
                   class_weight=weights,callbacks=callbacks,shuffle=True,verbose=2)
    metrics={}
    for name,mask in masks.items():
        idx=np.where(mask)[0];p=model.predict(seq[idx],batch_size=8192,verbose=0).reshape(-1)
        metrics[name]=_metrics(y[idx].astype(int),p)
    history=[{"epoch":i+1,"train_loss":float(hist.history["loss"][i]),"validation_pr_auc":float(hist.history["val_pr_auc"][i])}
             for i in range(len(hist.history["loss"]))]
    config={**meta,"parameters":int(model.count_params()),"epochs_ran":len(history),
            "best_validation_pr_auc":max(x["validation_pr_auc"] for x in history),"seed":seed}
    return model,metrics,config,history

def run_tensorflow_gru(cohort_path:Path,out_dir:Path):
    model,metrics,config,history=train_tensorflow_gru(pd.read_parquet(cohort_path));out_dir.mkdir(parents=True,exist_ok=True)
    evidence={"model":"tensorflow_gru","framework":"tensorflow","metrics":metrics,"config":config,"history":history}
    (out_dir/"tensorflow_gru_metrics.json").write_text(json.dumps(evidence,indent=2,sort_keys=True))
    model.save(out_dir/"tensorflow_gru.keras");return evidence
