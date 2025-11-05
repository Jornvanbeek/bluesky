import pandas as pd
import numpy as np
import pickle
from bluesky import core, stack, traf, network, sim
from collections import defaultdict


class ErrorHandler:

    def update_errors(self):
        # self.Flights['ETA'] = self.Flights['correct_ETA'] + error
        # self.Flights['totalerror'] = self.Flights['creation'] + self.Flights['deproute'] + self.Flights['outsidefir'] + self.Flights['insidefir']
        # self.Flights['Time error'] =
        # (SID - FH) * E_DEP
        #
        # TODO deze goed checken, met name de signs
        self.segments()
        self.Flights['Time error'] = (
                -self.Flights['t_departure'].fillna(0) * self.Flights['E_dep'].fillna(0) / 100
                - self.Flights['t_enroute'].fillna(0) * self.Flights['E_enroute'].fillna(0) / 100
                - self.Flights['t_fir'].fillna(0) * self.Flights['E_fir'].fillna(0) / 100
            # - self.Flights['E_TO'].fillna(0) * 60
        )
        self.Flights['ETO IAF'] = self.Flights['TP IAF'] + self.Flights['Time error']
        self.Flights['ETA'] = self.Flights['ETO IAF'] + self.Flights['TMA']

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
                    new_takeoff, new_dep_route, new_enroute, new_fir = \
                        self.errorgenerator.return_sample(acid, origin, lookahead=lookahead)
                    if float(new_takeoff) != 0.0:
                        self.shiftflight.shift(acid, new_takeoff * 60)
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








