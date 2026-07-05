import io
import re
import numpy as np
import pandas as pd

try:
    from sklearn.experimental import enable_iterative_imputer
    from sklearn.impute import KNNImputer, IterativeImputer
    from sklearn.preprocessing import LabelEncoder
    SKLEARN_AVAILABLE = True
except ImportError as _e:
    SKLEARN_AVAILABLE = False
    KNNImputer = None
    IterativeImputer = None
    LabelEncoder = None

_MISSING_KW = {
    'na', 'n/a', 'null', 'missing', 'unknown', 'none',
    'nil', 'undefined', 'nan', '?', '-', '.', ''
}

def _mask_missing(series: pd.Series) -> pd.Series:
    # replace all missing-like values with np.nan
    def _is_miss(v):
        if pd.isna(v):
            return True
        sv = str(v).strip().lower()
        return sv in _MISSING_KW or re.match(r'^\s*$', sv)
    return series.apply(lambda v: np.nan if _is_miss(v) else v)


def _skewness(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors='coerce').dropna()
    if len(clean) < 3:
        return 0.0
    return float(clean.skew())


# recommendation engine

def recommend_strategies(df_raw: pd.DataFrame, missing_counts: dict) -> dict:
    # returns {col_name: {'strategy': str, 'reason': str, 'pct': float}}
    # for every column that has at least one missing value
    df = df_raw.copy()
    total_rows = len(df)
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

    # count total missing cols for KNN/MICE heuristic
    cols_with_missing = [c for c, v in missing_counts.items() if v > 0]
    multi_missing = len(cols_with_missing) >= 3 and SKLEARN_AVAILABLE

    recommendations = {}
    for col in cols_with_missing:
        n_miss = missing_counts[col]
        pct = round(n_miss / total_rows * 100, 2) if total_rows else 0

        is_numeric = col in numeric_cols
        skew = _skewness(df[col]) if is_numeric else 0.0

        if pct > 60:
            strategy = 'constant'
            reason = f'{pct}% missing - high risk; filling with placeholder. Consider dropping.'
        elif pct > 30:
            if multi_missing and SKLEARN_AVAILABLE:
                strategy = 'knn'
                reason = f'{pct}% missing across multiple columns - KNN leverages correlations.'
            else:
                strategy = 'median' if is_numeric else 'mode'
                reason = f'{pct}% missing - using robust central tendency.'
        elif pct > 5:
            if multi_missing and SKLEARN_AVAILABLE:
                strategy = 'iterative'
                reason = f'{pct}% missing, correlated dataset - MICE iterative imputation.'
            elif is_numeric and abs(skew) > 1:
                strategy = 'median'
                reason = f'Skew={skew:.2f} -> median avoids outlier distortion.'
            elif is_numeric:
                strategy = 'mean'
                reason = f'Low skew ({skew:.2f}) - mean is appropriate.'
            else:
                strategy = 'mode'
                reason = 'Categorical - most frequent value.'
        else:
            strategy = 'mean' if is_numeric else 'mode'
            reason = f'Only {pct}% missing - simple imputation is safe.'

        recommendations[col] = {
            'strategy': strategy,
            'reason': reason,
            'pct': pct,
            'is_numeric': is_numeric,
        }

    return recommendations


# available strategies per type

NUMERIC_STRATEGIES = [
    ('mean', 'Mean'),
    ('median', 'Median'),
    ('mode', 'Mode (most frequent)'),
    ('knn', 'KNN Imputer'),
    ('iterative', 'Iterative / MICE'),
    ('constant', 'Constant (0 or custom)'),
    ('drop_rows', 'Drop rows'),
]

CATEGORICAL_STRATEGIES = [
    ('mode', 'Mode (most frequent)'),
    ('constant', 'Constant ("Unknown")'),
    ('knn', 'KNN Imputer (encoded)'),
    ('drop_rows', 'Drop rows'),
]


# core imputation

