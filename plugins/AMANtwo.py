"""
The Arrival Manager (AMAN) plugin is designed to efficiently allocate arrival slots for aircraft based on
their estimated times of arrival (ETAs) while ensuring necessary separation times. It dynamically updates
air traffic every 5 seconds around designated areas around airports based on ETAs to anticipate aircraft arrivals.
"""
from logging import currentframe, error

from numpy.ma.core import swapaxes
# from setuptools.dist import sequence

from bluesky import core, stack, traf, navdb, net, network, sim
from bluesky.tools.areafilter import Circle
from bluesky.network.common import GROUPID_SIM
from datetime import datetime

from collections import defaultdict
from plugins.RunwayConfigurations import RunwayConfiguration
from plugins.LIV_separation import LivSeparation
import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 250)
import numpy as np
import random
import pickle
from bluesky.tools.aero import casormach2tas, fpm, kts, ft, g0, Rearth, nm, tas2cas,\
                         vatmos,  vtas2cas, vtas2mach, vcasormach



#from bluesky.ui.palette import initialized
#from plugins.trajectory_predictor_new import total_pred_signals

# AMAN = None
def init_plugin():
    """Initializes the plugin and creates an instance of the ArrivalManager."""
    global AMAN
    AMAN = ArrivalManager()

    # Configuration for the plugin, specifying its name and type.
    config = {
        'plugin_name': 'AMANtwo',
        'plugin_type': 'sim'
    }

    return config



