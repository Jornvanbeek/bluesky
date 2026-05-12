from pathlib import Path
import re
import pandas as pd
import matplotlib.pyplot as plt


BASE_DIRS = {
    "FCFS14": Path(r"/Users/jornvanbeek/Desktop/bluesky/MC_AMAN_DF/FCFS14/"),
    "FCFS20": Path(r"/Users/jornvanbeek/Desktop/bluesky/MC_AMAN_DF/FCFS20/"),
    "BOL20": Path(r"/Users/jornvanbeek/Desktop/bluesky/MC_AMAN_DF/BACK20/"),
}



def read_run(run_name, base_dir):
    # Alleen mappen zoals output_sc1, output_sc2, output_sc12, etc.
    scenario_dirs = sorted(
        [p for p in base_dir.iterdir() if p.is_dir() and re.fullmatch(r"output_sc\d+", p.name)],
        key=lambda p: int(re.search(r"\d+$", p.name).group())
    )

    all_rows = []

    for scenario_dir in scenario_dirs:
        print(f"[{run_name}] {scenario_dir.name}")
        html_files = list(scenario_dir.rglob("*.html"))

        for html_file in html_files:
            found_valid_table = False

            try:
                tables = pd.read_html(html_file)

                for table in tables:
                    # Maak kolomnamen robuust plat, omdat de HTML vaak dubbele headers heeft
                    if isinstance(table.columns, pd.MultiIndex):
                        clean_columns = []
                        for col in table.columns:
                            candidates = [str(c).strip() for c in col]
                            candidates = [
                                c for c in candidates
                                if c and not c.startswith("Unnamed") and c != "nan"
                            ]
                            clean_columns.append(candidates[-1] if candidates else "")
                        table.columns = clean_columns
                    else:
                        table.columns = [str(c).strip() for c in table.columns]

                    table.columns = [str(c).strip() for c in table.columns]

                    if {"origin", "totaldelay"}.issubset(table.columns):
                        found_valid_table = True
                        df = table.copy()

                        df["run"] = run_name
                        df["scenario"] = scenario_dir.name
                        df["source_file"] = str(html_file)
                        df["totaldelay"] = pd.to_numeric(df["totaldelay"], errors="coerce")

                        all_rows.append(df)

                if not found_valid_table:
                    print(f"Geen geldige tabel met origin en totaldelay gevonden in: {html_file.name}")

            except Exception as e:
                print(f"Kon bestand niet lezen: {html_file}")
                print(f"Foutmelding: {e}")

    if not all_rows:
        raise ValueError(
            f"Geen bruikbare tabellen gevonden voor {run_name}. Controleer of de HTML-tabellen "
            "kolommen 'origin' en 'totaldelay' bevatten."
        )

    return pd.concat(all_rows, ignore_index=True)


# Lees beide runs in
combined_df = pd.concat(
    [read_run(run_name, base_dir) for run_name, base_dir in BASE_DIRS.items()],
    ignore_index=True
)

# Samenvatting per run
summary_per_run = (
    combined_df
    .groupby("run")
    .apply(lambda g: pd.Series({
        "n_all": g["totaldelay"].count(),
        "mean_totaldelay_all": g["totaldelay"].mean(),
        "n_ebbr": (g["origin"] == "EBBR").sum(),
        "mean_totaldelay_ebbr": g.loc[g["origin"] == "EBBR", "totaldelay"].mean(),
        "n_non_ebbr": (g["origin"] != "EBBR").sum(),
        "mean_totaldelay_non_ebbr": g.loc[g["origin"] != "EBBR", "totaldelay"].mean(),
    }), include_groups=False)
    .reset_index()
)

print("\n=== Summary per run ===")
print(summary_per_run)

# Samenvatting per scenario per run
summary_per_scenario = (
    combined_df
    .groupby(["run", "scenario"])
    .apply(lambda g: pd.Series({
        "n_all": g["totaldelay"].count(),
        "mean_totaldelay_all": g["totaldelay"].mean(),
        "n_ebbr": (g["origin"] == "EBBR").sum(),
        "mean_totaldelay_ebbr": g.loc[g["origin"] == "EBBR", "totaldelay"].mean(),
        "n_non_ebbr": (g["origin"] != "EBBR").sum(),
        "mean_totaldelay_non_ebbr": g.loc[g["origin"] != "EBBR", "totaldelay"].mean(),
    }), include_groups=False)
    .reset_index()
)

# Zorg dat output_sc2 niet na output_sc12 komt in de print
summary_per_scenario["scenario_number"] = summary_per_scenario["scenario"].str.extract(r"(\d+)$").astype(int)
summary_per_scenario = summary_per_scenario.sort_values(["run", "scenario_number"]).drop(columns="scenario_number")

print("\n=== Summary per scenario ===")
print(summary_per_scenario)

# Vergelijking tussen de twee runs, per scenario
comparison_per_scenario = summary_per_scenario.pivot(
    index="scenario",
    columns="run",
    values=[
        "mean_totaldelay_all",
        "mean_totaldelay_ebbr",
        "mean_totaldelay_non_ebbr",
    ]
)

print("\n=== Comparison per scenario ===")
print(comparison_per_scenario)

# Optioneel opslaan
# summary_per_run.to_csv("totaldelay_summary_per_run.csv", index=False)
# summary_per_scenario.to_csv("totaldelay_summary_per_scenario.csv", index=False)
# comparison_per_scenario.to_csv("totaldelay_comparison_per_scenario.csv")
# combined_df.to_csv("all_flights_from_html.csv", index=False)

