""" BlueSky Holding plugin"""

from bluesky import core, stack, traf, sim  # , settings, navdb, scr, tools
import math
from bluesky.tools import aero
import numpy as np
from bluesky.core import plugin



### Initialization function of your plugin. Do not change the name of this
### function, as it is the way BlueSky recognises this file as a plugin.
def init_plugin():

    # Addtional initilisation code
        # Configuration parameters

    holding = Holding()

    config = {
        # The name of your plugin
        'plugin_name':     'Holding',
        # The type of this plugin.
        'plugin_type':     'sim'
        }
        # init_plugin() should always return the config dict.
    return config


# Plugin use: holding + second command
# first holding define, if standard holding at schiphol is not sufficient
# then holding at {acid} {wpt} to start holding once aircraft arrives at waypoint (must be in route)
# a holding time can be included, which is approximately followed, or it can be indefinite
# holding cancel {acid} stops the hold


# determine the entry of the holding pattern
# choice between teardrop, parralel, or normal (none)
def determine_entry(inbound_track, radial_to_IAF):
    relative_bearing = (radial_to_IAF - inbound_track) % 360
    if 110.0 < relative_bearing < 180.0:
        return (inbound_track + 150.0) % 360.0, "teardrop"
    elif 180.0 <= relative_bearing < 290.0:
        return (inbound_track + 180.0) % 360.0, "parallel"
    return None