class ArrivalManager(core.Entity):
    """
    Manages arrival logic for the Arrival Manager, assigning arrival slots
    based on the estimated time of arrival at the destination waypoint.

    Attributes:
        acids_allocated (dict): Maps each destination to a dict that maps aircraft IDs to their allocated runway.
        ETAs (dict): Maps each destination to a dict that maps aircraft IDs to their estimated times of arrival.
        arrival_slots (dict): Maps each destination to a dict that maps aircraft IDs to their assigned arrival slots.
        ATAs (dict): Maps each destination to a dict that maps aircraft IDs to their actual times of arrival.
        separation_times (dict): Maps each destination to a dict that maps aircraft IDs to their separation times.
        aircraft_in_database (dict): Maps each airport to a dict that maps aircraft IDs to their designated runways.
        aman_area (dict): Stores the area around an airport where the aman will be initialised.
        acid_to_get_slot (set): Set of aircraft IDs that need to receive an arrival slot.
    """

    def __init__(self):
        super().__init__()

        # Define the column names
        columns = ['ACID', 'planningstate', 'ttlg', 'to eto', 'type', 'LIV', 'ETA', 'ETO IAF', 'ETO_original', 'ETO_act', 'IAF', 'runway', 'EAT', 'slot', 'manualslot', 'TMA flighttime', 'EAT adherence', 'LAS', 'LAf', 'origin', 'crossover', 'instruction', 'AMANstate', 'TPstate','tp_time', 'count', 'Flighttime', 'ETO adherence', 'casdesc', 'max_casdesc', 'min_casdesc']


        self.Flights = pd.DataFrame(columns = columns)
        self.Flights.set_index('ACID', inplace=True)

        self.iafs = ['ARTIP', 'SUGOL', 'RIVER']

        self.not_spawned = defaultdict(list)
        self.aman_parent_id = None
        self.planninghorizon = 40*60
        self.freezehorizon = 14*60
        self.TMA_scan = 5*60 #only aircraft within 5 mins of the tma get checked if they are in the tma
        self.visible_altitude = 10000 #(FL100)
        self.separation = 75
        self.LIV_separation = LivSeparation()
        self.cntrlz = None          # planning times backup

        self.standard_early = 60 # seconds that ASAP plans early if there is no slot taken before the slot being planned, make negative?
        self.late_approach_margin = 120
        self.early_approach_margin = 120 #s, make negative?
        self.tight_margin = 20# if only a speed instruction is required, in the first instruction, for optimization purposes, from aim
        self.tighter_count = 1000 #if aircraft has 1 or 0 instructions: tight approach margin is used
        self.approach_aim = 0 # 90 seconds before eat if an instruction is given is the aim (make negative)
        self.late_adjacent_threshold = 5*60 # if an aircraft is late then this is the threshold before communicating to an adjacent center
        self.early_adjacent_threshold = 5*60 # if an aircraft is early, then this is the ttlg threshold before communicating to an adjacent center, make negative?
        self.instruct = False # easy setting to disable all instructions to frozen aircraft
        self.mach_reduction = 0.04
        self.max_speedup = 25 #knots
        self.max_slowdown = 50 #knots
        self.abs_minspd = 180 #knots outside of tma
        self.nearby_threshold = 120 #seconds before iaf, no more instructions possible
        self.dogleg_multiplyer = 0.9
        self.descent_angle = 3.0 #degrees
        self.workload_speedinstruction = 1.0
        self.workload_dogleg = 2.0
        self.workload_direct = 1.0
        self.workload_adjacent_speed = 2.0
        self.workload_adjacent_dogleg = 3.0
        self.workload_adjacent_direct = 2.0
        self.workload_holding = 3.0



    # update of planningstates, core functionality
    @core.timed_function(dt= 30)
    def update_planningstate(self):
        if self.aman_parent_id or traf.ntraf == 0:
            return

        self.update_times()
        self.origin()
        self.popup()
        self.preplan()
        self.assignslots()
        self.update_times()
        self.freeze()
        # self.tma()
        self.update_times()
        stack.stack('instruct_frozen')




    def popup(self):

        # 1. Filter aircraft that have planningstate == 'new' and (ETO IAF - sim.simt) < freezehorizon
        mask_popup = (
                (self.Flights['planningstate'] == 'new')
                & ((self.Flights['ETO IAF'] - sim.simt) < self.freezehorizon)
        )
        if not mask_popup.any():
            return

        popup_candidates = self.Flights[mask_popup].sort_values(by='ETO IAF')


        for acid, row in popup_candidates.iterrows():
            idxac = traf.id2idx(acid)
            if idxac < 0:
                continue  # Not yet in traf

            alt_ft = round(traf.alt[idxac] / ft)
            if alt_ft < 100:
                # Below FL100, skip assigning slot (remain 'new')
                continue


            runway = row['runway']

            # Find the flight on the same runway whose ETO IAF is just earlier
            # and that already has a slot assigned

            earlier_df = self.Flights[
                (self.Flights['ETO IAF'] < row['ETO IAF'])
                & (self.Flights['runway'] == runway)
                & (self.Flights['slot'].notna())
                ].sort_values(by='ETO IAF')

            if earlier_df.empty:
                # No earlier slot => use own ETA
                new_slot = row['ETA']
            else:
                last_earlier = earlier_df.iloc[-1]
                slot_earlier = last_earlier['slot']
                separation = self.LIV_separation.required_separation(
                    last_earlier.name, last_earlier['type'],
                    acid, row['type']
                )
                new_slot = max(slot_earlier + separation, row['ETA'])

            self.Flights.at[acid, 'slot'] = new_slot

            if pd.notna(row['TMA flighttime']):
                self.Flights.at[acid, 'EAT'] = new_slot - row['TMA flighttime']

            # Color and set planningstate to 'POPUP'
            stack.stack(f"COLOR {acid} 255,0,0")
            self.Flights.at[acid, 'planningstate'] = 'POPUP'
            self.Flights.at[acid, 'popup'] = 'POPUP'



    def preplan(self):
        # 1) Find flights that go from 'new' to 'preplanned'
        mask_new = (
                (self.Flights['planningstate'] == 'new')
                & ((self.Flights['ETO IAF'] - sim.simt) < self.planninghorizon))

        if not mask_new.any():
            return
        new_candidates = self.Flights[mask_new]


        # # 2) Update their planningstate
        # self.Flights.loc[mask_new_to_preplan, 'planningstate'] = 'preplanned'
        #
        # # 3) Color those newly preplanned flights
        # newly_preplanned = self.Flights[mask_new_to_preplan]
        # for idx in newly_preplanned.index:
        #     stack.stack(f"COLOR {idx} 0,150,255")

        for acid, row in new_candidates.iterrows():
            idxac = traf.id2idx(acid)
            if idxac < 0:
                continue  # Not in traf yet

            # Check altitude in feet
            alt_ft = round(traf.alt[idxac] / ft)
            if alt_ft >= self.visible_altitude:  # FL100
                # Now we flip them to 'preplanned'
                self.Flights.at[acid, 'planningstate'] = 'preplanned'
                stack.stack(f"COLOR {acid} 0,150,255")


    def assignslots(self):
        if self.aman_parent_id:
            return

        for runway in self.Flights['runway'].unique():
            # Filter frozen and preplanned flights for the current runway
            frozen_flights = self.Flights.query("planningstate == 'frozen' and runway == @runway")
            preplanned_flights = self.Flights.query("planningstate == 'preplanned' and runway == @runway").sort_values(by='ETA')

            # Initialize last assigned variables
            if not frozen_flights.empty:
                max_row = frozen_flights.loc[frozen_flights['slot'].idxmax()]
                last_assigned_slot, last_assigned_flight, last_assigned_type = max_row['slot'], max_row.name, max_row['type']
            else:
                last_assigned_slot = last_assigned_flight = last_assigned_type = None


            # Iterate over the filtered DataFrame and calculate slots
            for idx, row in preplanned_flights.iterrows():
                if not np.isnan(row['manualslot']):
                    slot = row['manualslot']
                    separation = 0
                elif last_assigned_slot is None:
                    # First flight's slot is its ETA minus early aim
                    slot = row['ETA'] - self.standard_early
                    separation = 0
                else:
                    # Subsequent flight's slot is the last slot + separation

                    separation = self.LIV_separation.required_separation(last_assigned_flight, last_assigned_type, idx, row['type'])
                    slot = max(last_assigned_slot + separation, row['ETA']-self.standard_early)

                # Update the slot in the DataFrame
                self.Flights.loc[idx, ['slot', 'EAT', 'LIV', 'LAS', 'LAf']] = [
                    slot,
                    slot - row['TMA flighttime'],
                    separation,
                    last_assigned_slot,
                    last_assigned_flight,
                ]
                stack.stack(f'COLOR {idx} 0,150,255')  # Retaining stack logic

                # Update last assigned variables
                last_assigned_slot, last_assigned_flight, last_assigned_type = slot, idx, row['type']


        self.Flights = self.Flights.sort_values(by=['slot', 'ETA'], ascending=False)




    def freeze(self):
        for runway, runway_df in self.Flights.groupby('runway'):
            # Freeze aircraft with flighttime < 14 minutes and preplanned within this runway
            newfrozen = runway_df[(runway_df['planningstate'] == 'preplanned') & ((runway_df['ETO IAF'] - sim.simt) < self.freezehorizon)]
            # Get the maximum slot of the newfrozen aircraft within this runway
            max_slot_newfrozen = newfrozen['slot'].max()

            # Select all preplanned flights with a slot smaller than max_slot_newfrozen within this runway
            preplanned_before_max_slot = runway_df[(runway_df['planningstate'] == 'preplanned') & (runway_df['slot'] < max_slot_newfrozen)]


            # Set their planningstate to 'frozen'
            self.Flights.loc[newfrozen.index, 'planningstate'] = 'frozen'
            self.Flights.loc[preplanned_before_max_slot.index, 'planningstate'] = 'frozen'
            self.color(newfrozen, '100,255,100')
            self.color(preplanned_before_max_slot, '100,255,100')



    def tma(self):

        mask_tma = self.Flights['planningstate'].isin(['frozen', 'POPUP']) & (
                (self.Flights['ETO IAF'] - sim.simt) < self.TMA_scan)
        for flight in self.Flights[mask_tma].index:
            idxac = traf.id2idx(flight)
            iaf = self.Flights.at[flight, 'IAF']

            if idxac > -1:
                if traf.ap.route[idxac].iactwp > traf.ap.route[idxac].wpname.index(iaf):
                    self.Flights.at[flight, 'planningstate'] = 'TMA'
                    self.Flights.at[flight, 'ETO adherence'] = sim.simt - self.Flights.loc[flight]['ETO IAF']
                    self.Flights.at[flight, 'EAT adherence'] = sim.simt - self.Flights.loc[flight]['EAT']
                    # self.printflights()
        self.color(self.Flights.loc[self.Flights['planningstate'] == 'TMA'], '230,0,0')



    @stack.command
    def tma_cross(self,acid):
        # idxac = traf.id2idx(acid)
        # iaf = self.Flights.at[acid, 'IAF']
        self.Flights.at[acid, 'planningstate'] = 'TMA'
        self.Flights.at[acid, 'ETO adherence'] = sim.simt - self.Flights.loc[acid]['ETO IAF']
        self.Flights.at[acid, 'ETO_act'] = sim.simt
        self.Flights.at[acid, 'EAT adherence'] = round(sim.simt - self.Flights.loc[acid]['EAT'],1)
        # self.printflights()
        self.color(acid, '230,230,230')

