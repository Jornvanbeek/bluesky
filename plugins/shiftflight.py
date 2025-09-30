from bluesky import core, stack, traf, sim  #, settings, navdb, sim, scr, tools
import math, inspect
from bluesky.tools import aero
import numpy as np


def init_plugin():

    # Addtional initilisation code
        # Configuration parameters

    holding = shiftflight()

    config = {
        # The name of your plugin
        'plugin_name':     'shiftflight',
        # The type of this plugin.
        'plugin_type':     'sim'
        }
        # init_plugin() should always return the config dict.
    return config

class shiftflight(core.Entity):
    def __init__(self):
        super().__init__()

    @stack.command
    def shift(self, acid, error: float):
        """
        Shift all scheduled scenario commands for `acid` by `error` seconds.
        """
        cmds = stack.stackbase.Stack.scencmd
        times = stack.stackbase.Stack.scentime

        # count = 0
        # for i, cmd in enumerate(cmds):
        #     if acid in cmd:
        #         times[i] += error
        #         count += 1

        for i, cmd in enumerate(cmds):
            if acid in cmd:
                times[i] = max(0.0, times[i] + error)

        # sort back in time order
        pairs = sorted(zip(times, cmds), key=lambda x: x[0])
        stack.stackbase.Stack.scentime = [p[0] for p in pairs]
        stack.stackbase.Stack.scencmd = [p[1] for p in pairs]



        # ensure the mutated list/array is stored back
        # stack.stackbase.Stack.scentime = times
        print(stack.stackbase.Stack.scentime)
        # todo schedule gebruiken ipv shift?

    @stack.command
    def printstackbase(self):
        print(stack.stackbase.Stack.scencmd)
        print(stack.stackbase.Stack.scentime)