import numpy as np, pandas as pd, json, time, sys, warnings; warnings.filterwarnings("ignore")
from sklearn.model_selection import StratifiedKFold
from sklearn.ensemble import HistGradientBoostingClassifier as HGC, HistGradientBoostingRegressor as HGR
from causalpfn import CATEEstimator
import os
MP=os.environ.get("CAUSALPFN_WEIGHTS","vdblm/causalpfn")
if os.path.isdir(MP): MP=os.path.join(MP,"causalpfn_v0.pt")
def aipw(y,t,e,m0,m1):
    e=np.clip(e,.01,.99); psi=m1-m0+t*(y-m1)/e-(1-t)*(y-m0)/(1-e); est=psi.mean(); se=psi.std(ddof=1)/np.sqrt(len(y)); return est,[est-1.96*se,est+1.96*se]
def pfn_mu(Xtr,ttr,ytr,Xq):
    c=CATEEstimator(device="cpu",model_path=MP).fit(Xtr,ttr,ytr)
    n=len(Xq); o=c._predict_cepo(c.X_train,c.t_train,c.y_train,np.concatenate([Xq,Xq]),np.concatenate([np.zeros(n),np.ones(n)]).astype(Xq.dtype),temperature=c.prediction_temperature)
    return o[:n],o[n:]
def run(X,t,y,seed=1729):
    out={}; n=len(y); skf=StratifiedKFold(5,shuffle=True,random_state=seed)
    e=np.zeros(n); g0=np.zeros(n); g1=np.zeros(n); p0=np.zeros(n); p1=np.zeros(n)
    tg=tp=0
    for tr,te in skf.split(X,t):
        s=time.time()
        e[te]=HGC(max_iter=200,learning_rate=.05,max_leaf_nodes=15,random_state=seed).fit(X[tr],t[tr]).predict_proba(X[te])[:,1]
        for arm,arr in ((0,g0),(1,g1)):
            idx=tr[t[tr]==arm]; arr[te]=HGR(max_iter=300,learning_rate=.05,max_leaf_nodes=15,random_state=seed).fit(X[idx],y[idx]).predict(X[te])
        tg+=time.time()-s; s=time.time()
        p0[te],p1[te]=pfn_mu(X[tr],t[tr].astype(float),y[tr],X[te]); tp+=time.time()-s
    out["aipw_gbm"]=(*aipw(y,t,e,g0,g1),tg)
    out["aipw_pfn"]=(*aipw(y,t,e,p0,p1),tp+tg*0.33)   # pfn outcome models + gbm propensity
    s=time.time(); c=CATEEstimator(device="cpu",model_path=MP).fit(X,t.astype(float),y)
    ci=c._estimate_ate_cate_CI(X,n_samples=1000); est=float(c.estimate_cate(X).mean())
    out["pfn_raw"]=(est,[float(np.ravel(ci["ate_lower_bound"])[0]),float(np.ravel(ci["ate_upper_bound"])[0])],time.time()-s)
    return out
keys={k["name"]:k for k in json.load(open("keys.json"))}
rows=[]
for name,k in keys.items():
    if "file" in k: df=pd.read_csv(k["file"]); X=df[k["C"]].astype(float).values; t=df[k["T"]].values.astype(int); y=df[k["Y"]].values.astype(float)
    else: df=pd.read_csv(f"data/{name}.csv"); X=df[[c for c in df if c.startswith("x")]].values; t=df.t.values; y=df.y.values
    res=run(X,t,y)
    for m,(est,ci,sec) in res.items():
        rows.append({"dataset":name,"method":m,"est":est,"lo":ci[0],"hi":ci[1],"truth":k["ate_true"],"abs_err":abs(est-k["ate_true"]),"covers":ci[0]<=k["ate_true"]<=ci[1],"width":ci[1]-ci[0],"sec":round(sec,1)})
    print(name,{m:round(v[0],3) for m,v in res.items()},"truth",round(k["ate_true"],3),flush=True)
    pd.DataFrame(rows).to_csv("results.csv",index=False)
