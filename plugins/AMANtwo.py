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
from plugins.errorgenerator import ErrorGenerator
from plugins.shiftflight import shiftflight
import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 250)
import numpy as np
import random
import pickle
import time
from datetime import timedelta
from bluesky.tools.aero import casormach2tas, fpm, kts, ft, g0, Rearth, nm, tas2cas,\
                         vatmos,  vtas2cas, vtas2mach, vcasormach
from bluesky.tools import areafilter



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
        columns = ['ACID', 'planningstate', 'ttlg', 'to eto', 'type', 'LIV', 'ETA', 'ETO IAF', 'ETO_original', 'TP IAF', 'TP ETA', 'IAF', 'runway', 'EAT', 'slot', 'manualslot', 'TMA', 'EAT adherence', 'LAS', 'LAf', 'origin', 'TPstate', 'count', 'Flighttime', 'TP accuracy', 'casdesc', 'max_casdesc', 'min_casdesc', 'E_TO', 'E_dep', 'E_enroute', 'E_fir', 'creation', 'planning', 'SID', 'FIR entry', 'Time error']


        self.Flights = pd.DataFrame(columns = columns)
        self.Flights.set_index('ACID', inplace=True)

        self.iafs = ['ARTIP', 'SUGOL', 'RIVER']
        self.firname = 'FIRNL'

        self.not_spawned = defaultdict(list)
        self.aman_parent_id = None
        self.planninghorizon = 40*60
        self.freezehorizon = 25*60
        self.TMA_scan = 5*60 #only aircraft within 5 mins of the tma get checked if they are in the tma
        self.visible_altitude = 10000 #(FL100)
        self.separation = 75
        self.LIV_separation = LivSeparation()
        self.errorgenerator = ErrorGenerator() #todo seed
        self.shiftflight = shiftflight()
        self.cntrlz = None          # planning times backup

        self.standard_early = 60 # seconds that ASAP plans early if there is no slot taken before the slot being planned, make negative?
        self.late_approach_margin = 120
        self.early_approach_margin = 120 #s, make negative?
        self.tight_margin = 20# if only a speed instruction is required, in the first instruction, for optimization purposes, from aim
        self.tighter_count = 1000 #if aircraft has 1 or 0 instructions: tight approach margin is used
        self.approach_aim = 0 # 90 seconds before eat if an instruction is given is the aim (make negative)
        self.late_adjacent_threshold = 5*60 # if an aircraft is late then this is the threshold before communicating to an adjacent center
        self.early_adjacent_threshold = 5*60 # if an aircraft is early, then this is the ttlg threshold before communicating to an adjacent center, make negative?
        self.instruct = True # easy setting to disable all instructions to frozen aircraft
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
        # self.dynamic_LIV = False
        # self.single_rwy_capacity = 38 #aircraft per hour
        # self.double_rwy_capacity = 34 #each
        self.starttime = time.time()



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
            if alt_ft < self.visible_altitude:
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

            if pd.notna(row['TMA']):
                self.Flights.at[acid, 'EAT'] = new_slot - row['TMA']

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
                    slot - row['TMA'],
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
                    self.Flights.at[flight, 'TP accuracy'] = sim.simt - self.Flights.loc[flight]['TP IAF']
                    self.Flights.at[flight, 'EAT adherence'] = sim.simt - self.Flights.loc[flight]['EAT']
                    # self.printflights()
        self.color(self.Flights.loc[self.Flights['planningstate'] == 'TMA'], '230,0,0')



    @stack.command
    def tma_cross(self,acid):
        # idxac = traf.id2idx(acid)
        # iaf = self.Flights.at[acid, 'IAF']
        self.Flights.at[acid, 'planningstate'] = 'TMA'
        self.Flights.at[acid, 'TP accuracy'] = sim.simt - self.Flights.loc[acid]['TP IAF']
        self.Flights.at[acid, 'ETO_act'] = sim.simt
        self.Flights.at[acid, 'EAT adherence'] = round(sim.simt - self.Flights.loc[acid]['EAT'],1)
        # self.printflights()
        self.color(acid, '230,230,230')

