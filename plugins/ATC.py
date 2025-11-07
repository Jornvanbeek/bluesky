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
        self.instructions = []


    def instruct(self, acid, ttlg):



        instructed = 'delay' + speed/dogleg/mach/holding
        or = 'shorten' + direct/speed


    def on_prediction_received(self):
        if self.aman.Flights[acid, state] == instructed