class Holding(core.Entity):
    def __init__(self):
        super().__init__()
        self.altlimit = 14000
        self.standardleg = 60 #seconds

        self.rate_one = 60 #seconds
        #standard holding patterns for schiphol
        self.holdingpatterns = {
            'SUGOL' : [110,70,110,250],
            'RIVER' : [41,70,110,250],
            'ARTIP' : [252,70,110,250],
            'NARSO' : [355,200,999,220]
        }


        with self.settrafarrays():
            # per-aircraft list to store waypoint names where aircraft are holding, and delay
            self.holding_at = []
            self.timeatwp = []
            self.delay = []

        self.predictor = plugin.Plugin.plugins['NEWTP'].imp.predictor

    @stack.commandgroup
    def holding(self):
        return True, f'Holding patterns defined at {self.holdingpatterns}'


    # main stackcommand to start holding
    @holding.subcommand
    def at(self, acid: 'acid', wpt: 'wpt', delay: 'time' = 0.0):
        ''' Fly the aircraft to holding pattern and let it hold.'''
        # this function starts up the holding logic

        # check if wpt has a holding pattern
        if wpt not in self.holdingpatterns:
            return True, f'{wpt} currently has no holding pattern.'

        # retreive route, check if wpt is in aircraft route
        ac = traf.id[acid]
        acrte = traf.ap.route[acid]
        try:
            index = acrte.wpname.index(wpt)
        except ValueError:
            return True, f'Holding at {wpt} is not possible, not in {ac} route'

        # check if aircraft is already holding at another waypoint
        if self.holding_at[acid] and self.holding_at[acid] != wpt:
            print(self.holding_at[acid])
            return True, f'{ac} already holding at {self.holding_at[acid]}'

        # retreive altitude and speed limits, and selected and planned altitude and speeds of aircraft
        min_alt = 100 * self.holdingpatterns[wpt][1] * aero.ft
        max_alt = 100 * self.holdingpatterns[wpt][2] * aero.ft
        max_spd = self.holdingpatterns[wpt][3] * aero.kts

        selalt = traf.selalt[acid]
        wpalt = acrte.wpalt[index]
        selspd = traf.selspd[acid]
        wpspd = acrte.wpspd[index] if acrte.wpspd[index] > 0 else 0.0

        # check if planned or selected altitude is within bounds for holding
        if (min_alt <= selalt <= max_alt) or (min_alt <= wpalt <= max_alt):
            pass
        else:
            return True, f"{ac} has an altitude outside the holding pattern limits."
        if (selspd <= max_spd) or (wpspd <= max_spd):
            pass
        else:
            return True, f"{ac} has a speed higher than the maximum holding speed."
        if 0.5 < selspd < aero.casmach_thr and 0.5 < wpspd < aero.casmach_thr:
            return True, f"{ac} has a Mach speed selected, which is not allowed in holding."

        # store that the aircraft is holding, and remove planned stackcommands at the waypoint
        self.holding_at[acid] = wpt
        acrte.wpstack[index] = []

        # Make the waypoint a flyover point
        traf.ap.route[acid].wpflyby[index] = False
        if traf.ap.route[acid].wpname[0] == wpt:
            traf.actwp.flyby[acid] = False

        # determine entry track and use stack to enter next step
        entry_track = determine_entry(self.holdingpatterns[wpt][0], (traf.ap.route[acid].wpdirto[index]))
        if entry_track:
            eh, et = entry_track  # heading (deg), type ('parallel'/'teardrop')
            stack.stack(f'AT {ac} {wpt} DO HOLDING ATWP {ac} {eh} {et} {int(delay)}')
        else:
            stack.stack(f'AT {ac} {wpt} DO HOLDING ATWP {ac} 0 none {int(delay)}')


    #stackcommand used to actually hold, not by the user but by the plugin itself
    @holding.subcommand
    def atwp(self, acid: 'acid', entry_hdg: 'hdg', entry_type: 'txt'= 'none', delay: 'time'= 0.0):
        # this function is called each time the aircraft passes over the selected iaf, to perform holding logic
        if self.predictor.parent_id:
            return
        ac = traf.id[acid]
        wpt = self.holding_at[acid]
        acrte = traf.ap.route[acid]
        index = acrte.wpname.index(wpt)
        acrte.wpstack[index] = []
        stackcommands = []

        # determine remaining delay, or store required delay
        if not self.timeatwp[acid] and delay != 0.0:
            remaining_delay = delay
            self.timeatwp[acid] = sim.simt
            self.delay[acid] = delay
            indefinite = False
        elif delay == 0.0 and not self.timeatwp[acid]:
            indefinite = True
        else:
            remaining_delay = self.delay[acid] - (sim.simt - self.timeatwp[acid])
            indefinite = False




        # obtaining values and calculating correction for wind
        selalt = traf.selalt[acid]
        wpalt = acrte.wpalt[index]
        selspd = traf.selspd[acid]
        wpspd = acrte.wpspd[index]
        calculation_spd = wpspd if wpspd > 0 else selspd
        calculation_alt = wpalt if wpalt > 0 else selalt
        expected_tas, cas, mach = aero.vcasormach(calculation_spd, calculation_alt)

        # Calculate the wind correction
        vnorth, veast = traf.wind.getdata(traf.ap.route[acid].wplat[index], traf.ap.route[acid].wplon[index], calculation_alt)
        windspeed, angle = np.hypot(vnorth, veast), np.rad2deg(np.arctan2(veast, vnorth)) % 360
        perpendicular_wind = np.sin(np.deg2rad(angle) - self.holdingpatterns[wpt][0]) * windspeed
        correction = np.rad2deg(np.arctan(perpendicular_wind / expected_tas))


        # determining leg length
        # - Indefinite: fixed short legs for stability and predictable shape.
        # - <100 s remain: cancel (not worth another pattern).
        # - 100–120 s: send a final short segment (0 → handled below) then cancel.
        # - Otherwise: if multiple full patterns needed, use standard leg timing;
        #   if near target, split remainder after budgeting two turns (~2×60 s).

        if indefinite:
            timing = self.standardleg

        elif 100 < remaining_delay < 120:
            timing = 0

        elif remaining_delay < 100:
            # continue route
            stack.stack(f'HOLDING CANCEL {ac}')
            stack.stack(f'PREDICTOR WPTCROSS {ac} {wpt}')
            stack.stack(f'TMA_CROSS {ac}')
            return True, f'{ac} continuing with route, remaining delay of {remaining_delay} seconds.'

        else:
            full_holds = int(remaining_delay / 240)
            if full_holds > 1:
                timing = self.standardleg
            else:
                timing = (remaining_delay - 2*60) /2
        #timing is the time in each leg

        entry_track = None if str(entry_type).lower() == 'none' else (float(entry_hdg), str(entry_type).lower())

        #standard stackcommands, bank to make sure that a standard rate turn is maintained, the speed is due to a vnav bug requiring an override in selected speed
        stackcommands.append('BANK %s %s' % (ac, math.degrees(math.atan(expected_tas / aero.kts / 364))))
        stackcommands.append(f'{ac} SPD {calculation_spd / aero.kts}')
        stability_delay = 1 #second, to make sure that the aircraft behaves correctly

        if entry_track and entry_track[1] == "parallel":
            compensation = 20 ## assumption that part of the initial turn is skipped, (20 seconds is approximation)
            stackcommands.append(f'DELAY {stability_delay} {ac} HDG {(entry_track[0] + 2 * correction + 90) % 360}')                            # turning away from entry track
            stackcommands.append(f'DELAY {compensation} {ac} HDG {entry_track[0] + 2 * correction}')                                            # turning onto entry track
            stackcommands.append(f'DELAY {timing + compensation + 0.5*self.rate_one} HDG {ac} {(entry_track[0] - 90 + 2 * correction) % 360}')  #turning away again from entry track
            stackcommands.append(f'DELAY {timing + compensation + self.rate_one} DIRECT {ac} {wpt}')                                            # heading towards holding point


        elif entry_track and entry_track[1] == "teardrop":

            stackcommands.append(f'DELAY {stability_delay} {ac} HDG {entry_track[0] + 2 * correction}')
            stackcommands.append(f'DELAY {timing + 0.5*self.rate_one} HDG {ac} {(entry_track[0] + 120) % 360}')
            stackcommands.append(f'DELAY {timing + self.rate_one} DIRECT {ac} {wpt}')
            # approximation that outbound leg is half a turn longer than calculated due to lack of initial turn

        elif not entry_track:
            stackcommands.append(f'DELAY {stability_delay} HDG {ac} {(self.holdingpatterns[wpt][0] + 90) % 360}')
            stackcommands.append(f'DELAY {0.5*self.rate_one} HDG {ac} {(self.holdingpatterns[wpt][0] + 180 + 3 * correction) % 360}')           #heading away from iaf
            stackcommands.append(f'DELAY {timing + self.rate_one} DIRECT {ac} {wpt}')                                                           # direct iaf after leg

        # command to be called recursively each time the aircraft passes the iaf
        stackcommands.append(f'AT {ac} {wpt} DO HOLDING ATWP {ac} 0 none')
        stack.stack(*stackcommands)


    @holding.subcommand
    def cancel(self,acid: 'acid'):
        ''' Cancel holding pattern and let the aircraft continue its route.'''
        # automatically called if a holding time is included in holding at
        ac  = traf.id[acid]
        wpt = self.holding_at[acid]
        acrte = traf.ap.route[acid]
        index = acrte.wpname.index(wpt)
        self.holding_at[acid] = []
        acrte.wpstack[index] = []
        nextwpt = acrte.wpname[index+1]
        stack.stack('DIRECT %s %s' % (ac, nextwpt))
        stack.stack(f'{ac} LNAV ON')
        stack.stack(f'{ac} VNAV ON')
        return True, f'{ac} is no longer holding.'



    @holding.subcommand
    def define(self, wpt:'wpt', radial: 'hdg', lower_FL: 'alt' = 0.0, upper_FL: 'alt' =999.0, max_ias: 'spd'=250.0):
        # function to define holding pattern
        # Requires waypoint and radial, possible settings are lower and upper limits, and maximum entry speed
        if wpt in self.holdingpatterns.keys():
            stack.stack(f'ECHO WARNING: overwriting existing holdingpattern at {wpt}')
        self.holdingpatterns[wpt] = [radial, round(lower_FL/aero.ft,1), round(upper_FL/aero.ft,1), round(max_ias/aero.kts,1)]

        return True, f'Holding at {wpt} defined. radial: {radial}, lower FL {lower_FL}, upper FL {upper_FL}, max ias {max_ias}.`'