# ___________________________________ PREDICTOR FUNCTIONS
    # new prediction received
    @network.subscriber(topic='PREDICTION')
    def on_prediction_received(self, acid, wpt, wptime,flighttime, wptpredutc, parent_id, type):
        """
        Each acid getting a new ETA will be added to aircraft needing to get a slot.
        """

        if self.aman_parent_id:
            return

        self.sim_id_parent = parent_id
        idxac = traf.id2idx(acid)
        estimatedcreatetime = wptime - flighttime
        if idxac == -1:

            self.not_spawned[acid].append((wpt, wptime,flighttime,estimatedcreatetime, wptpredutc, parent_id, type))
            # dest, runway = parse_destination(wpt)
            # self.Flights.loc[acid] = {'planningstate': 'ground', 'ETA': wptime, 'runway': runway, 'type': type}
            # the above is future code for popups?

        elif acid in self.Flights.index:
            wptime = traf.ap.route[idxac].createtime + flighttime
            # print(f'{acid} at {wpt}')
            if wpt in self.iafs:
                data = {'ETO IAF': wptime, 'IAF': wpt , 'TPstate': 'updated iaf', 'ttlg': self.Flights.loc[acid,'EAT']-wptime}



            elif '/RW' in wpt:
                dest, runway = parse_destination(wpt)
                idxac = traf.id2idx(acid)
                tp_dt = sim.simt - traf.ap.route[idxac].createtime
                data = {'ETA': wptime, 'runway': runway, 'TPstate': 'updated', 'tp_time': tp_dt, 'instrtime': traf.ap.route[idxac].createtime, 'updatetime': sim.simt}






            # print(acid,wpt,wptime)
            elif 'CROSSOVER' in wpt:
                data = {'crossover': wptime}

            # Updates the existing row for acid

            for key, value in data.items():
                # print(f'{key}: {value}')
                self.Flights.at[acid, key] = value

            if '/RW' in wpt:
                stack.stack('instruct_frozen')

        else:
            wptime = traf.ap.route[idxac].createtime + flighttime
            data = {'planningstate': 'new', 'runway': ''}


            if wpt in self.iafs:
                data = {'planningstate': 'new', 'ETO IAF': wptime, 'IAF': wpt, 'type': type, 'origin': '', 'LAf': '', 'count': 0}

            elif '/RW' in wpt:
                dest, runway = parse_destination(wpt)
                data = {'planningstate': 'new', 'ETA': wptime, 'runway': runway, 'type': type, 'origin': '', 'LAf': '', 'count': 0}
            # print(acid,wpt,wptime)
            elif 'CROSSOVER' in wpt:
                data = {'planningstate': 'new', 'crossover': wptime}

            # data['instruction'] = []
            if acid not in self.Flights.index:
                # Adds a new row for acid if it doesn't exist
                self.Flights.loc[acid] = {'runway': '', 'type': '', 'IAF': '', 'planningstate': '', 'origin': '', 'LAf': '', 'count': 0}
                self.Flights.loc[acid] = data
            else:
                # Updates the existing row for acid
                for key, value in data.items():
                    self.Flights.at[acid, key] = value


    # new aircraft spawned
    def create(self, n=1):
        """ Gets triggered everytime n number of new aircraft are created. """
        super().create(n)

        # Ensure this runs only in the main node.
        if traf.traf_parent_id and self.aman_parent_id is None:
            self.aman_parent_id = traf.traf_parent_id
            return

        for i in range(n):
            acid = traf.id[-1 - i]
            id = len(traf.id) - i
            if acid in self.not_spawned.keys():
                for prediction in self.not_spawned[acid]:
                    wpt, wptime, flighttime, estimatedcreatetime, wptpredutc, parent_id, type = prediction
                    wptime = sim.simt + flighttime

                    if wpt in self.iafs:
                        data = {'planningstate': 'new', 'ETO IAF': wptime, 'ETO_original':wptime, 'IAF': wpt, 'type': type, 'origin': '', 'LAf': '', 'count':0, 'Flighttime': flighttime}
                    elif '/RW' in wpt:
                        dest, runway = parse_destination(wpt)
                        data = {'planningstate': 'new', 'ETA': wptime, 'runway':runway, 'type': type, 'origin': '', 'LAf': '','count':0, 'Flighttime': flighttime}
                    elif 'CROSSOVER' in wpt:
                        data = {'planningstate': 'new', 'crossover': wptime}

                    else:
                        print('something wrong with waypoints and prediction in aman')

                    # data['instruction'] = []
                    #add data to dataframe
                    if acid not in self.Flights.index:
                        # Adds a new row for acid if it doesn't exist
                        self.Flights.loc[acid] = {'runway': '', 'type': '', 'IAF': '', 'planningstate': '', 'origin': '', 'LAf': ''}
                        self.Flights.loc[acid] = data
                    else:
                        # Updates the existing row for acid
                        for key, value in data.items():
                            self.Flights.at[acid, key] = value




    def delete(self, idx):
        super().delete(idx)
        if self.aman_parent_id:
            return
        else:
            for id in idx:
                acid = traf.id[id]
                if acid in self.Flights.index:
                    self.Flights.at[acid, 'planningstate'] = 'deleted'

    def reset(self):
        """ Clear all traffic data when sim is reset and reset data for the predictor. """
        stack.stack('ECHO resetting AMAN, placeholder for storing planning permanently')
        super().reset()
        columns = ['ACID', 'planningstate', 'ttlg', 'to eto', 'type', 'LIV', 'ETA', 'ETO IAF', 'IAF', 'runway', 'EAT', 'slot', 'TMA flighttime', 'EAT adherence', 'LAS', 'LAf', 'origin', 'crossover']


        self.Flights = pd.DataFrame(columns = columns)
        self.Flights.set_index('ACID', inplace=True)

        self.iafs = ['ARTIP', 'SUGOL', 'RIVER']

        self.not_spawned = defaultdict(list)
        self.aman_parent_id = None
        self.planninghorizon = 40*60
        self.freezehorizon = 14*60
        self.TMA_scan = 5*60 #only aircraft within 5 mins of the tma get checked if they are in the tma
        self.visible_altitude = 10000 #(FL100)
        self.separation = 75
        self.LIV_separation = LivSeparation()
        self.cntrlz = None          # planning times backup
        self.standard_early = 60 # seconds that ASAP plans early if there is no slot taken before the slot being planned, make negative?
        self.late_approach_margin = 120
        self.early_approach_margin = 120 #s, make negative?
        self.tight_margin = 20 # if only a speed instruction is required, in the first instruction, for optimization purposes, from aim
        self.approach_aim = 0 # 90 seconds before eat if an instruction is given is the aim (make negative)
        self.late_adjacent_threshold = 5*60 # if an aircraft is late then this is the threshold before communicating to an adjacent center
        self.early_adjacent_threshold = 5*60 # if an aircraft is early, then this is the ttlg threshold before communicating to an adjacent center, make negative?
        self.instruct = False # easy setting to disable all instructions to frozen aircraft



