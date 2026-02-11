import numpy as np
import pandas as pd
import matplotlib

import matplotlib.pyplot as plt
from scipy import stats

from pathlib import Path
import pickle


plt.close("all")
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 0)          # 0 = auto, gebruik volledige notebook-breedte
pd.set_option("display.max_colwidth", None)
pd.set_option("display.expand_frame_repr", False)



#inputs: df
# unit col: unit om mee te pairen, seed of scenario
# condition_col: kolom om te vergelijken, in dit geval config
# conditions: lijst met conditions uit conditions_col
# measure: KPI's
# z score: z score meten of raw values meten
def make_paired_wide(df, unit_col, condition_col, conditions, measure, zscore_within_unit=False):
    """
    Build a paired wide table for ONE measure.

    Returns: wide DataFrame
        index   = unit (e.g. seed)
        columns = condition (e.g. scenario), in the given order
        values  = mean per (unit, condition) if duplicates exist

    Steps:
      1) filter to conditions
      2) keep only units present in ALL conditions (paired)
      3) coerce measure to numeric
      4) optional: z-score within each unit across conditions
      5) pivot to wide + drop incomplete rows
    """
    # filter conditions
    d = df[df[condition_col].isin(conditions)].copy()

    # 1) Ensure unit is comparable (seeds sometimes int/str mixed)
    d[unit_col] = d[unit_col].astype(str)

    # 2) Keep only paired units (intersection)
    common_units = set.intersection(*[
        set(d.loc[d[condition_col] == c, unit_col]) for c in conditions
    ])
    d = d[d[unit_col].isin(common_units)].copy()

    # 3) Numeric measure
    d[measure] = pd.to_numeric(d[measure], errors="coerce")

    # 4) Optional z-score within unit (across conditions)
    value_col = measure
    if zscore_within_unit:
        mu = d.groupby(unit_col)[measure].transform("mean")
        sd = d.groupby(unit_col)[measure].transform(lambda x: x.std(ddof=0)).replace(0, np.nan)
        d[measure + "_z"] = (d[measure] - mu) / sd
        value_col = measure + "_z"

    # 5) Wide table seed × condition (mean if duplicates)
    wide = d.pivot_table(
        index=unit_col,
        columns=condition_col,
        values=value_col,
        aggfunc="mean",
    )

    # Enforce column order + complete cases
    wide = wide[conditions].dropna(axis=0, how="any")
    return wide


# ----------------------------
# 1) Z-scores + boxplots
# ----------------------------
def zscores_and_boxplots(df, seed_col, config_col, configs, measures, make_plots=True):
    """
    Returns:
      d_z: long df filtered to paired seeds with <measure>_z columns
      wide_tables: dict {measure: wide_z_table}
    """
    d = df[df[config_col].isin(configs)].copy()
    d[seed_col] = d[seed_col].astype(str)

    common_units = set.intersection(*[
        set(d.loc[d[config_col] == c, seed_col]) for c in configs
    ])
    d = d[d[seed_col].isin(common_units)].copy()

    # numeric + zscores within seed
    for m in measures:
        d[m] = pd.to_numeric(d[m], errors="coerce")
        mu = d.groupby(seed_col)[m].transform("mean")
        sd = d.groupby(seed_col)[m].transform(lambda x: x.std(ddof=0)).replace(0, np.nan)
        d[m + "_z"] = (d[m] - mu) / sd

    wide_tables = {}
    for m in measures:
        wide = d.pivot_table(index=seed_col, columns=config_col, values=m + "_z", aggfunc="mean")
        wide = wide[configs].dropna(axis=0, how="any")
        wide_tables[m] = wide

        if make_plots:
            groups = [wide[c].to_numpy() for c in wide.columns]
            plt.figure(figsize=(12, 4))
            plt.boxplot(groups, tick_labels=list(wide.columns), showmeans=True)
            plt.axhline(0.0, linestyle="--")
            plt.title(f"{m} (z-scores within seed)")
            plt.ylabel("z-score [-]")
            plt.xticks(rotation=35, ha="right")
            plt.tight_layout()
            plt.show()
            plt.close()

    return None, wide_tables


# ----------------------------
# 2) Friedman ANOVA
# ----------------------------
def friedman_anova(df, seed_col, config_col, configs, measures, use_zscores=True, alpha=0.05):
    rows = []
    wide_tables = {}

    for m in measures:
        wide = make_paired_wide(
            df, unit_col=seed_col, condition_col=config_col,
            conditions=configs, measure=m, zscore_within_unit=use_zscores
        )
        wide_tables[m] = wide

        arrays = [wide[c].to_numpy() for c in wide.columns]
        chi2, p = stats.friedmanchisquare(*arrays)

        n, k = wide.shape
        W = chi2 / (n * (k - 1))

        rows.append({
            "measure": m,
            "chi2": float(chi2),
            "df": int(k - 1),
            "p": float(p),
            "alpha": float(alpha),
            "significant": bool(p <= alpha),
            "n": int(n),
            "k": int(k),
            "kendall_W": float(W),
            "used_zscores": bool(use_zscores),
        })

    friedman_results = pd.DataFrame(rows)

    # Keep measures in the same order as provided (helps readability across experiments)
    friedman_results["measure"] = pd.Categorical(friedman_results["measure"], categories=list(measures), ordered=True)
    friedman_results = friedman_results.sort_values("measure").reset_index(drop=True)

    return friedman_results, wide_tables

