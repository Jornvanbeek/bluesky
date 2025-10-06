""" BlueSky Holding plugin"""
# Import the global bluesky objects. Uncomment the ones you need
from bluesky import core, stack, traf, sim  #, settings, navdb, sim, scr, tools
import math, inspect
from bluesky.tools import aero
import numpy as np



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





# determine the entry of the holding pattern
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
        self.shortleg = 60 #seconds
        self.longleg = 90 #seconds
        self.rate_one = 60 #seconds
        self.holdingpatterns = {
            'SUGOL' : [110,70,100,250],
            'RIVER' : [41,70,100,250],
            'ARTIP' : [252,70,100,250],
            'NARSO' : [355,200,999,220]
        }

        with self.settrafarrays():
            # per-aircraft list to store waypoint names where aircraft are holding
            self.holding_at = []
            self.timeatwp = []
            self.delay = []



    @stack.command
    def holdat(self, acid: 'acid', wpt: 'wpt', delay: 'time' = 0.0):
        ''' Fly the aircraft to holding pattern and let it hold.'''

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

        # store that the aircraft is holding, and remove stackcommands at the waypoint
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
            stack.stack(f'AT {ac} {wpt} DO ATHOLDWP {ac} {eh} {et} {int(delay)}')
        else:
            stack.stack(f'AT {ac} {wpt} DO ATHOLDWP {ac} 0 none {int(delay)}')


    @stack.command
    def atholdwp(self, acid: 'acid', entry_hdg: 'hdg', entry_type: 'txt'= 'none', delay: 'time'= 0.0):


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
        vnorth, veast = traf.wind.getdata(traf.ap.route[acid].wplat[index], traf.ap.route[acid].wplat[index], calculation_alt)
        windspeed, angle = np.hypot(vnorth, veast), np.rad2deg(np.arctan2(veast, vnorth)) % 360
        perpendicular_wind = np.sin(np.deg2rad(angle) - self.holdingpatterns[wpt][0]) * windspeed
        correction = np.rad2deg(np.arctan(perpendicular_wind / expected_tas))


        # determining leg length
        # in short: <100 s is no delay, hold is canceled.
        # multiple holds? standard leglength for the coming one
        # (1 full and) 1 partial hold? determine leglength to end up near to the delay goal
        if indefinite:
            timing = self.shortleg
        elif 100 < remaining_delay < 120:
            timing = 0
        elif remaining_delay < 100:
            # continue route
            stack.stack(f'CANCELHOLD {ac}')
            stack.stack(f'PREDICTOR WPTCROSS {ac} {wpt}')
            stack.stack(f'TMA_CROSS {ac}')
            return True, f'{ac} continuing with route, remaining delay of {remaining_delay} seconds.'
        else:
            full_holds = int(remaining_delay / 240)
            if full_holds > 1:
                timing = self.shortleg
            else:
                timing = (remaining_delay - 2*60) /2


        entry_track = None if str(entry_type).lower() == 'none' else (float(entry_hdg), str(entry_type).lower())

        #standard stackcommands
        stackcommands.append('BANK %s %s' % (ac, math.degrees(math.atan(expected_tas / aero.kts / 364))))
        stackcommands.append(f'{ac} SPD {calculation_spd / aero.kts}')# todo add comment

        if entry_track and entry_track[1] == "parallel":
            stackcommands.append(f'DELAY 1 {ac} HDG {(entry_track[0] + 2 * correction + 90) % 360}')
            stackcommands.append(f'DELAY 20 {ac} HDG {entry_track[0] + 2 * correction}')
            stackcommands.append(f'DELAY {timing+20+30} HDG {ac} {(entry_track[0] - 90 + 2 * correction) % 360}')
            stackcommands.append(f'DELAY {timing +20+ 60} DIRECT {ac} {wpt}')
            # assumption that part of the initial turn is skipped, (20 seconds is approximation)

        elif entry_track and entry_track[1] == "teardrop":
            stackcommands.append(f'DELAY 1 {ac} HDG {entry_track[0] + 2 * correction}')
            stackcommands.append(f'DELAY {timing +30} HDG {ac} {(entry_track[0] + 120) % 360}')
            stackcommands.append(f'DELAY {timing +60} DIRECT {ac} {wpt}')
            # approximation that outbound leg is 30 seconds longer than calculated due to lack of initial turn

        elif not entry_track:
            stackcommands.append(f'DELAY 1 HDG {ac} {(self.holdingpatterns[wpt][0] + 90) % 360}')
            stackcommands.append(f'DELAY 30 HDG {ac} {(self.holdingpatterns[wpt][0] + 180 + 3 * correction) % 360}')
            stackcommands.append(f'DELAY {timing + 60} DIRECT {ac} {wpt}')


        stackcommands.append(f'AT {ac} {wpt} DO ATHOLDWP {ac} 0 none')
        stack.stack(*stackcommands)


    @stack.command
    def cancelhold(self,acid: 'acid'):
        ''' Cancel holding pattern and let the aircraft continue its route.'''
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



    @stack.command
    def defhold(self, wpt:'wpt', radial: 'hdg', lower_FL: 'alt' = 0.0, upper_FL: 'alt' =999.0, max_ias: 'spd'=250.0):
        # function to define holding pattern
        if wpt in self.holdingpatterns.keys():
            stack.stack(f'ECHO WARNING: overwriting existing holdingpattern at {wpt}')
        self.holdingpatterns[wpt] = [radial, round(lower_FL/aero.ft,1), round(upper_FL/aero.ft,1), round(max_ias/aero.kts,1)]





















    @stack.command
    def holdat_old(self, acid: 'acid', wpt: 'wpt'):
        ''' Fly the aircraft to holding pattern and let it hold.'''

        if wpt not in self.holdingpatterns:
            return True, f'{wpt} currently has no holding pattern.'


        # Define aircraft name and index
        ac  = traf.id[acid]

        if len(self.holding_at[acid]) > 0 and self.holding_at[acid] != wpt:
            return True, f'{ac} already holding at {self.holding_at[acid]}'


        # Altitude limits in meters
        min_alt = 100 * self.holdingpatterns[wpt][1] * aero.ft
        max_alt = 100 * self.holdingpatterns[wpt][2] * aero.ft
        max_kts = self.holdingpatterns[wpt][3]


        acrte = traf.ap.route[acid]
        try:
            index = acrte.wpname.index(wpt)
        except ValueError:
            return True, f'Holding at {wpt} is not possible, not in {ac} route'

        # actuele selected altitude
        selalt = traf.selalt[acid]
        selspd_kts = traf.selspd[acid] / aero.kts
        wpalt = acrte.wpalt[index]
        wp_spd_kts = acrte.wpspd[index] / aero.kts if acrte.wpspd[index] > 0 else 0.0
        selspd = traf.selspd[acid]
        wpspd = acrte.wpspd[index]

        calculation_alt = wpalt if wpalt > 0 else selalt
        calculation_spd = wpspd if wpspd > 0 else selspd



        if (min_alt <= selalt <= max_alt) or (min_alt <= wpalt <= max_alt):
            pass
        else:
            return True, f"{ac} has an altitude outside the holding pattern limits."

        if (selspd_kts <= max_kts) or (wp_spd_kts <= max_kts):
            pass
        else:
            return True, f"{ac} has a speed higher than the maximum holding speed."

        if 0.5 < selspd < aero.casmach_thr and 0.5 < wpspd < aero.casmach_thr:
            return True, f"{ac} has a Mach speed selected, which is not allowed in holding."



        expected_tas, cas, mach = aero.vcasormach(calculation_spd, calculation_alt)

        # check when to print in terminal
        echo = False

        # Calculate the wind correction
        vnorth, veast = traf.wind.getdata(traf.ap.route[acid].wplat[index],traf.ap.route[acid].wplat[index],calculation_alt)
        windspeed, angle = np.hypot(vnorth, veast), np.rad2deg(np.arctan2(veast, vnorth))%360
        perpendicular_wind = np.sin(np.deg2rad(angle)-self.holdingpatterns[wpt][0])*windspeed
        correction = np.rad2deg(np.arctan(perpendicular_wind/expected_tas))

        self.holding_at[acid] = wpt

        # Determine the entry of the holding pattern
        entry_track = determine_entry(self.holdingpatterns[wpt][0],(traf.ap.route[acid].wpdirto[index]))

        # Make the waypoint a flyover point
        traf.ap.route[acid].wpflyby[index] = False
        if traf.ap.route[acid].wpname[0] == wpt:
            traf.actwp.flyby[acid] = False


        # Set the holding pattern inbound time
        timing = (self.longleg if calculation_alt*100/aero.ft >= self.altlimit else self.shortleg)

        # rate one turn
        stack.stack('BANK %s %s' % (ac, math.degrees(math.atan(expected_tas/aero.kts/364))))
        funcname = inspect.currentframe().f_code.co_name

        if entry_track and entry_track[1] == "parallel":
            traf.ap.route[acid].wpstack[index] = [f'DIRECT {ac} {wpt}']
            traf.ap.route[acid].wpstack[index] += [f'{ac} SPD {calculation_spd/aero.kts}']
            traf.ap.route[acid].wpstack[index] += [f'{ac} HDG {entry_track[0]+2*correction}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing} HDG {ac} {(entry_track[0]-90+2*correction) %360}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing+30} DIRECT {ac} {wpt}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing+30} {funcname} {ac} {wpt}']
            print('parallel')

        elif entry_track and entry_track[1] == "teardrop":
            traf.ap.route[acid].wpstack[index] = [f'DIRECT {ac} {wpt}']
            traf.ap.route[acid].wpstack[index] += [f'{ac} SPD {calculation_spd/aero.kts}']
            traf.ap.route[acid].wpstack[index] += [f'{ac} HDG {entry_track[0]+2*correction}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing+10} HDG {ac} {(entry_track[0]+120) %360}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing+40} DIRECT {ac} {wpt}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing+40} {funcname} {ac} {wpt}']
            print('teardrop')

        elif not entry_track:
            traf.ap.route[acid].wpstack[index] = [f'DIRECT {ac} {wpt}']
            traf.ap.route[acid].wpstack[index] += [f'{ac} SPD {calculation_spd/aero.kts}']
            traf.ap.route[acid].wpstack[index] += [f'{ac} HDG {(self.holdingpatterns[wpt][0]+90)%360}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY 30 HDG {ac} {(self.holdingpatterns[wpt][0]+180+3*correction)%360}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing+60} DIRECT {ac} {wpt}']
            print('no entry track')

        if echo:
            return True, f'{ac} is now holding at {wpt}.'


