import numpy as np
import pandas as pd
import matplotlib
from typing import Dict

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

    # Enforce column order + complete cases (robust if some conditions are missing)
    wide = wide.reindex(columns=conditions)

    # If none of the requested conditions exist, give a clear error
    if wide.shape[1] == 0:
        raise KeyError(
            f"None of the requested conditions are present in the data. "
            f"Requested={conditions}. Available={sorted(d[condition_col].unique().tolist())}"
        )

    # Drop incomplete paired rows
    wide = wide.dropna(axis=0, how="any")
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
        wide = wide.reindex(columns=configs)

        # If none of the requested configs exist, stop early with a clear error
        if wide.shape[1] == 0:
            raise KeyError(
                f"None of the requested configs are present in the data. "
                f"Requested={configs}. Available={sorted(d[config_col].unique().tolist())}"
            )

        wide = wide.dropna(axis=0, how="any")
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

# Extra plots (report-friendly)
# ----------------------------


def plot_cumulative_delay_absorption(df, config_col, configs, title_prefix=None):
    """
    Cumulative delay absorption mechanism breakdown (stacked means):
    - mean_delay_speed
    - mean_delay_mach
    - mean_delay_dogleg
    - mean_delay_holding
    """
    d = df[df[config_col].isin(configs)].copy()

    cols = ["mean_delay_speed", "mean_delay_mach", "mean_delay_dogleg", "mean_delay_holding"]
    existing = [c for c in cols if c in d.columns]
    if not existing:
        return

    for c in existing:
        d[c] = pd.to_numeric(d[c], errors="coerce")

    means = d.groupby(config_col)[existing].mean(numeric_only=True).reindex(configs)

    # stacked bar (cumulative)
    x = np.arange(len(configs))
    bottom = np.zeros(len(configs), dtype=float)

    plt.figure(figsize=(10, 5))
    for c in existing:
        vals = means[c].to_numpy(dtype=float)
        plt.bar(x, vals, bottom=bottom, label=c)
        bottom = bottom + np.nan_to_num(vals)

    plt.xticks(x, [str(c) for c in configs], rotation=35, ha="right")
    plt.ylabel("Mean absorbed delay")
    if title_prefix:
        plt.title(f"{title_prefix} — Cumulative delay absorption by mechanism")
    else:
        plt.title("Cumulative delay absorption by mechanism")
    plt.legend()
    plt.tight_layout()
    plt.show()
    plt.close()






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

    `kpi` is a display label only. Edit MEASURE_DISPLAY_NAMES below.
    """
    rows = []

    d = df[df[condition_col].isin(conditions)].copy()

    for m in measures:
        kpi_label = display_name(m)

        if m not in d.columns:
            row = {"measure": m, "kpi": kpi_label}
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
        row = {"measure": m, "kpi": kpi_label}

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

    # --- voeg bron/run-id toe (bestandsnaam zonder extensie) ---
    df_i["run_id"] = pkl.stem

    # --- configuratie-label ---
    # Prefer an existing config column from the simulation output.
    # If absent, fall back to the filename stem.
    if "config" not in df_i.columns:
        df_i["config"] = pkl.stem

    dfs.append(df_i)

# combineer alles
df = pd.concat(dfs, ignore_index=True)

# =========================
# Normalization helpers
# =========================
# Some runs use scenario names like "no_ebbr_sc1" instead of "sc1".
# Some runs should be compared as separate variants, e.g. config "BOL25_no_ebbr".

# Normalize scenario: strip known prefixes
if "scenario" in df.columns:
    df["scenario_norm"] = df["scenario"].astype(str).str.replace(r"^no_ebbr_", "", regex=True)
else:
    df["scenario_norm"] = np.nan

# Normalize config: optionally append suffix if scenario indicates a variant
df["config_norm"] = df["config"].astype(str)

mask_no_ebbr = df["scenario"].astype(str).str.startswith("no_ebbr_") if "scenario" in df.columns else False
if isinstance(mask_no_ebbr, (pd.Series, np.ndarray)):
    needs_suffix = mask_no_ebbr & (~df["config_norm"].str.contains("no_ebbr", na=False))
    df.loc[needs_suffix, "config_norm"] = df.loc[needs_suffix, "config_norm"] + "_no_ebbr"

# Convenience: keep original scenario as well
if "scenario" in df.columns and "scenario_raw" not in df.columns:
    df["scenario_raw"] = df["scenario"].astype(str)

print(f"Loaded {len(dfs)} pickles")
print("Combined shape:", df.shape)
print("Configs:", df["config"].unique())



# %% =========================
# GLOBAL: choose measures once
# ===========================

# =========================
# EASY EDIT: measures + names
# =========================
# Edit ONLY these two objects to control output order + naming

MEASURES = [
    # stability
    "total_EAT_updates",
    "amount_of_swaps",

    # accuracy
    "pct_extrawork",
    "mean_totaldelay",      # rename this in display map if you want “mean delay”
    "mean_totalspeedup",    # if you want it shown separately
    "mean_LLDA",
    "count_LLDA_nonzero",
    "mean_delay_mach",
    "mean_delay_speed",
    "count_hold_events",

    # taskload
    "total_count",
]

MEASURE_DISPLAY_NAMES: Dict[str, str] = {
    "total_EAT_updates": "EAT Revisions [-]",
    "amount_of_swaps": "Sequence Position Changes [-]",

    "pct_extrawork": "Delay energy cost [%]",
    "mean_totaldelay": "Mean total delay [s/ac]",
    "mean_totalspeedup": "Mean totalspeedup [s/ac]",
    "mean_LLDA": "Mean vectoring delay [s/ac]",
    "count_LLDA_nonzero": "Nonzero vectoring delay [ac]",
    "mean_delay_mach": "Mean mach delay [s/ac]",
    "mean_delay_speed": "Mean delay speed [s/ac]",
    "count_hold_events": "Holdings [ac]",

    "total_count": "Instruction count [-]",
}

def display_name(key: str) -> str:
    return MEASURE_DISPLAY_NAMES.get(key, key)
# Pairing / grouping columns (edit once)
# Use normalized columns so variants like no_ebbr_sc1 can be paired with sc1
SEED_COL = "scenario_norm"       # paired unit
COND_COL = "config_norm"         # condition column you compare
VIOLIN_UNIT_COL = "seed"     # show violin distributions using individual seeds (optional)

# Common knobs
USE_ZSCORES = False

# Plot toggles
MAKE_PLOTS = False          # z-score boxplots
MAKE_ABSORPTION_PLOTS = False
MAKE_VIOLIN_PLOTS = False

P_CORR = "bonferroni"


# Helper function for running experiments
def run_experiment(title, configs):
    seed_col = SEED_COL
    config_col = COND_COL
    measures = MEASURES

    _, _ = zscores_and_boxplots(df, seed_col, config_col, configs, measures, make_plots=MAKE_PLOTS)

    if MAKE_ABSORPTION_PLOTS:
        plot_cumulative_delay_absorption(df, config_col, configs, title_prefix=title)

    if MAKE_VIOLIN_PLOTS:
        # Keep the number of figures reasonable for reports
        violin_measures = [m for m in ("pct_extrawork", "mean_count", "mean_LLDA", "mean_totaldelay", "amount_of_swaps", "total_EAT_updates") if m in measures]
        plot_violin_distributions(df, VIOLIN_UNIT_COL, config_col, configs, violin_measures, title_prefix=title)

    friedman_results, _ = friedman_anova(df, seed_col, config_col, configs, measures, use_zscores=USE_ZSCORES)
    posthoc, mean_table = wilcoxon_posthoc(df, seed_col, config_col, configs, measures, use_zscores=USE_ZSCORES, alpha=0.05)

    print(f"\n===== {title} =====")
    print("Configs:", configs)
    print("\nFriedman:\n", friedman_results)
    # print("\nPost-hoc Wilcoxon:\n", posthoc)

    # Print KPI labels first (easy to read)
    if "kpi" in mean_table.columns:
        other_cols = [c for c in mean_table.columns if c not in ("measure", "kpi")]
        display_table = mean_table[["kpi"] + other_cols]
    else:
        display_table = mean_table

    print("\nMean KPI comparison (raw values):\n", display_table)




# ----------------------------
# Violin plots (KPI distributions per config)
# ----------------------------
def plot_violin_distributions(df, unit_col, config_col, configs, measures, title_prefix=None):
    """
    For each measure: violin plot of the distribution across units (e.g., seeds or scenarios),
    grouped by configuration.
    """
    d = df[df[config_col].isin(configs)].copy()
    d[unit_col] = d[unit_col].astype(str)

    for m in measures:
        if m not in d.columns:
            continue

        # numeric
        d[m] = pd.to_numeric(d[m], errors="coerce")

        # Collapse to one value per (unit, config) in case df has multiple rows per seed/scenario
        d_agg = (
            d.groupby([unit_col, config_col])[m]
             .mean()
             .reset_index()
        )

        data = []
        labels = []
        for cfg in configs:
            vals = d_agg.loc[d_agg[config_col] == cfg, m].dropna()
            data.append(vals.to_numpy())
            labels.append(str(cfg))

        # Skip empty
        if not any(len(x) for x in data):
            continue

        plt.figure(figsize=(10, 4.5))
        plt.violinplot(data, showmeans=True, showmedians=True, showextrema=True)

        plt.xticks(np.arange(1, len(labels) + 1), labels, rotation=35, ha="right")
        plt.ylabel(display_name(m))

        if title_prefix:
            plt.title(f"{title_prefix} — Violin distribution: {m}")
        else:
            plt.title(f"Violin distribution: {m}")

        plt.tight_layout()
        plt.show()
        plt.close()

# EXP 1 — effect of uncertainty (compare configs)
# =============================================

configs = ["eaman_zero_uncertainty", "eaman_no_popup", "eaman_fcfs"]
run_experiment("EXP 1 — effect of uncertainty", configs)


# EXP 2 — effect of horizon extension (compare horizons)
# =====================================================

configs = ["eaman_fcfs", "eaman_fcfs_25", "standard_aman"]
run_experiment("EXP 2 — effect of horizon extension", configs)


# EXP 3 — different schedulers (same horizon, compare)
# =====================================================

configs = ["delay20", "eaman_fcfs", "eaman_BOL"]
run_experiment("EXP 3 — different schedulers", configs)


# EXP 4 — schedulers with extra-extended horizon
# ====================================================================

configs = ["delay25", "eaman_fcfs_25", "eaman_BOL_25"]

run_experiment("EXP 4 — schedulers with extra-extended horizon", configs)


# EXP 5 — comparing current to proposed
# ====================================================================

configs = ["standard_aman", "delay20", "eaman_BOL"]

run_experiment("EXP 5 — comparing current to proposed", configs)


configs = ["standard_aman", "delay20", "eaman_BOL", "EFDBOL20"]

run_experiment("EXP 5A — comparing current to proposed", configs)



configs = ["standard_aman", "delay25", "eaman_BOL_25", "EFDBOL25"]
run_experiment("EXP 5B — comparing current to proposed long range", configs)


# Helper: only run an experiment if ALL requested configs exist in the loaded data
def run_experiment_if_available(title: str, configs: list[str]):
    available = set(pd.Series(df[COND_COL].unique()).dropna().astype(str))
    missing = [c for c in configs if c not in available]
    if missing:
        print(f"\n===== {title} (SKIPPED) =====")
        print("Requested configs:", configs)
        print("Missing configs:", missing)
        print("Available configs (first 50):", sorted(list(available))[:50])
        return
    run_experiment(title, configs)


# EXP 6 — NO-EBBR comparison set (keep EXP1–EXP5B unchanged)
# Compares baseline vs no_ebbr variants side-by-side.
configs = ["standard_aman", "eaman_BOL",'no_ebbr_BOL20','no_ebbr_BOL25', 'no_ebbr_FCFS25',"eaman_fcfs", "eaman_BOL_25"]#, "eaman_BOL_25_no_ebbr"]


run_experiment_if_available("EXP 6 — NO-EBBR impact", configs)


configs = ["standard_aman", "eaman_BOL",'no_ebbr_BOL20', 'EFDBOL20', "no_ebbr_EFDBOL20", 'EFDBOL25', "no_ebbr_EFDBOL25"]


run_experiment_if_available("EXP 7 — NO-EBBR impact", configs)

# Helper: run an experiment on a subset (e.g., only *_no_ebbr configs)
def run_experiment_subset(title, configs_include=None, configs_exclude=None):
    cfgs = pd.Series(df[COND_COL].unique()).dropna().astype(str)
    if configs_include:
        pat = "|".join([f"({p})" for p in configs_include])
        cfgs = cfgs[cfgs.str.contains(pat, regex=True, na=False)]
    if configs_exclude:
        pat = "|".join([f"({p})" for p in configs_exclude])
        cfgs = cfgs[~cfgs.str.contains(pat, regex=True, na=False)]
    configs = cfgs.tolist()
    run_experiment(title, configs)

# Example: compare only the no-EBBR variant runs (independent from the rest)
# run_experiment_subset("NO-EBBR only", configs_include=[r"no_ebbr$", r"_no_ebbr$"])