import pandas as pd
import numpy as np
import os, re, json, traceback
from datetime import datetime

def make_json_serializable(obj):
    if obj is None: return None
    if isinstance(obj, (np.ndarray, pd.Series)): return [make_json_serializable(x) for x in obj]
    if isinstance(obj, pd.DataFrame): return make_json_serializable(obj.to_dict())
    try:
        if pd.isna(obj): return None
    except Exception: pass
    if isinstance(obj, (np.integer,)): return int(obj)
    if isinstance(obj, (np.floating,)): return None if np.isnan(obj) else float(round(obj,4))
    if isinstance(obj, np.bool_): return bool(obj)
    if isinstance(obj, (datetime, pd.Timestamp)): return obj.isoformat()
    if isinstance(obj, dict): return {make_json_serializable(k):make_json_serializable(v) for k,v in obj.items()}
    if isinstance(obj, (list, tuple)): return [make_json_serializable(i) for i in obj]
    return obj

_MISS_KW = {'na','n/a','null','missing','unknown','none','nil','undefined','nan','?','-','.',''}

def _is_missing(v):
    if pd.isna(v): return True
    return str(v).strip().lower() in _MISS_KW or re.match(r'^\s+$', str(v)) is not None

def detect_missing_values(df):
    mc, md = {}, {}
    for col in df.columns:
        n, d = 0, {'empty_strings':0,'whitespace_only':0,'null_keywords':0,'placeholders':0,'special_chars':0,'pandas_na':0}
        for v in df[col]:
            if pd.isna(v): n+=1; d['pandas_na']+=1; continue
            sv=str(v).strip(); svl=sv.lower()
            if sv=='': n+=1; d['empty_strings']+=1
            elif re.match(r'^\s+$',str(v)): n+=1; d['whitespace_only']+=1
            elif svl in _MISS_KW: n+=1; d['null_keywords']+=1
            elif sv in {'?','-','.','--','???','...','***'}: n+=1; d['placeholders']+=1
            elif len(sv)==1 and sv in {'#','*','!','@'}: n+=1; d['special_chars']+=1
        mc[col]=n; md[col]=d
    return mc, md

def detect_outliers(series):
    clean=pd.to_numeric(series,errors='coerce').dropna()
    if len(clean)<4: return {'count':0,'lower':None,'upper':None,'pct':0}
    q1,q3=clean.quantile(.25),clean.quantile(.75); iqr=q3-q1
    lo,hi=q1-1.5*iqr,q3+1.5*iqr
    count=int(((clean<lo)|(clean>hi)).sum())
    return {'count':count,'lower':round(float(lo),4),'upper':round(float(hi),4),'pct':round(count/len(clean)*100,2)}

def build_plot_data(df, num_cols, cat_cols, missing_counts):
    plots={}
    plots['histograms']=[{'col':c,'values':[round(v,4) for v in pd.to_numeric(df[c],errors='coerce').dropna().tolist()],'mean':round(float(pd.to_numeric(df[c],errors='coerce').mean()),4),'median':round(float(pd.to_numeric(df[c],errors='coerce').median()),4)} for c in num_cols if len(pd.to_numeric(df[c],errors='coerce').dropna())>0]
    plots['box_data']=[{'col':c,'values':[round(v,4) for v in pd.to_numeric(df[c],errors='coerce').dropna().tolist()]} for c in num_cols if len(pd.to_numeric(df[c],errors='coerce').dropna())>0]
    plots['bar_charts']=[{'col':c,'labels':df[c].value_counts().head(10).index.tolist(),'values':df[c].value_counts().head(10).values.tolist()} for c in cat_cols[:6] if not df[c].value_counts().empty]
    if len(num_cols)>=2:
        corr=df[num_cols].apply(pd.to_numeric,errors='coerce').corr(); cl=corr.columns.tolist()
        plots['correlation']={'cols':cl,'z':[[round(corr.loc[r,c],3) if not pd.isna(corr.loc[r,c]) else None for c in cl] for r in cl]}
    else: plots['correlation']=None
    mnz={k:v for k,v in missing_counts.items() if v>0}
    plots['missing_chart']={'cols':list(mnz.keys()),'counts':list(mnz.values()),'pcts':[round(v/len(df)*100,2) for v in mnz.values()]} if mnz else None
    if 2<=len(num_cols)<=6:
        sd={}
        for c in num_cols:
            vals=pd.to_numeric(df[c],errors='coerce').tolist()
            sd[c]=[None if isinstance(v,float) and np.isnan(v) else v for v in vals]
        plots['scatter_matrix']={'cols':list(num_cols),'data':sd}
    else: plots['scatter_matrix']=None
    return plots

def analyze_csv(file_path):
    try:
        df=pd.read_csv(file_path,keep_default_na=False,na_values=[])
        mc,md=detect_missing_values(df)
        num_cols=df.select_dtypes(include=[np.number]).columns.tolist()
        cat_cols=df.select_dtypes(exclude=[np.number]).columns.tolist()
        result={
            'filename':os.path.basename(file_path),'shape':[int(df.shape[0]),int(df.shape[1])],
            'columns':list(df.columns),'dtypes':{c:str(df[c].dtype) for c in df.columns},
            'missing_values':mc,'missing_details':md,
            'missing_summary':{'total_cells':int(df.shape[0]*df.shape[1]),'total_missing':sum(mc.values()),
                'columns_with_missing':sum(1 for v in mc.values() if v>0),
                'missing_percentage':round(sum(mc.values())/(df.shape[0]*df.shape[1])*100,2) if df.shape[0]*df.shape[1]>0 else 0},
            'stats':{},'outliers':{},'data_preview':{},'plot_data':{}
        }
        for col in num_cols:
            s=pd.to_numeric(df[col],errors='coerce')
            result['stats'][col]={'count':int(s.count()),'mean':round(float(s.mean()),4) if not pd.isna(s.mean()) else None,'std':round(float(s.std()),4) if not pd.isna(s.std()) else None,'min':round(float(s.min()),4) if not pd.isna(s.min()) else None,'25%':round(float(s.quantile(.25)),4) if not pd.isna(s.quantile(.25)) else None,'50%':round(float(s.median()),4) if not pd.isna(s.median()) else None,'75%':round(float(s.quantile(.75)),4) if not pd.isna(s.quantile(.75)) else None,'max':round(float(s.max()),4) if not pd.isna(s.max()) else None,'skew':round(float(s.skew()),4) if not pd.isna(s.skew()) else None,'kurt':round(float(s.kurt()),4) if not pd.isna(s.kurt()) else None}
            result['outliers'][col]=detect_outliers(df[col])
        for col in cat_cols:
            vm=df[col].apply(lambda x: str(x).strip().lower() not in _MISS_KW and not re.match(r'^\s*$',str(x)))
            uv=df[col][vm].unique()
            result['stats'][col]={'count':int(vm.sum()),'unique_values':len(uv),'sample_values':[str(v) for v in uv[:5]],'most_common':str(df[col].mode()[0]) if not df[col].mode().empty else None}
        prev=df.head(10).copy()
        result['data_preview']={'columns':list(prev.columns),'rows':make_json_serializable(prev.values.tolist())}
        result['plot_data']=make_json_serializable(build_plot_data(df,num_cols,cat_cols,mc))
        json.dumps(result)
        return result
    except Exception as e:
        return {'error':str(e),'error_type':type(e).__name__,'traceback':traceback.format_exc()}