# from bluesky import traf, sim
#
# from collections import defaultdict
# import pandas as pd
# pd.set_option('display.max_columns', None)
# pd.set_option('display.max_rows', None)
# pd.set_option('display.width', 250)
#
#
# class ErrorHandler:
#     def __init__(self, globalseed):
#         cols = [
#             'E_TO', 'E_dep', 'E_enroute', 'E_fir',
#             't_departure', 't_enroute', 't_fir',
#             'Time error'
#         ]
#         self.df = pd.DataFrame(columns=cols)
#         self.df.index.name = 'ACID'
#         self.globalseed = globalseed
#
#
#
#     def newprediction(self, acid, wpt, wptime, flighttime, wptpredutc, parent_id, type, origin, iafs, freezehorizon, idxac, firname):
#         """
#         Each acid getting a new ETA will be added to aircraft needing to get a slot.
#         """
#
#
#
#         if idxac == -1:
#
#
#             if wpt in self.iafs:
#                 # determining errors at iaf
#                 lookahead = round(int(self.freezehorizon - flighttime) / 60)  # minutes
#                 abslookahead = lookahead
#                 if lookahead < 0:
#                     lookahead = 0
#                 print(acid, 'error should be generated')
#                 takeoff, dep_route, enroute, fir = self.errorgenerator.return_sample(acid, origin, lookahead=lookahead)
#                 if float(takeoff) != 0.0:
#                     self.shiftflight.shift(acid, takeoff * 60)
#
#
#
#                 # store errors
#
#                 data = {'acid': acid, 'TP IAF':flighttime 'E_TO': takeoff, 'E_dep': dep_route, 'E_enroute': enroute, 'E_fir': fir, 'abs lookahead': abslookahead, 'origin': origin}
#
#             elif firname in wpt:
#                 data = {'FIR entry': flighttime} #time to fir entry from spawning
#
#             elif 'ALTCROSS CLIMB' in wpt:
#                 data = {'SID': flighttime}
#
#
#
#
#
#         elif idxac !=0:
#             wptime = traf.ap.route[idxac].createtime + flighttime
#             if wpt in iafs:
#                 data = {}
#             elif firname in wpt:
#                 data = {'FIR entry': wptime}  # time to fir entry from spawning
#
#             elif 'ALTCROSS CLIMB' in wpt:
#                 data = {'SID': wptime}
#
#         if acid not in self.df.index:
#             # Adds a new row for acid if it doesn't exist
#             self.df.loc[acid] = data
#         else:
#             # Updates the existing row for acid
#             for key, value in data.items():
#                 self.df.at[acid, key] = value
#
#          df['TP IAF'], df['takeoff'], df['planning']
#
#
#
#     def update_errors(self):
#         # self.Flights['ETA'] = self.Flights['correct_ETA'] + error
#         # self.Flights['totalerror'] = self.Flights['takeoff'] + self.Flights['deproute'] + self.Flights['outsidefir'] + self.Flights['insidefir']
#         # self.Flights['Time error'] =
#         # (SID - FH) * E_DEP
#         #
#         # TODO deze goed checken, met name de signs
#         self.segments()
#         self.Flights['Time error'] = (
#                 -self.Flights['t_departure'].fillna(0) * self.Flights['E_dep'].fillna(0) / 100
#                 - self.Flights['t_enroute'].fillna(0) * self.Flights['E_enroute'].fillna(0) / 100
#                 - self.Flights['t_fir'].fillna(0) * self.Flights['E_fir'].fillna(0) / 100
#             # - self.Flights['E_TO'].fillna(0) * 60
#         )
#         self.Flights['ETO IAF'] = self.Flights['TP IAF'] + self.Flights['Time error']
#         self.Flights['ETA'] = self.Flights['ETO IAF'] + self.Flights['TMA']
#         # tdep = self.Flights['']
#         #
#         # self.Flights['Time error'] = -self.Flights['E_TO']*60 + self.Flights['E_dep']
#
#
#     def segments(self):
#         df = self.Flights
#         simt_s = pd.Series(float(sim.simt), index=df.index)
#
#         # Extract main timestamps
#         SID, FIR, IAF, TO, Planning = df['SID'], df['FIR entry'], df['TP IAF'], df['takeoff'], df['planning']
#
#         # Determine actual segment start times
#         start_dep = pd.concat([simt_s, Planning, TO], axis=1).max(axis=1, skipna=True)
#         start_enr = pd.concat([simt_s, Planning, SID], axis=1).max(axis=1, skipna=True)
#         start_fir = pd.concat([simt_s, Planning, FIR], axis=1).max(axis=1, skipna=True)
#         # Compute durations, ensuring non-negative results
#         t_departure = (SID - start_dep).clip(lower=0).where(SID.notna())
#         t_enroute = (FIR - start_enr).clip(lower=0).where(FIR.notna())
#         t_fir = (IAF - start_fir).clip(lower=0).where(IAF.notna())
#
#         df['t_departure'], df['t_enroute'], df['t_fir'] = t_departure, t_enroute, t_fir
#
#
#
#
#     def regenerate_errors(self):
#         """
#         Re-run the error generator for all not_spawned predictions
#         to ensure fresh errors instead of cached ones.
#         """
#         updated_not_spawned = defaultdict(list)
#
#         for acid, predictions in self.not_spawned.items():
#             for (wpt, wptime, flighttime, estimatedcreatetime,
#                  wptpredutc, parent_id, type, origin) in predictions:
#                 #note that the errors are not stored in the previous predictions, these are stored in the TP, which does not include errors
#
#                 # compute lookahead in minutes
#                 lookahead = round(int(self.freezehorizon - flighttime) / 60)
#                 if lookahead < 0:
#                     lookahead = 0
#
#                 # always regenerate fresh errors
#                 new_takeoff, new_dep_route, new_enroute, new_fir = \
#                     self.errorgenerator.return_sample(acid, origin, lookahead=lookahead)
#                 if float(new_takeoff) != 0.0:
#                     self.shiftflight.shift(acid, new_takeoff * 60)
#                 updated_not_spawned[acid].append(
#                     (wpt, wptime, flighttime, estimatedcreatetime,
#                      wptpredutc, parent_id, type, origin,
#                      new_takeoff, new_dep_route, new_enroute, new_fir)
#                 )
#
#         self.not_spawned = updated_not_spawned
