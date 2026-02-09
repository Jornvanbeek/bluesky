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
        Updated behavior:
        - Drift starts at 'interesting window' (ETO IAF - (freezehorizon + 5 min)), not at creation.
        - Enroute error is applied immediately if SID is missing.
        - Drift TP values toward realized times using elapsed segment time.
        - Resets drift window if TP IAF is updated (TP-update reset behavior).
        """

        t = float(sim.simt)

        # --- bookkeeping columns for TP update reset logic ---
        for c in ('TP IAF initial', 'TP IAF last', 'TP IAF last_update'):
            if c not in self.Flights.columns:
                self.Flights[c] = np.nan

        SID = self.Flights['SID'].astype(float)
        FIR = self.Flights['FIR entry'].astype(float)

        tp_iaf = self.Flights['TP IAF'].astype(float)
        eto = self.Flights['ETO IAF'].astype(float) if 'ETO IAF' in self.Flights.columns else pd.Series(np.nan, index=self.Flights.index)

        # TP IAF update reset logic
        # Set TP IAF initial once (first time a valid TP IAF is available)
        m_init = self.Flights['TP IAF initial'].isna() & tp_iaf.notna()
        if m_init.any():
            self.Flights.loc[m_init, 'TP IAF initial'] = tp_iaf.loc[m_init]

        # Detect TP IAF updates (value changed). On update: reset accumulated drift to 0
        tp_last = self.Flights['TP IAF last'].astype(float)
        m_first_last = tp_last.isna() & tp_iaf.notna()
        if m_first_last.any():
            self.Flights.loc[m_first_last, 'TP IAF last'] = tp_iaf.loc[m_first_last]
            self.Flights.loc[m_first_last, 'TP IAF last_update'] = t

        tp_last = self.Flights['TP IAF last'].astype(float)
        m_changed = tp_iaf.notna() & tp_last.notna() & (tp_iaf != tp_last)
        if m_changed.any():
            self.Flights.loc[m_changed, 'TP IAF last'] = tp_iaf.loc[m_changed]
            self.Flights.loc[m_changed, 'TP IAF last_update'] = t

        Edep = self.Flights['E_dep'].astype(float).fillna(0.0)
        Eenr = self.Flights['E_enroute'].astype(float).fillna(0.0)
        Efir = self.Flights['E_fir'].astype(float).fillna(0.0) if 'E_fir' in self.Flights.columns else pd.Series(0.0, index=self.Flights.index)

        # If a mach/adjacent instruction has occurred (not in the future), switch to E_fir instead of E_enroute.
        # We detect this via the accumulated delay columns created in ATC.store_delay / instruction_correct.
        instr_cols = ['delay mach', 'short mach', 'delay adjacent', 'short adjacent']
        instr_happened = pd.Series(False, index=self.Flights.index)
        for c in instr_cols:
            if c in self.Flights.columns:
                instr_happened = instr_happened | (self.Flights[c].fillna(0.0).astype(float) != 0.0)
        # Effective enroute error: use E_fir after instruction happened
        Eenr_eff = Eenr.where(~instr_happened, Efir)

        # Anchor for window start: prefer ETO IAF, else TP IAF
        eto_ref = eto.where(eto.notna(), tp_iaf)

        # Start time of the 'interesting window'
        window_start = eto_ref - self.errorstart

        # If TP IAF has been updated, accumulated drift must restart at the update time
        # Use the later of (window_start) and (TP IAF last_update)
        tp_upd = self.Flights['TP IAF last_update'].astype(float)
        start_time = window_start
        m_has_upd = tp_upd.notna() & start_time.notna()
        if m_has_upd.any():
            start_time.loc[m_has_upd] = np.maximum(start_time.loc[m_has_upd], tp_upd.loc[m_has_upd])

        # Only apply drift once we are inside the window
        in_window = start_time.notna() & (t >= start_time)

        # End of enroute drift: FIR if known else eto_ref
        enr_end = FIR.where(FIR.notna(), eto_ref)

        # Departure elapsed (only if SID exists): start_time -> min(now, min(SID, enr_end))
        elapsed_dep = pd.Series(0.0, index=self.Flights.index, dtype=float)
        dep_ok = in_window & SID.notna() & enr_end.notna()
        if dep_ok.any():
            dep_end = np.minimum(SID.loc[dep_ok], enr_end.loc[dep_ok])
            elapsed_dep.loc[dep_ok] = (np.minimum(t, dep_end) - start_time.loc[dep_ok]).clip(lower=0.0)

        # Enroute elapsed:
        # - if SID exists: max(SID, start_time) -> min(now, enr_end)
        # - if SID missing: start_time -> min(now, enr_end)
        elapsed_enr = pd.Series(0.0, index=self.Flights.index, dtype=float)
        enr_ok = in_window & enr_end.notna()
        if enr_ok.any():
            enr_start = start_time.loc[enr_ok]
            sid_here = SID.loc[enr_ok]
            enr_start = enr_start.where(sid_here.isna(), np.maximum(sid_here, enr_start))
            elapsed_enr.loc[enr_ok] = (np.minimum(t, enr_end.loc[enr_ok]) - enr_start).clip(lower=0.0)

        # FIR elapsed:
        # - only if FIR entry exists: max(FIR, start_time) -> min(now, eto_ref)
        elapsed_fir = pd.Series(0.0, index=self.Flights.index, dtype=float)
        fir_ok = in_window & FIR.notna() & eto_ref.notna()
        if fir_ok.any():
            fir_start = np.maximum(FIR.loc[fir_ok], start_time.loc[fir_ok])
            elapsed_fir.loc[fir_ok] = (np.minimum(t, eto_ref.loc[fir_ok]) - fir_start).clip(lower=0.0)

        drift_seconds = (elapsed_dep * (Edep / 100.0)) + (elapsed_enr * (Eenr_eff / 100.0)) + (elapsed_fir * (Efir / 100.0))
        drift_seconds = drift_seconds.astype(float).fillna(0.0)

        # For debugging/plots
        self.Flights['Time error'] = drift_seconds

        # Only update ETO IAF where TP IAF exists
        m_tp = self.Flights['TP IAF'].notna()
        self.Flights.loc[m_tp, 'ETO IAF'] = self.Flights.loc[m_tp, 'TP IAF'] + drift_seconds.loc[m_tp]

        # Only update ETA if TP ETA exists
        if 'TP ETA' in self.Flights.columns:
            m = self.Flights['TP ETA'].notna()
            if m.any():
                self.Flights.loc[m, 'ETA'] = self.Flights.loc[m, 'TP ETA'] + drift_seconds.loc[m]

        # AMAN values based on drifted ETO (TMA must remain fixed)
        self.Flights['ETA'] = self.Flights['ETO IAF'] + self.Flights['TMA']

        # Apply percentile_time offset (minutes -> seconds), NaN treated as 0
        pt = self.Flights['percentile_time']#.fillna(0.0)
        self.Flights['delayed ETA'] = self.Flights['ETA'] + pt * 60.0


    # =========================
    # 1) Mapping Flights -> traf.gsfactor (NO FIR scaling)
    # =========================
    def update_traf_gsfactor_from_flights(self, Flights, simt: float):
        """
        Updated phases:
          - Error is applied starting from 5 min before freezehorizon window, anchored at ETO IAF (or TP IAF).
          - If SID is missing, enroute error is applied immediately.
          - If TP IAF is updated, restart factor window from update time.
        """
        n = traf.ntraf
        if n == 0:
            return

        ids = np.array([str(a).upper() for a in traf.id], dtype=object)

        cols = ['SID', 'FIR entry', 'E_dep', 'E_enroute', 'E_fir', 'ETO IAF', 'TP IAF',
                'TP IAF last', 'TP IAF last_update',
                'delay mach', 'short mach', 'delay adjacent', 'short adjacent']

        # Safe column selection: at sim start these instruction columns may not exist yet
        sub = Flights.reindex(ids).reindex(columns=cols)

        # Fill missing instruction columns with 0.0 (meaning: no past instruction)
        for c in ('delay mach', 'short mach', 'delay adjacent', 'short adjacent'):
            if c in sub.columns:
                sub[c] = sub[c].fillna(0.0)

        SID = sub['SID'].to_numpy(dtype=float)
        FIR = sub['FIR entry'].to_numpy(dtype=float)

        Edep = sub['E_dep'].to_numpy(dtype=float)
        Eenr = sub['E_enroute'].to_numpy(dtype=float)
        Efir = sub['E_fir'].to_numpy(dtype=float)

        eto = sub['ETO IAF'].to_numpy(dtype=float)
        tp_iaf = sub['TP IAF'].to_numpy(dtype=float)

        # Read TP IAF last_update for TP-update reset logic
        tp_last_update = sub['TP IAF last_update'].to_numpy(dtype=float) if 'TP IAF last_update' in sub.columns else np.full(n, np.nan)

        # If a mach/adjacent instruction has occurred, use E_fir instead of E_enroute for the enroute phase.
        n = len(SID)
        dm = sub['delay mach'].to_numpy(dtype=float) if 'delay mach' in sub.columns else np.full(n, np.nan)
        sm = sub['short mach'].to_numpy(dtype=float) if 'short mach' in sub.columns else np.full(n, np.nan)
        da = sub['delay adjacent'].to_numpy(dtype=float) if 'delay adjacent' in sub.columns else np.full(n, np.nan)
        sa = sub['short adjacent'].to_numpy(dtype=float) if 'short adjacent' in sub.columns else np.full(n, np.nan)
        instr_happened = (np.nan_to_num(dm) != 0.0) | (np.nan_to_num(sm) != 0.0) | (np.nan_to_num(da) != 0.0) | (np.nan_to_num(sa) != 0.0)
        Eenr_eff = np.where(instr_happened, Efir, Eenr)

        t = float(simt)

        has_SID = np.isfinite(SID)
        has_FIR = np.isfinite(FIR)

        # Reference time to anchor the 'interesting window'
        # Prefer ETO IAF, fall back to TP IAF
        eto_ref = np.where(np.isfinite(eto), eto, tp_iaf)
        has_eto_ref = np.isfinite(eto_ref)

        # Start applying error only from 5 minutes before the freeze horizon window
        window_start = eto_ref - (float(self.freezehorizon) + 5.0 * 60.0)

        # Restart factor application after TP IAF update: effective start is max(window_start, tp_last_update)
        eff_start = window_start
        has_upd = np.isfinite(tp_last_update)
        eff_start = np.where(has_upd, np.maximum(eff_start, tp_last_update), eff_start)

        active = has_eto_ref & (t >= eff_start)

        # End of enroute scaling: at FIR entry if known, otherwise at eto_ref
        enr_end = np.where(has_FIR, FIR, eto_ref)

        # If SID exists: departure error until SID (but not past enr_end)
        dep_end = np.where(has_SID, np.minimum(SID, enr_end), np.nan)
        dep_mask = active & has_SID & (t < dep_end)

        # Enroute error:
        # - If SID exists: from SID to enr_end
        # - If SID missing: from eff_start to enr_end (i.e. use enroute error immediately)
        enr_start = np.where(has_SID, np.maximum(SID, eff_start), eff_start)
        enr_mask = active & (t >= enr_start) & (t < enr_end)

        # FIR error:
        # - only if FIR entry exists: from max(FIR, eff_start) to eto_ref
        fir_start = np.where(has_FIR, np.maximum(FIR, eff_start), np.nan)
        fir_mask = active & has_FIR & (t >= fir_start) & (t < eto_ref)

        factor = np.ones(n, dtype=float)
        factor[dep_mask] = 1.0 - (Edep[dep_mask] / 100.0)
        factor[enr_mask] = 1.0 - (Eenr_eff[enr_mask] / 100.0)
        factor[fir_mask] = 1.0 - (Efir[fir_mask] / 100.0)

        # safety
        factor = np.clip(factor, self.min_groundspeed_factor, self.max_groundspeed_factor)
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