# ----------------------------------------------------------- misc functions
    def origin(self):
        # sadly, cannot be run in create, since orig is not set yet. this function is called in the update function
        for flight in self.Flights[(self.Flights['origin'] == '')].index:
            idxac = traf.id2idx(flight)

            if idxac == -1:
                continue
            else:
                try:
                    origin =traf.ap.orig[idxac]
                    self.Flights.at[flight, 'origin'] = origin

                except:
                    continue



    def update_times(self):
        if self.aman_parent_id:
            return
        self.Flights['TMA flighttime'] = self.Flights['ETA'] - self.Flights['ETO IAF']
        self.Flights['to eto'] = round((self.Flights['ETO IAF'] - sim.simt) / 60, 0)
        self.Flights['ttlg'] = self.Flights['EAT'] - self.Flights['ETO IAF']



    def color(self, df, rgb):
        if self.aman_parent_id:
            return
        if type(df) != str:
            # Iterate over the filtered DataFrame and calculate slots
            for idx in df.index:
                stack.stack('COLOR ' + idx +' '+ rgb)
        elif type(df) == str:
            stack.stack('COLOR ' + df + ' '+ rgb)





#--------------------------------------------------------------
    #planning functions

    @stack.command
    def freezehorizon(self, minutes):
        self.freezehorizon = 60.* minutes
        self.update_planningstate()

    @stack.command
    def planninghorizon(self, minutes):
        self.planninghorizon = 60.* minutes
        if self.planninghorizon < self.freezehorizon:
            self.planninghorizon = self.freezehorizon + 60*1.


