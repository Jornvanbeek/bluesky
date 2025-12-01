"""
The Arrival Manager (AMAN) plugin is designed to efficiently allocate arrival slots for aircraft based on
their estimated times of arrival (ETAs) while ensuring necessary separation times. It dynamically updates
air traffic every 5 seconds around designated areas around airports based on ETAs to anticipate aircraft arrivals.
"""

# from setuptools.dist import sequence

from bluesky import core, stack, traf, sim

from collections import defaultdict
from plugins.LIV_separation import LivSeparation
from plugins.errorgenerator import ErrorGenerator
from plugins.shiftflight import shiftflight
import plugins.amanhelpers.aman_settings as settings
import pandas as pd
import numpy as np
import random
import time
from bluesky.tools.aero import ft

# voeg toe bij de imports bovenaan
from plugins.amanhelpers.amanpredictionhandler import PredictionHandler
from plugins.amanhelpers.errorhandler import ErrorHandler
from plugins.amanhelpers.amanexport import AmanExporter


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



class ArrivalManager(PredictionHandler, ErrorHandler,AmanExporter, core.Entity):
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

        for k, v in vars(settings).items():
            if not k.startswith('_') and not callable(v):
                setattr(self, k, v)

        # Define the column names
        columns = ['ACID', 'planningstate', 'ttlg', 'to eto', 'type', 'LIV', 'ETA', 'ETO IAF', 'ETO_original', 'TP IAF', 'TP ETA', 'IAF', 'runway', 'EAT', 'slot', 'initialslot', 'manualslot', 'TMA', 'EAT adherence', 'LAS', 'LAf', 'origin', 'TPstate', 'count', 'updates','Flighttime', 'TP accuracy', 'casdesc', 'max_casdesc', 'min_casdesc', 'E_TO', 'E_dep', 'E_enroute', 'E_fir', 'creation', 'planning', 'SID', 'FIR entry', 'Time error', 'Error at Freeze', 'minwork', 'totalwork', 'extrawork', 'swaps']
        self.Flights = pd.DataFrame(columns = columns)
        self.Flights.set_index('ACID', inplace=True)
        self.not_spawned = defaultdict(list)
        self.aman_parent_id = None
        self.LIV_separation = LivSeparation()
        self.errorgenerator = ErrorGenerator() #todo check seed
        self.shiftflight = shiftflight()
        self.cntrlz = None          # planning times backup
        self.starttime = time.time()

        # self.Flights['updates'] = 0
        # self.Flights['updates'] = self.Flights['updates'].astype(int)


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
                if self.dynamic_LIV:
                    separation = self.LIV_separation.required_separation(
                        last_earlier.name, last_earlier['type'],
                        acid, row['type']
                    )

                else:
                    separation = self.separation

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

                    if self.dynamic_LIV:

                        separation = self.LIV_separation.required_separation(last_assigned_flight, last_assigned_type, idx, row['type'])
                    else:
                        separation = self.separation
                    slot = max(last_assigned_slot + separation, row['ETA']-self.standard_early)

                # Update the slot in the DataFrame
                self.Flights.loc[idx, ['slot','initialslot', 'EAT', 'LIV', 'LAS', 'LAf']] = [
                    slot,
                    slot,
                    slot - row['TMA'],
                    separation,
                    last_assigned_slot,
                    last_assigned_flight,
                ]
                stack.stack(f'COLOR {idx} 0,150,255')

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
            self.Flights.loc[newfrozen.index, 'Error at Freeze'] = self.Flights.loc[newfrozen.index, 'Time error']
            self.Flights.loc[preplanned_before_max_slot.index, 'planningstate'] = 'frozen'
            self.Flights.loc[preplanned_before_max_slot.index, 'Error at Freeze'] = self.Flights.loc[preplanned_before_max_slot.index, 'Time error']
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
        # self.Flights.at[acid, 'ETO_act'] = sim.simt
        self.Flights.at[acid, 'EAT adherence'] = round(sim.simt - self.Flights.loc[acid]['EAT'],1)
        # self.printflights()
        self.color(acid, '230,230,230')





    def delete(self, idx):
        super().delete(idx)
        if self.aman_parent_id:
            return
        else:
            if np.isscalar(idx):
                idx = [idx]
            for id in idx:
                acid = traf.id[id]
                if acid in self.Flights.index:
                    self.Flights.at[acid, 'planningstate'] = 'deleted'
                    self.Flights.at[acid, 'totalwork'] = traf.work[id]
                    self.Flights.at[acid, 'extrawork'] = traf.work[id] - self.Flights.at[acid, 'minwork']

    def reset(self):
        """ Clear all traffic data when sim is reset and reset data for the predictor. """
        stack.stack('ECHO resetting AMAN, placeholder for storing planning permanently')
        super().reset()

        for k, v in vars(settings).items():
            if not k.startswith('_') and not callable(v):
                setattr(self, k, v)

        # Define the column names
        columns = ['ACID', 'planningstate', 'ttlg', 'to eto', 'type', 'LIV', 'ETA', 'ETO IAF', 'ETO_original', 'TP IAF', 'TP ETA', 'IAF', 'runway', 'EAT', 'slot', 'manualslot', 'TMA', 'EAT adherence', 'LAS', 'LAf', 'origin', 'TPstate', 'count', 'Flighttime', 'TP accuracy', 'casdesc', 'max_casdesc', 'min_casdesc', 'E_TO', 'E_dep', 'E_enroute', 'E_fir', 'creation', 'planning', 'SID', 'FIR entry', 'Time error', 'Error at Freeze', 'minwork', 'totalwork', 'extrawork']
        self.Flights = pd.DataFrame(columns = columns)
        self.Flights.set_index('ACID', inplace=True)
        self.not_spawned = defaultdict(list)
        self.aman_parent_id = None
        self.LIV_separation = LivSeparation()
        self.errorgenerator = ErrorGenerator() #todo check seed
        self.shiftflight = shiftflight()
        self.cntrlz = None          # planning times backup
        self.starttime = time.time()

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
        self.Flights['planning'] = self.Flights['EAT'] - self.planninghorizon




    # def replan_late(self,acid, ETA = None):
    #     # simple version, only swap slots
    #     row_replan = self.Flights.loc[acid]
    #     if ETA is None:
    #         ETA = row_replan['ETA']
    #     runway = row_replan['runway']
    #     slot = row_replan['slot']
    #     frozen = self.Flights[
    #         (self.Flights['runway'] == runway) &
    #         (self.Flights['planningstate'] == 'frozen') &
    #         (self.Flights['slot'] > slot)
    #     ].sort_values('slot')
    #
    #     swaps = 0
    #     for flight, row in frozen.iterrows():
    #         if ETA <= row['ETA']:
    #             break
    #         else:
    #             current_slot = row['slot']
    #             liv = row['LIV']
    #             self.Flights.at[flight, 'slot'] = slot
    #             slot = current_slot
    #             swaps += 1
    #
    #     self.Flights.at[acid, 'slot'] = slot
    #     self.Flights.at[acid, 'swaps'] += swaps
    #     self.Flights['EAT'] = self.Flights['slot'] - self.Flights['TMA']


    def replan_late(self,acid, ETA = None):
        # simple version, only swap slots
        row_replan = self.Flights.loc[acid]
        if ETA is None:
            ETA = row_replan['ETA']
        runway = row_replan['runway']
        slot = row_replan['slot']
        frozen = self.Flights[
            (self.Flights['runway'] == runway) &
            (self.Flights['planningstate'] == 'frozen') &
            (self.Flights['slot'] > slot)
        ].sort_values('slot')

        before = self.Flights[
            (self.Flights['runway'] == runway) &
            (self.Flights['planningstate'] == 'frozen') &
            (self.Flights['slot'] < slot)
            ].sort_values('slot')

        if before.empty:
            last_assigned_slot = None
            last_assigned_flight = None
            last_assigned_type = None
        else:
            last_row = before.iloc[-1]  # laatste op basis van slot
            last_assigned_slot = last_row['slot']
            last_assigned_flight = last_row.name
            last_assigned_type = last_row['type']

        swaps = 0
        replanned = False
        for flight, row in frozen.iterrows():
            if ETA <= row['ETA'] and not replanned:
                # put too late flight in this slot first, then plan the rest

                if last_assigned_slot is None:
                    # First flight's slot is its ETA or slot, whichever is lower
                    slot = min(row['ETA'], row['slot'])
                    separation = 0
                else:
                    # Subsequent flight's slot is the last slot + separation

                    if self.dynamic_LIV:
                        separation = self.LIV_separation.required_separation(last_assigned_flight, last_assigned_type,
                                                                             acid,
                                                                             row['type'])
                    else:
                        separation = self.separation

                    # slot is based on either previous slot or ETA, whichever is lower and thus achievable, or the previous slot plus separation
                    slot = max(last_assigned_slot + separation, min(row['ETA'], row['slot']))

                self.Flights.loc[acid, ['slot', 'EAT', 'LIV', 'LAS', 'LAf']] = [
                    slot,
                    slot - row['TMA'],
                    separation,
                    last_assigned_slot,
                    last_assigned_flight,
                ]
                last_assigned_slot, last_assigned_flight, last_assigned_type = slot, acid, row['type']
                replanned = True


            else:
                swaps +=1

            if last_assigned_slot is None:
                # First flight's slot is its ETA or slot, whichever is lower
                slot = min(row['ETA'], row['slot'])
                separation = 0
            else:
                # Subsequent flight's slot is the last slot + separation

                if self.dynamic_LIV:
                    separation = self.LIV_separation.required_separation(last_assigned_flight, last_assigned_type, flight,
                                                                         row['type'])
                else:
                    separation = self.separation

                #to be clear, this is planning the slot of a flight that will have an earlier slot than the replanned flight

                # slot is based on either previous slot or ETA, whichever is lower and thus achievable, or the previous slot plus separation
                slot = max(last_assigned_slot + separation, min(row['ETA'], row['slot']))

            self.Flights.loc[flight, ['slot', 'EAT', 'LIV', 'LAS', 'LAf']] = [
                slot,
                slot - row['TMA'],
                separation,
                last_assigned_slot,
                last_assigned_flight,
            ]

            if 'swaps' not in self.Flights.columns:
                self.Flights['swaps'] = 0

            self.Flights['swaps'] = self.Flights['swaps'].fillna(0).astype(int)
            self.Flights.at[flight, 'swaps'] += 1

            last_assigned_slot, last_assigned_flight, last_assigned_type = slot, flight, row['type']


        #na de for loop de hoeveelheid swaps voor de vlucht die replanned werd opslaan
        if 'swaps' not in self.Flights.columns:
            self.Flights['swaps'] = 0

        self.Flights['swaps'] = self.Flights['swaps'].fillna(0).astype(int)
        self.Flights.at[acid, 'swaps'] += int(swaps)


    # def replan_late(self,acid, ETA = None):
    #     row_replan = self.Flights.loc[acid]
    #     if ETA is None:
    #         ETA = row_replan['ETA']
    #     runway = row_replan['runway']
    #     slot = row_replan['slot']
    #     frozen = self.Flights[
    #         (self.Flights['runway'] == runway) &
    #         (self.Flights['planningstate'] == 'frozen') &
    #         (self.Flights['slot'] > slot)
    #     ].sort_values('slot')
    #
    #
    #     last_row  = self.Flights[self.Flights[
    #         (self.Flights['runway'] == runway) &
    #         (self.Flights['planningstate'] == 'frozen') &
    #         (self.Flights['slot'] < slot)
    #     ].sort_values('slot').idxmax()]
    #     last_assigned_slot, last_assigned_flight, last_assigned_type = last_row['slot'], last_row.name, last_row['type']
    #
    #     swaps = 0
    #     for idx, row in frozen.iterrows():
    #         if not np.isnan(row['manualslot']):
    #             slot = row['manualslot']
    #             separation = 0
    #         elif last_assigned_slot is None:
    #             # First flight's slot is its ETA minus early aim
    #             slot = row['ETA']
    #             separation = 0
    #         else:
    #             # Subsequent flight's slot is the last slot + separation
    #
    #             if self.dynamic_LIV:
    #                 separation = self.LIV_separation.required_separation(last_assigned_flight, last_assigned_type, idx,
    #                                                                      row['type'])
    #             else:
    #                 separation = self.separation
    #             slot = max(last_assigned_slot + separation, row['ETA'] - self.standard_early)
    #
    #         # Update the slot in the DataFrame
    #         self.Flights.loc[idx, ['slot', 'EAT', 'LIV', 'LAS', 'LAf']] = [
    #             slot,
    #             slot - row['TMA'],
    #             separation,
    #             last_assigned_slot,
    #             last_assigned_flight,
    #         ]
    #
    #
    #         # Update last assigned variables
    #         last_assigned_slot, last_assigned_flight, last_assigned_type = slot, idx, row['type']
    #
    #     self.Flights = self.Flights.sort_values(by=['slot', 'ETA'], ascending=False)
    #
    # def replan_late(self, acid, ETA=None):
    #
    #     acid = acid.upper()
    #     row_replan = self.Flights.loc[acid]
    #
    #     if ETA is None:
    #         ETA = row_replan['ETA']
    #     self.Flights.at[acid, 'ETA'] = ETA
    #     runway = row_replan['runway']
    #     slot0 = row_replan['slot']
    #
    #     # Alle frozen vluchten op deze runway met geldige slot
    #     runway_frozen = self.Flights[
    #         (self.Flights['runway'] == runway) &
    #         (self.Flights['planningstate'] == 'frozen') &
    #         (self.Flights['slot'].notna())
    #     ]
    #
    #
    #     # Tail: alles vanaf en inclusief acid (slot >= slot0), op huidige slotvolgorde
    #     tail = runway_frozen[runway_frozen['slot'] >= slot0].sort_values('slot')
    #
    #     original_order = list(tail.index)
    #
    #     # Vluchten vóór de tail blijven staan; pak laatste frozen vóór slot0 als startpunt
    #     before = runway_frozen[runway_frozen['slot'] < slot0].sort_values('slot')
    #     if before.empty:
    #         last_slot = None
    #         last_acid = None
    #         last_type = None
    #     else:
    #         last_row = before.iloc[-1]
    #         last_slot = last_row['slot']
    #         last_acid = last_row.name
    #         last_type = last_row['type']
    #
    #     # Nieuwe volgorde van de tail: sorteer op ETA (tie-breaker oude slot)
    #     tail_sorted = self.Flights.loc[original_order].sort_values(['ETA', 'slot'])
    #     new_order = list(tail_sorted.index)
    #
    #     # Tail opnieuw plannen in nieuwe volgorde
    #     for f in new_order:
    #         row = self.Flights.loc[f]
    #         if last_slot is None:
    #             # Eerste in de hele rij op deze runway
    #             separation = 0.0
    #             slot = row['ETA']
    #         else:
    #             # Overige: slot = vorige slot + separation (of ETA-early, wat later is)
    #             if self.dynamic_LIV:
    #                 separation = self.LIV_separation.required_separation(
    #                     last_acid, last_type, f, row['type']
    #                 )
    #             else:
    #                 separation = self.separation
    #
    #             slot = max(last_slot + separation, row['ETA'])
    #
    #         # Schrijf planning terug
    #         self.Flights.at[f, 'slot'] = slot
    #         self.Flights.at[f, 'LIV'] = separation
    #         self.Flights.at[f, 'LAS'] = last_slot
    #         self.Flights.at[f, 'LAf'] = last_acid
    #
    #         if pd.notna(row['TMA']):
    #             self.Flights.at[f, 'EAT'] = slot - row['TMA']
    #
    #         last_slot = slot
    #         last_acid = f
    #         last_type = row['type']
    #
    #     # Aantal positie-swaps (inversies) t.o.v. de oude volgorde
    #     pos_new = {ac: i for i, ac in enumerate(new_order)}
    #     idxlist = [pos_new[ac] for ac in original_order]
    #     swaps = 0
    #     n = len(idxlist)
    #     for i in range(n):
    #         for j in range(i + 1, n):
    #             if idxlist[i] > idxlist[j]:
    #                 swaps += 1
    #
    #     # Swaps-kolom waarborgen en bijhouden op de herplande vlucht
    #     if 'swaps' not in self.Flights.columns:
    #         self.Flights['swaps'] = 0
    #         self.Flights['swaps'] = self.Flights['swaps'].astype(int)
    #
    #     self.Flights.at[acid, 'swaps'] += int(swaps)
    #
    #     # Optioneel: hele Flights weer netjes sorteren
    #     self.Flights.sort_values(['slot', 'ETA'], ascending=[True, True], inplace=True)





    @stack.command
    def printseed(self):

        print('seed: ', self.errorgenerator.seed)

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