# ------------------------------------------------------------
# Boxplot: comparison between runs based on scenario means
# ------------------------------------------------------------
plot_df = summary_per_scenario.rename(columns={
    "mean_totaldelay_all": "Total mean delay [s]",
    "mean_totaldelay_ebbr": "Brussels mean delay [s]",
    "mean_totaldelay_non_ebbr": "Non-Brussels mean delay [s]",
})

metrics = [
    "Total mean delay [s]",
    "Brussels mean delay [s]",
    "Non-Brussels mean delay [s]",
]

run_order = ["FCFS14", "FCFS20", "BOL20"]
run_labels = {
    "FCFS14": "FCFS14",
    "FCFS20": "FCFS20",
    "BOL20": "BOL20",
}


def split_label_and_unit(label: str) -> tuple[str, str]:
    """Split 'Mean delay [s]' into ('Mean delay', 's')."""
    match = re.match(r"^(.*?)\s*\[([^\]]+)\]\s*$", str(label))
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return str(label), "Value"


# Same visual style as the main statistics plots:
# - one figure
# - one subplot per metric
# - independent y-axis per metric
# - legend fixed on the left
n_metrics = len(metrics)
n_runs = len(run_order)

cmap = plt.get_cmap("tab10")
run_colors = {run: cmap(i % 10) for i, run in enumerate(run_order)}

legend_labels = [run_labels[run] for run in run_order]
max_legend_label_len = max([len(label) for label in legend_labels] + [len("Configuration")])
legend_area_in = min(2.15, max(1.25, 0.055 * max_legend_label_len + 0.85))

fig_w = max(7.0, 2.15 * n_metrics + 2.6 + 0.40 * legend_area_in)
fig_h = 3.35

legend_width = legend_area_in / fig_w
plot_left = min(0.34, legend_width + 0.035)

fig, axes = plt.subplots(
    nrows=1,
    ncols=n_metrics,
    figsize=(fig_w, fig_h),
    sharey=False,
    squeeze=False,
)
axes = axes.ravel()

if n_runs > 1:
    offset_span = 0.24
    offsets = list(pd.Series(range(n_runs)).map(lambda i: -offset_span + i * (2 * offset_span / (n_runs - 1))))
else:
    offsets = [0.0]

box_w = 0.22
x_margin = 0.58

for ax, metric in zip(axes, metrics):
    all_vals_for_ylim = []

    for j, run in enumerate(run_order):
        values = plot_df.loc[plot_df["run"] == run, metric].dropna()
        if values.empty:
            continue

        color = run_colors[run]
        all_vals_for_ylim.append(values.to_numpy())

        bp = ax.boxplot(
            [values.to_numpy()],
            positions=[offsets[j]],
            vert=True,
            widths=box_w,
            showmeans=True,
            manage_ticks=False,
            patch_artist=True,
            flierprops=dict(marker="o", markersize=2.5, markeredgewidth=0.4),
            meanprops=dict(marker="D", markersize=3.5, markeredgewidth=0.6),
        )

        for patch in bp["boxes"]:
            patch.set_facecolor(color)
            patch.set_alpha(0.5)
            patch.set_edgecolor(color)

        for median in bp["medians"]:
            median.set_color(color)
            median.set_linewidth(1.1)

        for whisker in bp["whiskers"]:
            whisker.set_color(color)

        for cap in bp["caps"]:
            cap.set_color(color)

        for flier in bp["fliers"]:
            flier.set_markerfacecolor(color)
            flier.set_markeredgecolor(color)
            flier.set_alpha(0.7)

        for mean in bp["means"]:
            mean.set_markerfacecolor(color)
            mean.set_markeredgecolor(color)

    label, unit = split_label_and_unit(metric)

    ax.set_xticks([0])
    ax.set_xticklabels([label], rotation=0, ha="center")
    ax.set_xlim(-x_margin, x_margin)
    ax.grid(axis="y", linewidth=0.4, alpha=0.35)
    ax.set_ylabel(
        unit,
        rotation=0,
        ha="right",
        va="center",
        labelpad=30,
    )
    ax.yaxis.set_label_coords(-0.25 if n_metrics > 1 else -0.18, 0.5)

    if all_vals_for_ylim:
        all_vals = pd.Series([v for arr in all_vals_for_ylim for v in arr]).dropna().to_numpy()
        ymin = all_vals.min()
        ymax = all_vals.max()

        if ymin == ymax:
            margin = 1.0 if ymin == 0 else abs(ymin) * 0.1
        else:
            margin = 0.08 * (ymax - ymin)

        ax.set_ylim(ymin - margin, ymax + margin)

from matplotlib.patches import Patch

handles = [
    Patch(
        facecolor=run_colors[run],
        edgecolor=run_colors[run],
        alpha=0.5,
        label=run_labels[run],
    )
    for run in run_order
]

legend_x = max(0.01, plot_left - legend_width - 0.012)
fig.legend(
    handles=handles,
    title="Configuration",
    loc="center left",
    bbox_to_anchor=(legend_x, 0.56),
    fontsize=8,
    title_fontsize=9,
    framealpha=0.9,
)

fig.subplots_adjust(
    left=plot_left,
    right=0.985,
    bottom=0.22,
    top=0.96,
    wspace=0.70 if n_metrics > 1 else 0.35,
)

fig.savefig("totaldelay_boxplot.png", dpi=300, bbox_inches="tight", pad_inches=0.04)
plt.show()