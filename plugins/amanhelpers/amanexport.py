
from bluesky import core, stack, traf, sim, HOLD, net
from bluesky.core import plugin
import pandas as pd
import time
import numpy as np

from datetime import timedelta


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
        output_path = f"AMAN_DF/output_{scen}.html"

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

    @core.timed_function(dt=10)  # is approx every 10 sec in ff mode
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
        self.pickleflights()
        self.Flights.to_csv('dataframe.txt', sep=',', index=True)

    @stack.command
    def pickleflights(self):
        if self.aman_parent_id:
            return
        scen = stack.get_scenname()
        self.Flights.to_pickle(f'AMAN_DF/flights_{scen}.pkl')
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
        s_eat = pd.to_numeric(df.get('EAT adherence'), errors='coerce')
        s_cnt = pd.to_numeric(df.get('count'), errors='coerce')
        s_eto = pd.to_numeric(df.get('E_TO'), errors='coerce')
        s_tpa = pd.to_numeric(df.get('TP accuracy'), errors='coerce')
        s_frz = pd.to_numeric(df.get('Error at Freeze'), errors='coerce')
        s_mw = pd.to_numeric(df.get('minwork'), errors='coerce')
        s_tw = pd.to_numeric(df.get('totalwork'), errors='coerce')
        s_xw = pd.to_numeric(df.get('extrawork'), errors='coerce')

        denom = s_tw.replace(0, np.nan)
        pct_xw = (s_xw / denom) * 100.0

        # counts
        max_count = s_cnt.max(skipna=True)
        uniq = np.sort(s_cnt.dropna().unique())
        second_highest = uniq[-2] if uniq.size >= 2 else (uniq[-1] if uniq.size == 1 else np.nan)
        max_count_acid = s_cnt.idxmax() if s_cnt.notna().any() else None

        return {
            # EAT adherence
            'mean_abs_eat_adherence': float(s_eat.abs().mean(skipna=True)),
            'max_abs_eat_adherence': float(s_eat.abs().max(skipna=True)),

            # count stats
            'pct_count_eq_0': float((s_cnt.fillna(0) == 0).mean() * 100.0),
            'mean_count': float(s_cnt.mean(skipna=True)),
            'max_count': float(max_count) if pd.notna(max_count) else np.nan,
            'second_highest_count': float(second_highest) if pd.notna(second_highest) else np.nan,
            'max_count_acid': str(max_count_acid) if max_count_acid is not None else None,

            # E_TO
            'mean_E_TO': float(s_eto.mean(skipna=True)),
            'mean_abs_E_TO': float(s_eto.abs().mean(skipna=True)),
            'min_E_TO': float(s_eto.min(skipna=True)),
            'max_E_TO': float(s_eto.max(skipna=True)),

            # TP accuracy
            'mean_TP_accuracy': float(s_tpa.mean(skipna=True)),
            'max_abs_TP_accuracy': float(s_tpa.abs().max(skipna=True)),

            # Time error at freeze
            'mean_time_error_at_freeze': float(s_frz.mean(skipna=True)),
            'max_time_error_at_freeze': float(s_frz.max(skipna=True)),
            'min_time_error_at_freeze': float(s_frz.min(skipna=True)),
            'mean_abs_time_error_at_freeze': float(s_frz.abs().mean(skipna=True)),

            # work
            'mean_minwork': float(s_mw.mean(skipna=True)),
            'mean_totalwork': float(s_tw.mean(skipna=True)),
            'mean_extrawork': float(s_xw.mean(skipna=True)),
            'mean_pct_extrawork': float(pct_xw.replace([np.inf, -np.inf], np.nan).mean(skipna=True)),

            # size
            'n_acids': int(len(df)),
            'error_seed': int(np.random.get_state()[1][0]),
        }


    @stack.command
    def sendresult(self):

        result = self.results()

        sender = stack.sender()
        net.send('MONTECARLORESULTS',result, sender)