#--------------------------------------------------------------
    #exporting functions


    @stack.command
    def usecache_aman(self):
        if not self.aman_parent_id:
            cache = self.open_cache()
            self.not_spawned = cache
            self.predictions_cache = cache
            self.use_cache = True




    def open_cache(self):
        try:
            # Open and load the predictions_cache file
            with open('predictions_cache.pkl', 'rb') as f:
                predictions = pickle.load(f)
            # Open and load the commands file
        except FileNotFoundError:
            # If either file is missing, return None for both
            return None, None
        return predictions


    @stack.command
    def storeflights(self):
        if self.aman_parent_id:
            return
        if traf.traf_parent_id and self.aman_parent_id is None:
            self.aman_parent_id = traf.traf_parent_id
            return
        self.printflights()
        self.pickleflights()
        self.Flights.to_csv('dataframe.txt', sep=',', index=True)

    @stack.command
    def pickleflights(self):
        if self.aman_parent_id:
            return
        self.Flights.to_pickle('flights.pkl')
        # Flights = pd.read_pickle('flights.pkl')

    @stack.command
    def totwohtml(self):

        if self.aman_parent_id:
            return

        # Split Flights into two subsets based on runway
        Flights_hhmmss = self.Flights.copy()
        Flights_hhmmss.rename(columns={'runway': 'rwy'}, inplace=True)
        Flights_hhmmss.rename(columns={'TMA flighttime': 'TMA'}, inplace=True)
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
        columns_to_transform = ['ETA', 'ETO IAF', 'ETO_original','ETO_act', 'EAT', 'slot', 'LAS', 'crossover']
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
                <h3>Runway RWY27  time:{sim_hhmmss}</h3>
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
        output_path = "output.html"

        # Write the HTML output to a file
        with open(output_path, "w") as f:
            f.write(html_with_style)

        # Automatically open in the browser
        # webbrowser.open(f"file://{os.path.abspath(output_path)}")

    @core.timed_function(dt=10 )
    def autohtmlflights(self):
        if not sim.ffmode:
            # self.htmlflights()
            self.totwohtml()
    @core.timed_function(dt=10) #is approx every 10 sec in ff mode
    def autohtmlflightsff(self):
        # self.time = time.time()
        # if self.previoustime - self.time < 60:
        if sim.ffmode and traf.ntraf >0:
            # self.htmlflights()
            self.totwohtml()




