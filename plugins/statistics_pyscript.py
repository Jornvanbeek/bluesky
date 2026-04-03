import numpy as np
import pandas as pd
import matplotlib
from typing import Dict
from pathlib import Path
import re
import math
import matplotlib.pyplot as plt
from scipy import stats

from pathlib import Path
import pickle
from pathlib import Path  # als die er nog niet staat

ZPLOT_DIR = Path("zscore_plots")
ZPLOT_DPI = 300

ABS_PLOT_DIR = Path("absorption_plots")
ABS_PLOT_DPI = 300

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
def zscores_and_boxplots(df, seed_col, config_col, configs, measures, make_plots=True, plot_prefix=None):
    """
    Returns:
      d_z: (unused) long df filtered to paired seeds with <measure>_z columns
      wide_tables: dict {measure: wide_z_table}

    Notes:
      - Boxplots are shown with display names for configs and KPIs.
      - Each figure includes Friedman ANOVA summary for that KPI:
        chi2, p, significant, Kendall's W, and n.
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
            # Data per config
            groups = [wide[c].to_numpy() for c in wide.columns]

            # Friedman stats on the shown data
            try:
                chi2, p = stats.friedmanchisquare(*groups)
            except Exception:
                chi2, p = np.nan, np.nan

            n, k = wide.shape
            W = (chi2 / (n * (k - 1))) if (np.isfinite(chi2) and n > 0 and k > 1) else np.nan
            significant = bool(np.isfinite(p) and (p <= 0.05))
            ZPLOT_DIR.mkdir(parents=True, exist_ok=True)

            plt.figure(figsize=(6.5, 3.6))  # smaller figure
            ax = plt.gca()

            plt.boxplot(
                groups,
                tick_labels=[display_config_name(c) for c in wide.columns],
                showmeans=True
            )

            plt.margins(x=0.02)  # reduce horizontal whitespace
            plt.axhline(0.0, linestyle="--")

            # plt.title(display_name(m))  # only KPI as title
            plt.ylabel("z-score [-]")
            plt.ylim(-2, 2)


            plt.xticks(rotation=30)

            # Friedman annotation text (placed OUTSIDE the plot area, in the top margin)
            ann = (
                "ANOVA: \n"
                + r"$\chi^2$" + f"={chi2:.3f}  "
                + f"p={p:.3g}  "
                + f"Sig.={significant}  "
                + f"W={W:.3f}  "
                + f"n={n}"
            )

            # Leave extra room at the top for the annotation
            plt.tight_layout(pad=0.5, rect=[-0.1, 0.0, 1.0, 0.86])

            # Put the annotation in the reserved top margin (figure coordinates)
            fig = plt.gcf()
            fig.text(
                0.02, 0.98, ann,
                ha="left", va="top",
                fontsize=10,
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.90, linewidth=0.5),
            )

            # Save AFTER adding the annotation so it is included in the PNG
            safe_kpi = re.sub(r"[^A-Za-z0-9_-]+", "_", display_name(m)).strip("_")
            safe_cfgs = re.sub(
                r"[^A-Za-z0-9_-]+", "_",
                "_".join([display_config_name(c) for c in wide.columns])
            ).strip("_")

            if plot_prefix:
                safe_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", str(plot_prefix)).strip("_")
                out_path = ZPLOT_DIR / f"{safe_prefix}__zscore_{safe_kpi}.png"
            else:
                out_path = ZPLOT_DIR / f"zscore_{safe_kpi}__{safe_cfgs}.png"

            plt.savefig(out_path, dpi=ZPLOT_DPI, bbox_inches="tight")
            plt.show()
            plt.close()

    return None, wide_tables

# ----------------------------

# Extra plots (report-friendly)
# ----------------------------
def save_clustered_zscore_boxplots(
    wide_tables: dict,          # {measure: wide_df(index=unit, columns=config) met z-scores}
    measures: list[str],
    configs: list[str],
    title: str,
    out_path: Path,
    xlim=(-2, 2),
    dpi: int = 300,
):
    """
    One compact figure:
      - x-axis = KPIs
      - y-axis = z-score
      - per KPI: one boxplot per config with small horizontal offsets
    """
    # Filter to measures that exist
    used_measures = [m for m in measures if m in wide_tables]
    if not used_measures:
        return None

    # Layout
    n_kpi = len(used_measures)
    n_cfg = len(configs)

    # Figure height scales mildly with #KPIs (tune as needed)
    fig_h = max(2.5, 0.55 * n_kpi + 1.2)
    plt.figure(figsize=(7.2, fig_h))
    ax = plt.gca()

    # Color palette per config
    cmap = plt.get_cmap("tab10")
    cfg_colors = {cfg: cmap(i % 10) for i, cfg in enumerate(configs)}

    # Base x positions for KPIs (left to right)
    # Increase spacing as number of configs grows to prevent overlap.
    step = 1.1 + 0.1 * max(0, n_cfg - 3)
    base_x = np.arange(n_kpi) * step

    # Offsets per config within each KPI column (centered around base_x)
    # Keep the full offset range bounded so it does not collide with the next KPI column.
    if n_cfg > 1:
        offset_span = min(0.28 + 0.06 * (n_cfg - 3), 0.55)  # cap span
        offsets = np.linspace(-offset_span, offset_span, n_cfg)
    else:
        offsets = np.array([0.0])

    # Narrower boxes when many configs (prevents overlap within the KPI column)
    box_w = 0.28 if n_cfg <= 3 else (0.22 if n_cfg == 4 else 0.18)

    # Draw
    for j, cfg in enumerate(configs):
        data = []
        positions = []
        for i, m in enumerate(used_measures):
            wide = wide_tables[m].reindex(columns=configs)
            if cfg not in wide.columns:
                continue
            vals = wide[cfg].dropna().to_numpy()
            data.append(vals)
            positions.append(base_x[i] + offsets[j])

        if data:
            bp = ax.boxplot(
                data,
                positions=positions,
                vert=True,
                widths=box_w,
                showmeans=False,
                manage_ticks=False,
                patch_artist=True,
                flierprops=dict(marker="o", markersize=3, markeredgewidth=0.5),
            )

            # Apply color to this config's boxes
            color = cfg_colors.get(cfg, "gray")
            for patch in bp["boxes"]:
                patch.set_facecolor(color)
                patch.set_alpha(0.5)
            for median in bp["medians"]:
                median.set_color(color)
            for whisker in bp["whiskers"]:
                whisker.set_color(color)
            for cap in bp["caps"]:
                cap.set_color(color)
            for flier in bp["fliers"]:
                flier.set_markerfacecolor(color)
                flier.set_markeredgecolor(color)

    # X tick labels at KPI centers
    ax.set_xticks(base_x)
    ax.set_xticklabels([display_name(m) for m in used_measures], rotation=25, ha="right")

    ax.axhline(0.0, linestyle="--", linewidth=0.8)
    ax.set_ylabel("z-score [-]")
    ax.set_ylim(*xlim)

    # “Legenda” als tekst bovenaan (zonder kleur-coding)
    # Zet gewoon de volgorde erbij, matcht offsets links->rechts
    # cfg_label = " | ".join([display_config_name(c) for c in configs])
    # ax.set_title(f"{title}\n{cfg_label}", fontsize=10)

    # -------------------------
    # Configuration legend (outside left)
    # -------------------------
    from matplotlib.patches import Patch

    config_handles = [
        Patch(
            facecolor=cfg_colors[c],
            edgecolor=cfg_colors[c],
            alpha=0.5,
            label=display_config_name(c),
        )
        for c in configs
    ]

    ax.legend(
        handles=config_handles,
        title="Configuration",
        loc="lower right",
        # bbox_to_anchor=(0.835, 0.225),  # slightly outside plot area
        fontsize=8,
        title_fontsize=9,
        borderaxespad=0.0,
    )

    plt.tight_layout(pad=0.4)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close()
    return out_path
def save_boxplot_grid(
    wide_tables: dict,           # {measure: wide_df} zoals in zscores_and_boxplots
    measures: list[str],         # volgorde
    title: str,                  # bestandsnaam prefix
    out_dir: Path,
    ncols: int = 2,              # 2 naast elkaar in paper werkt vaak goed
    ylim=(-2, 2),
    dpi: int = 300
):
    out_dir.mkdir(parents=True, exist_ok=True)

    n = len(measures)
    nrows = int(math.ceil(n / ncols))

    # compacte figuur; schaal mee met aantal rijen
    fig_w = 6.6 * ncols/2                 # ~2 kolomsbreedte-achtig; pas aan naar jouw template
    fig_h = 2.2 * nrows
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(fig_w, fig_h), sharey=True)
    axes = np.atleast_1d(axes).reshape(nrows, ncols)

    for i, m in enumerate(measures):
        r, c = divmod(i, ncols)
        ax = axes[r, c]

        wide = wide_tables[m]
        groups = [wide[col].to_numpy() for col in wide.columns]
        labels = [display_config_name(col) for col in wide.columns]

        ax.boxplot(groups, tick_labels=labels, showmeans=True, widths = 0.7)
        ax.axhline(0.0, linestyle="--", linewidth=0.7)
        ax.set_title(display_name(m))
        ax.set_ylim(*ylim)
        ax.tick_params(axis="x", rotation=25)

        if c == 0:
            ax.set_ylabel("z-score [-]")

    # lege subplots uitzetten
    for j in range(n, nrows * ncols):
        r, c = divmod(j, ncols)
        axes[r, c].axis("off")

    fig.tight_layout(pad=0.4)

    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(title)).strip("_")
    out_path = out_dir / f"{safe}__zscore_grid.png"
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    return out_path
def plot_cumulative_delay_absorption(df, config_col, configs, title_prefix=None):
    """
    Cumulative delay absorption mechanism breakdown (stacked means):
    - mean_delay_speed
    - mean_delay_mach
    - mean_delay_dogleg
    - mean_delay_holding

    Updates vs. previous version:
    - Uses display names consistent with the rest of the report (configs + KPI labels).
    - Saves the figure to ABS_PLOT_DIR as a PNG.
    """
    d = df[df[config_col].isin(configs)].copy()

    cols = ["mean_delay_speed", "mean_delay_mach", "mean_delay_dogleg", "mean_delay_holding"]
    existing = [c for c in cols if c in d.columns]
    if not existing:
        return

    for c in existing:
        d[c] = pd.to_numeric(d[c], errors="coerce")

    means = d.groupby(config_col)[existing].mean(numeric_only=True).reindex(configs)

    # Pretty labels for legend (prefer your global KPI naming where available)
    abs_labels = {
        "mean_delay_speed": MEASURE_DISPLAY_NAMES.get("mean_delay_speed", "Speed control [s/ac]"),
        "mean_delay_mach": MEASURE_DISPLAY_NAMES.get("mean_delay_mach", "Mach control [s/ac]"),
        "mean_delay_dogleg": MEASURE_DISPLAY_NAMES.get("mean_delay_dogleg", "Vectoring (dogleg) [s/ac]"),
        "mean_delay_holding": MEASURE_DISPLAY_NAMES.get("mean_delay_holding", "Holding [s/ac]"),
    }

    # Stacked bar (cumulative)
    x = np.arange(len(configs))
    bottom = np.zeros(len(configs), dtype=float)

    plt.figure(figsize=(7.2, 2.8))
    for c in existing:
        vals = means[c].to_numpy(dtype=float)
        plt.bar(x, vals, bottom=bottom, label=abs_labels.get(c, c))
        bottom = bottom + np.nan_to_num(vals)

    plt.xticks(x, [display_config_name(str(c)) for c in configs], rotation=25, ha="right")
    plt.ylabel("Mean absorbed delay [s/ac]")

    # Keep title minimal and consistent with the rest
    # if title_prefix:
    #     plt.title(str(title_prefix))
    plt.grid()
    plt.ylim(0,100)
    plt.legend(
        fontsize=8,
        loc="upper left",
        bbox_to_anchor=(0.02, 1.0),
        borderaxespad=0.0
    )
    plt.tight_layout(pad=0.4, rect=[0, 0, 0.82, 1])

    # Save figure
    ABS_PLOT_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", str(title_prefix) if title_prefix else "absorption").strip("_")
    out_path = ABS_PLOT_DIR / f"{safe_title}__cumulative_delay_absorption.png"
    plt.savefig(out_path, dpi=ABS_PLOT_DPI, bbox_inches="tight")
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
                     use_zscores=True, alpha=0.05, pairs=None):
    # Pair selection: allow passing an explicit subset of pairs.
    # Expected format: pairs=[("cfgA","cfgB"), ...]
    if pairs is None:
        pairs = [(configs[i], configs[j]) for i in range(len(configs)) for j in range(i + 1, len(configs))]
    else:
        # Basic validation + keep only pairs that are in the requested configs
        pairs = [(a, b) for (a, b) in pairs if (a in configs and b in configs)]

    # Always keep a baseline-vs-rest pair set available (used for starred KPI tables)
    baseline = configs[0] if configs else None
    baseline_pairs = [(baseline, c) for c in configs[1:]] if baseline else []

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

    # Also compute baseline-vs-rest tests if the user requested a different subset of pairs.
    # This is used to add "*" markers in the mean KPI table.
    if baseline_pairs:
        missing_baseline_pairs = [(a, b) for (a, b) in baseline_pairs
                                 if not (((posthoc["A"] == a) & (posthoc["B"] == b)).any())]
        if missing_baseline_pairs:
            extra_rows = []
            for m in measures:
                wide = make_paired_wide(
                    df, unit_col=seed_col, condition_col=config_col,
                    conditions=configs, measure=m, zscore_within_unit=use_zscores
                )
                for a, b in missing_baseline_pairs:
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
                    extra_rows.append({
                        "measure": m,
                        "A": a,
                        "B": b,
                        "stat": float(stat) if stat is not None else np.nan,
                        "p_raw": float(p) if p is not None else np.nan,
                        "n": int(len(x)),
                        "median_diff": float(np.nanmedian(diff)),
                        "mean_diff": float(np.nanmean(diff)),
                        "used_zscores": bool(use_zscores),
                        "alpha": float(alpha_corr),
                        "significant": bool(np.isfinite(p) and (p <= alpha_corr)),
                    })
            if extra_rows:
                posthoc = pd.concat([posthoc, pd.DataFrame(extra_rows)], ignore_index=True)

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

    # ---- Build the clear mean KPI comparison table and attach significance from posthoc ----
    mean_table = mean_comparison_table(
        df,
        condition_col=config_col,
        conditions=configs,
        measures=measures,
    )
    mean_table["alpha_corr"] = float(alpha_corr)

    # ---- Create a starred mean table (compare every config to the first/baseline) ----
    # Star rule: for each KPI row, append "*" to mean values that differ significantly from baseline.
    baseline_disp = display_config_name(baseline) if baseline else None

    # Map: (measure, config) -> significant (baseline vs config)
    sig_map = {}
    if baseline:
        for _, r in posthoc.iterrows():
            if r.get("A") == baseline and r.get("B") in configs:
                sig_map[(r.get("measure"), r.get("B"))] = bool(r.get("significant"))

    mean_table_star = mean_table.copy()

    def _fmt_star(val, add_star: bool):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return ""
        try:
            s = f"{float(val):.3f}" if isinstance(val, (float, np.floating, int, np.integer)) else str(val)
        except Exception:
            s = str(val)
        return s + ("*" if add_star else "")

    if baseline:
        for c in configs:
            col = f"mean_{display_config_name(c)}"
            if col not in mean_table_star.columns:
                continue
            if c == baseline:
                mean_table_star[col] = mean_table_star[col].apply(lambda v: _fmt_star(v, False))
                continue
            mean_table_star[col] = mean_table_star.apply(
                lambda r: _fmt_star(r[col], sig_map.get((r.get("measure"), c), False)),
                axis=1,
            )

    # Drop pairwise significance columns; stars encode baseline significance
    drop_sig_cols = [c for c in mean_table_star.columns if str(c).startswith("significant_")]
    mean_table_star = mean_table_star.drop(columns=drop_sig_cols, errors="ignore")

    return posthoc.sort_values(["measure", "p_raw"]), mean_table_star

# Helper: mean KPI comparison table
def mean_comparison_table(df, condition_col, conditions, measures):
    """
    Clear, descriptive table (raw values):
    - mean_<condition> for each condition

    `kpi` is a display label only. Edit MEASURE_DISPLAY_NAMES below.
    This function returns numeric means (stars applied later).
    """
    rows = []

    d = df[df[condition_col].isin(conditions)].copy()

    for m in measures:
        kpi_label = display_name(m)

        if m not in d.columns:
            row = {"measure": m, "kpi": kpi_label}
            for c in conditions:
                row[f"mean_{display_config_name(c)}"] = np.nan
            rows.append(row)
            continue

        d_m = d[[condition_col, m]].copy()
        d_m[m] = pd.to_numeric(d_m[m], errors="coerce")

        means = (
            d_m.groupby(condition_col)[m]
               .mean()
               .reindex(conditions)
        )

        row = {"measure": m, "kpi": kpi_label}
        for c in conditions:
            row[f"mean_{display_config_name(c)}"] = means.loc[c]

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

# Merge variants into one config label (e.g., seed32/higherseed runs)
df["config_norm"] = (
    df["config_norm"]
      .str.replace(r"(_seed\d+)$", "", regex=True)   # removes _seed32, _seed16, etc.
      .str.replace(r"(_higherseed)$", "", regex=True)
)

# Optional: also merge other similar suffix patterns if you have them
# df["config_norm"] = df["config_norm"].str.replace(r"(_lowerseed)$", "", regex=True)

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
    # "mean_totalspeedup",    # if you want it shown separately
    "mean_LLDA",
    "count_LLDA_nonzero",
    # "mean_delay_mach",
    # "mean_delay_speed",
    # "count_hold_events",

    # taskload
    "total_count",
    # 'count_popup',
]

MEASURE_DISPLAY_NAMES: Dict[str, str] = {
    "total_EAT_updates": "EAT Revisions [-]",
    "amount_of_swaps": "Sequence Position Changes [-]",

    "pct_extrawork": "Delay energy cost [%]",
    "mean_totaldelay": "Mean total delay [s/ac]",
    "mean_totalspeedup": "Mean totalspeedup [s/ac]",
    "mean_LLDA": "Mean vectoring delay [s/ac]",
    "count_LLDA_nonzero": "Vectored flights [ac]",
    "mean_delay_mach": "Mean mach delay [s/ac]",
    "mean_delay_speed": "Mean delay speed [s/ac]",
    "count_hold_events": "Total hold events [ac]",

    "total_count": "Instruction count [-]",
    'count_popup': "Pop-ups [ac]",
}

# =========================
# EASY EDIT: configuration display names
# =========================
CONFIG_DISPLAY_NAMES: Dict[str, str] = {

    # --- Baseline / Standard AMAN ---
    "standard_aman": "FCFS14",

    # --- E-AMAN FCFS ---
    "eaman_fcfs": "FCFS20",
    "eaman_fcfs_25": "FCFS25",

    # --- E-AMAN BOL ---
    "eaman_BOL": "BOL20",
    "eaman_BOL_25": "BOL25",

    # --- Delay Scheduler ---
    "delay20": "Delay20",
    "delay25": "Delay25",

    # --- EFD Variants ---
    "EFDFCFS14": "FCFS14, Planning at T/O enabled",
    "EFDFCFS20": "FCFS20, Planning at T/O enabled",
    "EFDFCFS25": "FCFS25, Planning at T/O enabled",

    "EFDBOL20": "BOL20, Planning at T/O enabled",
    "EFDBOL25": "BOL25, Planning at T/O enabled",

    # --- Uncertainty Ablations ---
    "eaman_zero_uncertainty": "FCFS20 no uncertainty",
    "eaman_no_popup": "FCFS20 no pop-ups",

    "NOTP20": "FCFS20 no TP uncertainty",
    "NO_ENROUTE20": "FCFS20 no enroute",

    # --- No-EBBR Variants ---
    "no_ebbr_BOL20": "BOL20 Excl. EBBR",
    "no_ebbr_BOL25": "BOL25 Excl. EBBR",

    "no_ebbr_delay20": "Delay20 Excl. EBBR",
    "no_ebbr_delay25": "Delay25 Excl. EBBR",

    "no_ebbr_EFDBOL20": "BOL20 Excl. EBBR, Planning at T/O enabled",
    "no_ebbr_EFDBOL25": "BOL25 Excl. EBBR, Planning at T/O enabled",

    "no_ebbr_EFDFCFS20": "FCFS20 Excl. EBBR, Planning at T/O enabled",

    "no_ebbr_FCFS14": "FCFS14 Excl. EBBR",
    "no_ebbr_FCFS20": "FCFS20 Excl. EBBR",
    "no_ebbr_FCFS25": "FCFS25 Excl. EBBR",
}




def display_name(key: str) -> str:
    return MEASURE_DISPLAY_NAMES.get(key, key)


def display_config_name(key: str) -> str:
    return CONFIG_DISPLAY_NAMES.get(key, key)

# -------------------------
# Header helpers for LaTeX KPI tables
# -------------------------
_CONFIG_FH_RE = re.compile(r"(\d{2})")

# Known special suffixes (keep order: most specific first)
_KNOWN_SPECIALS = [
    "no_ebbr",
    "no_popup",
    "zero_uncertainty",
    "no_tp",
    "no_enroute_tp",
]

def split_config_components(cfg_display: str) -> tuple[str, str, str]:
    """
    Split a displayed config name into (planner, FH, special).

    Examples:
      - "FCFS14" -> ("FCFS", "14", "")
      - "BOL20_no_ebbr" -> ("BOL", "20", "no_ebbr")
      - "EFD_BOL25" -> ("EFD_BOL", "25", "")
      - "FCFS20_zero_uncertainty" -> ("FCFS", "20", "zero_uncertainty")
    """
    s = str(cfg_display)

    # Special: detect known suffix (after last underscore)
    special = ""
    for sp in _KNOWN_SPECIALS:
        if s.endswith("_" + sp):
            special = sp
            s = s[: -(len(sp) + 1)]
            break

    # FH: first 2-digit block (14/20/25)
    m = _CONFIG_FH_RE.search(s)
    fh = m.group(1) if m else ""

    # Planner: strip FH digits from the remainder (keep underscores like EFD_BOL)
    planner = s
    if fh:
        planner = planner.replace(fh, "")
    planner = planner.strip("_")

    return planner, fh, special


def build_kpi_header_rows(cols: list[str]) -> list[list[str]]:
    """
    Build three extra header rows for KPI mean/significance tables:
      1) Planner
      2) FH
      3) Special

    For mean columns: use the config name after 'mean_'.
    For significance columns: show 'A vs B' for each component.
    """
    planner_row: list[str] = []
    fh_row: list[str] = []
    special_row: list[str] = []

    for col in cols:
        c = str(col)

        # Left-most label column
        if c in ("kpi", "KPI"):
            planner_row.append("Planner")
            fh_row.append("Freeze Horizon")
            special_row.append("Special")
            continue

        # Mean columns
        if c.startswith("mean_"):
            cfg = c[len("mean_"):]
            p, fh, sp = split_config_components(cfg)
            planner_row.append(p)
            fh_row.append(fh)
            special_row.append(sp)
            continue

        # Significance columns: significant_A_vs_B
        if c.startswith("significant_") and "_vs_" in c:
            rest = c[len("significant_"):]
            a, b = rest.split("_vs_", 1)
            pa, fha, spa = split_config_components(a)
            pb, fhb, spb = split_config_components(b)

            def fmt_pair(x, y):
                s = f"{x} vs {y}".strip()
                if len(s) > 10:
                    return rf"\shortstack{{{x} vs\\{y}}}"
                return s

            planner_row.append(fmt_pair(pa, pb))
            fh_row.append(fmt_pair(fha, fhb))
            special_row.append(fmt_pair(spa, spb))
            continue

        # Everything else (alpha_corr etc.)
        planner_row.append("")
        fh_row.append("")
        special_row.append("")

    return [planner_row, fh_row, special_row]

# -------------------------
# Apply config display names inside generated table column headers
# (mean_*, diff_*_minus_*, significant_*_vs_*)
# -------------------------
_MEAN_COL_RE = re.compile(r"^mean_(.+)$")
_DIFF_COL_RE = re.compile(r"^diff_(.+)_minus_(.+)$")
_SIG_COL_RE  = re.compile(r"^significant_(.+)_vs_(.+)$")

def prettify_result_columns(cols: list[str]) -> list[str]:
    out: list[str] = []
    for col in cols:
        col = str(col)

        m = _MEAN_COL_RE.match(col)
        if m:
            cfg = m.group(1)
            out.append(f"mean_{display_config_name(cfg)}")
            continue

        m = _DIFF_COL_RE.match(col)
        if m:
            a, b = m.group(1), m.group(2)
            out.append(f"diff_{display_config_name(a)}_minus_{display_config_name(b)}")
            continue

        m = _SIG_COL_RE.match(col)
        if m:
            a, b = m.group(1), m.group(2)
            out.append(f"significant_{display_config_name(a)}_vs_{display_config_name(b)}")
            continue

        out.append(col)

    return out

def with_pretty_result_columns(df_in: pd.DataFrame) -> pd.DataFrame:
    df_out = df_in.copy()
    df_out.columns = prettify_result_columns([str(c) for c in df_out.columns])
    return df_out


# Pairing / grouping columns (edit once)
# Use normalized columns so variants like no_ebbr_sc1 can be paired with sc1
SEED_COL = "scenario_norm"       # paired unit
COND_COL = "config_norm"         # condition column you compare
VIOLIN_UNIT_COL = "seed"     # show violin distributions using individual seeds (optional)

# Common knobs
USE_ZSCORES = True

# Plot toggles
MAKE_PLOTS = True        # z-score boxplots
MAKE_ABSORPTION_PLOTS = True
MAKE_VIOLIN_PLOTS = False

P_CORR = "bonferroni"

# =========================
# LaTeX table export options
# =========================
EXPORT_LATEX_TABLES = True  # zet True om .tex output te schrijven
LATEX_TABLE_DIR = Path("latex_tables")
LATEX_CAPTION_PREFIX = ""    # bv. "Results: " als je dat wil
# Make tables smaller / more compact
# Examples: "\\small", "\\footnotesize", "\\scriptsize"
LATEX_FONT_CMD = "\\footnotesize"
LATEX_TABCOLSEP_PT = 3      # default ~6pt; lager = smaller columns
LATEX_ARRAYSTRETCH = 1.0    # default ~1.0; lager = compact rows (bv 0.95)

_LATEX_ESCAPE_RE = re.compile(r"([\\%&_#{}$])")

def latex_escape(s: object) -> str:
    if s is None:
        return ""
    s = str(s)
    s = s.replace("\\", r"\\")
    return _LATEX_ESCAPE_RE.sub(r"\\\1", s)

def df_to_latex_table(
    df: pd.DataFrame,
    caption: str,
    label: str,
    notes: str | None = None,
    float_spec: str = "htbp",
    col_align: str = "c",
    index: bool = False,
    float_format: str = "{:.3f}",
    extra_header_rows: list[list[str]] | None = None,
    include_header: bool = True,
) -> str:
    if index:
        use_df = df.reset_index()
    else:
        use_df = df.copy()

    def fmt_cell(x):
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return ""
        # bool is subclass of int -> eerst afvangen, anders krijg je 1/0
        if isinstance(x, (bool, np.bool_)):
            return "True" if bool(x) else "False"
        if isinstance(x, (int, np.integer)):
            return str(int(x))
        if isinstance(x, (float, np.floating)):
            try:
                return float_format.format(float(x))
            except Exception:
                return str(x)
        return str(x)

    # Column headers may intentionally contain LaTeX (e.g., $\chi^2$).
    # Only escape headers that look like plain text.
    def _latex_escape_header(x: object) -> str:
        s = "" if x is None else str(x)
        # If the header already contains LaTeX math or commands, keep it raw.
        if ("$" in s) or ("\\" in s):
            return s
        return latex_escape(s)

    def _latex_escape_cell(s: object) -> str:
        t = "" if s is None else str(s)
        if ("$" in t) or ("\\" in t):
            return t
        return latex_escape(t)

    cols = [_latex_escape_header(c) for c in use_df.columns]
    ncol = len(cols)
    spec = "|" + "|".join([col_align] * ncol) + "|"

    lines = []
    lines.append(f"\\begin{{table}}[{float_spec}]")
    lines.append(f"\\caption{{{latex_escape(caption)}}}")
    lines.append("\\begin{center}")
    # Compact styling
    if LATEX_FONT_CMD:
        lines.append(LATEX_FONT_CMD)
    if LATEX_TABCOLSEP_PT is not None:
        lines.append(f"\\setlength{{\\tabcolsep}}{{{int(LATEX_TABCOLSEP_PT)}pt}}")
    if LATEX_ARRAYSTRETCH is not None:
        lines.append(f"\\renewcommand{{\\arraystretch}}{{{float(LATEX_ARRAYSTRETCH):.3f}}}")
    lines.append(f"\\begin{{tabular}}{{{spec}}}")
    lines.append("\\hline")

    # Optional extra header rows (e.g., Planner / FH / Special)
    if extra_header_rows:
        for row in extra_header_rows:
            # Ensure correct width
            if len(row) != ncol:
                raise ValueError(f"extra_header_rows width mismatch: expected {ncol}, got {len(row)}")
            row_cells = [_latex_escape_cell(x) for x in row]
            lines.append(" & ".join(row_cells) + r" \\")
            lines.append("\\hline")

    # Header row (bold)
    if include_header:
        header = " & ".join([f"\\textbf{{{c}}}" for c in cols]) + r" \\"
        lines.append(header)
        lines.append("\\hline")

    # Body
    for _, row in use_df.iterrows():
        vals = [latex_escape(fmt_cell(v)) for v in row.tolist()]
        lines.append(" & ".join(vals) + r" \\")
        lines.append("\\hline")

    # Optional footnote line (right aligned)
    # NOTE: do NOT LaTeX-escape `notes` because it may intentionally contain LaTeX math (e.g., $\alpha$).
    if notes:
        lines.append(f"\\multicolumn{{{ncol}}}{{r}}{{{str(notes)}}}\\\\")
        # geen extra hline in jouw guide na footnote; laat dit zo

    lines.append("\\end{tabular}")
    lines.append(f"\\label{{{latex_escape(label)}}}")
    lines.append("\\end{center}")
    lines.append("\\end{table}")

    return "\n".join(lines)



def format_friedman_table(friedman_results: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Compact Friedman output table:
    Columns: KPI, chi2, p, W, Sig.
    Meta (n,k,df,alpha) returned separately for a single footnote line.
    """
    if friedman_results is None or friedman_results.empty:
        return pd.DataFrame(), {}

    def _mode_or_none(series_like):
        s = pd.to_numeric(series_like, errors="coerce")
        s = s.dropna()
        if s.empty:
            return None
        return s.mode().iloc[0]

    meta = {
        "n": _mode_or_none(friedman_results.get("n", pd.Series(dtype=float))),
        "k": _mode_or_none(friedman_results.get("k", pd.Series(dtype=float))),
        "df": _mode_or_none(friedman_results.get("df", pd.Series(dtype=float))),
        "alpha": _mode_or_none(friedman_results.get("alpha", pd.Series(dtype=float))),
    }

    out = friedman_results.copy()

    # KPI display names (same mapping as your KPI table)
    out["KPI"] = out["measure"].apply(display_name)

    # Keep only what you want
    out = out[["KPI", "chi2", "p", "kendall_W", "significant"]].rename(
        columns={
            "chi2": r"$\chi^2$",
            "kendall_W": "W",
            "significant": "Sig.",
        }
    )

    # Replace bools by Yes/No (cleaner in paper tables)
    out["Sig."] = out["Sig."].map(lambda x: "Yes" if bool(x) else "No")

    # Ensure numeric types for formatting
    out[r"$\chi^2$"] = pd.to_numeric(out[r"$\chi^2$"], errors="coerce")
    out["p"] = pd.to_numeric(out["p"], errors="coerce")
    out["W"] = pd.to_numeric(out["W"], errors="coerce")

    return out, meta


