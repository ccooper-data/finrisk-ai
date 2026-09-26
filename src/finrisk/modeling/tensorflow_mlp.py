from __future__ import annotations
import json, os, random
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss
from finrisk.modeling.baseline import FEATURES, TemporalSplit, temporal_split

def _tf():
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL","2")
    import tensorflow as tf
    return tf

def _metrics(y,p):
    return {"rows":int(len(y)),"positives":int(np.sum(y)),"prevalence":float(np.mean(y)),
            "pr_auc":float(average_precision_score(y,p)),"roc_auc":float(roc_auc_score(y,p)),
            "brier":float(brier_score_loss(y,p))}

def train_tensorflow_mlp(frame:pd.DataFrame,split:TemporalSplit=TemporalSplit(),epochs:int=50,batch_size:int=4096):
    tf=_tf();seed=42
    random.seed(seed);np.random.seed(seed);tf.keras.utils.set_random_seed(seed)
    try: tf.config.experimental.enable_op_determinism()
    except Exception: pass
    train,val,test=temporal_split(frame,split);features=[c for c in FEATURES if c in frame.columns]
    imputer=SimpleImputer(strategy="median",add_indicator=True);scaler=StandardScaler()
    xtr=scaler.fit_transform(imputer.fit_transform(train[features])).astype("float32")
    def transform(part):return scaler.transform(imputer.transform(part[features])).astype("float32")
    xval,xtest=transform(val),transform(test)
    ytr=train["distress_12m"].astype("float32").to_numpy();yval=val["distress_12m"].astype("float32").to_numpy()
    inputs=tf.keras.Input(shape=(xtr.shape[1],))
    x=tf.keras.layers.Dense(128)(inputs);x=tf.keras.layers.BatchNormalization()(x);x=tf.keras.layers.ReLU()(x)
    x=tf.keras.layers.Dropout(.25)(x);x=tf.keras.layers.Dense(64,activation="relu")(x);x=tf.keras.layers.Dropout(.15)(x)
    outputs=tf.keras.layers.Dense(1,activation="sigmoid")(x)
    model=tf.keras.Model(inputs,outputs)
    model.compile(optimizer=tf.keras.optimizers.AdamW(learning_rate=1e-3,weight_decay=1e-4),
                  loss="binary_crossentropy",metrics=[tf.keras.metrics.AUC(curve="PR",name="pr_auc")])
    pos=float(ytr.sum());neg=float(len(ytr)-pos);class_weight={0:1.0,1:neg/pos}
    callbacks=[
        tf.keras.callbacks.EarlyStopping(monitor="val_pr_auc",mode="max",patience=8,min_delta=1e-5,restore_best_weights=True),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_pr_auc",mode="max",factor=.5,patience=3,min_lr=1e-6),
    ]
    hist=model.fit(xtr,ytr,validation_data=(xval,yval),epochs=epochs,batch_size=batch_size,
                   class_weight=class_weight,callbacks=callbacks,verbose=2,shuffle=True)
    results={}
    for name,part,xdata in [("train",train,xtr),("validation",val,xval),("test",test,xtest)]:
        p=model.predict(xdata,batch_size=8192,verbose=0).reshape(-1)
        results[name]=_metrics(part["distress_12m"].astype(int).to_numpy(),p)
    history=[{"epoch":i+1,"train_loss":float(hist.history["loss"][i]),
              "validation_pr_auc":float(hist.history["val_pr_auc"][i])} for i in range(len(hist.history["loss"]))]
    config={"features":features,"train_end":split.train_end,"validation_end":split.validation_end,
            "epochs_ran":len(history),"best_validation_pr_auc":max(x["validation_pr_auc"] for x in history),
            "parameters":int(model.count_params()),"seed":seed}
    return model,results,config,history

def run_tensorflow_mlp(cohort_path:Path,out_dir:Path):
    frame=pd.read_parquet(cohort_path);model,metrics,config,history=train_tensorflow_mlp(frame)
    out_dir.mkdir(parents=True,exist_ok=True)
    evidence={"model":"tensorflow_mlp","framework":"tensorflow","metrics":metrics,"config":config,"history":history}
    (out_dir/"tensorflow_mlp_metrics.json").write_text(json.dumps(evidence,indent=2,sort_keys=True))
    model.save(out_dir/"tensorflow_mlp.keras")
    return evidence
