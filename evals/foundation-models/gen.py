"""Semi-synthetic binary-treatment test sets with known ATE (unconfounded given X)."""
import numpy as np, pandas as pd, json, os
os.makedirs("data", exist_ok=True)
def make(name, n, p, seed, kind):
    r=np.random.default_rng(seed); X=r.normal(size=(n,p))
    if kind=="linear":
        lo=0.8*X[:,0]-0.5*X[:,1]; tau=np.full(n,2.0); mu0=1+X[:,0]+0.5*X[:,1]+0.3*X[:,2]
    elif kind=="nonlinear":
        lo=1.2*np.sin(2*X[:,0])+0.8*(X[:,1]>0)-0.6*X[:,2]**2+0.3; tau=1+2*(X[:,0]>0)+X[:,3]; mu0=np.exp(0.5*X[:,0])+2*np.abs(X[:,1])+X[:,2]*X[:,3]
    elif kind=="strong_confounding":
        lo=2.2*X[:,0]+1.2*X[:,1]; tau=3+1.5*X[:,0]; mu0=4*X[:,0]+2*X[:,1]+X[:,2]
    elif kind=="many_features":
        lo=X[:,:5]@np.array([.6,-.5,.4,.3,-.3]); tau=1.5+0.5*X[:,5]-0.5*(X[:,6]>0); mu0=X[:,:10]@np.linspace(1,.1,10)+np.sin(X[:,10])
    e=1/(1+np.exp(-lo)); t=r.binomial(1,e); y=mu0+tau*t+r.normal(scale=1.0,size=n)
    df=pd.DataFrame(X,columns=[f"x{i}" for i in range(p)]); df["t"]=t; df["y"]=y
    df.to_csv(f"data/{name}.csv",index=False)
    return {"name":name,"n":n,"p":p,"kind":kind,"ate_true":float(tau.mean()),"share_extreme_e":float(((e<.05)|(e>.95)).mean())}
keys=[]
for seed in range(3):
    keys+= [make(f"lin_n2000_s{seed}",2000,5,100+seed,"linear"),
            make(f"nonlin_n2000_s{seed}",2000,6,200+seed,"nonlinear"),
            make(f"strongconf_n2000_s{seed}",2000,5,300+seed,"strong_confounding"),
            make(f"wide_n3000_s{seed}",3000,30,400+seed,"many_features")]
json.dump(keys,open("keys.json","w"),indent=1); print(len(keys))
