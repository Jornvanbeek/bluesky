

import numpy as np
from bluesky import core, stack, traf
from bluesky.core import signal
from bluesky.core import plugin, timed_function
from bluesky.traffic import Traffic
from bluesky.traffic.autopilot import Autopilot
from bluesky.tools.aero import casormach2tas, fpm, kts, ft, g0, Rearth, nm, tas2cas,\
                         vatmos,  vtas2cas, vtas2mach, vcasormach, casmach_thr
from bluesky.stack.cmdparser import command, commandgroup, append_commands, \
    remove_commands, get_commands

def init_plugin():
    global CROSSOVER
    CROSSOVER = MachCrossoverPlugin()

    # 3) Return a config dict so BlueSky knows this is a sim plugin
    config = {
        'plugin_name': 'MACH_CROSSOVER',
        'plugin_type': 'sim',
        'update frequency': 1.0,
        'M_cruise': None,
        'M_descent': None,
        'CAS_descent': None,
        'M_climb': None,      # <-- new field for climb Mach
        'CAS_climb': None,
        'CAS_cruise': None,
        'max_CAS_desc': None,# <-- new field for climb CAS
    }
    return config



class Traffic(Traffic):
    def __init__(self, **kwds):
        super().__init__(**kwds)


class MachCrossoverPlugin(core.Entity):

    def __init__(
            self,
            standard_mcruise=0.78,
            standard_mdescent=0.76,
            standard_casdesc=275,
            standard_mclimb=0.77,
            standard_casclimb=270,
            standard_cascruise = 280,
            transition_altitude=100,
            descentspd=250,
            descent_threshold=3000 * ft,
            standard_max_casdesc = 295


    ):
        super().__init__()
        self.standard_mcruise = float(standard_mcruise)
        self.standard_mdescent = float(standard_mdescent)
        self.standard_casdesc = float(standard_casdesc)*kts
        self.transition_altitude = float(transition_altitude)*ft*100
        self.descentspd = float(descentspd)*kts
        self.descent_threshold = float(descent_threshold)

        # New climb defaults
        self.standard_mclimb = float(standard_mclimb)
        self.standard_casclimb = float(standard_casclimb) * kts
        self.standard_cascruise = float(standard_cascruise) * kts
        self.standard_max_casdesc = float(standard_max_casdesc) * kts

        # Initialize traffic arrays
        with self.settrafarrays():
            self.mcruise = np.array([])
            self.cascruise = np.array([])
            self.mdescent = np.array([])
            self.casdesc = np.array([])
            self.max_casdesc = np.array([])
            self.spdtype = np.array([])
            self.max_alt = np.array([])
            self.mclimb = np.array([])
            self.casclimb = np.array([])
            self.flight_phase = np.array([], dtype=str)
            self.user_spdcmd = np.array([], dtype=bool)

        # stack.stack('IMPLEMENTATION POS POSM')

    @stack.command
    def standard_speeds(
        self,
        standard_mcruise=0.78,
        standard_cascruise=290,
        standard_mdescent=0.76,
        standard_casdesc=270,
        standard_mclimb=0.75,
        standard_casclimb=280,
        transition_altitude=110,
        descentspd=250,
        standard_max_casdesc = 295

    ):
        self.standard_mcruise = float(standard_mcruise)
        self.standard_cascruise = float(standard_cascruise)
        self.standard_mdescent = float(standard_mdescent)
        self.standard_casdesc = float(standard_casdesc*kts)
        self.transition_altitude = float(transition_altitude)*ft*100
        self.descentspd = float(descentspd)*kts
        self.standard_mclimb = float(standard_mclimb)
        self.standard_casclimb = float(standard_casclimb) * kts
        self.standard_max_casdesc = float(standard_max_casdesc) * kts

    @stack.command
    def set_speed(self, acid, mcruise=None,cascruise=None, mdescent=None, casdesc=None, mclimb=None, casclimb=None, max_casdesc=None):

        acid = acid.upper()

        # Find the index of the aircraft using the provided ID
        idx = traf.id2idx(acid)
        if idx == -1:
            message = f"Aircraft '{acid}' not found."
            print(f"[MachCrossoverPlugin] {message}")
            return False, message
        if mcruise is not None:
            self.mcruise[idx] = float(mcruise)
        if mdescent is not None:
            self.mdescent[idx] = float(mdescent)
        if casdesc is not None:
            self.casdesc[idx] = float(casdesc)*kts
            self.max_casdesc[idx] = float(casdesc)*kts + 25
        if mclimb is not None:
            self.mclimb[idx] = float(mclimb)
        if casclimb is not None:
            self.casclimb[idx] = float(casclimb) * kts
        if cascruise is not None:
            self.cascruise[idx] = float(cascruise)*kts

        if max_casdesc is not None:
            self.max_casdesc[idx] = float(max_casdesc)*kts






    def create(self, n=1):
        """
        Creates traffic arrays for new aircraft.

        Parameters:
            n (int): Number of aircraft to create.
        """
        super().create(n)
        # print(f"[MachCrossoverPlugin] Creating {n} new aircraft")

        # Initialize arrays with standard values or NaN
        if self.standard_mcruise is not None:
            self.mcruise[-n:] = self.standard_mcruise
        else:
            self.mcruise[-n:] = np.nan

        if self.standard_mdescent is not None:
            self.mdescent[-n:] = self.standard_mdescent
        else:
            self.mdescent[-n:] = np.nan

        if self.standard_casdesc is not None:
            self.casdesc[-n:] = self.standard_casdesc
        else:
            self.casdesc[-n:] = np.nan

        # Climb Mach/CAS arrays
        if self.standard_mclimb is not None:
            self.mclimb[-n:] = self.standard_mclimb
        else:
            self.mclimb[-n:] = np.nan

        if self.standard_casclimb is not None:
            self.casclimb[-n:] = self.standard_casclimb
        else:
            self.casclimb[-n:] = np.nan

        if self.standard_cascruise is not None:
            self.cascruise[-n:] = self.standard_cascruise
        else:
            self.cascruise[-n:] = np.nan

        if self.standard_max_casdesc is not None:
            self.max_casdesc[-n:] = self.standard_max_casdesc
        else:
            self.max_casdesc[-n:] = np.nan


        self.spdtype[-n:] = np.nan
        self.max_alt[-n:] = traf.alt[-n:]
        self.flight_phase[-n:] = 'new'
        self.user_spdcmd[-n:] = False
        # print("[MachTraffic] create() called for", n, "new aircraft")



    @stack.command
    def printspds(self, acid):
        idx = traf.id2idx(acid)
        print(self.mcruise[idx])
        print(self.mdescent[idx])
        print(self.casdesc[idx])
        print(self.max_casdesc[idx])
        print(traf.selspd[idx])
        print(traf.M[idx])
        print(traf.cas[idx])
        print(traf.alt[idx])
        print(traf.vs[idx])

    @core.timed_function(dt= 1.0)
    def update(self):
        n_ac = len(self.mcruise)
        if n_ac == 0:
            return

        # 1) Build a mask for aircraft that have received user speed commands
        manual_mask = self.user_spdcmd  # True where user set SPD, we skip logic


        # Let's define an "auto_mask" that indicates the plugin *can* set speeds
        auto_mask = ~manual_mask

        # 2) Update max_alt
        higher_mask = (traf.alt > self.max_alt) & auto_mask
        self.max_alt[higher_mask] = traf.alt[higher_mask]

        # Default flight_phase to 'cruise' for *every* aircraft.
        # We can keep flight phases for reference. That’s not harmful even if user SPD is set.
        self.flight_phase[:] = 'cruise'

        descent_mask = ((traf.vs < -0.1) | (traf.alt < (self.max_alt - self.descent_threshold))) & auto_mask
        climb_mask = (traf.vs > 0.1) & auto_mask

        self.flight_phase[descent_mask] = 'descent'
        self.flight_phase[climb_mask] = 'climb'

        # 3) Create references
        alt = traf.alt
        selspd = traf.selspd  # We will override these only for the auto_mask subset
        old_selspd = np.copy(traf.selspd)

        def get_selcas_mach():
            _, out_cas, out_mach = vcasormach(selspd, alt)
            return out_cas, out_mach

        # 1 knot tolerance in m/s:
        tol_1kt = 1.0 * kts

        def approx(x, y, tol=tol_1kt):
            return np.abs(x - y) < tol

        descentspd = self.descentspd
        climbcas = self.casclimb
        Mclimb = self.mclimb
        cascruise = self.cascruise
        Mcruise = self.mcruise
        casdescent = self.casdesc
        Mdescent = self.mdescent

        machthreshold = casmach_thr

        # Masks for altitude + phase
        below_ta = (alt < self.transition_altitude)  #& auto_mask
        above_ta = ~below_ta & auto_mask  # remain consistent with skipping manual

        # We'll define phase-based masks:
        climb_mask2 = (self.flight_phase == 'climb') & above_ta
        cruise_mask = (self.flight_phase == 'cruise') & above_ta
        desc_mask = (self.flight_phase == 'descent') & above_ta

        # -----------------------------
        # 3) "If aircraft is below transition altitude: selspd = descentspd"
        # -----------------------------
        selspd[below_ta] = descentspd

        # -----------------------------
        # 4) Climbing Aircraft
        # -----------------------------
        # "if selspd is approx descentspd => selspd= climbcas"
        cond_c1 = climb_mask2 & approx(selspd, descentspd)
        selspd[cond_c1] = climbcas[cond_c1]

        # "elif selspd is approx climbspd and selmach > Mclimb => selspd = Mclimb"
        # We'll compute current selcas, selmach:
        this_cas, this_mach = get_selcas_mach()
        cond_c2 = climb_mask2 & approx(selspd, climbcas) & (this_mach > Mclimb)
        selspd[cond_c2] = Mclimb[cond_c2]

        # "if selspd < machthreshold and selspd > climbcas => selspd= climbcas"
        cond_c3 = climb_mask2 & (selspd < machthreshold) & (selspd > climbcas)
        selspd[cond_c3] = climbcas[cond_c3]

        # -----------------------------
        # 5) Cruise Aircraft
        # -----------------------------
        # Recompute selcas/selmach if selspd changed above
        this_cas, this_mach = get_selcas_mach()

        # "if selcas < cascruise and selmach < Mcruise => selspd= cascruise"
        cond_cr1 = cruise_mask & (this_cas < cascruise) & (this_mach < Mcruise)
        selspd[cond_cr1] = cascruise[cond_cr1]

        # "elif selmach > Mcruise => selspd= Mcruise"
        # We'll do it as a separate mask:
        this_cas, this_mach = get_selcas_mach()
        cond_cr2 = cruise_mask & (this_mach > Mcruise)
        selspd[cond_cr2] = Mcruise[cond_cr2]

        # -----------------------------
        # 6) Descent Aircraft
        # -----------------------------
        # Recompute selcas/selmach again if needed
        this_cas, this_mach = get_selcas_mach()

        # "if selspd is approx Mcruise => selspd= selcas"
        # Must be an "approx" check: we do approx(selspd, Mcruise).
        cond_d1 = desc_mask & approx(selspd, Mcruise) & (this_cas > casdescent + 1)
        # We want selspd = selcas, so let's re-run vcasormach for each after any changes
        # But let's do it with the *old* array we already have from get_selcas_mach()
        # (since selspd hasn't changed except in c1/c2/c3/cr1/cr2 above).
        selspd[cond_d1] = this_cas[cond_d1]

        # "elif selcas < casdescent and selmach < Mdescent => selspd= Mdescent"
        # Because selspd changed in cond_d1, let's re-check:
        this_cas, this_mach = get_selcas_mach()
        cond_d2 = desc_mask & (this_cas < casdescent) & (this_mach < Mdescent)
        selspd[cond_d2] = Mdescent[cond_d2]

        # "elif selcas > casdescent => selspd= casdescent"
        this_cas, this_mach = get_selcas_mach()
        cond_d3 = desc_mask & (this_cas > casdescent)
        selspd[cond_d3] = casdescent[cond_d3]

        # -----------------------------
        # 7) Final: Write back speeds
        # -----------------------------


        # 1) Build a mask of aircraft crossing from below casmach_thr to above it
        crossed_mask = (old_selspd < casmach_thr) & (selspd > casmach_thr)
        crossed_idxs = np.where(crossed_mask)[0]
        # print(crossed_mask)
        # print(crossed_idxs)
        # print(old_selspd)
        # print(selspd)
        # print(selspd[cond_d1])
        # 2) For each aircraft that just crossed, stack a 'CROSSOVER' command
        for idx in crossed_idxs:
            acid = traf.id[idx]  # get aircraft callsign
            stack.stack(f'PREDICTOR CROSSOVER {acid}')
            # print(acid)

        traf.selspd[:] = selspd


    @signal.subscriber(topic='stack-changed')
    def on_stack_changed(self, cmdline):
        if ('SPD' in cmdline.upper().split() or 'SPEED' in cmdline.upper().split()) and 'DELAY' not in cmdline.upper() and 'ORIG' not in cmdline.upper():
            acid = cmdline.upper().split()[1]
            idx = traf.id2idx(acid)
            if idx<0:

                acid = cmdline.upper().split()[0]
                idx = traf.id2idx(acid)
                if idx<0:
                    print(f'mach crossover {cmdline} not found in spd cmdline, or not in traf, idx = {idx}')
                    return
            self.user_spdcmd[idx] = True

        elif 'VNAV ON' in cmdline.upper():
            acid = cmdline.upper().split()[2]
            idx = traf.id2idx(acid)
            if idx < 0:
                acid = cmdline.upper().split()[1]
                idx = traf.id2idx(acid)
                if idx < 0:
                    acid = cmdline.upper().split()[0]
                    idx = traf.id2idx(acid)
                    if idx < 0:
                        print(f'mach crossover {acid} not found in vnav on cmdline')
                        return
            self.user_spdcmd[idx] = False

    @stack.command
    def reduce_mach(self,acid, mach):
        idx = traf.id2idx(acid)
        self.mcruise[idx] = self.mcruise[idx] - float(mach)
        self.mdescent[idx] = self.mdescent[idx] - float(mach)
        traf.selspd[idx] = traf.selspd[idx] - float(mach)

    @stack.command
    def setdescentspd(self,acid, spd):
        idx = traf.id2idx(acid)
        traf.selspd[idx] = float(spd)*kts
        self.user_spdcmd[idx] = True

    @stack.command
    def printfrommach(self, acid):
        idx = traf.id2idx(acid)
        print(idx)
        print(traf.id)





    # @stack.command
    # def POS(self, acid):
    #
    #     idx = traf.id2idx(acid)
    #     # bool, lines = traf.poscommand(idx)
    #     # print(bool)
    #     # print(lines)
    #     # for line in lines:
    #     stack.stack(f'POS_OLD {acid}')
    #     if traf.selspd[idx] > casmach_thr:
    #         selspd = round(traf.selspd[idx]/kts)
    #     else:
    #         selspd = traf.selspd[idx]
    #     stack.stack(f'ECHO selspd: {selspd}')