#---------------debugging------------------------

    @stack.command
    def setslot(self,acid,ttlg, planningstate = 'frozen'):
        acid = acid.upper()
        eta = self.Flights.loc[acid,'ETA']
        currentslot = self.Flights.loc[acid,'slot']
        requiredslot = eta + float(ttlg)
        # if self.Flights[acid,'planningstate'] =='preplanned':
        self.Flights.loc[acid,'manualslot'] = requiredslot
        if self.Flights.loc[acid,'planningstate'] == 'frozen':
            self.Flights.at[acid, 'planningstate'] = 'preplanned'
            self.assignslots()
            self.update_times()
            self.freeze()


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

    @stack.command
    def stopinstruct(self):
        self.instruct = False

    @stack.command
    def startinstruct(self):
        self.instruct = True

    @stack.command
    def randomspeedinstruction(self, n, group='preplanned', seed=42):
        """
        Randomly selects 'n' aircraft from the specified 'group' (default 'preplanned')
        and issues a random speed (between 150 and 350) instruction to each.
        Uses a fixed random seed to ensure reproducibility.
        """
        # Set the seed for reproducible "random" results
        random.seed(seed)

        # Filter flights by planningstate (group), e.g. 'preplanned'
        eligible_flights = self.Flights[self.Flights['planningstate'] == group].index.tolist()

        # Clamp n if it’s greater than the number of eligible flights
        n = min(int(n), len(eligible_flights))

        # Randomly pick n flights
        selected_flights = random.sample(eligible_flights, n)
        print(selected_flights)

        # For each flight, create a random speed between 150 and 350, then send it
        for acid in selected_flights:
            spd_cmd = random.randint(150, 350)
            stack.stack(f"SPD {acid} {spd_cmd}")





