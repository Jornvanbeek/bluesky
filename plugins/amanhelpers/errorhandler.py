import pandas as pd
import numpy as np
import pickle
from bluesky import core, stack, traf, network, sim
from collections import defaultdict
from plugins.amanhelpers.aman_settings import expected_delay_percentile
from plugins.amanhelpers.amanpredictionhandler import parse_destination
from bluesky.tools.aero import Rearth



class ErrorHandler:


    def update_pos_error(self):
        """Integrate position with an optional per-aircraft distance factor.

        Goal:
        - Do NOT change traf.gs (or gsnorth/gseast as *state*).
        - Only make the aircraft cover less/more distance in this integration step.

        Mechanism:
        - Use an optional `traf.gsfactor` (scalar or array len=ntraf).
        - Apply factor only to the displacement integration (lat/lon) and distflown.
        """

        dt = float(sim.simdt)

        # Altitude update: keep identical to original
        traf.alt = np.where(traf.swaltsel, np.round(traf.alt + traf.vs * dt, 6), traf.aporasas.alt)

        # Get factor (scalar or array). Default = 1.0.
        factor = getattr(traf, 'gsfactor', 1.0)
        if np.isscalar(factor):
            factor = np.full(traf.ntraf, float(factor), dtype=float)
        else:
            factor = np.asarray(factor, dtype=float)
            if factor.shape[0] != traf.ntraf:
                factor = np.ones(traf.ntraf, dtype=float)
        factor = np.where(np.isfinite(factor), factor, 1.0)

        # Integrate displacement using scaled components (do NOT overwrite gsnorth/gseast/gs)
        gsn = traf.gsnorth * factor
        gse = traf.gseast * factor

        traf.lat = traf.lat + np.degrees(dt * gsn / Rearth)
        traf.coslat = np.cos(np.deg2rad(traf.lat))
        traf.lon = traf.lon + np.degrees(dt * gse / traf.coslat / Rearth)

        # Keep distflown consistent with the scaled displacement
        traf.distflown += (traf.gs * factor) * dt



    def update_errors(self):
        """
        Requested behavior:
        - SID error applies from creation -> ALTCROSS CLIMB time (= df['SID'])
        - Enroute error applies from ALTCROSS CLIMB (=SID) -> FIR entry (=df['FIR entry'])
        - Within FIR: do nothing (no additional drift here)
        - TP values drift toward realized times using elapsed segment time:
              drift = elapsed_dep * E_dep/100 + elapsed_enr * E_enroute/100

        Sign convention:
        - E > 0  => later/slower => positive drift (adds seconds)
        """



        # # Store immutable TP baselines once
        # if 'TP IAF_base' not in self.Flights.columns or self.Flights['TP IAF_base']:
        #     self.Flights['TP IAF_base'] = self.Flights['TP IAF']
        # if 'TP ETA' in self.Flights.columns and 'TP ETA_base' not in self.Flights.columns:
        #     self.Flights['TP ETA_base'] = self.Flights['TP ETA']

        t = float(sim.simt)

        TO = self.Flights['creation'].astype(float)
        SID = self.Flights['SID'].astype(float)  # mag NaN zijn
        FIR = self.Flights['FIR entry'].astype(float)  # mag NaN zijn
        IAF = self.Flights['TP IAF'].astype(float)  # mag NaN zijn

        Edep = self.Flights['E_dep'].astype(float).fillna(0.0)
        Eenr = self.Flights['E_enroute'].astype(float).fillna(0.0)

        # --- kies een "departure end" ---
        # voorkeur: SID, anders FIR, anders IAF, anders nu
        dep_end = SID.copy()
        dep_end = dep_end.fillna(FIR)
        dep_end = dep_end.fillna(IAF)
        dep_end = dep_end.fillna(t)

        # elapsed departure: creation -> min(now, dep_end)
        elapsed_dep = (np.minimum(t, dep_end) - TO).clip(lower=0.0)
        elapsed_dep = elapsed_dep.fillna(0.0)

        # --- enroute start is dep_end (dus SID als die er is, anders FIR/IAF/nu) ---
        enr_start = dep_end

        # enroute end: FIR (als die er is), anders 0 enroute (want jij wil binnen FIR niets aanpassen)
        elapsed_enr = pd.Series(0.0, index=self.Flights.index, dtype=float)
        enr_ok = FIR.notna() & enr_start.notna()

        # elapsed enroute: enr_start -> min(now, FIR)
        elapsed_enr.loc[enr_ok] = (np.minimum(t, FIR.loc[enr_ok]) - enr_start.loc[enr_ok]).clip(lower=0.0)
        elapsed_enr = elapsed_enr.fillna(0.0)

        drift_seconds = elapsed_dep * (Edep / 100.0) + elapsed_enr * (Eenr / 100.0)
        drift_seconds = drift_seconds.astype(float).fillna(0.0)

        # For debugging/plots
        self.Flights['Time error'] = drift_seconds
        # print('drift: ', drift_seconds)

        # Drift TP values toward realized times
        self.Flights['ETO IAF'] = self.Flights['TP IAF'] + drift_seconds
        if 'TP ETA_base' in self.Flights.columns:
            self.Flights['ETA'] = self.Flights['TP ETA'] + drift_seconds


        # AMAN values based on drifted TP
        # self.Flights['ETO IAF'] = self.Flights['TP IAF']
        self.Flights['ETA'] = self.Flights['ETO IAF'] + self.Flights['TMA']

        # Apply percentile_time offset (minutes -> seconds), NaN treated as 0
        pt = self.Flights['percentile_time'].fillna(0.0)
        self.Flights['delayed ETA'] = self.Flights['ETA'] + pt * 60.0


    # =========================
    # 1) Mapping Flights -> traf.gsfactor (NO FIR scaling)
    # =========================
    def update_traf_gsfactor_from_flights(self, Flights, simt: float):
        """
        Phases (as requested):
          - SID error applies from creation -> ALTCROSS CLIMB time (= Flights['SID'])
          - enroute error applies from ALTCROSS CLIMB (=SID) -> FIR entry (=Flights['FIR entry'])
          - within FIR: DO NOTHING (factor = 1.0)

        Requires Flights index = ACID, and columns:
          'creation', 'SID', 'FIR entry', 'E_dep', 'E_enroute'

        Sign convention used here:
          - E > 0  => slower => factor = 1 - E/100
          - If you want E > 0 => faster: change to 1 + E/100
        """
        n = traf.ntraf
        if n == 0:
            return

        ids = np.array([str(a).upper() for a in traf.id], dtype=object)

        cols = ['creation', 'SID', 'FIR entry', 'E_dep', 'E_enroute']
        sub = Flights.reindex(ids)[cols]

        TO = sub['creation'].to_numpy(dtype=float)
        SID = sub['SID'].to_numpy(dtype=float)
        FIR = sub['FIR entry'].to_numpy(dtype=float)

        Edep = sub['E_dep'].to_numpy(dtype=float)
        Eenr = sub['E_enroute'].to_numpy(dtype=float)

        t = float(simt)

        has_TO = np.isfinite(TO)
        has_SID = np.isfinite(SID)
        has_FIR = np.isfinite(FIR)

        # creation -> SID
        dep_mask = has_TO & has_SID & (t >= TO) & (t < SID)

        # SID -> FIR
        enr_mask = has_SID & has_FIR & (t >= SID) & (t < FIR)

        factor = np.ones(n, dtype=float)
        factor[dep_mask] = 1.0 - (Edep[dep_mask] / 100.0)
        factor[enr_mask] = 1.0 - (Eenr[enr_mask] / 100.0)

        # safety
        factor = np.clip(factor, 0.2, 2.0)
        factor[~np.isfinite(factor)] = 1.0

        traf.gsfactor = factor

        # Also store factor per ACID in Flights for debugging/validation
        if 'gsfactor' not in Flights.columns:
            Flights['gsfactor'] = np.nan

        # Update only those ACIDs that exist in Flights
        in_df = np.isin(ids, Flights.index.to_numpy(dtype=object))
        if np.any(in_df):
            Flights.loc[ids[in_df], 'gsfactor'] = factor[in_df]

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