# ----------------------------
# 3) Wilcoxon post-hoc (pairwise)
# ----------------------------
def wilcoxon_posthoc(df, seed_col, config_col, configs, measures,
                     use_zscores=True, alpha=0.05):
    pairs = [(configs[i], configs[j]) for i in range(len(configs)) for j in range(i + 1, len(configs))]
    n_pairs = len(pairs)

    rows = []
    for m in measures:
        wide = make_paired_wide(
            df, unit_col=seed_col, condition_col=config_col,
            conditions=configs, measure=m, zscore_within_unit=use_zscores
        )

        for a, b in pairs:
            x = wide[a].to_numpy()
            y = wide[b].to_numpy()
            diff = x - y

            if np.all(np.isfinite(diff)) and np.allclose(diff, 0.0):
                stat, p = 0.0, 1.0
            else:
                try:
                    stat, p = stats.wilcoxon(x, y)
                except Exception:
                    stat, p = np.nan, np.nan

            rows.append({
                "measure": m,
                "A": a,
                "B": b,
                "stat": float(stat) if stat is not None else np.nan,
                "p_raw": float(p) if p is not None else np.nan,
                "n": int(len(x)),
                "median_diff": float(np.nanmedian(diff)),
                "mean_diff": float(np.nanmean(diff)),
                "used_zscores": bool(use_zscores),
            })

    posthoc = pd.DataFrame(rows)

    # Bonferroni correction: adjust alpha, do not output p_adj
    alpha_corr = alpha / n_pairs if n_pairs > 0 else alpha
    posthoc["alpha"] = float(alpha_corr)
    posthoc["significant"] = posthoc["p_raw"] <= alpha_corr

    # ---- Attach raw mean values to the posthoc table (per measure, per condition) ----
    # This helps interpret the Wilcoxon result: mean_A, mean_B, and diff_B_minus_A.
    d = df[df[config_col].isin(configs)].copy()

    for m in measures:
        if m not in d.columns:
            continue
        d[m] = pd.to_numeric(d[m], errors="coerce")

    mean_map = (
        d.groupby([config_col])[measures]
         .mean(numeric_only=True)
         .to_dict()
    )

    def _lookup_mean(measure_name, cond_name):
        try:
            return float(mean_map.get(measure_name, {}).get(cond_name, np.nan))
        except Exception:
            return np.nan

    posthoc["mean_A"] = posthoc.apply(lambda r: _lookup_mean(r["measure"], r["A"]), axis=1)
    posthoc["mean_B"] = posthoc.apply(lambda r: _lookup_mean(r["measure"], r["B"]), axis=1)
    posthoc["diff_B_minus_A"] = posthoc["mean_B"] - posthoc["mean_A"]

    # ---- Build the clear mean KPI comparison table and attach significance from posthoc ----
    mean_table = mean_comparison_table(
        df,
        condition_col=config_col,
        conditions=configs,
        measures=measures,
    )
    mean_table["alpha_corr"] = float(alpha_corr)

    # ---- Add pairwise significance columns for ALL config pairs ----
    # Column naming: config1/config2, config2/config3, config1/config3
    for i in range(len(configs)):
        for j in range(i + 1, len(configs)):
            c1 = configs[i]
            c2 = configs[j]
            colname = f"significant_{c1}_vs_{c2}"

            sig_series = posthoc.loc[
                (posthoc["A"] == c1) & (posthoc["B"] == c2),
                ["measure", "significant"]
            ].set_index("measure")["significant"]

            mean_table[colname] = mean_table["measure"].map(sig_series).fillna(False).astype(bool)

    return posthoc.sort_values(["measure", "p_raw"]), mean_table