# ___________________________________ PREDICTOR FUNCTIONS
    # new prediction received
    @network.subscriber(topic='PREDICTION')
    def on_prediction_received(self, acid, wpt, wptime,flighttime, wptpredutc, parent_id, type, origin):
        """
        Each acid getting a new ETA will be added to aircraft needing to get a slot.
        """

        if self.aman_parent_id:
            return

        self.sim_id_parent = parent_id
        idxac = traf.id2idx(acid)
        estimatedcreatetime = wptime - flighttime
        if idxac == -1:
            if wpt in self.iafs:
                #determining errors at iaf
                lookahead = round(int(self.freezehorizon - flighttime) / 60)  # minutes
                abslookahead = lookahead
                if lookahead < 0:
                    lookahead = 0
                print(acid, 'error should be generated')
                takeoff, dep_route, enroute, fir = self.errorgenerator.return_sample(acid, origin, lookahead=lookahead)
                if float(takeoff) != 0.0:
                    self.shiftflight.shift(acid, takeoff * 60)
            else:
                takeoff, dep_route, enroute, fir, abslookahead = 0,0,0,0,0# to be disregarded later
            self.not_spawned[acid].append((wpt, wptime,flighttime,estimatedcreatetime, wptpredutc, parent_id, type, origin, takeoff, dep_route, enroute, fir, abslookahead))
            # dest, runway = parse_destination(wpt)
            # self.Flights.loc[acid] = {'planningstate': 'ground', 'TP ETA': wptime, 'runway': runway, 'type': type}
            # the above is future code for popups?

        elif acid in self.Flights.index:
            wptime = traf.ap.route[idxac].createtime + flighttime
            # print(f'{acid} at {wpt}')
            if wpt in self.iafs:
                # data = {'TP IAF': wptime, 'IAF': wpt , 'TPstate': 'updated iaf', 'ttlg': self.Flights.loc[acid,'EAT']-wptime}

                TMA = self.Flights.loc[acid, 'TMA']
                # 'TP ETA': wptime + TMA
                data = {'TP IAF': wptime, 'IAF': wpt, 'TPstate': 'updated', 'ttlg': self.Flights.loc[acid, 'EAT'] - wptime, 'TP ETA': wptime + TMA}



            elif '/RW' in wpt:
                dest, runway = parse_destination(wpt)
                idxac = traf.id2idx(acid)
                data = {'TP ETA': wptime, 'runway': runway, 'TPstate': 'updated including TMA'}

            elif self.firname in wpt:
                data = {'FIR entry': wptime} #time to fir entry from spawning

            elif 'ALTCROSS CLIMB' in wpt:
                data = {'SID': wptime}



            else:
                data = {}


            # Updates the existing row for acid

            for key, value in data.items():
                self.Flights.at[acid, key] = value

            if '/RW' in wpt or ('TPstate' in data.keys() and data['TPstate'] == 'updated'):
                stack.stack('instruct_frozen')

        else:
            wptime = traf.ap.route[idxac].createtime + flighttime
            data = {'planningstate': 'new', 'runway': ''}


            if wpt in self.iafs:
                data = {'planningstate': 'new', 'TP IAF': wptime, 'IAF': wpt, 'type': type, 'origin': '', 'LAf': '', 'count': 0}

            elif '/RW' in wpt:
                dest, runway = parse_destination(wpt)
                data = {'planningstate': 'new', 'TP ETA': wptime, 'runway': runway, 'type': type, 'origin': '', 'LAf': '', 'count': 0}
            # print(acid,wpt,wptime)

            elif self.firname in wpt:
                data = {'FIR entry': wptime} #time to fir entry from spawning

            elif 'ALTCROSS CLIMB' in wpt:
                data = {'SID': wptime}


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
                    wpt, wptime, flighttime, estimatedcreatetime, wptpredutc, parent_id, type, origin, takeoff, dep_route, enroute, fir, abslookahead = prediction
                    wptime = sim.simt + flighttime

                    if wpt in self.iafs:
                        data = {'planningstate': 'new', 'TP IAF': wptime, 'ETO_original':wptime, 'IAF': wpt, 'type': type, 'origin': '', 'LAf': '', 'count':0, 'Flighttime': flighttime, 'E_TO': takeoff, 'E_dep':dep_route, 'E_enroute':enroute, 'E_fir':fir, 'creation': sim.simt, 'lookahead':abslookahead}

                    elif '/RW' in wpt:
                        dest, runway = parse_destination(wpt)
                        data = {'planningstate': 'new', 'TP ETA': wptime, 'runway':runway, 'type': type, 'origin': '', 'LAf': '','count':0, 'Flighttime': flighttime}

                    elif self.firname in wpt:
                        data = {'FIR entry': wptime}

                    elif 'ALTCROSS CLIMB' in wpt:
                        data = {'SID': wptime}

                    elif 'ALTCROSS DESC' in wpt:
                        data = {}

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
        columns = ['ACID', 'planningstate', 'ttlg', 'to eto', 'type', 'LIV', 'ETA', 'ETO IAF', 'IAF', 'runway', 'EAT', 'slot', 'TMA', 'EAT adherence', 'LAS', 'LAf', 'origin']


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

        # error introduction here
        # self.Flights['totalerror'] = self.Flights['creation'] + self.Flights['deproute'] + self.Flights['outsidefir'] + self.Flights
        # self.Flights['ETA'] = self.Flights['correct_ETA'] + self.Flights['totalerror']
        self.update_errors()

        self.Flights['TMA'] = self.Flights['TP ETA'] - self.Flights['TP IAF']
        self.Flights['to eto'] = round((self.Flights['ETO IAF'] - sim.simt) / 60, 0)
        self.Flights['ttlg'] = self.Flights['EAT'] - self.Flights['ETO IAF']
        self.Flights['planning'] = self.Flights['TP IAF'] - self.planninghorizon

    def update_errors(self):



        # self.Flights['ETA'] = self.Flights['correct_ETA'] + error
        # self.Flights['totalerror'] = self.Flights['creation'] + self.Flights['deproute'] + self.Flights['outsidefir'] + self.Flights['insidefir']
        # self.Flights['Time error'] =
        # (SID - FH) * E_DEP
        #
        #TODO deze goed checken, met name de signs
        self.segments()
        self.Flights['Time error'] = (
                -self.Flights['t_departure'].fillna(0) * self.Flights['E_dep'].fillna(0) / 100
                - self.Flights['t_enroute'].fillna(0) * self.Flights['E_enroute'].fillna(0) / 100
                - self.Flights['t_fir'].fillna(0) * self.Flights['E_fir'].fillna(0) / 100
                #- self.Flights['E_TO'].fillna(0) * 60
        )
        self.Flights['ETO IAF'] = self.Flights['TP IAF'] + self.Flights['Time error']
        self.Flights['ETA'] = self.Flights['ETO IAF'] + self.Flights['TMA']
        # tdep = self.Flights['']
        #
        # self.Flights['Time error'] = -self.Flights['E_TO']*60 + self.Flights['E_dep']


    def segments(self):
        df = self.Flights
        simt_s = pd.Series(float(sim.simt), index=df.index)


        # Extract main timestamps
        SID, FIR, IAF, TO, Planning = df['SID'], df['FIR entry'], df['TP IAF'], df['creation'], df['planning']

        # Determine actual segment start times
        start_dep = pd.concat([simt_s, Planning, TO], axis=1).max(axis=1, skipna=True)
        start_enr = pd.concat([simt_s, Planning, SID], axis=1).max(axis=1, skipna=True)
        start_fir = pd.concat([simt_s, Planning, FIR], axis=1).max(axis=1, skipna=True)
        # Compute durations, ensuring non-negative results
        t_departure = (SID - start_dep).clip(lower=0).where(SID.notna())
        t_enroute = (FIR - start_enr).clip(lower=0).where(FIR.notna())
        t_fir = (IAF - start_fir).clip(lower=0).where(IAF.notna())

        df['t_departure'], df['t_enroute'], df['t_fir'] = t_departure, t_enroute, t_fir


    def color(self, df, rgb):
        if self.aman_parent_id:
            return
        if type(df) != str:

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
            self.regenerate_errors()
            print('regenerate errors?')
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




    def regenerate_errors(self):
        """
        Re-run the error generator for all not_spawned predictions
        to ensure fresh errors instead of cached ones.
        """
        updated_not_spawned = defaultdict(list)

        for acid, predictions in self.not_spawned.items():
            for (wpt, wptime, flighttime, estimatedcreatetime,
                 wptpredutc, parent_id, type, origin) in predictions:
                #note that the errors are not stored in the previous predictions, these are stored in the TP, which does not include errors

                if wpt in self.iafs:
                # compute lookahead in minutes
                    lookahead = round(int(self.freezehorizon - flighttime) / 60)
                    abslookahead = lookahead
                    if lookahead < 0:
                        lookahead = 0

                    # always regenerate fresh errors
                    new_takeoff, new_dep_route, new_enroute, new_fir = \
                        self.errorgenerator.return_sample(acid, origin, lookahead=lookahead)
                    if float(new_takeoff) != 0.0:
                        self.shiftflight.shift(acid, new_takeoff * 60)
                else:
                    new_takeoff, new_dep_route, new_enroute, new_fir, abslookahead = 0,0,0,0,0
                updated_not_spawned[acid].append(
                    (wpt, wptime, flighttime, estimatedcreatetime,
                     wptpredutc, parent_id, type, origin,
                     new_takeoff, new_dep_route, new_enroute, new_fir, abslookahead)
                )

        self.not_spawned = updated_not_spawned



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






