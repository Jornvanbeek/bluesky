import pandas as pd
import numpy as np
import pickle
from bluesky import core, stack, traf, network, sim
from collections import defaultdict
from plugins.amanhelpers.aman_settings import expected_delay_percentile
from plugins.amanhelpers.amanpredictionhandler import parse_destination


class ErrorHandler:

    def update_errors(self):
        # self.Flights['ETA'] = self.Flights['correct_ETA'] + error
        # self.Flights['totalerror'] = self.Flights['creation'] + self.Flights['deproute'] + self.Flights['outsidefir'] + self.Flights['insidefir']
        # self.Flights['Time error'] =
        # (SID - FH) * E_DEP
        #
        # TODO deze goed checken, met name de signs
        self.segments()
        # self.Flights['Time error'] = (
        #         -self.Flights['t_departure'].fillna(0) * self.Flights['E_dep'].fillna(0) / 100
        #         - self.Flights['t_enroute'].fillna(0) * self.Flights['E_enroute'].fillna(0) / 100
        #         - self.Flights['t_fir'].fillna(0) * self.Flights['E_fir'].fillna(0) / 100
        #     # - self.Flights['E_TO'].fillna(0) * 60
        # )

        self.Flights['Time error'] = (
                - self.Flights['t_departure'].infer_objects(copy=False).fillna(0) * self.Flights['E_dep'].infer_objects(
            copy=False).fillna(0) / 100
                - self.Flights['t_enroute'].infer_objects(copy=False).fillna(0) * self.Flights[
                    'E_enroute'].infer_objects(copy=False).fillna(0) / 100
                - self.Flights['t_fir'].infer_objects(copy=False).fillna(0) * self.Flights['E_fir'].infer_objects(
            copy=False).fillna(0) / 100
        )

        self.Flights['ETO IAF'] = self.Flights['TP IAF'] + self.Flights['Time error']


        self.Flights['ETA'] = self.Flights['ETO IAF'] + self.Flights['TMA']

        # Apply percentile_time offset (minutes -> seconds), NaN treated as 0
        pt = self.Flights['percentile_time'].fillna(0.0)
        self.Flights['delayed ETA'] = self.Flights['ETA'] + pt * 60.0

        # tdep = self.Flights['']
        #
        # self.Flights['Time error'] = -self.Flights['E_TO']*60 + self.Flights['E_dep']

    def regenerate_errors(self):
        """
        Re-run the error generator for all not_spawned predictions
        to ensure fresh errors instead of cached ones.
        """
        updated_not_spawned = defaultdict(list)

        for acid, predictions in self.not_spawned.items():
            for (wpt, wptime, flighttime, estimatedcreatetime,
                 wptpredutc, parent_id, type, origin, work) in predictions:
                # note that the errors are not stored in the previous predictions, these are stored in the TP, which does not include errors

                if wpt in self.iafs:
                    # compute lookahead in minutes
                    lookahead = round(int(self.freezehorizon - flighttime) / 60)
                    abslookahead = lookahead
                    if lookahead < 0:
                        lookahead = 0

                    # always regenerate fresh errors
                    new_takeoff, new_dep_route, new_enroute, new_fir, percentile_time = \
                        self.errorgenerator.return_sample(acid, origin, expected_delay_percentile, lookahead=lookahead)
                    if float(new_takeoff) != 0.0:
                        #get create time of flight here
                        scheduledtime = self.shiftflight.shift(acid, new_takeoff * 60)
                        self.preplan_popup_handler(acid, wpt,flighttime, type, origin, work, new_takeoff, new_dep_route, new_enroute, new_fir, abslookahead, percentile_time, scheduledtime)
                        #already adding popup flights that are still on ground to aman planning

                elif acid in self.Flights.index:
                    self.preplan_popup_handler(acid, wpt,flighttime, type, origin, work, 0, 0, 0, 0, 0, 0)

                else:
                    new_takeoff, new_dep_route, new_enroute, new_fir, abslookahead = 0 ,0 ,0 ,0 ,0
                updated_not_spawned[acid].append(
                    (wpt, wptime, flighttime, estimatedcreatetime,
                     wptpredutc, parent_id, type, origin,
                     new_takeoff, new_dep_route, new_enroute, new_fir, abslookahead, work)
                )

        self.not_spawned = updated_not_spawned


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




    def preplan_popup_handler(self, acid, wpt,flighttime, type, origin, work, takeoff, dep_route, enroute, fir, abslookahead, percentile_time, scheduledtime = None):
        idxac = traf.id2idx(acid)
         #scheduled time is time of creation of aircraft in bluesky
        if idxac == -1:
            if wpt in self.iafs:
                wptime = flighttime + scheduledtime
                # determining errors at iaf

                data = {'planningstate': 'ground', 'TP IAF': wptime, 'ETO_original': wptime, 'IAF': wpt,
                        'type': type, 'origin': origin, 'LAf': '', 'count': 0, 'Flighttime': flighttime,
                        'E_TO': takeoff, 'E_dep': dep_route, 'E_enroute': enroute, 'E_fir': fir,
                        'lookahead': abslookahead, 'percentile_time': percentile_time, 'creation': scheduledtime, 'ETD':scheduledtime}
                self.Flights.loc[acid] = data

            elif acid in self.Flights.index:
                wptime = flighttime + self.Flights.loc[acid]['creation']
                if '/RW' in wpt:
                    dest, runway = parse_destination(wpt)
                    data = {'planningstate': 'ground', 'TP ETA': wptime, 'runway': runway, 'type': type,
                            'LAf': '', 'count': 0, 'Flighttime': flighttime, 'minwork': work}

                elif self.firname in wpt:
                    data = {'FIR entry': wptime}

                elif 'ALTCROSS CLIMB' in wpt:
                    data = {'SID': wptime}

                elif 'ALTCROSS DESC' in wpt:
                    data = {}

                else:
                    print('something wrong with waypoints and prediction in aman')

                # Ensure string/bool-like columns keep compatible dtypes even when DF started empty
                for _c in ('runway', 'planningtype', 'planningstate', 'TPstate'):
                    if _c in self.Flights.columns:
                        self.Flights[_c] = self.Flights[_c].astype('object')

                for key, value in data.items():
                    self.Flights.at[acid, key] = value
