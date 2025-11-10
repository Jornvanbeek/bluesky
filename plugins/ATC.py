# amanatc.py
from textwrap import shorten

from PIL.ImageChops import difference
from scipy.optimize import direct

from bluesky import core, stack, traf, sim, HOLD, net
from bluesky import server
# from plugins.AMANtwo import AMAN  # Import the global reference from AMANtwo
from bluesky.core import plugin
from bluesky.plugins.sectorcount import update
from bluesky.test.tcp.test_simple import test_pos
from bluesky.tools.aero import kts, ft, nm
import pandas as pd
from bluesky.tools.geo import kwikpos, qdrpos, kwikdist, qdrdist
from bluesky.tools.geo import kwikqdrdist
from bluesky.traffic.route import Route
import math

from plugins.amanhelpers.aman_settings import instruct


def init_plugin():
    config = {
        'plugin_name': 'amanATC',
        'plugin_type': 'sim'
    }
    # Create an instance of the class below so BlueSky recognizes it as a plugin
    atc_plugin = ATC()
    return config

class ATC(core.Entity):
    def __init__(self):
        super().__init__()
        self.crossover = None#this gives some errors with initialization
        # plugin.Plugin.plugins['MACH_CROSSOVER'].imp.CROSSOVER
        self.aman = plugin.Plugin.plugins['AMANTWO'].imp.AMAN
        self.predictor = plugin.Plugin.plugins['NEWTP'].imp.predictor
        self.mach_threshold = 0
        self.handover_alt = 260.*100 # moet naar amansettings
        self.aman.Flights['instruction'] = None
        self.aman.Flights['TPstate'] = ' '
        self.aman.Flights['count'] = 0
        self.aman.Flights['count'] = self.aman.Flights['count'].astype(int)
        self.aman.Flights['instruction'] = self.aman.Flights['instruction'].astype(object)
        self.aman.Flights['TPstate'] = self.aman.Flights['TPstate'].astype(object)


        self.aman.Flights['selspd'] = None
        self.aman.Flights['dogleg'] = None
        self.aman.Flights['dogleg'] = self.aman.Flights['dogleg'].astype(bool)
        self.aman.Flights['direct'] = None
        self.aman.Flights['holding'] = None
        self.aman.Flights['earliest'] = False
        self.instructionlist = {}
        self.instructions = []




    def reset(self):
        super().reset()
        self.crossover = None#this gives some errors with initialization
        # plugin.Plugin.plugins['MACH_CROSSOVER'].imp.CROSSOVER
        self.aman = plugin.Plugin.plugins['AMANTWO'].imp.AMAN
        self.predictor = plugin.Plugin.plugins['NEWTP'].imp.predictor
        self.mach_threshold = 0
        self.handover_alt = 260.*100
        self.aman.Flights['instruction'] = None
        self.aman.Flights['TPstate'] = ' '
        self.aman.Flights['count'] = 0
        self.aman.Flights['count'] = self.aman.Flights['count'].astype(int)
        self.aman.Flights['instruction'] = self.aman.Flights['instruction'].astype(object)
        self.aman.Flights['TPstate'] = self.aman.Flights['TPstate'].astype(object)
        self.aman.Flights['selspd'] = None
        self.aman.Flights['dogleg'] = None
        self.aman.Flights['dogleg'] = self.aman.Flights['dogleg'].astype(bool)
        self.aman.Flights['direct'] = None
        self.aman.Flights['holding'] = None
        self.aman.Flights['earliest'] = False
        self.instructionlist = {}
        columns = ['acid', 'speed', 'dogleg', 'holding', '']
        self.instructions = pd.DataFrame()



    @stack.command
    def instruct_frozen(self):
        frozen_flights = self.aman.Flights[self.aman.Flights['planningstate'] == 'frozen']
        if self.aman.instruct:
            self.instructions = []
            if len(frozen_flights) > 0:
                if sim.state != HOLD:
                    self.rtf = sim.dtmult
                    self.ff = sim.ffmode

                sim.hold()
                # while True:
                self.aman.update_times()

                delay = frozen_flights[frozen_flights['ttlg'] > self.aman.late_approach_margin]
                shorten = frozen_flights[frozen_flights['ttlg'] < self.aman.early_approach_margin]
                delay = delay.dropna(subset=['ttlg'])
                shorten = shorten.dropna(subset=['ttlg'])

                for acid, row in delay.iterrows():
                    self.delay(acid, float(row['ttlg']))

                for acid, row in shorten.iterrows():
                    self.shorten(acid, float(row['ttlg']))

                #TODO
                # evt small instructions
                # update TP

    def delay(self, acid, ttlg):
        instructed = 'delay' + speed/dogleg/mach/holding
        self.aman.Flights.at[acid, state] = instructed

    def shorten(self, acid, ttlg):

        'shorten' + direct / speed
        self.aman.Flights.at[acid, state] = instructed

    def on_prediction_received(self):
        if self.aman.Flights[acid, state] == instructed
            process prediction
            calculate ttlg
            calculate effective delay/speed up
            ttlg still too large? onto the next option
            ttlg too small now? reduce last option

    def further_instruction(self, acid, ttlg):
