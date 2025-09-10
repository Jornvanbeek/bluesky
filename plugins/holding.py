""" BlueSky Holding plugin"""
# Import the global bluesky objects. Uncomment the ones you need
from bluesky import core, stack, traf  #, settings, navdb, sim, scr, tools
import math
from bluesky.tools import aero
import numpy as np


### Initialization function of your plugin. Do not change the name of this
### function, as it is the way BlueSky recognises this file as a plugin.
def init_plugin():

    # Addtional initilisation code
        # Configuration parameters
    config = {
        # The name of your plugin
        'plugin_name':     'Holding',

        # The type of this plugin.
        'plugin_type':     'sim'
        }
        # init_plugin() should always return the config dict.
    return config


holding_patterns = {
    'SUGOL' : [110,70,100,250],
    'RIVER' : [41,70,100,250],
    'ARTIP' : [252,70,100,250],
    'NARSO' : [355,200,999,220]
}


# determine the entry of the holding pattern
def determine_entry(inbound_track, radial_to_IAF):
    relative_bearing = (radial_to_IAF - inbound_track) % 360
    if relative_bearing < 180 and relative_bearing > 110: # teardrop
        return (inbound_track + 150) % 360, "teardrop"
    elif relative_bearing >= 180 and relative_bearing < 290: # parallel
        return (inbound_track + 180) % 360, "parallel"
    return None


class Holding(core.Entity):
    def __init__(self):
        super().__init__()

        with self.settrafarrays():
            # per-aircraft list to store waypoint names where aircraft are holding
            self.holding_at = []

    @stack.command
    def holdat(self, acid: 'acid', wpt: 'wpt'):
        ''' Fly the aircraft to holding pattern and let it hold.'''

        if wpt not in holding_patterns:
            return True, f'{wpt} currently has no holding pattern.'
        
        # Define aircraft name and index
        ac  = traf.id[acid]
        index = traf.ap.route[acid].wpname.index(wpt)

        # Check if the aircraft is at the right altitude for the holding
        if traf.selalt[acid] < holding_patterns[wpt][1]*0.3048 or traf.selalt[acid] > holding_patterns[wpt][2]*0.3048:
            return True, f'{ac} has an altitude outside the holding pattern limits.'
        
        # Check if the aircraft is at the right speed for the holding
        if traf.selspd[acid] > holding_patterns[wpt][3]*1.852/3.6:
            return True, f'{ac} has a speed higher than the maximum holding speed.'
        
        # check when to print in terminal
        echo = False

        # Calculate the wind correction
        vnorth, veast = traf.wind.getdata(traf.ap.route[acid].wplat[index],traf.ap.route[acid].wplat[index],traf.alt[acid])
        windspeed, angle = np.hypot(vnorth, veast), np.rad2deg(np.arctan2(veast, vnorth))%360
        perpendicular_wind = np.sin(np.deg2rad(angle)-holding_patterns[wpt][0])*windspeed
        correction = np.rad2deg(np.arctan(perpendicular_wind/traf.tas[acid]))

        # Check if the flight level is already occupied in holding at the waypoint
        if not self.holding_at[acid]:
            echo = True
            for i in range(len(self.holding_at)):
                if self.holding_at[i] == wpt and traf.alt[i] == traf.alt[acid] and i != acid:
                    return True,  f'{traf.id[i]} is already holding at {wpt}.'

        self.holding_at[acid] = wpt
        
        # Determine the entry of the holding pattern
        entry_track = determine_entry(holding_patterns[wpt][0],(traf.ap.route[acid].wpdirto[index]))

        # Make the waypoint a flyover point
        traf.ap.route[acid].wpflyby[index] = False
        if traf.ap.route[acid].wpname[0] == wpt:
            traf.actwp.flyby[acid] = False

        # Set the holding pattern inbound time
        timing = (90 if traf.selalt[acid]*100/aero.ft > 14000 else 60)

        # rate one turn
        stack.stack('BANK %s %s' % (ac, math.degrees(math.atan(traf.tas[acid]*3.6/1.852/364))))

        if entry_track and entry_track[1] == "parallel":
            traf.ap.route[acid].wpstack[index] = [f'DIRECT {ac} {wpt}']
            traf.ap.route[acid].wpstack[index] += [f'{ac} HDG {entry_track[0]+2*correction}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing} HDG {ac} {(entry_track[0]-90+2*correction) %360}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing+30} DIRECT {ac} {wpt}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing+30} start_holding {ac} {wpt}']

        elif entry_track and entry_track[1] == "teardrop":
            traf.ap.route[acid].wpstack[index] = [f'DIRECT {ac} {wpt}']
            traf.ap.route[acid].wpstack[index] += [f'{ac} HDG {entry_track[0]+2*correction}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing+10} HDG {ac} {(entry_track[0]+120) %360}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing+40} DIRECT {ac} {wpt}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing+40} start_holding {ac} {wpt}']

        elif not entry_track:
            traf.ap.route[acid].wpstack[index] = [f'DIRECT {ac} {wpt}']
            traf.ap.route[acid].wpstack[index] += [f'{ac} HDG {(holding_patterns[wpt][0]+90)%360}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY 30 HDG {ac} {(holding_patterns[wpt][0]+180+3*correction)%360}']
            traf.ap.route[acid].wpstack[index] += [f'DELAY {timing+60} DIRECT {ac} {wpt}']

        if echo:
            return True, f'{ac} is now holding at {wpt}.'

    @stack.command
    def cancel_holding(acid: 'acid', wpt: 'wpt'):
        ''' Cancel holding pattern and let the aircraft continue its route.'''
        ac  = traf.id[acid]
        self.holding_at[acid] = []
        traf.ap.route[acid].wpstack[traf.ap.route[acid].wpname.index(wpt)] = []
        stack.stack('DIRECT %s %s' % (ac, wpt))
        return True, f'{ac} is no longer holding.'
