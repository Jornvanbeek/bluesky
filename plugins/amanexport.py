
from bluesky import core, stack, traf, sim, HOLD, net
from bluesky.core import plugin
import pandas as pd
import time
import numpy as np

from datetime import timedelta

def init_plugin():
    config = {
        'plugin_name': 'amanexport',
        'plugin_type': 'sim'
    }
    # Create an instance of the class below so BlueSky recognizes it as a plugin
    atc_plugin = exporter()
    return config

class exporter(core.Entity):
    def __init__(self):
        super().__init__()

        self.aman = plugin.Plugin.plugins['AMANTWO'].imp.AMAN

        # self.aman_parent_id = self.aman.aman_parent_id
        self.starttime = self.aman.starttime

    def reset(self):
        super().reset()
        self.aman = plugin.Plugin.plugins['AMANTWO'].imp.AMAN

        # self.aman_parent_id = self.aman.aman_parent_id
        self.starttime = self.aman.starttime

    @stack.command
    def totwohtml(self):

        if self.aman.aman_parent_id:
            return

        # Split Flights into two subsets based on runway
        Flights_hhmmss = self.aman.Flights.copy()
        Flights_hhmmss.rename(columns={'runway': 'rwy'}, inplace=True)
        # Flights_hhmmss.rename(columns={'TMA flighttime': 'TMA'}, inplace=True)
        if 'rwy' in Flights_hhmmss.columns:
            Flights_hhmmss['rwy'] = Flights_hhmmss['rwy'].str[3:]  # Remove first 3 characters

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
        columns_to_transform = ['ETA', 'ETO IAF', 'ETO_original', 'TP IAF', 'TP ETA', 'EAT', 'slot', 'LAS', 'FIR entry',
                                'creation', 'SID', 'planning']
        for col in columns_to_transform:
            if col in Flights_hhmmss.columns:
                Flights_hhmmss[col] = Flights_hhmmss[col].apply(
                    lambda x: None if pd.isna(x) else f"{int(x // 3600):02}:{int((x % 3600) // 60):02}:{int(x % 60):02}"
                )

        # Split data into RWY27 and RWY18C
        Flights_RWY27 = Flights_hhmmss[Flights_hhmmss['rwy'] == '27']
        Flights_RWY18C = Flights_hhmmss[Flights_hhmmss['rwy'] == '18C']

        # Generate HTML tables for each runway
        html_RWY27 = Flights_RWY27.to_html(classes='table table-bordered', index=True)
        html_RWY18C = Flights_RWY18C.to_html(classes='table table-bordered', index=True)

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
                <div class="table-container">
                    <h3>Runway RWY27  simtime: {sim_hhmmss}, elapsedtime: {timedelta(seconds=int(time.time() - self.starttime))}</h3>
                    {html_RWY27}
                </div>
                <div class="table-container">
                    <h3>Runway RWY18C</h3>
                    {html_RWY18C}
                </div>
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
        if self.aman.aman_parent_id:
            return
        if not sim.ffmode:
            # self.htmlflights()
            self.totwohtml()

    @core.timed_function(dt=10)  # is approx every 10 sec in ff mode
    def autohtmlflightsff(self):
        # self.time = time.time()
        # if self.previoustime - self.time < 60:
        if self.aman.aman_parent_id:
            return
        if sim.ffmode and traf.ntraf > 0:
            # self.htmlflights()
            self.totwohtml()



    @stack.command
    def storeflights(self):
        if self.aman.aman_parent_id:
            return
        if traf.traf_parent_id and self.aman.aman_parent_id is None:
            self.aman_parent_id = traf.traf_parent_id
            return
        self.printflights()
        self.pickleflights()
        self.aman.Flights.to_csv('dataframe.txt', sep=',', index=True)

    @stack.command
    def pickleflights(self):
        if self.aman.aman_parent_id:
            return
        scen = stack.get_scenname()
        self.aman.Flights.to_pickle(f'AMAN_DF/flights_{scen}.pkl')
        # Flights = pd.read_pickle('flights.pkl')


    @stack.command
    def printflights(self, key=None):
        if self.aman.aman_parent_id:
            return
        if key is None:
            # Print the entire DataFrame
            print(self.aman.Flights)
        else:
            # Check if the key is a valid column in the DataFrame
            if key in self.aman.Flights.columns:
                print(self.aman.Flights[key])



    def results(self):
        df = self.aman.Flights
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