# Helper: mean KPI comparison table
def mean_comparison_table(df, condition_col, conditions, measures):
    """
    Clear, descriptive table (raw values):
    - mean_<condition> for each condition
    - diff_<condition>_minus_<baseline> where baseline is conditions[0]
    """
    rows = []

    d = df[df[condition_col].isin(conditions)].copy()

    for m in measures:
        if m not in d.columns:
            row = {"measure": m}
            for c in conditions:
                row[f"mean_{c}"] = np.nan
            for c in conditions[1:]:
                row[f"diff_{c}_minus_{conditions[0]}"] = np.nan
            rows.append(row)
            continue

        d_m = d[[condition_col, m]].copy()
        d_m[m] = pd.to_numeric(d_m[m], errors="coerce")

        means = (
            d_m.groupby(condition_col)[m]
               .mean()
               .reindex(conditions)
        )

        base = means.iloc[0]
        row = {"measure": m}

        for c in conditions:
            row[f"mean_{c}"] = means.loc[c]

        for c in conditions[1:]:
            row[f"diff_{c}_minus_{conditions[0]}"] = means.loc[c] - base

        rows.append(row)

    return pd.DataFrame(rows)



PICKLE_DIR = Path("/Users/jornvanbeek/Desktop/bluesky/Montecarlo")  # <-- map met pickles


def load_pickle(path: Path):
    with path.open("rb") as f:
        return pickle.load(f)

dfs = []

pickle_files = sorted(PICKLE_DIR.glob("*.pkl")) + sorted(PICKLE_DIR.glob("*.pickle"))
if not pickle_files:
    raise FileNotFoundError(f"No pickle files found in {PICKLE_DIR}")

for pkl in pickle_files:
    obj = load_pickle(pkl)

    # --- haal DataFrame uit pickle ---
    if isinstance(obj, pd.DataFrame):
        df_i = obj.copy()

    elif isinstance(obj, dict):
        for k in ("results_df", "results", "df", "data"):
            if k in obj and isinstance(obj[k], pd.DataFrame):
                df_i = obj[k].copy()
                break
        else:
            raise KeyError(f"{pkl.name}: no DataFrame key found")

    else:
        raise TypeError(f"{pkl.name}: unsupported pickle content {type(obj)}")

    # --- voeg configuratie-label toe ---
    # standaard: bestandsnaam zonder extensie
    df_i["config"] = pkl.stem

    dfs.append(df_i)

# combineer alles
df = pd.concat(dfs, ignore_index=True)

print(f"Loaded {len(dfs)} pickles")
print("Combined shape:", df.shape)
print("Configs:", df["config"].unique())



# %% =========================
# GLOBAL: choose measures once
# ===========================

# Default measure sets (edit here; experiment cells typically just pick one of these)
MEASURES = [

    "pct_extrawork",
    'mean_count',
    'pct_count_eq_0',
    "total_EAT_updates",
    "amount_of_swaps",
    "mean_LLDA",
    "count_LLDA_nonzero",
    "mean_totaldelay",
    "mean_delay_mach",

    "mean_delay_speed"
]
# Pairing / grouping columns (edit once)
SEED_COL = "scenario"       # paired unit
COND_COL = "configuration"   # condition column you compare (scenario OR config OR title etc.)

# Common knobs
USE_ZSCORES = False

MAKE_PLOTS = True
MAKE_PLOTS = False
P_CORR = "bonferroni"


# Helper function for running experiments
def run_experiment(title, configs):
    seed_col = SEED_COL
    config_col = COND_COL
    measures = MEASURES


    _, _ = zscores_and_boxplots(df, seed_col, config_col, configs, measures, make_plots=MAKE_PLOTS)
    friedman_results, _ = friedman_anova(df, seed_col, config_col, configs, measures, use_zscores=USE_ZSCORES)
    posthoc, mean_table = wilcoxon_posthoc(df, seed_col, config_col, configs, measures, use_zscores=USE_ZSCORES, alpha=0.05)

    print(f"\n===== {title} =====")
    print("Configs:", configs)
    # print("\nFriedman:\n", friedman_results)
    # print("\nPost-hoc Wilcoxon:\n", posthoc)

    print("\nMean KPI comparison (raw values):\n", mean_table)




# EXP 1 — effect of uncertainty (compare configs)
# =============================================

configs = ["FCFS20certain", "FCFS20nopopup", "FCFS20"]
run_experiment("EXP 1 — effect of uncertainty", configs)


# EXP 2 — effect of horizon extension (compare horizons)
# =====================================================

configs = ["FCFS14", "FCFS20", "FCFS25"]
run_experiment("EXP 2 — effect of horizon extension", configs)


# EXP 3 — different schedulers (same horizon, compare)
# =====================================================

configs = ["delay20","FCFS20", "BOL20"]
run_experiment("EXP 3 — different schedulers", configs)


# EXP 4 — schedulers with extra-extended horizon
# ====================================================================

configs = ["delay25", "FCFS25","BOL25"]

run_experiment("EXP 4 — schedulers with extra-extended horizon", configs)


# EXP 5 — comparing current to proposed
# ====================================================================

configs = ["FCFS14", "delay20", "BOL20"]

run_experiment("EXP 5 — comparing current to proposed", configs)


configs = ["FCFS14", "delay25", "BOL25"]

run_experiment("EXP 5B — comparing current to proposed long range", configs)

