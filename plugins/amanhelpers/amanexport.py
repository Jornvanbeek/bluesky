
from bluesky import core, stack, traf, sim, HOLD, net
from bluesky.core import plugin
import pandas as pd
import time
import os
import numpy as np

from datetime import timedelta
import matplotlib.pyplot as plt
import numpy as np

class AmanExporter():

    @stack.command
    def totwohtml(self):

        if self.aman_parent_id:
            return

        # Split Flights into two subsets based on runway
        Flights_hhmmss = self.Flights.copy()
        Flights_hhmmss.rename(columns={'runway': 'rwy'}, inplace=True)
        # Flights_hhmmss.rename(columns={'TMA flighttime': 'TMA'}, inplace=True)
        if 'rwy' in Flights_hhmmss.columns:

            s = Flights_hhmmss['rwy'].astype('string')
            s = s.str.strip()
            s = s.str.replace(r'^RWY', '', regex=True)
            Flights_hhmmss['rwy'] = s

        # Convert specified columns to integers
        columns_to_convert = ['ttlg', 'to eto', 'TMA', 'manualslot']
        for col in columns_to_convert:
            if col in Flights_hhmmss.columns:
                Flights_hhmmss[col] = (
                    pd.to_numeric(Flights_hhmmss[col], errors='coerce')  # strings -> NaN
                    .fillna(0)  # NaN -> 0
                    .astype(int)  # float -> int
                )

        # Transform specified columns to HH:MM:SS
        columns_to_transform = ['ETA','delayed ETA', 'ETO IAF', 'ETO_original', 'TP IAF', 'TP ETA', 'EAT', 'slot','initialslot', 'LAS', 'FIR entry',
                                'creation', 'SID', 'planning', 'ETD']
        for col in columns_to_transform:
            if col in Flights_hhmmss.columns:
                Flights_hhmmss[col] = Flights_hhmmss[col].apply(
                    lambda x: None if pd.isna(x) else f"{int(x // 3600):02}:{int((x % 3600) // 60):02}:{int(x % 60):02}"
                )

        # Split data into one table per runway (dynamic)
        runways = (
            Flights_hhmmss['rwy'].dropna().astype('string').str.strip().unique().tolist()
            if 'rwy' in Flights_hhmmss.columns else []
        )
        # Keep a stable order for readability
        runways = sorted([r for r in runways if r and r.lower() != 'nan'])

        runway_tables = []
        for rwy in runways:
            df_rwy = Flights_hhmmss[Flights_hhmmss['rwy'] == rwy]
            html_rwy = df_rwy.to_html(classes='table table-bordered', index=True)
            runway_tables.append((rwy, html_rwy))

        # Fallback if runway column missing or empty
        if not runway_tables:
            runway_tables = [("ALL", Flights_hhmmss.to_html(classes='table table-bordered', index=True))]

        # After creating html_RWY27 / html_RWY18C
        sim_sec = int(sim.simt)
        sim_hhmmss = f"{sim_sec // 3600:02d}:{(sim_sec % 3600) // 60:02d}:{sim_sec % 60:02d}"

        # Updated HTML layout with CSS to avoid compression and enable scrolling
        html_with_style = f"""
            <html>
            <head>
            <style>
                .container {{
                    display: flex;
                    gap: 10px;
                    flex-wrap: nowrap;
                    overflow-x: auto; /* Allow scrolling for the container if content overflows */
                }}
                .table-container {{
                    flex: 0 0 auto;  /* Prevent container from compressing */
                    overflow-x: auto; /* Enable horizontal scrolling for each table container */
                }}
                .table {{
                    border-collapse: collapse;
                    font-size: 12px;
                    white-space: nowrap; /* Prevent cell content from wrapping */
                }}
                .table th {{
                    position: sticky;
                    top: 0;
                    background: #f1f1f1;
                }}
                .table th, .table td {{
                    border: 1px solid black;
                    padding: 4px;
                    text-align: left;
                }}
            </style>
            </head>
            <body>
            <div class="container">
                {''.join([
                    f"""
                    <div class=\"table-container\">
                        <h3>Runway RWY{rwy}  simtime: {sim_hhmmss}, elapsedtime: {timedelta(seconds=int(time.time() - self.starttime))}</h3>
                        {html}
                    </div>
                    """
                    for rwy, html in runway_tables
                ])}
            </div>
            </body>
            </html>
            """
        scen = stack.get_scenname()
        if not self.html_outputname:
            seed = np.random.get_state()[1][0]
            fh = int(self.freezehorizon/60)
            planner = self.popup_planner
            if self.error_multiplicator != (1.0,1.0,1.0,1.0):
                mult = f'{int(self.error_multiplicator[0])}_{int(self.error_multiplicator[1])}_{int(self.error_multiplicator[2])}_{int(self.error_multiplicator[3])}'
                output_path = f"MC_AMAN_DF/{planner}{fh}{mult}/output_{scen}/{seed}.html"
            else:

                output_path = f"MC_AMAN_DF/{planner}{fh}/output_{scen}/{seed}.html"
        else:
            output_path = f"AMAN_DF/output_{scen}.html"

        # Ensure output directory exists
        outdir = os.path.dirname(output_path)
        if outdir:
            os.makedirs(outdir, exist_ok=True)
        # Write the HTML output to a file
        with open(output_path, "w") as f:
            f.write(html_with_style)

        # Automatically open in the browser
        # webbrowser.open(f"file://{os.path.abspath(output_path)}")

    @core.timed_function(dt=10)
    def autohtmlflights(self):
        if self.aman_parent_id:
            return
        if not sim.ffmode:
            # self.htmlflights()
            self.totwohtml()

    @core.timed_function(dt=100)  # is approx every 10 sec in ff mode
    def autohtmlflightsff(self):
        # self.time = time.time()
        # if self.previoustime - self.time < 60:
        if self.aman_parent_id:
            return
        if sim.ffmode and traf.ntraf > 0:
            # self.htmlflights()
            self.totwohtml()



    @stack.command
    def storeflights(self):
        if self.aman_parent_id:
            return
        if traf.traf_parent_id and self.aman_parent_id is None:
            self.aman_parent_id = traf.traf_parent_id
            return
        # self.printflights()
        # self.pickleflights()
        # self.Flights.to_csv('dataframe.txt', sep=',', index=True)

    @stack.command
    def pickleflights(self):
        if self.aman_parent_id:
            return
        scen = stack.get_scenname()
        # self.Flights.to_pickle(f'AMAN_DF/flights_{scen}.pkl')
        # Flights = pd.read_pickle('flights.pkl')


    @stack.command
    def printflights(self, key=None):
        if self.aman_parent_id:
            return
        if key is None:
            # Print the entire DataFrame
            print(self.Flights)
        else:
            # Check if the key is a valid column in the DataFrame
            if key in self.Flights.columns:
                print(self.Flights[key])



    def results(self):
        df = self.Flights
        if df is None or df.empty:
            return {'n_acids': 0}

        # veilige numerieke Series

        # --- Settings (try instance attrs first, then aman_settings module) ---
        def _get_setting(attr: str):
            v = getattr(self, attr, None)
            if v is not None:
                return v
            try:
                import aman_settings  # project-level settings module
                return getattr(aman_settings, attr, None)
            except Exception:
                return None

        setting_freezehorizon = _get_setting('freezehorizon')
        setting_popup_planner = _get_setting('popup_planner')
        setting_error_multiplicator = _get_setting('error_multiplicator')
        setting_capacity = _get_setting('capacity')
        def get_num(col: str) -> pd.Series:
            """Return numeric Series for df[col] if present, else all-NaN Series with df.index."""
            if col in df.columns:
                return pd.to_numeric(df[col], errors='coerce')
            return pd.Series(np.nan, index=df.index)

        def get_num_any(cols: list[str]) -> pd.Series:
            """Return numeric Series for the first column that exists in df, else all-NaN Series."""
            for c in cols:
                if c in df.columns:
                    return pd.to_numeric(df[c], errors='coerce')
            return pd.Series(np.nan, index=df.index)

        def _mean_nonzero(s: pd.Series) -> float:
            if s is None or len(s) == 0:
                return np.nan
            m = s.notna() & (s != 0)
            return float(s[m].mean(skipna=True)) if m.any() else np.nan

        def _count_nonzero(s: pd.Series) -> int:
            if s is None or len(s) == 0:
                return 0
            return int(((s.notna()) & (s != 0)).sum())

        def _count_notna(s: pd.Series) -> int:
            if s is None or len(s) == 0:
                return 0
            return int(s.notna().sum())

        def _min(s: pd.Series) -> float:
            return float(s.min(skipna=True))

        def _max(s: pd.Series) -> float:
            return float(s.max(skipna=True))

        def _mean(s: pd.Series) -> float:
            return float(s.mean(skipna=True))

        def _mean_abs(s: pd.Series) -> float:
            return float(s.abs().mean(skipna=True))

        def _median(s: pd.Series) -> float:
            return float(s.median(skipna=True))

        s_eat = get_num('EAT adherence')
        s_cnt = get_num('count')
        s_eto = get_num('E_TO')
        s_tpa = get_num('TP accuracy')
        s_frz = get_num('Error at Freeze')
        s_mw = get_num('minwork')
        s_tw = get_num('totalwork')
        s_xw = get_num('extrawork')
        s_ptime = get_num('percentile_time')

        # ATC / instruction bookkeeping (optional columns)
        # "short adjacent" may have different column names and may only be created once nonzero values exist
        s_short_adj = get_num_any(['short adjacent', 'short_adjacent', 'short_adj', 'adjacent'])
        # Delay-adjacent (optional column; different names may exist)
        s_delay_adj = get_num_any(['delay adjacent', 'delay_adjacent', 'delay_adj', 'delay adjacent count'])
        s_totaldelay = get_num('totaldelay')
        s_totalspeedup = get_num('totalspeedup')
        s_short_speed = get_num('short speed')
        s_delay_speed = get_num('delay speed')
        s_delay_mach = get_num('delay mach')
        s_delay_dogleg = get_num('delay dogleg')
        s_short_dogleg = get_num('short dogleg')
        # Holding time (seconds) (optional)
        s_holdingtime = get_num('holdingtime')

        # --- Low-level delay absorption (LLDA) ---
        # LLDA = delay dogleg + holding delay (if available)
        s_holding_delay = get_num_any(['delay holding', 'holding_delay', 'holding delay'])

        # If no explicit holding-delay column exists, treat it as 0 (can't sum holding in seconds from a bool)
        if s_holding_delay.isna().all():
            s_holding_delay = pd.Series(0.0, index=df.index)

        s_llda = s_delay_dogleg.fillna(0.0) + s_holding_delay.fillna(0.0)

        # --- Instruction counts: mach / adjacent ---
        has_mach_instr = (s_delay_mach.notna()) & (s_delay_mach != 0)
        has_adj_del = (s_delay_adj.notna()) & (s_delay_adj != 0)
        has_adj_sh  = (s_short_adj.notna()) & (s_short_adj != 0)
        has_adj_instr = has_adj_sh | has_adj_sh
        has_mach_or_adj = has_mach_instr | has_adj_instr

        # Slot changes
        s_slot = get_num('slot')
        s_islot = get_num('initialslot')
        slot_diff = (s_slot - s_islot)
        slot_absdiff = slot_diff.abs()
        slot_absdiff_nz = slot_absdiff[(slot_absdiff > 0) & slot_absdiff.notna()]

        # Swaps
        s_swaps = get_num('swaps')
        # EAT_updates
        s_eat_updates = get_num('EAT_updates')
        # TTLG at freeze
        s_ttlg_freeze = get_num('ttlg at freeze')

        # FH margin at freeze (optional column; multiple possible names)
        s_fh_margin_freeze = get_num('fh_margin_at_freeze')

        # --- Extrawork percentage (system-level) ---
        # Instead of averaging per-flight percentages, compute the ratio of sums:
        # pct = sum(extrawork) / sum(totalwork) * 100
        sum_tw = float(s_tw.fillna(0).sum())
        sum_xw = float(s_xw.fillna(0).sum())
        pct_xw_system = (sum_xw / sum_tw) * 100.0 if sum_tw > 0 else np.nan

        # popup masks (optional column)
        popup_col = df.get('popup')
        is_popup = (popup_col.astype('string').str.upper() == 'POPUP') if popup_col is not None else pd.Series(False, index=df.index)
        is_nonpopup = ~is_popup

        # Also compute the same ratio-of-sums for popup / non-popup subsets (if available)
        sum_tw_popup = float(s_tw[is_popup].fillna(0).sum()) if 'is_popup' in locals() else 0.0
        sum_xw_popup = float(s_xw[is_popup].fillna(0).sum()) if 'is_popup' in locals() else 0.0
        pct_xw_system_popup = (sum_xw_popup / sum_tw_popup) * 100.0 if sum_tw_popup > 0 else np.nan

        sum_tw_nonpopup = float(s_tw[is_nonpopup].fillna(0).sum()) if 'is_nonpopup' in locals() else 0.0
        sum_xw_nonpopup = float(s_xw[is_nonpopup].fillna(0).sum()) if 'is_nonpopup' in locals() else 0.0
        pct_xw_system_nonpopup = (sum_xw_nonpopup / sum_tw_nonpopup) * 100.0 if sum_tw_nonpopup > 0 else np.nan



        holding_col = df.get('holding')
        if holding_col is None:
            is_holding = pd.Series(False, index=df.index)
            hold_events_total = 0.0
        else:
            # If 'holding' is used as a counter (numeric), sum it as number of hold events.
            # Otherwise (bool/object), treat True as 1 event.
            holding_num = pd.to_numeric(holding_col, errors='coerce')
            if holding_num.notna().any() and (holding_num.fillna(0) > 1).any():
                hold_events_total = float(holding_num.fillna(0).sum())
                is_holding = (holding_num.fillna(0) > 0)
            else:
                holding_bool = holding_col.astype('boolean').fillna(False)
                hold_events_total = float(holding_bool.sum())
                is_holding = holding_bool

        # count stats split by popup / holding
        s_cnt_popup = s_cnt[is_popup] if is_popup is not None else pd.Series(np.nan, index=df.index)
        s_cnt_holding = s_cnt[is_holding] if is_holding is not None else pd.Series(np.nan, index=df.index)

        # counts
        max_count = s_cnt.max(skipna=True)
        uniq = np.sort(s_cnt.dropna().unique())
        second_highest = uniq[-2] if uniq.size >= 2 else (uniq[-1] if uniq.size == 1 else np.nan)
        max_count_acid = s_cnt.idxmax() if s_cnt.notna().any() else None

        holdingtime_valid = s_holdingtime[s_holdingtime.notna()]
        holdingtime_min = float(holdingtime_valid.min()) if holdingtime_valid.size else np.nan
        holdingtime_mean = float(holdingtime_valid.mean()) if holdingtime_valid.size else np.nan
        holdingtime_max = float(holdingtime_valid.max()) if holdingtime_valid.size else np.nan
        holdingtime_total = float(holdingtime_valid.sum()) if holdingtime_valid.size else 0.0

        total_count = float(s_cnt.fillna(0).sum())

        has_dogleg_instr = ((s_delay_dogleg.notna()) & (s_delay_dogleg != 0))
        count_flights_with_dogleg = int(has_dogleg_instr.sum())

        return {
            # --- Top: extrawork percentage ---
            'pct_extrawork': float(pct_xw_system),

            # --- Scenario / AMAN settings snapshot ---
            'freezehorizon': float(setting_freezehorizon) if setting_freezehorizon is not None else None,
            'popup_planner': str(setting_popup_planner) if setting_popup_planner is not None else None,
            'error_multiplicator': tuple(setting_error_multiplicator) if setting_error_multiplicator is not None else None,
            'capacity': float(setting_capacity) if setting_capacity is not None else None,

            # --- Count stats (plus mean nonzero) ---
            'pct_count_eq_0': float((s_cnt.fillna(0) == 0).mean() * 100.0),
            'mean_count': _mean(s_cnt),
            'mean_count_nonzero': _mean_nonzero(s_cnt),
            'max_count': float(max_count) if pd.notna(max_count) else np.nan,
            'second_highest_count': float(second_highest) if pd.notna(second_highest) else np.nan,
            'max_count_acid': str(max_count_acid) if max_count_acid is not None else None,
            'total_count': float(total_count),

            # Holding event count + holdingtime
            'count_hold_events': float(hold_events_total),
            'min_holdingtime': float(holdingtime_min) if pd.notna(holdingtime_min) else np.nan,
            'mean_holdingtime': float(holdingtime_mean) if pd.notna(holdingtime_mean) else np.nan,
            'max_holdingtime': float(holdingtime_max) if pd.notna(holdingtime_max) else np.nan,
            'total_holdingtime': float(holdingtime_total),

            # --- Popup count per scenario ---
            'count_popup': int(is_popup.fillna(False).sum()) if is_popup is not None else 0,

            # --- FH margin at freeze ---
            'count_fh_margin_at_freeze': _count_notna(s_fh_margin_freeze),
            'min_fh_margin_at_freeze': _min(s_fh_margin_freeze) if s_fh_margin_freeze.notna().any() else np.nan,
            'mean_fh_margin_at_freeze': _mean(s_fh_margin_freeze),
            'max_fh_margin_at_freeze': _max(s_fh_margin_freeze) if s_fh_margin_freeze.notna().any() else np.nan,

            # --- EAT_updates stats ---
            'min_EAT_updates': _min(s_eat_updates) if s_eat_updates.notna().any() else np.nan,
            'max_EAT_updates': _max(s_eat_updates) if s_eat_updates.notna().any() else np.nan,
            'total_EAT_updates': float(s_eat_updates.fillna(0).sum()),

            # --- Swaps stats (plus sums) ---
            'min_swaps': _min(s_swaps) if s_swaps.notna().any() else np.nan,
            'mean_swaps': _mean(s_swaps),
            'max_swaps': _max(s_swaps) if s_swaps.notna().any() else np.nan,
            'mean_swaps_nonzero': _mean_nonzero(s_swaps),
            'amount_of_swaps': float(s_swaps.fillna(0).sum()),

            # --- TTLG at freeze ---
            'min_ttlg_at_freeze': _min(s_ttlg_freeze) if s_ttlg_freeze.notna().any() else np.nan,
            'mean_ttlg_at_freeze': _mean(s_ttlg_freeze),
            'median_ttlg_at_freeze': _median(s_ttlg_freeze),
            'max_ttlg_at_freeze': _max(s_ttlg_freeze) if s_ttlg_freeze.notna().any() else np.nan,
            'mean_abs_ttlg_at_freeze': _mean_abs(s_ttlg_freeze),

            # --- E_TO (as before) ---
            'mean_E_TO': _mean(s_eto),
            'mean_abs_E_TO': _mean_abs(s_eto),
            'min_E_TO': _min(s_eto) if s_eto.notna().any() else np.nan,
            'max_E_TO': _max(s_eto) if s_eto.notna().any() else np.nan,

            # --- Delay / speedup / short-adjacent / delay-mach instruction statistics ---
            # totaldelay: mean, max, mean(nonzero)
            'mean_totaldelay': _mean(s_totaldelay),
            'max_totaldelay': _max(s_totaldelay) if s_totaldelay.notna().any() else np.nan,
            'mean_totaldelay_nonzero': _mean_nonzero(s_totaldelay),

            # totalspeedup: min, mean, mean(nonzero)
            'min_totalspeedup': _min(s_totalspeedup) if s_totalspeedup.notna().any() else np.nan,
            'mean_totalspeedup': _mean(s_totalspeedup),
            'mean_totalspeedup_nonzero': _mean_nonzero(s_totalspeedup),

            # --- LLDA stats ---
            'mean_LLDA': _mean(s_llda),
            'max_LLDA': _max(s_llda) if s_llda.notna().any() else np.nan,
            'mean_LLDA_nonzero': _mean_nonzero(s_llda),
            'count_LLDA_nonzero': _count_nonzero(s_llda),

            # --- Instruction presence counts (per flight) ---
            'count_flights_with_mach_instr': int(has_mach_instr.sum()),
            'count_flights_with_adjacent_instr': int(has_adj_instr.sum()),
            'count_flights_with_mach_or_adj_instr': int(has_mach_or_adj.sum()),
            'count_flights_with_dogleg_instr': int(count_flights_with_dogleg),

            # short-adjacent: min, mean, mean(nonzero) and total count
            # "short adjacent" may have different column names and may only be created once nonzero values exist
            'min_short_adjacent': _min(s_short_adj) if s_short_adj.notna().any() else np.nan,
            'mean_short_adjacent': _mean(s_short_adj),
            'mean_short_adjacent_nonzero': _mean_nonzero(s_short_adj),
            'count_short_adjacent_nonzero': _count_nonzero(s_short_adj),

            # delay-adjacent stats
            'min_delay_adjacent': _min(s_delay_adj) if s_delay_adj.notna().any() else np.nan,
            'mean_delay_adjacent': _mean(s_delay_adj),
            'mean_delay_adjacent_nonzero': _mean_nonzero(s_delay_adj),
            'count_delay_adjacent_nonzero': _count_nonzero(s_delay_adj),

            # delay mach: min, mean, mean(nonzero) and total count
            'min_delay_mach': _min(s_delay_mach) if s_delay_mach.notna().any() else np.nan,
            'mean_delay_mach': _mean(s_delay_mach),
            'mean_delay_mach_nonzero': _mean_nonzero(s_delay_mach),
            'count_delay_mach_nonzero': _count_nonzero(s_delay_mach),

            # keep some additional instruction fields (useful for analysis)
            'mean_short_speed': _mean(s_short_speed),
            'mean_delay_speed': _mean(s_delay_speed),
            'mean_delay_dogleg': _mean(s_delay_dogleg),
            'mean_short_dogleg': _mean(s_short_dogleg),

            # --- EAT adherence ---
            'mean_abs_eat_adherence': float(s_eat.abs().mean(skipna=True)),
            'max_abs_eat_adherence': float(s_eat.abs().max(skipna=True)),

            # --- TP accuracy ---
            'mean_TP_accuracy': float(s_tpa.mean(skipna=True)),
            'max_abs_TP_accuracy': float(s_tpa.abs().max(skipna=True)),

            # --- Time error at freeze (existing field) ---
            'mean_time_error_at_freeze': float(s_frz.mean(skipna=True)),
            'max_time_error_at_freeze': float(s_frz.max(skipna=True)),
            'min_time_error_at_freeze': float(s_frz.min(skipna=True)),
            'mean_abs_time_error_at_freeze': float(s_frz.abs().mean(skipna=True)),

            # --- Work / popup splits ---
            'pct_extrawork_popup': float(pct_xw_system_popup),
            'pct_extrawork_nonpopup': float(pct_xw_system_nonpopup),
            'mean_minwork': float(s_mw.mean(skipna=True)),
            'mean_totalwork': float(s_tw.mean(skipna=True)),
            'mean_extrawork': float(s_xw.mean(skipna=True)),

            # --- Percentile time ---
            'mean_percentile_time': float(s_ptime.mean(skipna=True)),

            # --- Slot change statistics ---
            'mean_slot_minus_initialslot': float(slot_diff.mean(skipna=True)),
            'mean_abs_slot_minus_initialslot_nonzero': float(slot_absdiff_nz.mean(skipna=True)) if slot_absdiff_nz.size else np.nan,

            # --- Size / reproducibility ---
            'n_acids': int(len(df)),
            'error_seed': int(np.random.get_state()[1][0]),
        }


    @stack.command
    def sendresult(self):

        result = self.results()

        sender = stack.sender()
        net.send('MONTECARLORESULTS',result, sender)

    @stack.command
    def etarateplot(self, data, step_min: int = 1, window_min: int = 15):
        """
        Plot moving-average arrival rate (ac/hr) over the scenario up to current sim time.
        - ETA <= sim.simt
        - x-axis in minutes since t0
        """
        # simt = float(sim.simt) if hasattr(sim, 'simt') else None
        simt = None
        # # only ETAs up to current sim time
        # eta = pd.to_numeric(df['ETA'], errors='coerce')
        # eta = eta[(eta.notna()) & (eta <= simt)].values

        # Extract ETA array
        if isinstance(data, pd.DataFrame):
            df = data
            if df is None or df.empty or 'ETA' not in df.columns:
                print("etarateplot: no Flights/ETA available")
                df = getattr(self, 'Flights', None)
                if df is None or df.empty or 'ETA' not in df.columns:
                    return
            eta = pd.to_numeric(df['ETA'], errors='coerce').values
        else:
            # list/array/Series
            eta = pd.to_numeric(pd.Series(list(data)), errors='coerce').values

        eta = eta[np.isfinite(eta)]
        if eta.size == 0:
            print("etarateplot: no valid ETA values")
            return

        # pick a safe plotting horizon
        max_eta = float(np.nanmax(eta))
        if max_eta > 24*3600:
            max_eta = 500*60
        if simt is None or (not np.isfinite(simt)) or simt <= 0:
            simt_plot = max_eta
        else:
            simt_plot = min(float(simt), max_eta)

        # only ETAs up to horizon
        eta = eta[eta <= simt_plot]
        if eta.size == 0:
            print("etarateplot: no valid ETA values before simt")
            return

        # --- robust binning on fixed axis from t0..simt ---
        step_min_i = int(step_min)
        window_min_i = int(window_min)
        if step_min_i <= 0 or window_min_i <= 0:
            print("etarateplot: step_min and window_min must be > 0")
            return

        step_s = step_min_i * 60.0

        # bin edges from 0 to simt_plot
        edges = np.arange(0.0, float(simt_plot) + step_s, step_s)
        # counts per bin
        bin_idx = np.searchsorted(edges, eta, side="right") - 1
        bin_idx = bin_idx[(bin_idx >= 0) & (bin_idx < len(edges) - 1)]
        binned_vals = np.bincount(bin_idx, minlength=len(edges) - 1).astype(float)

        # index as Timedelta for convenient x-axis
        binned = pd.Series(
            binned_vals,
            index=pd.to_timedelta(edges[:-1], unit="s")
        )

        # rolling window in bins
        win_bins = max(1, int(round((window_min_i * 60.0) / step_s)))
        rolling = binned.rolling(win_bins, min_periods=1).sum()

        # convert to ac/hr
        rate = rolling * (60.0 / float(window_min_i))

        # x-axis in minutes since t0
        x_min = edges[:-1] / 60.0

        # plot
        plt.figure()
        ax = plt.gca()

        ax.plot(x_min, rate.values)
        ax.set_xlabel("Time since t0 (minutes)")
        ax.set_ylabel("Arrival rate (ac/hr)")
        ax.set_title(f"ETA-based arrival rate ({window_min_i}-min moving avg)")
        # grid
        ax.grid(True)

        # linker y-as: ticks per 4 ac/hr
        max_rate = float(np.nanmax(rate.values)) if rate.size else 0.0
        yticks_left = np.arange(0, max_rate + 4, 4)
        ax.set_yticks(yticks_left)
        ax.set_ylabel("Arrival rate (ac/hr)")

        # dashed mean line
        mean_rate = float(np.nanmean(rate.values)) if rate.size else 0.0
        ax.axhline(mean_rate, linestyle='--')

        # rechter y-as: arrivals per 15 min (=/4)
        ax2 = ax.twinx()
        yticks_right = yticks_left * (window_min_i / 60.0)  # 15 min -> /4
        ax2.set_yticks(yticks_left)
        ax2.set_yticklabels([f"{int(v)}" for v in yticks_right])
        ax2.set_ylabel(f"Arrivals per {window_min_i} min")

        scen = stack.get_scenname()
        outpath = f"AMAN_DF/etarate_{scen}.png"
        plt.savefig(outpath, dpi=200, bbox_inches="tight")
        plt.close()

        print(f"Saved: {outpath}")

    @stack.command
    def etabinsplot(self, data, bin_min: int = 15):
        """
        Plot arrival counts per bin_min-minute bins (no moving average), up to simt.
        x-axis: minutes since t0.
        """
        # if df is None or df.empty or 'ETA' not in df.columns:
        #     print("etabinsplot: no Flights/ETA available")
        #     return

        # Determine sim horizon
        # simt = float(sim.simt) if hasattr(sim, 'simt') else None
        simt = None
        # Extract ETA array
        if isinstance(data, pd.DataFrame):
            df = data
            if df is None or df.empty or 'ETA' not in df.columns:
                print("etabinsplot: no Flights/ETA available")
                return
            eta = pd.to_numeric(df['ETA'], errors='coerce').values
        else:
            eta = pd.to_numeric(pd.Series(list(data)), errors='coerce').values

        eta = eta[np.isfinite(eta)]
        if eta.size == 0:
            print("etabinsplot: no valid ETA values")
            return

        # pick a safe plotting horizon
        max_eta = float(np.nanmax(eta))
        if max_eta > 24*3600:
            max_eta = 500*60
        if simt is None or (not np.isfinite(simt)) or simt <= 0:
            simt_plot = max_eta
        else:
            simt_plot = min(float(simt), max_eta)

        # Only ETAs up to plot horizon
        eta = eta[eta <= simt_plot]
        if eta.size == 0:
            print("etabinsplot: no valid ETA values before simt")
            return



        bin_min_i = int(bin_min)
        if bin_min_i <= 0:
            print("etabinsplot: bin_min must be > 0")
            return

        bin_s = bin_min_i * 60.0

        # fixed-width bin edges from 0..simt_plot
        edges = np.arange(0.0, float(simt_plot) + bin_s, bin_s)
        bin_idx = np.searchsorted(edges, eta, side="right") - 1
        bin_idx = bin_idx[(bin_idx >= 0) & (bin_idx < len(edges) - 1)]
        counts = np.bincount(bin_idx, minlength=len(edges) - 1).astype(float)

        # x = left edges in minutes (fixed-width bins)
        x_min = edges[:-1] / 60.0

        plt.figure()
        ax = plt.gca()
        ax.bar(x_min, counts, width=(bin_s / 60.0), align='edge')
        ax.set_xlabel("Time since t0 (minutes)")
        ax.set_ylabel(f"Arrivals per {bin_min_i} min")
        ax.set_title(f"ETA arrivals per {bin_min_i}-minute bins")
        ax.grid(True)

        # integer y-ticks, steps of 2 (no half aircraft)
        max_cnt = int(np.nanmax(counts)) if counts.size else 0
        yticks_left = np.arange(0, max_cnt + 2, 2)
        ax.set_yticks(yticks_left)

        # dashed mean line (mean arrivals per bin)
        mean_cnt = float(np.nanmean(counts)) if counts.size else 0.0
        ax.axhline(mean_cnt, linestyle='--')

        # rechter y-as: arrivals per hour
        ax = plt.gca()
        ax2 = ax.twinx()

        # conversie: per bin -> per uur
        factor = 60.0 / float(bin_min_i)
        y_right = yticks_left * factor
        ax2.set_yticks(yticks_left)
        ax2.set_yticklabels([f"{int(v)}" for v in y_right])
        ax2.set_ylabel("Arrivals per hour")

        scen = stack.get_scenname()
        outpath = f"AMAN_DF/etabins_{scen}_{bin_min_i}min.png"
        plt.savefig(outpath, dpi=200, bbox_inches="tight")
        plt.close()

        print(f"Saved: {outpath}")

    # import pickle
    # from plugins.amanhelpers.amanexport import AmanExporter
    # exporter = AmanExporter()
    # exporter.etarateplot(dataframe)
    # exporter.etabinsplot(dataframe)

    # with open('AMAN_DF/flights_5_scenariotest.pkl', 'rb') as f:
    #     dataframe = pickle.load(f)



    @stack.command
    def eta_from_cache(self, minutes: int = 15):
        # if cache:
        from plugins.amanhelpers.amanpredictionhandler import PredictionHandler
        from plugins.shiftflight import shiftflight

        handler = PredictionHandler()
        self.shiftflight = shiftflight()
        preds = handler.open_cache()

        # else:
        #     preds = self.not_spawned

        eta_list = []
        for acid in preds.keys():
            # print(acid)
            for prediction in preds[acid]:
                wpt, wptime, flighttime, estimatedcreatetime, wptpredutc, parent_id, type, origin, work = prediction
                scheduledtime = self.shiftflight.spawntime(acid)

                wptime = scheduledtime + flighttime

                if '/RW' in wpt:
                    # dest, runway = handler.parse_destination(wpt)
                    # data = {'planningstate': 'new', 'TP ETA': wptime, 'runway': runway, 'type': type, 'origin': '',
                    #         'LAf': '', 'count': 0, 'Flighttime': flighttime, 'minwork': work}
                    eta = wptime
                    eta_list.append(wptime)
        print(eta_list)
        print('plotting bins')
        self.etabinsplot(eta_list, bin_min=15)
        print('plotting rate')
        self.etarateplot(eta_list, window_min=15)
        # return eta_list