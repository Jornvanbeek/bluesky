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


from plugins.amanhelpers.amanpredictionhandler import PredictionHandler
from plugins.amanhelpers.errorhandler import ErrorHandler
from plugins.amanhelpers.amanexport import AmanExporter
import warnings


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
        columns = ['ACID', 'planningstate', 'planningtype', 'creation', 'ETD', 'ttlg', 'to eto', 'type', 'LIV', 'ETA', 'delayed ETA', 'ETO IAF', 'ETO_original', 'TP IAF', 'TP ETA', 'IAF', 'runway', 'EAT', 'slot', 'initialslot', 'manualslot', 'TMA', 'EAT adherence', 'LAS', 'LAf', 'origin', 'popup', 'TPstate', 'EAT_updates','count', 'updates','Flighttime', 'TP accuracy', 'casdesc', 'max_casdesc', 'min_casdesc', 'E_TO','fh_margin', 'fh_margin_at_spawn', 'fh_margin_at_freeze', 'percentile_time','E_dep', 'E_enroute', 'E_fir', 'gsfactor',  'planning', 'SID', 'FIR entry', 'Time error', 'Error at Freeze', 'ttlg at freeze', 'minwork', 'totalwork', 'extrawork', 'swaps', 'lookahead', 'holdingtime', 'pending_delay']
        self.Flights = pd.DataFrame(columns = columns)
        self.Flights.set_index('ACID', inplace=True)
        # --- explicit dtypes for non-numeric columns (prevents FutureWarning on assignment) ---
        self.obj_cols = [
            'planningstate', 'planningtype', 'type', 'IAF', 'runway', 'origin', 'popup', 'TPstate',
            'SID', 'FIR entry']
        self.intcols = ['EAT_updates', 'count', 'updates', 'swaps']
        self.boolcols = ['dogleg', 'direct', 'holding', 'earliest']
        self.set_coltype(self.intcols, 'int64')
        self.set_coltype(self.obj_cols, 'object')
        self.set_coltype(self.boolcols, 'bool')

        self.not_spawned = defaultdict(list)
        self.aman_parent_id = None
        self.LIV_separation = LivSeparation()
        self.errorgenerator = ErrorGenerator() #todo check seed
        self.shiftflight = shiftflight()
        self.cntrlz = None          # planning times backup
        self.starttime = time.time()

        # self.Flights['updates'] = 0
        # self.Flights['updates'] = self.Flights['updates'].astype(int)
        traf.update_pos = self.update_pos_error

    def set_coltype(self, cols, dtype):
        """Set column dtypes safely, also when the DataFrame is still empty.

        Key point: don't use fillna(0) for object/bool columns.
        """
        for c in cols:
            if c not in self.Flights.columns:
                continue

            # If the DF is empty, keep an empty Series with the right dtype.
            if len(self.Flights.index) == 0:
                self.Flights[c] = pd.Series(dtype=dtype, index=self.Flights.index)
                continue

            # Int/counter columns
            if str(dtype) in ('int64', 'int32', 'int'):
                self.Flights[c] = self.Flights[c].fillna(0).astype(dtype)

            # Nullable boolean is safer than plain bool when NaNs exist
            elif str(dtype) in ('bool', 'boolean'):
                target = 'boolean' if str(dtype) == 'bool' else dtype
                self.Flights[c] = self.Flights[c].astype(target)

            # Object/string columns
            else:
                self.Flights[c] = self.Flights[c].astype(dtype)


    # update of planningstates, core functionality
    @core.timed_function(dt= 30)
    def update_planningstate(self):
        if self.aman_parent_id or traf.ntraf == 0:
            return

        self.update_times()
        self.origin()
        # self.popup()
        self.maskpopup()
        self.preplan()
        self.update_times()
        self.planpopup()
        self.update_times()
        self.assignslots()
        self.update_times()
        self.freeze()
        # self.tma()
        self.update_times()
        stack.stack('instruct_frozen')

    @core.timed_function(dt= 6)
    def update_errors_timed(self):

        self.update_traf_gsfactor_from_flights(self.Flights, sim.simt)

    # def popup(self):
    #
    #     # 1. Filter aircraft that have planningstate == 'new' and (ETO IAF - sim.simt) < freezehorizon
    #     mask_popup = (
    #             (self.Flights['planningstate'] == 'new')
    #             & ((self.Flights['ETO IAF'] - sim.simt) < self.freezehorizon)
    #     )
    #     if not mask_popup.any():
    #         return
    #
    #     popup_candidates = self.Flights[mask_popup].sort_values(by='ETA')
    #
    #
    #     for acid, row in popup_candidates.iterrows():
    #         idxac = traf.id2idx(acid)
    #         if idxac < 0:
    #             continue  # Not yet in traf
    #
    #         alt_ft = round(traf.alt[idxac] / ft)
    #         if alt_ft < self.visible_altitude:
    #             # Below FL100, skip assigning slot (remain 'new')
    #             continue
    #
    #
    #         runway = row['runway']
    #
    #         # Find the flight on the same runway whose ETO IAF is just earlier
    #         # and that already has a slot assigned
    #
    #         earlier_df = self.Flights[
    #             (self.Flights['ETO IAF'] < row['ETO IAF'])
    #             & (self.Flights['runway'] == runway)
    #             & (self.Flights['slot'].notna())
    #             ].sort_values(by='ETA')
    #
    #         if earlier_df.empty:
    #             # No earlier slot => use own ETA
    #             new_slot = row['ETA']
    #         else:
    #             last_earlier = earlier_df.iloc[-1]
    #             slot_earlier = last_earlier['slot']
    #             if self.dynamic_LIV:
    #                 separation = self.LIV_separation.required_separation(
    #                     last_earlier.name, last_earlier['type'],
    #                     acid, row['type']
    #                 )
    #
    #             else:
    #                 separation = self.separation
    #
    #             new_slot = max(slot_earlier + separation, row['ETA'])
    #
    #         self.Flights.at[acid, 'slot'] = new_slot
    #
    #         if pd.notna(row['TMA']):
    #             self.Flights.at[acid, 'EAT'] = new_slot - row['TMA']
    #
    #         # Color and set planningstate to 'POPUP'
    #         stack.stack(f"COLOR {acid} 255,0,0")
    #         self.Flights.at[acid, 'planningstate'] = 'POPUP'
    #         self.Flights.at[acid, 'popup'] = 'POPUP'

    def assign_slot_bookkeep(
            self,
            acid: str,
            row: pd.Series,
            *,
            eta: float,
            prev_slot: float | None,
            prev_acid: str | None,
            prev_type: str | None,
            write_initial: bool = False,
            force_back_of_queue: bool = False,
    ):
        """
        Berekent een slot en schrijft meteen slot + bookkeeping weg:
        slot, (optional initialslot), EAT, LIV, LAS, LAf.

        - eta: de ETA die jij wil gebruiken (ETA of delayed ETA etc)
        - prev_*: de voorganger in de sequence (slot + acid + type)
        - write_initial: zet ook initialslot gelijk aan slot
        - force_back_of_queue: zet slot = prev_slot + separation (dus echt 'achteraan'),
          i.p.v. max(prev_slot+sep, eta-standard_early)
        Returns: (slot, sep)
        """

        # separation
        if prev_slot is None:
            sep = 0.0
        else:
            if self.dynamic_LIV:
                sep = float(self.LIV_separation.required_separation(prev_acid, prev_type, acid, row['type']))
            else:
                sep = float(self.separation)

        # base target slot (early aim)
        base = float(eta) - float(self.standard_early)

        # slot rule
        if prev_slot is None:
            slot = base
        else:
            if force_back_of_queue:
                slot = max(float(prev_slot) + sep, (eta - self.replan_pull_forward))
            else:
                slot = max(float(prev_slot) + sep, base)

        # write to DF
        cols = ['slot', 'EAT', 'LIV', 'LAS', 'LAf']
        vals = [slot, slot - float(row['TMA']), sep, prev_slot, prev_acid]

        if write_initial:
            cols.insert(1, 'initialslot')
            vals.insert(1, slot)

        self.eat_update_plusone(slot, acid)

        self.Flights.loc[acid, cols] = vals
        return slot, sep

    def eat_update_plusone(self, slot, flight):
        """Increment EAT_updates only when the flight is frozen."""
        if flight not in self.Flights.index:
            return

        # Only count slot/EAT updates once the flight is frozen
        if self.Flights.at[flight, 'planningstate'] in ['preplanned', 'ground']:
            return

        self.Flights['EAT_updates'] = self.Flights['EAT_updates'].fillna(0).astype(int)
        old_slot = self.Flights.at[flight, 'slot']
        # Only count as an update if the slot change exceeds a threshold (seconds)
        thr = float(getattr(self, 'eat_count_threshold', 0.0) or 0.0)

        cur = self.Flights.at[flight, 'EAT_updates']
        if pd.isna(cur):
            cur = 0

        if pd.notna(old_slot):

            delta = abs(float(slot) - float(old_slot))
            if delta > thr:
                # self.Flights.at[flight, 'EAT_updates'] = int(self.Flights.at[flight, 'EAT_updates']) + 1
                self.Flights.at[flight, 'EAT_updates'] = int(cur) + 1

                
    def update_popup_entry(self,acid):
        stack.stack(f"COLOR {acid} 255,128,0")
        self.Flights.at[acid, 'planningstate'] = 'frozen'
        self.Flights.loc[acid, 'Error at Freeze'] = self.Flights.loc[acid, 'Time error']
        ttlg = self.Flights.loc[acid, 'ttlg']
        if ttlg == 0 or pd.isna(ttlg):
            ttlg = self.Flights.loc[acid, 'EAT'] - self.Flights.loc[acid, 'ETO IAF']
        self.Flights.loc[acid, 'ttlg at freeze'] = self.Flights.loc[acid, 'ttlg']

        if 'fh_margin_at_freeze' in self.Flights.columns:
            idxac = traf.id2idx(acid)
            alt_ft = round(traf.alt[idxac] / ft)
            self.Flights.loc[acid, 'fh_margin_at_freeze'] = (self.Flights.loc[acid, 'ETO IAF'] - sim.simt) - self.freezehorizon
            self.Flights.at[acid, 'alt_at_freeze'] = alt_ft
        self.Flights.at[acid, 'popup'] = 'POPUP'

    def maskpopup(self):
        plannertype = self.popup_planner

        # FCFS special rule: if the aircraft is already spawned but still below the visible altitude,
        # keep it as 'new' (do not treat it as popup yet).
        if plannertype == 'FCFS':
            mask_popup = (
                    (self.Flights['planningstate'].isin(['new']))
                    & ((self.Flights['ETO IAF'] - sim.simt) < self.freezehorizon)
            )

            # Default: mark as POPUP
            self.Flights.loc[mask_popup, 'planningstate'] = 'POPUP'

            low_alt = []
            for acid in self.Flights.index[mask_popup]:
                idxac = traf.id2idx(acid)
                if idxac < 0:
                    continue
                alt_ft = round(traf.alt[idxac] / ft)

                origin = self.Flights.loc[acid, 'origin']
                if origin in self.visible_altitude_specific.keys():
                    if alt_ft < self.visible_altitude_specific[origin]:
                        low_alt.append(acid)

                elif alt_ft < self.standard_visible_altitude:
                    low_alt.append(acid)
            if low_alt:
                self.Flights.loc[low_alt, 'planningstate'] = 'new'

        elif plannertype == 'EFDFCFS':
            # EFDFCFS behaves like FCFS for sequencing, but does NOT use altitude-gating for popup visibility.
            mask_popup = (
                    (self.Flights['planningstate'].isin(['new']))
                    & ((self.Flights['ETO IAF'] - sim.simt) < self.freezehorizon)
            )
            self.Flights.loc[mask_popup, 'planningstate'] = 'POPUP'



        elif plannertype in ('DELAY', 'BACK', 'EFDBACK'):
            mask_popup = (
                    (self.Flights['planningstate'].isin(['new']))
                    & ((self.Flights['ETO IAF'] - sim.simt) < self.freezehorizon)
            )

            # Default: mark as POPUP
            self.Flights.loc[mask_popup, 'planningstate'] = 'POPUP'

        mask_early = (
                (self.Flights['planningstate'].isin(['early popup']))
                & ((self.Flights['ETO IAF'] - sim.simt) < self.freezehorizon)
        )
        # Convert the ground mask to only those that are actually spawned (idx >= 0)
        spawned_ground = [acid for acid in self.Flights.index[mask_early] if traf.id2idx(acid) >= 0]

        self.Flights.loc[spawned_ground, 'planningstate'] = 'POPUP'


    def planpopup(self):
        plannertype = self.popup_planner
        # print(plannertype)
        # self.returnplanner()
        # print(settings.popup_planner)
        # print(plannertype == 'FCFS')
        # print()
        if plannertype in ('FCFS', 'EFDFCFS'):
            mask_popup = (
                    (self.Flights['planningstate'] == 'POPUP')
                    & ((self.Flights['ETO IAF'] - sim.simt) < self.freezehorizon)
            )
            popup_candidates = self.Flights[mask_popup].sort_values(by='ETA')

            for acid, row in popup_candidates.iterrows():
                idxac = traf.id2idx(acid)
                if idxac < 0:
                    continue  # Not yet in traf

                runway = row['runway']
                # sim.hold()

                # print('holding because of popup ', acid)
                self.totwohtml()
                earlier_df = self.Flights[
                    (self.Flights['ETA'] < row['ETA'])
                    & (self.Flights['runway'] == runway)
                    & (self.Flights['slot'].notna())
                    # & (self.Flights['planningstate'] == 'frozen')
                    ].sort_values(by='slot')

                if earlier_df.empty:
                    prev_slot = None
                    prev_acid = None
                    prev_type = None
                else:
                    last_earlier = earlier_df.iloc[-1]
                    prev_slot = float(last_earlier['slot'])
                    prev_acid = last_earlier.name
                    prev_type = last_earlier['type']

                new_slot, sep = self.assign_slot_bookkeep(
                    acid, row,
                    eta=float(row['ETA']),
                    prev_slot=prev_slot,
                    prev_acid=prev_acid,
                    prev_type=prev_type,
                    write_initial=True
                )
                # Color to 'POPUP'
                self.update_popup_entry(acid) #function for color, error at freeze etc.


                later_df = self.Flights[
                    (self.Flights['ETA'] > row['ETA'])
                    & (self.Flights['runway'] == runway)
                    & (self.Flights['slot'].notna())
                    & (self.Flights['planningstate'] == 'frozen')
                    ].sort_values(by='slot')

                # Bookkeeping: FCFS popup causes a swap for all frozen flights behind it
                if not later_df.empty:
                    if 'swaps' not in self.Flights.columns:
                        self.Flights['swaps'] = 0
                    self.Flights['swaps'] = self.Flights['swaps'].fillna(0).astype(int)
                    self.Flights.loc[later_df.index, 'swaps'] += 1


                last_assigned_slot = new_slot
                last_assigned_flight = acid
                last_assigned_type = row['type']

                self.replanslots(later_df, last_assigned_slot, last_assigned_flight, last_assigned_type)

            # Ensure object dtype before assignment to avoid FutureWarning
            self.Flights['planningtype'] = self.Flights['planningtype'].astype('object')
            self.Flights.loc[mask_popup, 'planningtype'] = 'EFDFCFS' if plannertype == 'EFDFCFS' else 'FCFS'



        elif plannertype in ('DELAY', 'BACK', 'EFDBACK'):

            airborne_popup = (
                    (self.Flights['planningstate'] == 'POPUP')
                    & (self.Flights['ETO IAF'] - sim.simt < self.freezehorizon)
            )

            for acid, row in self.Flights[airborne_popup].iterrows():
                idxac = traf.id2idx(acid)
                if idxac < 0:
                    continue
                runway = row['runway']
                frozen_df = self.Flights[
                    (self.Flights['runway'] == runway)
                    & (self.Flights['slot'].notna())
                    & (self.Flights['planningstate'] == 'frozen')
                    ].sort_values(by='slot')

                if frozen_df.empty:
                    prev_slot = None
                    prev_acid = None
                    prev_type = None
                else:
                    last = frozen_df.iloc[-1]
                    prev_slot = float(last['slot'])
                    prev_acid = last.name
                    prev_type = last['type']

                slot, sep = self.assign_slot_bookkeep(
                    acid, row,
                    eta=float(row['ETA']),  # eta wordt hier toch niet gebruikt door force_back_of_queue
                    prev_slot=prev_slot,
                    prev_acid=prev_acid,
                    prev_type=prev_type,
                    write_initial=True,
                    force_back_of_queue=True
                )
                self.update_popup_entry(acid) #function for color, error at freeze etc.
            # Ensure object dtype before assignment to avoid FutureWarning
            self.Flights['planningtype'] = self.Flights['planningtype'].astype('object')
            if plannertype == 'EFDBACK':
                self.Flights.loc[airborne_popup, 'planningtype'] = 'efdback'
            elif plannertype == 'BACK':
                self.Flights.loc[airborne_popup, 'planningtype'] = 'back of the line'
            else:
                self.Flights.loc[airborne_popup, 'planningtype'] = 'airborne'


    def replan_late_popup(self, acid):
        """Remove a too-late popup from the frozen chain.

        Requirements:
        - The popup loses its slot immediately.
        - Flights behind it on the same runway get earlier slots (compressed).
        - The popup is reset so that when it spawns/creates again it is treated like a normal popup.

        Implementation notes:
        - Uses stored `LAS` (previous slot) and `LAf` (previous flight) from the DataFrame.
        - Uses `replanslots(..., force_compress=True)` for compression.
        """
        sim.hold()
        print('replanning late popup ', acid)

        if acid not in self.Flights.index:
            return

        runway = self.Flights.at[acid, 'runway']
        if pd.isna(runway) or runway == '':
            return

        old_slot = self.Flights.at[acid, 'slot']
        if pd.isna(old_slot):
            return
        old_slot = float(old_slot)

        # Only compress if the flight is currently part of the frozen chain
        was_frozen = (self.Flights.at[acid, 'planningstate'] == 'frozen')

        # Determine predecessor from stored bookkeeping
        last_assigned_slot = self.Flights.at[acid, 'LAS']
        last_assigned_flight = self.Flights.at[acid, 'LAf']

        if pd.isna(last_assigned_slot):
            last_assigned_slot = None
        else:
            last_assigned_slot = float(last_assigned_slot)

        if pd.isna(last_assigned_flight) or last_assigned_flight == 'None':
            last_assigned_flight = None

        if last_assigned_flight is not None and last_assigned_flight in self.Flights.index:
            last_assigned_type = self.Flights.at[last_assigned_flight, 'type']
        else:
            last_assigned_type = None

        # Flights behind the removed popup (same runway, frozen)
        after_df = self.Flights[
            (self.Flights['runway'] == runway)
            & (self.Flights['planningstate'] == 'frozen')
            & (self.Flights['slot'].notna())
            & (self.Flights['slot'] > old_slot)
        ].sort_values('slot')

        # Bookkeeping: all flights behind the removed popup get swaps += 1
        if not after_df.empty:
            if 'swaps' not in self.Flights.columns:
                self.Flights['swaps'] = 0
            self.Flights['swaps'] = self.Flights['swaps'].fillna(0).astype(int)
            self.Flights.loc[after_df.index, 'swaps'] += 1

        # 1) Compress the frozen chain behind the removed popup
        if was_frozen and (last_assigned_slot is not None) and (not after_df.empty):
            self.replanslots(
                after_df,
                last_assigned_slot,
                last_assigned_flight,
                last_assigned_type,
                force_compress=True,
            )

        # 2) Remove the popup's reserved slot and reset state
        # Make it eligible to be treated as a normal popup again once (re)created.
        self.Flights.at[acid, 'planningstate'] = 'late popup'

        # Clear slot-related fields
        for c in ('slot', 'EAT', 'manualslot', 'LIV', 'LAS', 'LAf', 'slot'):
            if c in self.Flights.columns:
                self.Flights.at[acid, c] = np.nan

        # Optional bookkeeping cleanup
        if 'planningtype' in self.Flights.columns:
            self.Flights['planningtype'] = self.Flights['planningtype'].astype('object')
            self.Flights.at[acid, 'planningtype'] = 'late popup'
        if 'popup' in self.Flights.columns:
            self.Flights['popup'] = self.Flights.get('popup', pd.Series(dtype='object')).astype('object')
            self.Flights.at[acid, 'popup'] = 'POPUP'






    def replanslots(self, df, last_assigned_slot, last_assigned_flight, last_assigned_type, force_compress: bool = False):

        for flight, row in df.iterrows():
            if self.dynamic_LIV:
                separation = self.LIV_separation.required_separation(last_assigned_flight, last_assigned_type, flight, row['type'])
            else:
                separation = self.separation

            # If there's a gap, the default behaviour is to stop replanning and keep remaining slots as-is.
            # For some operations (e.g. removing a flight from the frozen chain) we want to fully compress.
            if (not force_compress) and (row['slot'] > last_assigned_slot + separation):
                slot = row['slot']
                last_assigned_slot, last_assigned_flight, last_assigned_type = slot, flight, row['type']
                break

            slot = last_assigned_slot + separation

            self.eat_update_plusone(slot, flight)

            self.Flights.loc[flight, ['slot', 'EAT', 'LIV', 'LAS', 'LAf']] = [
                slot,
                slot - row['TMA'],
                separation,
                last_assigned_slot,
                last_assigned_flight,
            ]
            last_assigned_slot, last_assigned_flight, last_assigned_type = slot, flight, row['type']

        return last_assigned_slot, last_assigned_flight, last_assigned_type



    def preplan(self):
        # 1) Find flights that go from 'new' to 'preplanned'
        mask_new = (
                (self.Flights['planningstate'] == 'new')
                & ((self.Flights['ETO IAF'] - sim.simt) < self.planninghorizon))

        if not mask_new.any():
            return
        new_candidates = self.Flights[mask_new]

        for acid, row in new_candidates.iterrows():
            idxac = traf.id2idx(acid)
            if idxac < 0:
                continue  # Not in traf yet

            # Check altitude in feet

            origin = self.Flights.loc[acid, 'origin']

            # For DELAY  / EFDBACK: do not use altitude-gating for becoming preplanned.
            # This prevents fast-spawned aircraft from becoming POPUP before reaching FL100.
            if self.popup_planner in ('DELAY', 'EFDBACK', 'EFDFCFS'):
                self.Flights.at[acid, 'planningstate'] = 'preplanned'
                stack.stack(f"COLOR {acid} 0,150,255")
                continue

            # Default behaviour (FCFS): altitude gate
            alt_ft = round(traf.alt[idxac] / ft)

            if origin in self.visible_altitude_specific.keys():
                if alt_ft >= self.visible_altitude_specific[origin]:
                    self.Flights.at[acid, 'planningstate'] = 'preplanned'
                    stack.stack(f"COLOR {acid} 0,150,255")
            elif alt_ft >= self.standard_visible_altitude:  # FL100
                # Now we flip them to 'preplanned'
                self.Flights.at[acid, 'planningstate'] = 'preplanned'
                stack.stack(f"COLOR {acid} 0,150,255")


    def assignslots(self):
        if self.aman_parent_id:
            return

        for runway in self.Flights['runway'].unique():
            # Filter frozen and preplanned flights for the current runway
            frozen_flights = self.Flights.query("planningstate == 'frozen' and runway == @runway")

            if self.popup_planner == 'DELAY':
                # Include preplanned + ground, and sort by delayed ETA
                mask = (
                        (self.Flights['runway'] == runway)
                        & (self.Flights['planningstate'].isin(['preplanned', 'ground']))
                )

                # Ensure 'delayed ETA' exists for sorting.
                # Preplanned: delayed ETA = ETA
                pmask = mask & (self.Flights['planningstate'] == 'preplanned')
                self.Flights.loc[pmask, 'delayed ETA'] = self.Flights.loc[pmask, 'ETA']

                preplanned_flights = self.Flights[mask].sort_values(by='delayed ETA')
                groundmask = mask & (self.Flights['planningstate'] == 'ground')
                self.Flights.loc[groundmask, 'planningtype'] = 'pre-onground'


            else:
                # FCFS/default: only preplanned, sort by ETA
                preplanned_flights = self.Flights.query(
                    "planningstate == 'preplanned' and runway == @runway"
                ).sort_values(by='ETA')



            # Initialize last assigned variables
            if not frozen_flights.empty:
                max_row = frozen_flights.loc[frozen_flights['slot'].idxmax()]
                last_assigned_slot, last_assigned_flight, last_assigned_type = max_row['slot'], max_row.name, max_row['type']
            else:
                last_assigned_slot = last_assigned_flight = last_assigned_type = None


            # Iterate over the filtered DataFrame and calculate slots
            for idx, row in preplanned_flights.iterrows():
                eta = row['ETA']
                if 'delayed ETA' in row.index and pd.notna(row['delayed ETA']):
                    eta = row['delayed ETA']

                slot, sep = self.assign_slot_bookkeep(
                    idx, row,
                    eta=float(eta),
                    prev_slot=last_assigned_slot,
                    prev_acid=last_assigned_flight,
                    prev_type=last_assigned_type,
                    write_initial=True
                )

                last_assigned_slot, last_assigned_flight, last_assigned_type = slot, idx, row['type']
                stack.stack(f'COLOR {idx} 0,150,255')

                # Update last assigned variables



        self.Flights = self.Flights.sort_values(by=['slot', 'ETA'], ascending=False)




    def freeze(self):
        for runway, runway_df in self.Flights.groupby('runway'):
            # Freeze aircraft with flighttime < 14 minutes and preplanned within this runway
            newfrozen = runway_df[(runway_df['planningstate'] == 'preplanned') & ((runway_df['ETO IAF'] - sim.simt) < self.freezehorizon)]
            # Get the maximum slot of the newfrozen aircraft within this runway
            max_slot_newfrozen = newfrozen['slot'].max()

            # Ground flights with a slot that should become frozen when their *delayed* ETO IAF is inside the horizon.
            # delayed ETO IAF is derived as: (delayed ETA - TMA). If delayed ETA is missing, fall back to ETA.
            delayed_eta = runway_df['delayed ETA'] if 'delayed ETA' in runway_df.columns else runway_df['ETA']
            # delayed_eta = delayed_eta.fillna(runway_df['ETA'])
            delayed_eto_iaf = delayed_eta - runway_df['TMA']

            ground_to_freeze = runway_df[
                (runway_df['planningstate'] == 'ground')
                & (runway_df['slot'].notna())
                & ((delayed_eto_iaf - sim.simt) < self.freezehorizon)
            ]

            # Combine indices to freeze
            freeze_idx = newfrozen.index.union(ground_to_freeze.index)

            # Get the maximum slot of the newly frozen aircraft within this runway
            max_slot_newfrozen = runway_df.loc[freeze_idx, 'slot'].max()

            # Select all preplanned flights with a slot earlier than max_slot_newfrozen within this runway
            preplanned_before_max_slot = runway_df[
                (runway_df['planningstate'] == 'preplanned')
                & (runway_df['slot'] < max_slot_newfrozen)
            ]

            # Set their planningstate to 'frozen'
            self.Flights.loc[freeze_idx, 'planningstate'] = 'frozen'
            self.Flights.loc[freeze_idx, 'Error at Freeze'] = self.Flights.loc[freeze_idx, 'Time error']
            self.Flights.loc[freeze_idx, 'ttlg at freeze'] = self.Flights.loc[freeze_idx, 'ttlg']

            self.Flights.loc[preplanned_before_max_slot.index, 'planningstate'] = 'frozen'
            self.Flights.loc[preplanned_before_max_slot.index, 'Error at Freeze'] = self.Flights.loc[preplanned_before_max_slot.index, 'Time error']
            self.Flights.loc[preplanned_before_max_slot.index, 'ttlg at freeze'] = self.Flights.loc[
                preplanned_before_max_slot.index, 'ttlg']

            self.color(self.Flights.loc[freeze_idx], '100,255,100')
            self.color(preplanned_before_max_slot, '100,255,100')

            self.Flights.loc[ground_to_freeze.index, 'planningtype'] = 'ground freeze'

            # if not ground_to_freeze.empty:
            #     sim.hold()
            #     print('holding to freeze on ground ')
            #     print(ground_to_freeze)



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

        # Define the column names (keep in sync with __init__)
        columns = ['ACID', 'planningstate', 'planningtype', 'creation', 'ETD', 'ttlg', 'to eto', 'type', 'LIV', 'ETA',
                   'delayed ETA', 'ETO IAF', 'ETO_original', 'TP IAF', 'TP ETA', 'IAF', 'runway', 'EAT', 'slot',
                   'initialslot', 'manualslot', 'TMA', 'EAT adherence', 'LAS', 'LAf', 'origin', 'popup', 'TPstate',
                   'EAT_updates', 'count', 'updates', 'Flighttime', 'TP accuracy', 'casdesc', 'max_casdesc',
                   'min_casdesc', 'E_TO', 'fh_margin', 'fh_margin_at_spawn', 'fh_margin_at_freeze', 'percentile_time', 'E_dep', 'E_enroute', 'E_fir', 'gsfactor', 'planning', 'SID',
                   'FIR entry', 'Time error', 'Error at Freeze', 'ttlg at freeze', 'minwork', 'totalwork', 'extrawork', 'swaps',
                   'lookahead', 'holdingtime', 'pending_delay']
        self.Flights = pd.DataFrame(columns = columns)
        self.Flights.set_index('ACID', inplace=True)
        self.set_coltype(self.intcols, 'int64')
        self.set_coltype(self.obj_cols, 'object')
        self.set_coltype(self.boolcols, 'bool')

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
            try:
                self.Flights.loc[flight, 'fh_margin_at_spawn'] = int((self.Flights.loc[flight, 'ETO IAF'] - sim.simt) - self.freezehorizon)
            except:
                print(self.Flights.loc[flight, 'ETO IAF'])
                return


    def update_times(self):
        if self.aman_parent_id:
            return

        # error introduction here
        # self.Flights['totalerror'] = self.Flights['creation'] + self.Flights['deproute'] + self.Flights['outsidefir'] + self.Flights
        # self.Flights['ETA'] = self.Flights['correct_ETA'] + self.Flights['totalerror']
        self.Flights['TMA'] = self.Flights['TP ETA'] - self.Flights['TP IAF']
        self.update_errors()

        self.Flights['TMA'] = self.Flights['TP ETA'] - self.Flights['TP IAF']
        try:
            self.Flights['to eto'] = round((self.Flights['ETO IAF'] - sim.simt) / 60, 0)
        except:
            (self.Flights['ETO IAF'] - sim.simt) / 60
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
    #     before = self.Flights[
    #         (self.Flights['runway'] == runway) &
    #         (self.Flights['planningstate'] == 'frozen') &
    #         (self.Flights['slot'] < slot)
    #         ].sort_values('slot')
    #
    #     if before.empty:
    #         last_assigned_slot = None
    #         last_assigned_flight = None
    #         last_assigned_type = None
    #     else:
    #         last_row = before.iloc[-1]  # laatste op basis van slot
    #         last_assigned_slot = last_row['slot']
    #         last_assigned_flight = last_row.name
    #         last_assigned_type = last_row['type']
    #
    #     swaps = 0
    #     replanned = False
    #     for flight, row in frozen.iterrows():
    #         if ETA <= row['ETA'] and not replanned:
    #             # put too late flight in this slot first, then plan the rest
    #
    #             if last_assigned_slot is None:
    #                 # First flight's slot is its ETA or slot, whichever is lower
    #                 slot = min(row['ETA'], row['slot'])
    #                 separation = 0
    #             else:
    #                 # Subsequent flight's slot is the last slot + separation
    #
    #                 if self.dynamic_LIV:
    #                     separation = self.LIV_separation.required_separation(last_assigned_flight, last_assigned_type,
    #                                                                          acid,
    #                                                                          row_replan['type'])
    #                 else:
    #                     separation = self.separation
    #
    #                 # If a flight in between disappears, the next flight should inherit the vacated slot.
    #                 # So we always compress the sequence by assigning the next slot directly behind the previous one,
    #                 # even if the flight cannot make it based on ETA.
    #                 # slot = float(last_assigned_slot) + float(separation)
    #
    #                 slot = max(last_assigned_slot + separation, (ETA- self.late_approach_margin))
    #
    #             self.eat_update_plusone(slot, acid)
    #
    #             self.Flights.loc[acid, ['slot', 'EAT', 'LIV', 'LAS', 'LAf']] = [
    #                 slot,
    #                 slot - row_replan['TMA'],
    #                 separation,
    #                 last_assigned_slot,
    #                 last_assigned_flight,
    #             ]
    #             last_assigned_slot, last_assigned_flight, last_assigned_type = slot, acid, row_replan['type']
    #             replanned = True
    #
    #
    #         else:
    #             swaps +=1
    #
    #         if last_assigned_slot is None:
    #             # First flight's slot is its ETA or slot, whichever is lower
    #             slot = min(row['ETA'], row['slot'])
    #             separation = 0
    #         else:
    #             # Subsequent flight's slot is the last slot + separation
    #
    #             if self.dynamic_LIV:
    #                 separation = self.LIV_separation.required_separation(last_assigned_flight, last_assigned_type, flight,
    #                                                                      row['type'])
    #             else:
    #                 separation = self.separation
    #
    #             #to be clear, this is planning the slot of a flight that will have an earlier slot than the replanned flight
    #
    #             # If a flight in between disappears, the next flight should inherit the vacated slot.
    #             # So we always compress the sequence by assigning the next slot directly behind the previous one,
    #             # even if the flight cannot make it based on ETA.
    #             slot = max(last_assigned_slot + separation, (row['ETA']- self.late_approach_margin))
    #
    #         self.eat_update_plusone(slot, flight)
    #
    #         self.Flights.loc[flight, ['slot', 'EAT', 'LIV', 'LAS', 'LAf']] = [
    #             slot,
    #             slot - row['TMA'],
    #             separation,
    #             last_assigned_slot,
    #             last_assigned_flight,
    #         ]
    #
    #         if 'swaps' not in self.Flights.columns:
    #             self.Flights['swaps'] = 0
    #
    #         self.Flights['swaps'] = self.Flights['swaps'].fillna(0).astype(int)
    #         self.Flights.at[flight, 'swaps'] += 1
    #         print('replan late swap ', flight)
    #
    #         last_assigned_slot, last_assigned_flight, last_assigned_type = slot, flight, row['type']
    #
    #
    #     #na de for loop de hoeveelheid swaps voor de vlucht die replanned werd opslaan
    #     if 'swaps' not in self.Flights.columns:
    #         self.Flights['swaps'] = 0
    #
    #     self.Flights['swaps'] = self.Flights['swaps'].fillna(0).astype(int)
    #     self.Flights.at[acid, 'swaps'] += int(swaps)
    #     print('replan late swap ', acid, swaps)
    #
    #     self.update_times()


    def replan_late(self,acid, ETA = None):
        # simple version, only swap slots
        row_replan = self.Flights.loc[acid]
        if ETA is None:
            ETA = row_replan['ETA']
        runway = row_replan['runway']
        slot = row_replan['slot']
        # frozen = self.Flights[
        #     (self.Flights['runway'] == runway) &
        #     (self.Flights['planningstate'] == 'frozen') &
        #     (self.Flights['slot'] > slot)
        # ].sort_values('slot')

        before = self.Flights[
            (self.Flights['runway'] == runway) &
            (self.Flights['planningstate'] == 'frozen') &
            (self.Flights['slot'] < slot)
            ].sort_values('slot')

        later = self.Flights[
            (self.Flights['runway'] == runway) &
            (self.Flights['planningstate'] == 'frozen') &
            (self.Flights['slot'] > slot)
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
        replan_df = None
        row_replan_df = row_replan.to_frame().T
        row_replan_df.index = [acid]
        noswap = False

        for i, (flight, row) in enumerate(later.iterrows()):
            if (ETA <= row['slot'] and ETA < row['ETA'] - self.late_approach_margin) and not replanned:
                parts = [later.iloc[:i], row_replan_df, later.iloc[i:]]
                # parts = [p for p in parts if not p.empty]
                if len(later.iloc[:i]) == 0 or later.iloc[:i].empty:
                    parts = [row_replan_df, later.iloc[i:]]
                    noswap = True

                replan_df = pd.concat(parts, axis=0)


                replanned = True
                break
            else:
                swaps += 1

                # Bookkeeping: this frozen flight is affected by the swap (row is a copy; write to DF instead)
                if 'swaps' not in self.Flights.columns:
                    self.Flights['swaps'] = 0
                self.Flights['swaps'] = pd.to_numeric(self.Flights['swaps'], errors='coerce').fillna(0).astype(int)
                self.Flights.at[flight, 'swaps'] += 1

        if replan_df is None:
            replan_df = pd.concat([later, row_replan_df], axis=0)
            replanned = True

        if noswap and (not later.empty):
            # 1) bepaal newslot van replanned flight t.o.v. voorganger
            if last_assigned_slot is None:
                sep_prev = 0.0
                newslot = float(row_replan['ETA']) - float(self.replan_pull_forward)
            else:
                if self.dynamic_LIV:
                    sep_prev = float(self.LIV_separation.required_separation(
                        last_assigned_flight, last_assigned_type, acid, row_replan['type']
                    ))
                else:
                    sep_prev = float(self.separation)

                newslot = max(
                    float(last_assigned_slot) + sep_prev,
                    float(row_replan['ETA']) - float(self.replan_pull_forward)
                )

            # 2) bepaal required separation van replanned -> volgende vlucht
            next_flight = later.index[0]
            nextrow = later.iloc[0]
            nextslot = float(nextrow['slot'])

            if self.dynamic_LIV:
                sep_next = float(self.LIV_separation.required_separation(
                    acid, row_replan['type'], next_flight, nextrow['type']
                ))
            else:
                sep_next = float(self.separation)

            # 3) als het past: alleen replanned flight updaten; rest NIET replannen
            if (newslot + sep_next) <= nextslot:
                replan_df = row_replan_df


        for f, r in replan_df.iterrows():
            if last_assigned_slot is None:
                separation = 0.0
                newslot = r['ETA'] - self.replan_pull_forward
                prev_slot_for_bookkeep = np.nan
                prev_flight_for_bookkeep = None
            else:
                if self.dynamic_LIV:
                    separation = float(self.LIV_separation.required_separation(last_assigned_flight, last_assigned_type, f, r['type']))
                else:
                    separation = float(self.separation)
                newslot = max(last_assigned_slot + separation, r['ETA'] - self.replan_pull_forward)
                prev_slot_for_bookkeep = float(last_assigned_slot)
                prev_flight_for_bookkeep = last_assigned_flight


            last_assigned_slot = newslot
            last_assigned_flight = f
            last_assigned_type = r['type']
            self.eat_update_plusone(newslot, f)


            self.Flights.loc[f, ['slot', 'EAT', 'LIV', 'LAS', 'LAf']] = [
                float(newslot),
                float(newslot) - float(r['TMA']) if pd.notna(r['TMA']) else np.nan,
                float(separation),
                prev_slot_for_bookkeep,
                prev_flight_for_bookkeep,
            ]





        if 'swaps' not in self.Flights.columns:
            self.Flights['swaps'] = 0

        self.Flights['swaps'] = self.Flights['swaps'].fillna(0).astype(int)
        self.Flights.at[acid, 'swaps'] += int(swaps)


        self.update_times()



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
    def freezehorizon(self, minutes: float):
        self.freezehorizon = 60.* minutes
        # self.update_planningstate()
        stack.stack(f'ECHO FH set to {self.freezehorizon}')



    @stack.command
    def stopinstruct(self):
        self.instruct = False

    @stack.command
    def startinstruct(self):
        self.instruct = True

    @stack.command
    def instruct(self, value):
        """Set whether ATC instructions are enabled. Usage: INSTRUCT ON/OFF or INSTRUCT TRUE/FALSE or INSTRUCT 1/0"""
        s = str(value).strip().lower()
        if s in ('1', 'true', 't', 'yes', 'y', 'on'):
            self.instruct = True
        elif s in ('0', 'false', 'f', 'no', 'n', 'off'):
            self.instruct = False
        else:
            stack.stack("INSTRUCT expects ON/OFF (or TRUE/FALSE, 1/0). Got:", value)

    @stack.command
    def popup_planner(self, planner: str):
        """Set popup planner. Usage: POPUP_PLANNER FCFS|DELAY|BACK|EFDBACK|EFDFCFS"""
        p = str(planner).strip().upper()
        if p not in ('FCFS', 'DELAY', 'BACK', 'EFDBACK', 'EFDFCFS'):
            stack.stack("ECHO POPUPPLANNER expects 'FCFS', 'DELAY', 'BACK', 'EFDBACK', or 'EFDFCFS'. Got:", planner)
            return

        # Keep both the instance attribute and the settings module in sync
        self.popup_planner = p

        stack.stack(f"ECHO planner set to {self.popup_planner}")

    @stack.command
    def returnplanner(self):
        stack.stack(f"ECHO planner is {self.popup_planner}")

    @stack.command
    def capacity(self, per_hour):
        """Set runway capacity (ac/hr) and update separation accordingly. Usage: CAPACITY 30"""
        try:
            cap = float(per_hour)
        except Exception:
            stack.stack("CAPACITY expects a number (aircraft per hour). Got:", per_hour)
            return
        if cap <= 0:
            stack.stack("CAPACITY must be > 0. Got:", cap)
            return

        self.capacity = cap

        # separation in seconds between slots
        self.separation = round(60 * 60 / cap, 0)


    @stack.command
    def set_uncertainty(self, takeoff: float, dep_route: float, enroute: float, fir: float):
        """Set error multiplicators. Usage: SET_UNCERTAINTY 1 1 1 1"""
        try:
            vals = (float(takeoff), float(dep_route), float(enroute), float(fir))
        except Exception as e:
            stack.stack("SET_UNCERTAINTY expects 4 numbers. Error:", e)
            return

        self.error_multiplicator = vals
        settings.error_multiplicator = vals
        stack.stack(f'ECHO uncertainty set to {self.error_multiplicator}')


        # #todo list


# shorten scenario
# change method of data setting due to future warning

        # handle popups
        # define ltfm, eetn, lybe origs

        # change route if runway is changed
        # set horizons function
        # check scenario generator if it is the same as info in so6 file. (replacing aircraft is verified, not validated)