def parse_destination(wpt_name):
    try:
        # Create an instance of WptArg parser
        parser = stack.argparser.WptArg()

        # Parse the command string
        argstring = wpt_name + ", more arguments if any"
        parsed_name, remaining_string = parser.parse(argstring)

        # Check if the parsed name is a runway (look for the '/' pattern in parsed_name followed by "RW")
        if '/RW' in parsed_name:
            airport, runway = parsed_name.split('/')
            return airport, runway  # Return the airport and runway
        else:
            return wpt_name, None  # Return None if it's not a runway
    except ValueError:
        return None, None  # Return None if an error occurs, indicating not a valid waypoint or runway


        # #todo list
        # basic aman
        #

        # dataframe according to slottimes: maybe eat?
# shorten scenario
# change method of data setting due to future warning
        # define separation times
        # handle popups
# export dataframe
        # planned status to TMA in tma
        # remove aman from tp node
        # define ltfm, eetn, lybe origs
        # individual performance of aircraft in scenario generator



        # read and import runways
        # change route if runway is changed
# export dataframe
        # set horizons function
        # EAT adherence
        # check what happens if same runway but later slot gets frozen earlier



        # total
        # atc based on ttlg etc
        # swap function
        # expedite margin function
        # visualization
        # check scenario generator if it is the same as info in so6 file. (replacing aircraft is verified, not validated)