def friedman_table_to_latex(
    friedman_results: pd.DataFrame,
    caption: str,
    label: str,
    float_spec: str = "htbp",
    float_format: str = "{:.3f}",
) -> str:
    """
    LaTeX table (style-guide-ish):
    - Minimal columns
    - One footnote line with n,k,df,alpha (no repeated columns)
    """
    tbl, meta = format_friedman_table(friedman_results)
    if tbl.empty:
        return ""

    parts = []
    if meta.get("n") is not None:
        parts.append(f"n={int(meta['n'])}")
    if meta.get("k") is not None:
        parts.append(f"k={int(meta['k'])}")
    if meta.get("df") is not None:
        parts.append(f"df={int(meta['df'])}")
    if meta.get("alpha") is not None:
        parts.append(rf"$\alpha$={float(meta['alpha']):.3f}")

    notes = "; ".join(parts) if parts else None

    return df_to_latex_table(
        tbl,
        caption=caption,
        label=label,
        notes=notes,
        float_spec="!t",
        col_align="c",
        index=False,
        float_format=float_format,
        include_header=True,
    )

# Helper function for running experiments
def run_experiment(title, configs, pairs=None):
    seed_col = SEED_COL
    config_col = COND_COL
    measures = MEASURES

    _, wide_tables = zscores_and_boxplots(df, seed_col, config_col, configs, measures, make_plots=False, plot_prefix=title)
    # save_boxplot_grid(
    #     wide_tables=wide_tables,
    #     measures=MEASURES,
    #     title=title,
    #     out_dir=ZPLOT_DIR,
    #     ncols=2,
    #     ylim=(-2, 2),
    #     dpi=ZPLOT_DPI
    # )

    out_path = ZPLOT_DIR / (re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_") + "__zscore_clustered.png")
    save_clustered_zscore_boxplots(wide_tables, MEASURES, configs, title, out_path, xlim=(-2, 2), dpi=ZPLOT_DPI)
    if MAKE_ABSORPTION_PLOTS:
        plot_cumulative_delay_absorption(df, config_col, configs, title_prefix=title)

    if MAKE_VIOLIN_PLOTS:
        # Keep the number of figures reasonable for reports
        violin_measures = [m for m in ("pct_extrawork", "mean_count", "mean_LLDA", "mean_totaldelay", "amount_of_swaps", "total_EAT_updates") if m in measures]
        plot_violin_distributions(df, VIOLIN_UNIT_COL, config_col, configs, violin_measures, title_prefix=title)
    if len(configs) >=3:
        friedman_results, _ = friedman_anova(df, seed_col, config_col, configs, measures, use_zscores=USE_ZSCORES)
    posthoc, mean_table = wilcoxon_posthoc(
        df,
        seed_col,
        config_col,
        configs,
        measures,
        use_zscores=USE_ZSCORES,
        alpha=0.05,
        pairs=pairs,
    )

    print(f"\n===== {title} =====")
    print("Configs:", [display_config_name(c) for c in configs])
    if len(configs) >= 3:
        print("\nFriedman:\n", friedman_results)
    # print("\nPost-hoc Wilcoxon:\n", posthoc)

    # Print KPI labels first (easy to read)
    if "kpi" in mean_table.columns:
        keep_cols = [c for c in mean_table.columns if c == "kpi" or str(c).startswith("mean_") or c == "alpha_corr"]
        display_table = mean_table[keep_cols]
    else:
        display_table = mean_table

    print("\nMean KPI comparison (raw values):\n", display_table)

    # Optional LaTeX export (style-guide compliant)
    if EXPORT_LATEX_TABLES:
        LATEX_TABLE_DIR.mkdir(parents=True, exist_ok=True)

        # Gebruik de tabel die je ook print (kpi eerst) voor leesbaarheid
        latex_df = display_table.copy() if "display_table" in locals() else mean_table.copy()
        latex_df = with_pretty_result_columns(latex_df)

        safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", str(title)).strip("_")
        tex_path = LATEX_TABLE_DIR / f"{safe_title}.tex"

        caption = f"{LATEX_CAPTION_PREFIX}{title}" if LATEX_CAPTION_PREFIX else str(title)
        label = f"tab:{safe_title.lower()}"

        extra_rows = build_kpi_header_rows([str(c) for c in latex_df.columns])

        tex = df_to_latex_table(
            latex_df,
            caption=caption,
            label=label,
            notes=None,
            float_spec="htbp",
            col_align="c",
            index=False,
            float_format="{:.3f}",
            extra_header_rows=extra_rows,
        )

        tex_path.write_text(tex, encoding="utf-8")
        print(f"LaTeX table written: {tex_path}")

    # --- Friedman table export (compact) ---
    if len(configs) >= 3:
        friedman_tex = friedman_table_to_latex(
            friedman_results,
            caption=f"{title} — Friedman ANOVA Summary",
            label=f"tab:{safe_title.lower()}_friedman",
            float_spec="!t",
            float_format="{:.3f}",
        )
        if friedman_tex:
            friedman_path = LATEX_TABLE_DIR / f"{safe_title}_friedman.tex"
            friedman_path.write_text(friedman_tex, encoding="utf-8")
            print(f"LaTeX table written: {friedman_path}")

    return {
        "title": title,
        "configs": list(configs),
        "posthoc": posthoc.copy(),
        "mean_table": mean_table.copy(),
        "friedman_results": friedman_results.copy() if len(configs) >= 3 else None,
    }
# ----------------------------
# Violin plots (KPI distributions per config)

def build_experiment_summary_table(
    experiment_results: list[dict],
    zero_threshold_rel: float = 0.05,
) -> pd.DataFrame:
    """
    Build one large qualitative summary table across multiple experiments.

    Per experiment:
    - the first config is the reference
    - every other config is compared to that reference

    Output columns:
    - Experiment
    - Reference
    - Configuration
    - one column per KPI display name
    """
    rows = []

    for result in experiment_results:
        if not result:
            continue

        title = result["title"]
        configs = result["configs"]
        mean_table = result["mean_table"].copy()
        posthoc = result["posthoc"].copy()

        if not configs or len(configs) < 2:
            continue

        baseline = configs[0]
        baseline_disp = display_config_name(baseline)
        baseline_col = f"mean_{display_config_name(baseline)}"

        for cfg in configs[1:]:
            cfg_disp = display_config_name(cfg)
            cfg_col = f"mean_{cfg_disp}"

            out = {
                "Experiment": title,
                "Reference": baseline_disp,
                "Configuration": cfg_disp,
            }

            for _, row in mean_table.iterrows():
                measure = row["measure"]
                kpi_label = row["kpi"]

                base_val = row.get(baseline_col, np.nan)
                other_val = row.get(cfg_col, np.nan)

                hit = posthoc[
                    (posthoc["measure"] == measure) &
                    (posthoc["A"] == baseline) &
                    (posthoc["B"] == cfg)
                ]
                significant = bool(hit["significant"].iloc[0]) if len(hit) else False

                out[kpi_label] = _qualitative_symbol(
                    base_val=base_val,
                    other_val=other_val,
                    significant=significant,
                    lower_is_better=(measure in LOWER_IS_BETTER_MEASURES),
                    zero_threshold_rel=zero_threshold_rel,
                )

            rows.append(out)

    summary_df = pd.DataFrame(rows)

    fixed_cols = ["Experiment", "Reference", "Configuration"]
    kpi_cols = [display_name(m) for m in MEASURES]
    present_kpi_cols = [c for c in kpi_cols if c in summary_df.columns]

    ordered_cols = fixed_cols + present_kpi_cols
    summary_df = summary_df.reindex(columns=ordered_cols)
    return summary_df



def export_experiment_summary_table_to_latex(
    summary_df: pd.DataFrame,
    caption: str,
    label: str,
    out_path: Path,
) -> Path:
    """
    Export one large cross-experiment qualitative summary table to LaTeX.

    Layout:
    - one full-width table* for two-column papers
    - for each experiment, one compact section row:
      "<experiment title> (reference: <reference>)"
    - below that, one row per configuration
    - no separate Experiment / Reference columns in the body
    """

    def _esc_cell(x: object) -> str:
        s = "" if x is None else str(x)
        return latex_escape(s)

    def _stack_words(s: str) -> str:
        txt = str(s).strip()
        if not txt:
            return ""
        parts = txt.split()
        if len(parts) <= 1:
            return latex_escape(txt)
        return r"\shortstack[l]{" + r"\\".join(latex_escape(p) for p in parts) + "}"

    def _stack_header_label(s: str) -> str:
        """
        Make long KPI headers multi-line inside the header cell.
        Break at spaces and keep bracketed units on the last line when possible.
        """
        txt = str(s).strip()
        if not txt:
            return ""

        if " [" in txt and txt.endswith("]"):
            main, unit = txt.rsplit(" [", 1)
            unit = "[" + unit
            parts = main.split()
            if len(parts) >= 2:
                return r"\shortstack[c]{" + r"\\".join(latex_escape(p) for p in parts[:-1]) + r"\\" + latex_escape(parts[-1] + " " + unit) + "}"
            return r"\shortstack[c]{" + latex_escape(main) + r"\\" + latex_escape(unit) + "}"

        parts = txt.split()
        if len(parts) <= 1:
            return latex_escape(txt)
        return r"\shortstack[c]{" + r"\\".join(latex_escape(p) for p in parts) + "}"

    fixed_cols = ["Experiment", "Reference", "Configuration"]
    kpi_cols = [c for c in summary_df.columns if c not in fixed_cols]

    # Only one descriptive column on the left, then KPI columns
    col_spec = r"|p{4.6cm}|" + "".join([r"p{1.45cm}|" for _ in kpi_cols])

    lines = []
    lines.append(r"\begin{table*}[htbp]")
    lines.append(rf"\caption{{{latex_escape(caption)}}}")
    lines.append(r"\begin{center}")
    if LATEX_FONT_CMD:
        lines.append(LATEX_FONT_CMD)
    lines.append(r"\setlength{\tabcolsep}{1.5pt}")
    lines.append(r"\renewcommand{\arraystretch}{1.08}")
    lines.append(rf"\begin{{tabular}}{{{col_spec}}}")
    lines.append(r"\hline")

    header_cells = [r"\textbf{Configuration}"] + [rf"\textbf{{{_stack_header_label(c)}}}" for c in kpi_cols]
    lines.append(" & ".join(header_cells) + r" \\")
    lines.append(r"\hline")

    prev_experiment = None
    prev_reference = None
    total_cols = 1 + len(kpi_cols)

    for _, row in summary_df.iterrows():
        experiment = str(row.get("Experiment", ""))
        reference = str(row.get("Reference", ""))
        configuration = str(row.get("Configuration", ""))

        # Add one section row per experiment block
        if experiment != prev_experiment or reference != prev_reference:
            if prev_experiment is not None:
                lines.append(r"\hline\hline")
            section_text = f"{experiment} (reference: {reference})"
            lines.append(
                rf"\multicolumn{{{total_cols}}}{{|l|}}{{\textbf{{{latex_escape(section_text)}}}}} \\"
            )
            lines.append(r"\hline")

        vals = [latex_escape(configuration)]
        for c in kpi_cols:
            v = row.get(c, "")
            vals.append("" if pd.isna(v) else str(v))

        lines.append(" & ".join(vals) + r" \\")
        lines.append(r"\hline")

        prev_experiment = experiment
        prev_reference = reference

    lines.append(
        rf"\multicolumn{{{total_cols}}}{{r}}{{{{\footnotesize ++ / --: significant improvement / deterioration relative to the reference; + / -: non-significant but meaningful difference; 0: minimal difference.}}}}\\"
    )
    lines.append(r"\end{tabular}")
    lines.append(rf"\label{{{latex_escape(label)}}}")
    lines.append(r"\end{center}")
    lines.append(r"\end{table*}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"LaTeX experiment summary table written: {out_path}")
    return out_path
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
            labels.append(display_config_name(str(cfg)))

        # Skip empty
        if not any(len(x) for x in data):
            continue

        plt.figure(figsize=(10, 4.5))
        plt.violinplot(data, showmeans=True, showmedians=True, showextrema=True)

        plt.xticks(np.arange(1, len(labels) + 1), labels, rotation=35, ha="right")
        plt.ylabel(display_name(m))

        if title_prefix:
            plt.title(f"{title_prefix} — Violin distribution: {display_name(m)}")
        else:
            plt.title(f"Violin distribution: {display_name(m)}")

        plt.tight_layout()
        plt.show()
        plt.close()






# ----------------------------
# 4) Qualitative summary table (+ / - / 0 / ++ / --)
# ----------------------------

LOWER_IS_BETTER_MEASURES = {
    "total_EAT_updates",
    "amount_of_swaps",
    "pct_extrawork",
    "mean_totaldelay",
    "mean_LLDA",
    "count_LLDA_nonzero",
    "total_count",
    "mean_delay_mach",
    "mean_delay_speed",
    "count_hold_events",
    "count_popup",
}


def _parse_numeric_cell(value):
    """
    Convert table cells like 13.215* back to float.
    Returns np.nan if conversion is not possible.
    """
    if pd.isna(value):
        return np.nan

    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)

    s = str(value).strip()
    s = s.replace("*", "")
    s = s.replace(",", ".")

    try:
        return float(s)
    except Exception:
        return np.nan

def _qualitative_symbol(base_val, other_val, significant, lower_is_better=True, zero_threshold_rel=0.05):
    """
    Map difference to one of: ++, +, 0, -, --

    Rules:
    - 0  : abs(relative difference) < zero_threshold_rel
    - +  : improvement, not significant
    - ++ : improvement, significant
    - -  : deterioration, not significant
    - -- : deterioration, significant
    """
    base_val = _parse_numeric_cell(base_val)
    other_val = _parse_numeric_cell(other_val)

    if pd.isna(base_val) or pd.isna(other_val):
        return ""

    denom = max(abs(base_val), 1e-9)
    rel_change = (other_val - base_val) / denom

    if abs(rel_change) < zero_threshold_rel:
        return "0"

    improved = (rel_change < 0) if lower_is_better else (rel_change > 0)

    if improved:
        return "++" if significant else "+"
    return "--" if significant else "-"


def build_qualitative_summary_table(
    df,
    seed_col,
    config_col,
    configs,
    measures,
    use_zscores=True,
    alpha=0.05,
    zero_threshold_rel=0.05,
    pairs=None,
):
    """
    Build a qualitative comparison table against the first config in `configs`.

    Output:
    - measure
    - kpi
    - baseline
    - one column per non-baseline config with symbols: ++, +, 0, -, --
    """
    baseline = configs[0]

    posthoc, _ = wilcoxon_posthoc(
        df,
        seed_col=seed_col,
        config_col=config_col,
        configs=configs,
        measures=measures,
        use_zscores=use_zscores,
        alpha=alpha,
        pairs=pairs,
    )

    mean_table = mean_comparison_table(
        df,
        condition_col=config_col,
        conditions=configs,
        measures=measures,
    )

    rows = []
    baseline_disp = display_config_name(baseline)
    baseline_col = f"mean_{baseline_disp}"

    for _, row in mean_table.iterrows():
        measure = row["measure"]
        out = {
            "measure": measure,
            "kpi": row["kpi"],
            "baseline": baseline_disp,
        }

        base_val = row.get(baseline_col, np.nan)
        lower_is_better = measure in LOWER_IS_BETTER_MEASURES

        for cfg in configs[1:]:
            cfg_disp = display_config_name(cfg)
            cfg_col = f"mean_{cfg_disp}"
            other_val = row.get(cfg_col, np.nan)

            hit = posthoc[
                (posthoc["measure"] == measure) &
                (posthoc["A"] == baseline) &
                (posthoc["B"] == cfg)
            ]
            significant = bool(hit["significant"].iloc[0]) if len(hit) else False

            out[cfg_disp] = _qualitative_symbol(
                base_val=base_val,
                other_val=other_val,
                significant=significant,
                lower_is_better=lower_is_better,
                zero_threshold_rel=zero_threshold_rel,
            )

        rows.append(out)

    return pd.DataFrame(rows)


def qualitative_summary_to_latex(
    summary_df,
    caption,
    label,
    out_path,
    baseline_label="Reference",
):
    """
    Export the qualitative summary table to LaTeX.
    """
    display_df = summary_df.copy()

    if "measure" in display_df.columns:
        display_df = display_df.drop(columns=["measure"])

    if "baseline" in display_df.columns:
        display_df = display_df.rename(columns={"baseline": baseline_label, "kpi": "KPI"})
    else:
        display_df = display_df.rename(columns={"kpi": "KPI"})

    col_headers = list(display_df.columns)
    align = "l" + "c" * (len(col_headers) - 1)

    lines = []
    lines.append("\\begin{table}[htbp]")
    lines.append("\\caption{" + caption + "}")
    lines.append("\\label{" + label + "}")
    lines.append("\\centering")
    lines.append("\\begin{tabular}{" + align + "}")
    lines.append("\\hline")
    lines.append(" & ".join(col_headers) + r" \\")
    lines.append("\\hline")

    for _, r in display_df.iterrows():
        vals = [str(v) if not pd.isna(v) else "" for v in r.tolist()]
        lines.append(" & ".join(vals) + r" \\")

    lines.append("\\hline")
    lines.append("\\end{tabular}")
    lines.append(r"\\[2pt]")
    lines.append(
        r"{\footnotesize ++ / --: significant improvement / deterioration relative to the reference; "
        r"+ / -: non-significant but meaningful difference; 0: minimal difference.}"
    )
    lines.append("\\end{table}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"LaTeX qualitative summary table written: {out_path}")
    return out_path





# Helper: only run an experiment if ALL requested configs exist in the loaded data
def run_experiment_if_available(title: str, configs: list[str], pairs=None):
    available = set(pd.Series(df[COND_COL].unique()).dropna().astype(str))
    missing = [c for c in configs if c not in available]
    if missing:
        print(f"\n===== {title} (SKIPPED) =====")
        print("Requested configs:", configs)
        print("Missing configs:", missing)
        print("Available configs (first 50):", sorted(list(available))[:50])
        return
    run_experiment(title, configs, pairs=pairs)



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














EXPERIMENT_SPECS = [
    ("EXP 1 — effect of horizon extension", ["FCFS14", "FCFS20", "FCFS25"]),
    ("EXP 2 — effect of uncertainty", ["nouncertainty20", "nopopup20", "NOTP20", "NO_ENROUTE20", "FCFS20"]),
    ("EXP 3 — effect of scheduler", ["FCFS20", "BOL20", "DELAY20"]),
    ("EXP 3B — schedulers with extra-extended horizon", ["FCFS25", "BOL25", "DELAY25"]),
    ("Baseline AMAN in comparison to Back-of-the-line E-AMAN", ["FCFS14", "BOL20", "DELAY20"]),
    ("EXP 4A FCFS EFD and EBBR", ["FCFS20", "EFDFCFS20", "no_ebbr_FCFS20", "no_ebbr_EFDFCFS20"]),
    ("EXP 4B BOL EFD and EBBR", ["BOL20", "EFDBOL20", "no_ebbr_BOL20", "no_ebbr_EFDBOL20"]),
    ("EXP 5 BOL vs no ebbr en efd", ["FCFS20", "BOL20", "no_ebbr_EFDFCFS20"]),
    ("EXP6 BOL vs no ebbr en efd", ["FCFS14", "EFDFCFS14", "no_ebbr_EFDFCFS20"]),
]

all_experiment_results = []

for experiment_title, configs in EXPERIMENT_SPECS:
    result = run_experiment(experiment_title, configs)
    all_experiment_results.append(result)

summary_df = build_experiment_summary_table(
    all_experiment_results,
    zero_threshold_rel=0.02,
)

print("\n===== OVERALL QUALITATIVE SUMMARY =====")
print(summary_df)

if EXPORT_LATEX_TABLES:
    export_experiment_summary_table_to_latex(
        summary_df,
        caption="Qualitative summary of all experiments relative to the reference configuration within each experiment.",
        label="tab:overall_experiment_summary",
        out_path=LATEX_TABLE_DIR / "overall_experiment_summary.tex",
    )
#conclusie: EFD op FCFS 14 biedt al flinke voordelen eigenlijk

# # EXP 3A — different schedulers (same horizon, compare)
# # =====================================================
#
# configs = ["delay20", "eaman_fcfs", "eaman_BOL"]
# run_experiment("EXP 3 — different schedulers", configs)



## EXP 3B — schedulers with extra-extended horizon
# # ====================================================================
#
# configs = ["delay25", "eaman_fcfs_25", "eaman_BOL_25"]
#
# run_experiment("EXP 3A — schedulers with extra-extended horizon", configs)

#
# # EXP 4A — different schedulers (same horizon, compare)
# # =====================================================
#
# configs = ["delay20", "eaman_fcfs", "eaman_BOL"]
# run_experiment("EXP 3 — different schedulers", configs)
#
#
# # EXP 5 — comparing current to proposed
# # ====================================================================
#
# configs = ["standard_aman", "delay20", "eaman_BOL"]
#
# run_experiment("EXP 5 — comparing current to proposed", configs)
#
#
# configs = ["standard_aman", "delay20", "eaman_BOL", "EFDBOL20"]
#
# run_experiment("EXP 5A — comparing current to proposed", configs)
#
#
#
# configs = ["standard_aman", "delay25", "eaman_BOL_25", "EFDBOL25"]
# run_experiment("EXP 5B — comparing current to proposed long range", configs)
#
# # EXP 6 — NO-EBBR comparison set (keep EXP1–EXP5B unchanged)
# # Compares baseline vs no_ebbr variants side-by-side.
# configs = ["standard_aman", "eaman_BOL",'no_ebbr_BOL20','no_ebbr_BOL25', 'no_ebbr_FCFS25',"eaman_fcfs", "eaman_BOL_25"]#, "eaman_BOL_25_no_ebbr"]
#
#
# run_experiment_if_available("EXP 6 — NO-EBBR impact", configs)
#
#
# configs = ["standard_aman", "eaman_BOL",'no_ebbr_BOL20', 'EFDBOL20', "no_ebbr_EFDBOL20", 'EFDBOL25', "no_ebbr_EFDBOL25"]
#
#
# run_experiment_if_available("EXP 7 — NO-EBBR impact", configs)
#
#
#
#
# configs = ["standard_aman", 'EFDFCFS14', 'EFDFCFS20', 'eaman_fcfs', 'eaman_BOL']
#
#
# run_experiment_if_available("EXP 8 — FCFS EFD", configs)