def apply_imputation(df_raw: pd.DataFrame, strategies: dict, constant_vals: dict = None) -> pd.DataFrame:
    # strategies : {col_name: strategy_string}
    # constant_vals : {col_name: value_to_use}  (optional, for 'constant' strategy)
    # returns a new imputed DataFrame
    df = df_raw.copy()
    constant_vals = constant_vals or {}

    # normalize all missing-like values to np.nan first
    for col in df.columns:
        df[col] = _mask_missing(df[col])

    # convert numeric cols properly
    numeric_cols = [c for c in df.columns if c in strategies and
                    pd.to_numeric(df[c], errors='coerce').notna().sum() / max(len(df), 1) > 0.5]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # separate knn / iterative cols (need joint processing)
    knn_cols = [c for c, s in strategies.items() if s == 'knn' and c in df.columns]
    iterative_cols = [c for c, s in strategies.items() if s == 'iterative' and c in df.columns]
    drop_cols = [c for c, s in strategies.items() if s == 'drop_rows' and c in df.columns]
    simple_cols = [c for c, s in strategies.items()
                      if s not in ('knn', 'iterative', 'drop_rows') and c in df.columns]

    # simple per-column strategies
    for col in simple_cols:
        strat = strategies[col]
        if df[col].isna().sum() == 0:
            continue
        try:
            if strat == 'mean':
                val = pd.to_numeric(df[col], errors='coerce').mean()
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(round(val, 4))
            elif strat == 'median':
                val = pd.to_numeric(df[col], errors='coerce').median()
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(round(val, 4))
            elif strat == 'mode':
                mode_val = df[col].mode()
                if not mode_val.empty:
                    df[col] = df[col].fillna(mode_val[0])
            elif strat == 'constant':
                fill = constant_vals.get(col, 0 if col in numeric_cols else 'Unknown')
                df[col] = df[col].fillna(fill)
        except Exception as e:
            print(f"[imputation] {col} / {strat} failed: {e}")

    # drop rows
    if drop_cols:
        df.dropna(subset=drop_cols, inplace=True)

    # knn (joint)
    if knn_cols and SKLEARN_AVAILABLE:
        try:
            df = _knn_impute(df, knn_cols)
        except Exception as e:
            print(f"[imputation] KNN failed: {e} - falling back to median/mode")
            for col in knn_cols:
                _fallback(df, col, numeric_cols)

    # iterative - mice
    if iterative_cols and SKLEARN_AVAILABLE:
        try:
            df = _iterative_impute(df, iterative_cols)
        except Exception as e:
            print(f"[imputation] Iterative failed: {e} - falling back to median/mode")
            for col in iterative_cols:
                _fallback(df, col, numeric_cols)
    return df


def _fallback(df, col, numeric_cols):
    if col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(
            pd.to_numeric(df[col], errors='coerce').median()
        )
    else:
        m = df[col].mode()
        df[col] = df[col].fillna(m[0] if not m.empty else 'Unknown')


def _encode_all_categoricals(work: pd.DataFrame, target_cols: list):
    encoders = {}
    for col in work.columns:
        if work[col].dtype == object or work[col].dtype.name == 'category':
            non_null = work[col].dropna().astype(str)
            if non_null.empty:
                continue
            le = LabelEncoder()
            le.fit(non_null)

            work[col] = work[col].apply(
                lambda x: le.transform([str(x)])[0] if pd.notna(x) else np.nan
            )

            work[col] = pd.to_numeric(work[col], errors='coerce')

            if col in target_cols:
                encoders[col] = le
    return work, encoders


def _knn_impute(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    # knn imputation on selected columns using ALL columns as features
    work = df.copy()
    work, encoders = _encode_all_categoricals(work, cols)

    feature_cols = work.select_dtypes(include=[np.number]).columns.tolist()
    feature_cols = [c for c in feature_cols if work[c].notna().any()]
    if not feature_cols:
        raise ValueError("No usable features for KNN")

    imputer = KNNImputer(n_neighbors=5)
    imputed_matrix = imputer.fit_transform(work[feature_cols])
    imputed_df = pd.DataFrame(imputed_matrix, columns=feature_cols, index=work.index)

    for col in cols:
        if col not in feature_cols:
            continue
        if col in encoders:
            # decode back to string labels
            le = encoders[col]
            idx_vals = imputed_df[col].round().astype(int).clip(0, len(le.classes_) - 1)
            df[col] = le.inverse_transform(idx_vals)
        else:
            df[col] = imputed_df[col].values
    return df


def _iterative_impute(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    work = df.copy()
    work, encoders = _encode_all_categoricals(work, cols)

    feature_cols = work.select_dtypes(include=[np.number]).columns.tolist()
    feature_cols = [c for c in feature_cols if work[c].notna().any()]
    if not feature_cols:
        raise ValueError("No usable features for Iterative imputer")

    imputer = IterativeImputer(max_iter=10, random_state=42)
    imputed_matrix = imputer.fit_transform(work[feature_cols])
    imputed_df = pd.DataFrame(imputed_matrix, columns=feature_cols, index=work.index)

    for col in cols:
        if col not in feature_cols:
            continue
        if col in encoders:
            le = encoders[col]
            idx_vals = imputed_df[col].round().astype(int).clip(0, len(le.classes_) - 1)
            df[col] = le.inverse_transform(idx_vals)
        else:
            df[col] = imputed_df[col].values
    return df


# generate imputed csv bytes

def get_imputed_csv(df_raw: pd.DataFrame, strategies: dict, constant_vals: dict = None) -> bytes:
    # returns the imputed DataFrame as CSV bytes ready for HttpResponse
    imputed = apply_imputation(df_raw, strategies, constant_vals)
    buf = io.StringIO()
    imputed.to_csv(buf, index=False)
    return buf.getvalue().encode('utf-8')