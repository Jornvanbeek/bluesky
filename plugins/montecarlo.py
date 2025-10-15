
from bluesky import core, stack, scr, traf, sim, net, network, settings, HOLD, INIT, END
from bluesky.core import signal
# from bluesky.plugins.windecmwf import datadir
from bluesky.stack.simstack import readscn
from bluesky.network.common import genid, GROUPID_SIM, GROUPID_CLIENT
from bluesky.traffic.route import Route
from bluesky.tools.position import txt2pos
from bluesky.tools.aero import casormach2tas, fpm, kts, ft, g0, Rearth, nm, tas2cas, \
    vatmos, vtas2cas, vtas2mach, vcasormach

from bluesky.core import Signal
from bluesky.traffic import Traffic

from multiprocessing import cpu_count

import pandas as pd


def init_plugin():
    """Initializes the plugin and creates an instance of the Predictor."""

    # Create an instance of the Predictor class
    global amanbatch
    amanbatch = aman_batch()

    # Configuration for the plugin, specifying its name and type.
    config = {
        'plugin_name': 'MONTECARLO',
        'plugin_type': 'sim',
    }
    return config




class aman_batch(core.Entity):
    """
    Manages prediction logic for the Trajectory Predictor.

    Attributes:
        parent_id (bytes): ID for the parent node process.
        child_id (bytes): ID for the child node prediction process.
        commands_to_schedule (list): List of commands with their scheduled execution times.
        previous_scenario_file (str): Name of the last scenario file loaded.
        utc (int): Universal Time Coordinated (UTC) used for time synchronization in predictions.
        scenario_commands (list): Cache of commands extracted from scenario files for execution.
        acid_to_predict (set): Set of aircraft to predict each time the prediction starts
    """

    def __init__(self):
        super().__init__()

        # Initialize class properties with default values.
        self.parent_id = b''
        self.children = dict()
        self.names = dict()
        self.avail_nodes = set()

        # super().__init__()
        #
        # net.send(b'BATCH', (scentime, scencmd), bs.net.server_id)

    @signal.subscriber(topic='node-added')
    def on_node_added(self, node_id):
        """ Gets triggered everytime a new node is added. """

        # Check if the added node is the child node to start the predict method.
        print('MONTECARLO: ', node_id)
