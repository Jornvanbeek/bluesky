"""
Plugin containing a deterministic trajectory predictor that predicts the arrival times of aircraft at the waypoints.

The methodology that is used for building the trajectory predictor is by running two simulations in two different
nodes, where the scenario in one node is restarted and fast-forwarded each time its gets triggered by the autopilot,
and the other simulation is the main simulation and runs the scenario as it is. The fast-forwarded simulation sends
the measured states of the aircraft back to the other simulation, where this other simulation can then show on the
interface what the future states of the aircraft will be. The main simulation is run in the parent node, and the
fast-forwarded simulation is run in the child node.

In the Bluesky Python files, the comment '# PREDICTOR' is added where changes in code are made for the trajectory
predictor to function.
"""
import csv
import re
from collections import defaultdict
from datetime import datetime
import pickle
import difflib

import numpy as np

# from OpenGL.raw.GL.APPLE.vertex_program_evaluators import glIsVertexAttribEnabledAPPLE

from bluesky import core, stack, scr, traf, sim, net, network
from bluesky.core import signal, timed_function
from bluesky.network.context import topic
# from bluesky.plugins.windecmwf import datadir
from bluesky.stack.simstack import readscn
from bluesky.network.common import genid, GROUPID_SIM
from bluesky.traffic.route import Route
from bluesky.tools.position import txt2pos
from bluesky.tools.aero import casormach2tas, fpm, kts, ft, g0, Rearth, nm, tas2cas,\
                         vatmos,  vtas2cas, vtas2mach, vcasormach

from bluesky.core import Signal
from bluesky.traffic import Traffic


def init_plugin():
    """Initializes the plugin and creates an instance of the Predictor."""

    # Create an instance of the Predictor class
    global predictor
    predictor = Predictor()

    # Configuration for the plugin, specifying its name and type.
    config = {
        'plugin_name': 'NEWTP',
        'plugin_type': 'sim',
    }
    return config





def pack_attrs(obj, exclude: set[str] | None = None, include: set[str] | None = None) -> dict:

    exclude = exclude or set()
    dct = getattr(obj, "__dict__", {})
    if include is not None:
        return {k: v for k, v in dct.items() if k in include and k not in exclude}
    return {k: v for k, v in dct.items() if k not in exclude}

def unpack_attribs(obj, data: dict):

    for k, v in data.items():
        setattr(obj, k, v)




class Route(Route):
    """Extends the Route class to save the prediction times."""
    def __init__(self, acid):
        super().__init__(acid)
        # PREDICTOR
        self.wptime = []  # The predicted time that the aircraft arrives at the waypoint
        self.wptpredutc = []  # The predicted utc time that the aircraft arrives at the waypoint
        self.iaf = None
        self.EAT = None
        self.planningstate = None
        self.ETA = None
        self.ETO_IAF = None
        self.slot = None
        self.createtime = None

    def addwpt_data(self, overwrt, wpidx, wpname, wplat, wplon, wptype, wpalt, wpspd):
        """Initialize the prediction times for the waypoints."""
        super().addwpt_data(overwrt, wpidx, wpname, wplat, wplon, wptype, wpalt, wpspd)
        if overwrt:
            self.wptime[wpidx] = -999.0
            self.wptpredutc[wpidx] = -999.0
        else:
            self.wptime.insert(wpidx, -999.0)
            self.wptpredutc.insert(wpidx, -999.0)

        if wpname in ['ARTIP', 'SUGOL', 'RIVER']:
            self.iaf = wpname
            stack.stack(f'{self.acid} AT {self.iaf} DO TMA_CROSS {self.acid}')
        if wpname in ['ARTIP', 'SUGOL', 'RIVER'] or 'EHAM/RW' in wpname:
            global predictor
            if self.acid in predictor.predicted_ac_not_spawned.keys():
                predictor.assign_tp_data(self.acid, wpname)
            # stack.stack(f'{self.acid} ADDPREDICTION {wpname}')# DO PREDICTOR WPTCROSS {self.acid} {wpname}')
        if 'EHAM/RW' in wpname and self.iaf:
            stack.stack(f'{self.acid} AT {self.iaf} DO TMA_CROSS {self.acid}')




class Route(Route):
    """Extends the Route class for use with prediction for the child prediction node."""

    def addwpt_data(self, overwrt, wpidx, wpname, wplat, wplon, wptype, wpalt, wpspd):
        """Upon adding waypoint data, triggers a prediction for the waypoint crossing."""
        if wpname in ['ARTIP', 'SUGOL', 'RIVER'] or 'EHAM/RW' in wpname:
            stack.stack(f'{self.acid} AT {wpname} DO PREDICTOR WPTCROSS {self.acid} {wpname}')
        return super().addwpt_data(overwrt, wpidx, wpname, wplat, wplon, wptype, wpalt, wpspd)


class Predictor(core.Entity):
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
        self.child_id = b''


        self.commands_to_schedule = []

        # The following attributes are for filtering the scenario commands
        self.acid_to_predict = set()
        self.previous_scenario_file = ''
        self.scenario_commands = []
        self.scenario_commands_times = []
        self.commands_per_flight = defaultdict(list)
        self.predicted_ac_not_spawned = {}
        self.predictions_cache = {}
        self.use_cache = False
        self.acids = set()

        # Counter for automatic fast-forward functionality
        self.counter = 0
        self.wptcrosscount = 0
        self.predictions = 0
        self.predictions_count_required = None

        self.predictions_complete = False

        self.fast_tp = True

        traf.traf_parent_id = None

        # self.incorrect_predictions = ['AIA6768', 'KLM76QSH', 'EZY91XM']
        self.incorrect_predictions = ['KLM590SH']
        # Change the route class implementation for the child node using PredictorNodeRoute class.
        stack.stack('IMPLEMENTATION Route Route')


    @stack.command
    def printattrib(self, attrib):

        try:
            print(getattr(self, attrib))
        except AttributeError:
            print(f"Attribute '{attrib}' does not exist.")

    @stack.command
    def print_wpnames(self,acid):
        idxac = traf.id2idx(acid)
        print(traf.ap.route[idxac].wpname)

    @signal.subscriber(topic='stack-changed')
    def on_stack_changed(self, cmdline):
        """ Handles changes in the command stack, filtering commands. Every stack whether a stack command or a command
        from a scenerio file is published through the signal. Therefore, it is also important to ensure that commands.
        Are not called twice in the predictor node."""

        # Ensure this runs only in the main node.
        # Filter out commands that would disrupt the functionality of the predictor.
        if wptcross_check(cmdline):
            self.wptcrosscount += 1

        if self.parent_id or cmds_disrupt_predictor(cmdline):
            return
        # print('outside', cmdline)
        # if cmds_disrupt_predictor(cmdline):
            # print('not', cmdline)
        # Save the command time
        cmdtime = sim.simt


        # Add scheduled commands as scenario commands else they will be executed twice.
        if schedule_in_cmdline(cmdline):
            self.scenario_commands.append(schedule_in_cmdline(cmdline))
            self.scenario_commands_times.append(cmdtime)
            self.commands_to_schedule.append((cmdtime, schedule_in_cmdline(cmdline)))
            acid = self.acid_in_cmdline(cmdline)
            self.commands_per_flight[acid].append((cmdtime, schedule_in_cmdline(cmdline)))

        # Load commands from a scenario file if specified.
        elif scenario_in_cmdline(cmdline):
            self.load_scenario_commands(cmdline)

        # Do not execute commands from the scenario files for the predictor else it will be executed twice.
        elif cmdline in self.scenario_commands:
            idx = self.scenario_commands.index(cmdline)

            if cmdtime == self.scenario_commands_times[idx]:
                del self.scenario_commands[idx]
                del self.scenario_commands_times[idx]
        else:

            if self.acid_in_cmdline(cmdline):
                tes = 1
                # cmd_checks = (addwpt_cmd_check(cmdline) or
                #           speed_cmd_check(cmdline)  or
                #           alt_cmd_check(cmdline) or
                #           direct_cmd_check(cmdline))

            cmd_checks = (speed_cmd_check(cmdline) or alt_cmd_check(cmdline) or direct_cmd_check(cmdline) or reduce_mach_check(cmdline))
            # Add the acid in the cmdline if it is there to acid_to_predict to make a new prediction for it.
            (self.acid_in_cmdline(cmdline) and cmd_checks and self.acid_to_predict.add(self.acid_in_cmdline(cmdline)))

            # Add the commands in commands_to_schedule to schedule them in the predictor node.
            if not sim_cmds_check(cmdline):
                self.commands_to_schedule.append((cmdtime, cmdline))
                acid = self.acid_in_cmdline(cmdline)
                self.commands_per_flight[acid].append((cmdtime, cmdline))

            if self.predictions_complete and cmd_checks:
                stack.stack('PREDICTOR UPDATE '+self.acid_in_cmdline(cmdline))
                # print('predictor started? ', cmdline, self.parent_id, self.child_id)




        if wptcross_check(cmdline):
            self.wptcrosscount +=1




    def load_scenario_commands(self, cmdline):
        """ Loads commands from a scenario file. """

        # Get the filename from the cmdline using the 'scenario_in_cmdline' function
        filename = scenario_in_cmdline(cmdline)

        # If the filename is 'IC', use the most recently loaded scenario file's name instead.
        if filename == 'IC':
            filename = self.previous_scenario_file

        # Update the last loaded scenario file.
        self.previous_scenario_file = filename

        # Attempt to read the scenario file and append each command found within to the list of scenario commands.
        try:
            for (cmdtime, cmd) in readscn(filename):




                # Add the commands in commands_to_schedule to schedule them in the predictor node.
                self.commands_to_schedule.append((cmdtime, cmd))

                # Add the acid in the cmdline to acid_to_predict to make a new prediction for it, if it exists.
                if self.acid_in_cmdline(cmd):
                    self.acid_to_predict.add(self.acid_in_cmdline(cmd))

                # Add commands to scenario_commands to make sure that they are not executed twice.
                self.scenario_commands.append(cmd)
                self.scenario_commands_times.append(cmdtime)
                acid = self.acid_in_cmdline(cmd)
                self.commands_per_flight[acid].append((cmdtime, cmd))

                if wptcross_check(cmd):
                    self.wptcrosscount += 1



        except FileNotFoundError:
            stack.echo('Error from predictor: the following scenario file is not found: ' + filename)

    def create(self, n=1):
        """ Gets triggered everytime n number of new aircraft are created. """
        super().create(n)
        # if self.child_id:
        for i in range(n):
            traf.ap.route[-i-1].createtime = sim.simt
        # print(traf.ap.route[-n].createtime)
        # Ensure this runs only in the main node.
        if self.parent_id:
            return


        self.acid_to_predict.update(traf.id[-1 - i] for i in range(n))


    def assign_tp_data(self,acid,wpname):#,id):
        wptlist  = self.predicted_ac_not_spawned[acid]
        idxac = traf.id2idx(acid)
        # if idxac == id:
        for items in wptlist:
            (wpt, wptime, wptpredutc,flighttime, estimatedcreatetime, parent_id, type) = items
            if wpname == wpt:

                idxwp = traf.ap.route[idxac].wpname.index(wpt)
                traf.ap.route[idxac].wptpredutc[idxwp] = wptpredutc
                traf.ap.route[idxac].wptime[idxwp] = wptime
                wptlist.remove(items)
                if len(wptlist) == 0:
                    del self.predicted_ac_not_spawned[acid]


                #scr.echo(f'Prediction assigned: {acid} reached {wpt} at {datetime.fromtimestamp(wptpredutc, tz=None)} seconds, stored in traf')

                break


    @signal.subscriber(topic='node-added')
    def on_node_added(self, node_id):
        """ Gets triggered everytime a new node is added. """

        # Check if the added node is the child node to start the predict method.
        if node_id == self.child_id:
            stack.forward('PREDICTOR CLAIM', target_id=node_id)
            stack.stack('ECHO PREDICTOR_successfully started.')

            self.predict()

    @stack.commandgroup
    def predictor(self):
        """Controls predictor parent and child simulations."""

        # Check if the child prediction node is running.
        if self.child_id:
            return True, 'Predictor has started'
        else:
            return True, 'No Predictor process running yet, call PREDICTOR START to start one.'

    @predictor.subcommand
    def start(self, acid = None):
        """Starts and manages the child node for the prediction process."""

        # if not self.acid_to_predict:
        #     stack.stack(f"ECHO There are no aircraft which need to be predicted.")
        #     return

        # Ensure this runs only in the parent node if there is a child node else start a new child node.
        if self.child_id:
            stack.forward('RESET', target_id=self.child_id)
            if self.predictions_complete and acid:
                self.update_fullflight(acid)

            else:
                self.predict()

        elif not self.parent_id:
            # Generate a new child node ID and create a new child prediction node.
            self.child_id = genid(GROUPID_SIM)
            net.addnodes(1, self.child_id)
        print(f'Parent id in predictor class: {self.parent_id}')
        print(f'child id in predictor class: {self.child_id}')

    @predictor.subcommand
    def claim(self):
        """Automatically called by the parent process to identify the child process's owner."""
        self.parent_id = stack.sender()
        traf.traf_parent_id = self.parent_id
        print('My parent is', self.parent_id)

    @predictor.subcommand
    def update(self, acid):
        acid = acid.upper()
        if self.child_id:
            idxac = traf.id2idx(acid)
            traf.ap.route[idxac].createtime = sim.simt
            info = self.packer(acid)
            # route_info = traf.ap.route[idxac].pack_route()
            # autopilot_info = pack_ap_idx(idxac)

            print('sent info: ', info)

            net.send('UPDATE_PREDICTOR', info, self.child_id)
            newcommand = self.filter_per_aircraft(acid)[-1][1]
            print(newcommand)
            stack.forward(newcommand, target_id=self.child_id)

    @network.subscriber(topic='UPDATE_PREDICTOR')
    def update_requested(self, acid, route_info, actwp_info, traf_info):
        if self.parent_id:

            print('received INFO: ', acid, route_info, actwp_info, traf_info)
            info = (acid, route_info, actwp_info, traf_info)

            actype = traf_info['type']
            aclat = traf_info['lat']
            aclon = traf_info['lon']
            achdg = traf_info['hdg']
            acalt = traf_info['alt']
            acspd = traf_info['cas']

            idxac = traf.id2idx(acid)
            print('update received: ', acid, aclat, aclon, achdg, acalt, acspd)

            if idxac < 0:
                traf.cre(acid, actype, aclat, aclon, achdg, acalt, acspd)
            else:
                traf.delete(idxac)
                print(f'ACID {acid} has been deleted in update received function.')
                traf.cre(acid, actype, aclat, aclon, achdg, acalt, acspd)

            self.unpacker(info)
            # acrte = Route._routes[acid]
            # acrte.calcfp()
            traf.update()
            acrte = traf.ap.route[idxac]
            acrte.calcfp()
            iactwp = acrte.iactwp
            traf.ap.ComputeVNAV(idxac, acrte.wptoalt[iactwp], acrte.wpxtoalt[iactwp], acrte.wptorta[iactwp],acrte.wpxtorta[iactwp])


    @stack.command
    def packer(self, acid):

        include_route = [
            "acid", "nwp", "wpname", "wptype", "wplat", "wplon", "wpalt", "wpspd",
            "wprta", "wpflyby", "wpstack", "wpflyturn", "wpturnbank", "wpturnrad",
            "wpturnspd", "wpturnhdgr", "iactwp", "swflyby", "swflyturn", "bank",
            "turnbank", "turnrad", "turnspd", "turnhdgr", "last_2_defined",
            "flag_landed_runway", "wpdirfrom", "wpdirto", "wpdistto", "wpialt",
            "wptoalt", "wpxtoalt", "wptorta", "wpxtorta", 'wptpredutc', 'actwp.lat']

        include_traf = ['type', 'lat', 'lon', 'alt', 'hdg', 'trk', 'vs', 'selspd', 'swlnav',
         'swvnav', 'swvnavspd', 'cas'] #optionally selspd selalt selvs

        include_actwp = [
            "lat", "lon", "nextturnlat", "nextturnlon", "nextturnspd", "nextturnbank",
            "nextturnrad", "nextturnhdgr", "nextturnidx", "nextaltco", "xtoalt",
            "nextspd", "spd", "spdcon", "vs", "turndist", "flyby", "flyturn",
            "turnbank", "turnrad", "turnspd", "turnhdgr", "oldturnspd",
            "turnfromlastwp", "turntonextwp", "torta", "xtorta", "next_qdr",
            "swlastwp", "curlegdir", "curleglen"]
        acid = acid.upper()
        idxac = traf.id2idx(acid)

        # Route packing via pack_attrs
        route_obj = traf.ap.route[idxac]
        route_info = pack_attrs(route_obj, include=include_route)

        actwp_info = {}
        for name in include_actwp:

            arr = getattr(traf.actwp, name)
            item = arr[idxac]
            if isinstance(item, np.generic):
                actwp_info[name] = item.item()
            else:
                actwp_info[name] = item



        # Traffic packing via inclusion list van per-aircraft arrays
        traf_info = {}
        for name in include_traf:

            arr = getattr(traf, name)
            item = arr[idxac]
            if isinstance(item, np.generic):
                traf_info[name] = item.item()
            else:
                traf_info[name] = item

        #todo: conditionals ook packen

        return (acid, route_info, actwp_info, traf_info)

    @stack.command
    def printpacker(self,acid):

        print(self.packer(acid))
        if self.child_id:
            stack.forward(f'PRINTPACKER {acid}', self.child_id)


    def unpacker(self,info):
        acid, route_info, actwp_info, traf_info = info
        idxac = traf.id2idx(acid)
        route_obj = traf.ap.route[idxac]
        unpack_attribs(route_obj, route_info)

        for key,value in traf_info.items():
            getattr(traf, key)[idxac] = value


        for key,value in actwp_info.items():
            getattr(traf.actwp, key)[idxac] = value


    @predictor.subcommand
    def update_throughstack(self,acid):
        if self.child_id:
            # stack.stack('HOLD')
            filtered_commands = self.filter_per_aircraft(acid)
            self.filtered = filtered_commands
            inittime = filtered_commands[0][0] # use inittime when simulating the entire flight: the amount of seconds into the simulated flight is cmdtime - inittime, but only for an entire flight
            #inittime is create time of the aircraft in the original sim

            # commands_to_schedule_list = [f'DELAY {cmdtime - inittime} {cmdline}' for cmdtime, cmdline in filtered_commands] # for tp of entire flights
            # commands_to_schedule_list = [f'DELAY {max(cmdtime-sim.simt, 0.0)} {cmdline}'for cmdtime, cmdline in filtered_commands] # for tp of partial flights
            commands_to_schedule_list = [
                cmdline if (cmdtime - sim.simt) <= 0
                else f"DELAY {cmdtime - sim.simt} {cmdline}"
                for cmdtime, cmdline in filtered_commands]
            idxac = traf.id2idx(acid)
            traf.ap.route[idxac].createtime = sim.simt # essentially setting cmdtime

            commands_to_schedule_list.insert(5, f'MOVE {acid} {traf.lat[idxac]} {traf.lon[idxac]} {round(traf.alt[idxac]/ft)} {traf.hdg[idxac]} {round(traf.cas[idxac]/kts)} {round(traf.vs[idxac]/ft*60.)}')
            # print(commands_to_schedule_list)
            # todo: possibly insert method to change selspd and selalt


            commands_to_schedule_list.append(f'set_active_waypoint {acid} {traf.ap.route[idxac].iactwp} {traf.selspd[idxac]} {traf.selvs[idxac]} {traf.selalt[idxac]} {traf.swlnav[idxac]} {traf.swvnav[idxac]} {traf.swvnavspd[idxac]}')

            # todo: setactivewp naar net.send omzetten??


            beginstack = sim.simt

            stack.forward(f'REMOVEWPTS {acid}', target_id=self.child_id)
            stack.forward(commands_to_schedule_list[0], target_id=self.child_id) #sending the commands in two steps helps with first creating a traf object
            stack.forward(*commands_to_schedule_list[1:], target_id=self.child_id)
            # stack.forward(f'HOWLONGDOESTHESTACKTAKE {beginstack}', target_id=self.child_id)
            beginsim = sim.simt




            if self.fast_tp:
                # stack.forward('DT 1', target_id=self.child_id)
                stack.forward('ff', target_id=self.child_id)
            if acid in self.incorrect_predictions:
                stack.stack('hold')
                stack.forward('HOLD', target_id=self.child_id)
                print(commands_to_schedule_list)
            #     print(acid)
            #     print(inittime)
            #     # self.fast_tp = False


    # @stack.command
    # def howlongdoesthestacktake(self, beginstack):
    #     net.send('STACKTIME', beginstack, self.parent_id)
    #
    # @network.subscriber(topic='STACKTIME')
    # def thestacktakes(self,beginstack):
    #     if self.child_id:
    #         print('stacktime: ', sim.simt - float(beginstack))

    @predictor.subcommand
    def update_fullflight(self, acid):
        if self.child_id:
            filtered_commands = self.filter_per_aircraft(acid)
            self.filtered = filtered_commands
            inittime = filtered_commands[0][0]
            commands_to_schedule_list = [f'DELAY {cmdtime - inittime} {cmdline}' for cmdtime, cmdline in filtered_commands]  # for tp of entire flights
            idxac = traf.id2idx(acid)
            # traf.ap.route[idxac].createtime = inittime
            stack.forward(commands_to_schedule_list[0], target_id=self.child_id) #sending the commands in two steps helps with first creating a traf object
            stack.forward(*commands_to_schedule_list[1:], target_id=self.child_id)
            if self.fast_tp:
                stack.forward('DT 1', target_id=self.child_id)
                stack.forward('ff', target_id=self.child_id)
            if acid in self.incorrect_predictions:
                stack.stack('hold')
                stack.forward('hold', target_id=self.child_id)
                print(commands_to_schedule_list)
                print(acid)
                print(inittime)

    @predictor.subcommand
    def predict(self):
        if self.child_id:
            commands_to_schedule_list = []

            if self.use_cache == True:
                stack.stack('ECHO cache is used for predictions')
                for acid in self.commands_per_flight.keys():
                    filtered_commands = self.filter_per_aircraft(acid)
                    self.filtered = filtered_commands
                    inittime = filtered_commands[0][0]
                    commands_to_schedule_list += [f'DELAY {cmdtime - inittime} {cmdline}' for cmdtime, cmdline in
                                                 filtered_commands]

                cmds_to_forward = []
                for  cmd in self.scenario_commands:
                    if cache_cmds_check(cmd):
                        # Add the commands in commands_to_schedule to schedule them in the predictor node.
                        cmds_to_forward.append(cmd.upper())
                print(cmds_to_forward)
                stack.forward(*cmds_to_forward, target_id=self.child_id)
                stack.forward('DT 1', target_id=self.child_id)
                # stack.forward('ff', target_id=self.child_id)

            else:
                for acid in self.commands_per_flight.keys():
                    filtered_commands = self.filter_per_aircraft(acid)
                    self.filtered = filtered_commands
                    inittime = filtered_commands[0][0]
                    commands_to_schedule_list += [f'DELAY {cmdtime - inittime} {cmdline}' for cmdtime, cmdline in
                                                 filtered_commands]

                    # if not self.predictions_complete:
                    #     self.acid_to_predict = set()

                stack.forward(*commands_to_schedule_list, target_id=self.child_id)
                    # print(*commands_to_schedule_list)
                stack.forward('DT 1', target_id=self.child_id)
                stack.forward('ff', target_id=self.child_id)

    @stack.command
    def usecache(self, scenario = 'scenariotest'):
        if not self.parent_id:
            cache = self.open_cache()

            self.predicted_ac_not_spawned = cache
            self.predictions_cache = cache
            self.use_cache = True

            stack.stack(f'PCALL {scenario}')


            stack.stack('USECACHE_AMAN')
            stack.stack('FF')
            # stack.forward('ECHO send general scenario commands, such as wind')
            # stack.stack(f'PREDICTOR CACHEREAD {scenario}')
            self.complete()

    @stack.command
    def REMOVEWPTS(self,acid):

        if self.parent_id:
            idxac = traf.id2idx(acid)

            if idxac >=0:
                for name in traf.ap.route[idxac].wpname:
                    traf.ap.route[idxac].delwpt(idxac, name)



    # @predictor.subcommand
    # def cacheread(self,scenario):
    #     stack.forward('ECHO hello from the parent', target_id=self.child_id)
    #


    def open_cache(self):
        try:
            # Open and load the predictions_cache file
            with open('predictions_cache.pkl', 'rb') as f:
                predictions = pickle.load(f)
            # Open and load the commands file
        except FileNotFoundError:
            # If either file is missing, return None for both
            return None
        return predictions



    @stack.command
    def complete(self):
        self.predictions_complete = True
        stack.stack('ECHO PREDICTOR COMPLETE')
        if self.parent_id:
            stack.forward('COMPLETE', target_id=self.parent_id)
            stack.stack('HOLD')
        elif self.child_id:
            stack.stack('STOREFLIGHTS')
            with open(r'predictions_cache.pkl', 'wb') as f:
                pickle.dump(self.predictions_cache, f)
            with open(r'commands.pkl', 'wb') as f:
                pickle.dump(self.commands_per_flight, f)
            stack.stack('FF 3270')


    @stack.command
    def predictions_required(self, aircraft, waypoints):
        print('stackcommand predictions called ', aircraft,waypoints, self.child_id, self.parent_id)
        self.predictions_count_required = int(aircraft) * int(waypoints)
        if self.child_id:
            stack.forward(f'PREDICTIONS REQUIRED {aircraft} {waypoints}', target_id=self.child_id)

    def iscomplete(self):

        if self.predictions_count_required and self.predictions_count_required == self.predictions:
            self.complete()

            # 26: 00:00 > STOREFLIGHTS
            # 26: 00:01 > ECHO
            # PREDICTIONS
            # SHOULD
            # BE
            # COMPLETE, HOLDING
            # 26: 00:02 > COMPLETE
            # 26: 00:02 > HOLD

    @stack.command
    def amount_aircraft(self, n):
        print(n)

    # @stack.command
    # def set_active_waypoint(self, acid, iactwp, selspd, selvspd, selalt, lnav, vnav, vnavspd):
    #     if self.parent_id:
    #         # print(idxac, iactwp)
    #         # print(type(idxac), type(iactwp))
    #         idxac = traf.id2idx(acid)
    #         traf.ap.route[idxac].iactwp = int(iactwp)
    #         # traf.ap.route[idxac].selspd = float(selspd)
    #         # traf.ap.route[idxac].selvs = float(selvspd)
    #         # traf.ap.route[idxac].selalt = float(selalt)
    #
    #
    #         traf.selspd[idxac] = float(selspd)
    #         traf.selvs[idxac] = float(selvspd)
    #         traf.selalt[idxac] = float(selalt)
    #
    #         traf.swlnav[idxac] = lnav
    #         traf.swvnav[idxac] = vnav
    #         traf.swvnavspd[idxac] = vnavspd


    # @stack.command  # This is a decorator that marks this function as a command in the stack
    # def spdadjust(self, idx: 'acid', casmach: 'spd'):
    #     """
    #     Custom speed adjustment command used to control aircraft speeds at certain distances from the runway threshold.
    #     Args:
    #         idx (acid): The index of the trajectory to adjust.
    #         casmach ('spd'): The new speed value to set.
    #
    #     Returns:
    #         True if successful
    #     """
    #
    #     # Set the selected speed at the given index to the new value
    #     traf.selspd[idx] = casmach
    #     # Clear the switch velocity navigation speed flag for this trajectory
    #     traf.swvnavspd[idx] = False
    #
    #     return True  # Return True indicating success
    #


    @stack.command
    def slowtp(self):
        self.fast_tp = False

    @stack.command
    def fasttp(self):
        self.fast_tp = True

    @stack.command(annotations='string')
    def forwardchild(self, text = '', flags = 0):
        if self.child_id:
            stack.forward(str, target_id=self.child_id)


    def filter_commands(self):
        """ Filtering commands to only predict aircraft which are required to be predicted."""

        # Initialize an empty list to store commands that meet the filtering criteria.
        necessary_commands = []

        self.commands_to_schedule.sort(key=lambda x: x[0])

        # Loop over each command in scheduled commands.
        for cmdtime, cmdline in self.commands_to_schedule:

            # If the command does not contain an acid and does not trigger a scenario
            # OR if the command line contains any acid specified in self.acid_to_predict,
            # add the command to the list if it meets the criteria.
            if self.acid_in_cmdline(cmdline):
                if any(acid.upper() in cmdline.upper() for acid in self.acid_to_predict):

                    if cmdline.upper() != self.acid_in_cmdline(cmdline):
                        necessary_commands.append((cmdtime, cmdline))
            else:
                necessary_commands.append((cmdtime, cmdline))

        # Return the list of commands that met the filtering criteria.
        return necessary_commands

    def filter_per_aircraft(self,acid):
        """ Filtering commands to only predict aircraft which are required to be predicted."""

        # Initialize an empty list to store commands that meet the filtering criteria.
        necessary_commands = []

        self.commands_per_flight[acid].sort(key=lambda x: x[0])

        # Loop over each command in scheduled commands.
        for cmdtime, cmdline in self.commands_per_flight[acid]:

            # If the command does not contain an acid and does not trigger a scenario
            # OR if the command line contains any acid specified in self.acid_to_predict,
            # add the command to the list if it meets the criteria.
            if self.acid_in_cmdline(cmdline):
                if any(acid.upper() in cmdline.upper() for acid in self.acid_to_predict):

                    if cmdline.upper() != self.acid_in_cmdline(cmdline):
                        necessary_commands.append((cmdtime, cmdline))
            else:
                necessary_commands.append((cmdtime, cmdline))

        # Return the list of commands that met the filtering criteria.
        return necessary_commands

    @predictor.subcommand
    def wptcross(self, acid: str, wpt: str):
        """Handles aircraft waypoint crossing."""
        # if self.parent_id and self.predictions_complete:
        #     print('wptcross: ', acid, wpt, sim.simt)
        # Find the index of the aircraft and waypoint.
        idxac = traf.id2idx(acid)
        idxwp = traf.ap.route[idxac].wpname.index(wpt)
        createtime = traf.ap.route[idxac].createtime
        if wpt in ['EHAM/RWY01', 'EHAM/RWY101'] and self.parent_id:
            # stack.stack('HOLD')
            stack.forward('HOLD',target_id=self.parent_id )
            print(acid, wpt, idxwp)

        # If the prediction time changes, forward the new waypoint crossing times
        # If operating within the child node, forward the waypoint crossing event to the parent process.
        val = None

        try:
            val = traf.ap.route[idxac].wptpredutc[idxwp]
        except:
            print('maybe this?')
            print('parent: ', self.parent_id, 'child: ', self.child_id)
            print(acid, wpt, idxac, idxwp)
            print('route: ', traf.ap.route[idxac].wpname)
            pass

        if self.parent_id and (val != sim.utc.timestamp()):

            net.send('PREDICTION', (acid, wpt, sim.simt, sim.simt - createtime, sim.utc.timestamp(), self.parent_id, traf.type[idxac]), self.parent_id)
            self.predictions +=1
            self.iscomplete()


    @predictor.subcommand
    def crossover(self, acid: str):
        """Handles aircraft waypoint crossing."""
        idxac = traf.id2idx(acid)
        createtime = traf.ap.route[idxac].createtime
        # print('crossover subcommand called')
        if self.parent_id:
            # net.send('PREDICTION', (acid, 'CROSSOVER', sim.simt, sim.simt-createtime, sim.utc.timestamp(), self.parent_id, traf.type[idxac]), GROUPID_SIM)

            net.send('PREDICTION', (acid, 'CROSSOVER', sim.simt, sim.simt - createtime, sim.utc.timestamp(), self.parent_id, traf.type[idxac]),
             self.parent_id)

    # @predictor.subcommand
    # def publish(self):
    #     """Sends the current state back to parent."""
    #     net.send('prediction', 'Prediction data should go here :)', self.parent_id)

    @network.subscriber(topic='PREDICTION')#, to_group=GROUPID_SIM)
    def on_prediction_received(self, acid, wpt, wptime, flighttime, wptpredutc, parent_id, type):
        """ Displays the prediction results received from the child process. """
        # print(acid)
        # print(self.parent_id)
        # print(self.child_id)
        #
        # print()
        if self.parent_id:
            return
        self.counter += 1
        num_signals = None
        pred_signals = None

        # Find the index of the aircraft and waypoint.
        idxac = traf.id2idx(acid)
        # when using tp with aircraft not airborne: seems that they are not yet in traf, thus idxac becomes -1!
        estimatedcreatetime = wptime - flighttime
        #following code stores the tp data from non-airborne aircraft in a different object
        if self.predictions_complete == False:
            self.predictions_cache.setdefault(acid, []).append((wpt, wptime, flighttime, estimatedcreatetime, wptpredutc, parent_id, type))
        if idxac == -1:
            self.predicted_ac_not_spawned.setdefault(acid, []).append((wpt, wptime, flighttime, estimatedcreatetime, wptpredutc, parent_id, type))
            #scr.echo(f'Prediction stored: {acid} reached {wpt} at {datetime.fromtimestamp(wptpredutc, tz=None)} seconds, stored in object')

        else:
            if 'CROSSOVER' in wpt:
                # print('crossover update not handled yet')
                return

            # idxwp = traf.ap.route[idxac].wpname.index(wpt)
            try:
                idxwp = traf.ap.route[idxac].wpname.index(wpt)
                traf.ap.route[idxac].wptpredutc[idxwp] = wptpredutc
                traf.ap.route[idxac].wptime[idxwp] = wptime
                if self.predictions_complete:
                    # traf.ap.route[idxac].wptime[idxwp] = traf.ap.route[idxac].createtime + flighttime # former method, with complete track simulated DO NOT REMOVE
                    traf.ap.route[idxac].wptime[idxwp] = traf.ap.route[idxac].createtime + flighttime

            except:
                stack.stack('ECHO ERROR IN PREDICTION RECEIVEMENT, CHECK COMMANDLINE FOR SPECIFICS')
                print(acid, wptime, wpt)
                print(traf.ap.route[idxac].wpname)
                print('parent: ', self.parent_id)
                print('child: ', self.child_id)
                stack.forward(f'PRINT_WPNAMES {acid}', target_id=self.child_id)
            #scr.echo(f'Prediction received: {acid} reached {wpt} at {datetime.fromtimestamp(wptpredutc, tz=None)} seconds, stored in traf')

        # self.acids_received.add(acid)
        # if self.child_id and len(self.scenario_commands_times)>1 and wptime > self.scenario_commands_times[-2]:
        #     self.all_aircraft = True
        #     print('allaircraft called from parent')
        #     stack.forward('PREDICTOR ALLAIRCRAFT', target_id=self.child_id)


        #
        # # Optional code to automatically fast-forward simulation after all predictions have been received
        # num_signals = total_pred_signals()

        # if self.counter != 0 and len(traf.ap.route) == 0 and self.parent_id:# or (self.predictions_complete and idxwp == len(traf.ap.route[idxac].wpname)-1):
        #     self.predictions_complete = True
        #     # self.counter = 0
        #
        #     if self.parent_id:
        #         stack.stack(f"ECHO Stopping child simulation node")
        #         stack.stack(f"HOLD")
        #         print('pred complete')
        #
            # if self.child_id:
            #     stack.stack(f'ECHO ---- Predictions Complete ----')
        #         stack.stack(f'FF')
        #         # retrieve route dictionaries for all aircrafts
        #         list_of_routes = traf.ap.route
        #         # export_csv_eto_eta(list_of_routes)




    def reset(self):
        """ Clear all traffic data when sim is reset and reset data for the predictor. """
        super().reset()
        self.commands_to_schedule = []
        self.previous_scenario_file = ''
        self.scenario_commands = []





    def acid_in_cmdline(self, cmdline):
        cmdline = re.sub(r'^\d+:\d+:\d+\.\d+>', '', cmdline).strip()
        pattern =r'\b[A-Z]{2,}[0-9]+[A-Z]*\b'

        if 'CREATE' in cmdline.upper():
            # Try to find a match using the pattern
            # match = re.search(pattern, cmdline, re.IGNORECASE)
            # if match:
            #     acid = match.group(0).upper()
            #     self.acids.add(acid)
            #     return acid
            # else:
                # If no match, assume the second item is the ACID
                # Typically: 'CREATE KLM1226SH, ...'
            parts = cmdline.split()
            if len(parts) > 1:
                # parts[0] should be 'CREATE', parts[1] should be the ACID (with possible trailing comma)
                acid_candidate = parts[1].strip(',').upper()
                self.acids.add(acid_candidate)
                # print(acid_candidate)
                return acid_candidate
        else:
            # Not a CREATE line, try matching the pattern to see if a known ACID is present
            match = re.search(pattern, cmdline, re.IGNORECASE)
            if match:
                acid = match.group(0).upper()
                if acid in self.acids:
                    return acid

            # If no direct match, check if any known acid is a substring of the cmdline
            for acid in self.acids:
                if acid in cmdline.upper():
                    return acid

        return False

    @stack.command
    def printfromtp(self, acid):
        print(self.filter_per_aircraft(acid.upper()))

    @stack.command
    def printtraf(self, attrib):
        arr = getattr(traf, attrib, None)
        if arr is None:
            stack.stack(f"ECHO Attribute {attrib} not found")
        else:

            stack.stack(f"ECHO {arr}")



def cmds_disrupt_predictor(cmdline):
    """
    Checks if the command line contains disruptive predictor commands which should not be run in the predictor node.
    """

    # Search for disruptive keywords 'predictor' or 'aman' (case insensitive)
    # matches = re.search(r'\bpredictor\b|\baman\b', cmdline, re.IGNORECASE)
    matches = (re.search(r'\bPREDICTOR\b', cmdline, re.IGNORECASE))
    return True if matches else None


def scenario_in_cmdline(cmdline):
    """ Determines if a line contains a scenario command and returns the term after 'pcall' or 'ic'. """

    # Updated regex to capture the word following 'pcall' or 'ic'
    matches = re.findall(r'\b(pcall|ic)\b\s+(\w+)', cmdline, re.IGNORECASE)

    # Return the term following 'pcall' or 'ic' if found
    # print("scen", matches[0][1]) if matches else None
    return matches[0][1] if matches else None


def schedule_in_cmdline(cmdline):
    """ Determines if a line contains a schedule command. """

    # Search for keywords indicating schedule commands.
    match = re.search(r'SCHEDULE \d+(\.\d+)? (.*)', cmdline)
    # print('schedule', match.group(2)) if match else None
    return match.group(2) if match else None





def total_pred_signals():
    """ Counts the total number of prediction signals that will be sent to the parent simulation"""

    tot = 0
    for ac in traf.ap.route:
        tot += len(ac.wptime)

    return tot


def sim_cmds_check(cmdline):
    """ Determines if a line contains a OP, HOLD or FF command, case insensitive. """
    matches =[]

    opcheck = re.search(r'\bOP\b', cmdline, re.IGNORECASE)
    holdcheck = re.search(r'\bHOLD\b', cmdline, re.IGNORECASE)
    ffcheck  = re.search(r'\bFF\b', cmdline, re.IGNORECASE)
    amancheck = re.search(r'\bAMAN_SHOW \b', cmdline, re.IGNORECASE)
    colorcheck = re.search(r'\bCOLOR\b', cmdline, re.IGNORECASE)
    poscheck = re.search(r'\bPOS\b', cmdline, re.IGNORECASE)
    echocheck = re.search(r'\bECHO\b', cmdline, re.IGNORECASE)
    matches = [opcheck, holdcheck, ffcheck, amancheck, colorcheck, poscheck, echocheck]
    match = any(matches)
    return True if match else False

def cache_cmds_check(cmdline):

    defwpt = re.search(r'\bdefwpt\b', cmdline, re.IGNORECASE)
    plugin = re.search(r'\bplugin\b', cmdline, re.IGNORECASE)
    wind = re.search(r'\bwind\b', cmdline, re.IGNORECASE)
    circle = re.search(r'\bcircle\b', cmdline, re.IGNORECASE)
    matches = [defwpt, plugin, wind, circle]
    match = any(matches)
    return True if match else False

def speed_cmd_check(cmdline):
    # Search for "SPD  " case insensitive
    match = re.search(r'\bSPD \b', cmdline, re.IGNORECASE)
    return True if match else False

def reduce_mach_check(cmdline):
    # Search for "SPD  " case insensitive
    descentspd = re.search(r'\bSETDESCENTSPD \b', cmdline, re.IGNORECASE)
    mach = re.search(r'\bREDUCE_MACH \b', cmdline, re.IGNORECASE)
    matches = [descentspd, mach]
    match = any(matches)
    return True if match else False
#
def alt_cmd_check(cmdline):
    # Search for "ALT " case insensitive
    match = re.search(r'\bALT \b', cmdline, re.IGNORECASE)
    return True if match else False

def direct_cmd_check(cmdline):
    # Search for "DIRECT " case insensitive
    match = re.search(r'\bDIRECT \b', cmdline, re.IGNORECASE)
    return True if match else False

def cre_filter(commands):
    filtered_list = []
    for cmdtime, cmdline in commands:
        match = re.search(r'CRE ', cmdline, re.IGNORECASE)
        if not match:
            filtered_list.append((cmdtime, cmdline))

    filtered_list.sort(key=lambda x: x[0], reverse=False)
    return filtered_list


def wptcross_check(cmdline):
    # Search for "ALT " case insensitive
    match = re.search(r'\bWPTCROSS \b', cmdline, re.IGNORECASE)
    return True if match else False



def parse_runway(acid):
    idxac = traf.id2idx(acid)

    acrte = Route._routes[acid]

    rwyrteidx = -1
    i = 0

    while i < acrte.nwp and rwyrteidx < 0:
        if acrte.wpname[i].count("/") > 0:
            rwyrteidx = i
        i += 1

    if rwyrteidx != -1:
        destination = acrte.wpname[rwyrteidx]
    else:
        print('No runway specified for: ', acid)
        return


    # possibly put into seperate function
    if acrte.nwp == 0:
        reflat = traf.lat[idxac]
        reflon = traf.lon[idxac]

    # Or last waypoint before destination
    else:
        if acrte.wptype[-1] != Route.dest or acrte.nwp == 1:
            reflat = acrte.wplat[-1]
            reflon = acrte.wplon[-1]
        else:
            reflat = acrte.wplat[-2]
            reflon = acrte.wplon[-2]

    if destination.count("/") > 0:
        aptid, rwyname = destination.split("/")
    else:
        # Runway specified
        aptid = destination[1]
        rwyname = destination[2]

    rwyid = rwyname.replace("RWY", "").replace("RW", "")  # take away RW or RWY
    print("apt,rwy=", aptid, rwyid)

    # Try to get it from the database
    # try:
    rwyhdg = navdb.rwythresholds[aptid][rwyid][2]
    # except:
    #     rwydir = rwyid.replace("L", "").replace("R", "").replace("C", "")
    #     try:
    #         rwyhdg = float(rwydir) * 10.
    #     except:
    #         return False, rwyname + " not found."

    success, posobj = txt2pos(aptid + "/RW" + rwyid, reflat, reflon)
    if success:
        rwylat, rwylon = posobj.lat, posobj.lon
    else:
        rwylat = traf.lat[idxac]
        rwylon = traf.lon[idxac]

    return rwylat, rwylon, rwyhdg



def export_csv_eto_eta(route_dict):
    timestamp = sim.utc
    total_data = []
    aircraft_states = [(traf.lat[i], traf.lon[i], traf.alt[i], traf.cas[i]) for i, _ in enumerate(traf.id)]

    k = 0
    for i, aircraft_route in enumerate(route_dict):
        acid = traf.id[i]

        for j, pred_timestamp in enumerate(aircraft_route.wptpredutc):

            # [unique_key, acidx, wptname, predicted utc time]
            datapoint = [k, i, acid, aircraft_route.wpname[j],
                         datetime.fromtimestamp(pred_timestamp, tz=None),
                         timestamp, aircraft_states[i]]

            total_data.append(datapoint)
            k += 1

    header = ['key', 'aircraft index', 'aircraft callsign', 'waypoint name', 'predicted utc time',
              'timestamp', 'aircraft state']

    data = [header] + total_data
    filepath = './output/TP_predicted_times_log.csv'

    with open(filepath, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerows(data)

    print(f'Data has been written to {filepath}')










# def pack_ap_idx(idx: int) -> dict:
#     """
#     Pack alle autopilot-waarden van interesse voor één aircraft-index.
#     Dit spiegelt de arrays die in Autopilot.__init__ zijn gedefinieerd,
#     met uitzondering van 'route'. Geen typeconversies; we nemen de huidige types over.
#     """
#     ap = traf.ap
#     return {
#         'acid': traf.id[idx],
#
#         # FMS directions
#         'trk': ap.trk[idx],
#         'spd': ap.spd[idx],
#         'tas': ap.tas[idx],
#         'alt': ap.alt[idx],
#         'vs': ap.vs[idx],
#
#         # VNAV variables
#         'swtoc': ap.swtoc[idx],
#         'swtod': ap.swtod[idx],
#         'dist2vs': ap.dist2vs[idx],
#         'dist2accel': ap.dist2accel[idx],
#         'swvnavvs': ap.swvnavvs[idx],
#         'vnavvs': ap.vnavvs[idx],
#
#         # LNAV variables
#         'qdr2wp': ap.qdr2wp[idx],
#         'dist2wp': ap.dist2wp[idx],
#         'qdrturn': ap.qdrturn[idx],
#         'dist2turn': ap.dist2turn[idx],
#         'inturn': ap.inturn[idx],
#
#         # Traffic navigation information
#         'orig': ap.orig[idx],
#         'dest': ap.dest[idx],
#
#         # Defaults & current roll/bank
#         'bankdef': ap.bankdef[idx],
#         'vsdef': ap.vsdef[idx],
#         'cruisespd': ap.cruisespd[idx],
#         'turnphi': ap.turnphi[idx],
#     }
#
#
# # Unpack autopilot payload for an aircraft
# def unpack_ap(payload: dict) -> bool:
#     """Unpack a packed autopilot dict and set values on traf.ap for the given ACID.
#     Returns True on success, False if ACID is missing or not found. Does not create/delete aircraft.
#     """
#     acid = payload.get('acid')
#     if not acid:
#         return False
#
#     idx = traf.id2idx(acid)
#     if idx < 0:
#         return False
#
#     ap = traf.ap
#
#     # Known payload keys we set (mirrors pack_ap_idx)
#     keys = [
#         'trk', 'spd', 'tas', 'alt', 'vs',
#         'swtoc', 'swtod', 'dist2vs', 'dist2accel', 'swvnavvs', 'vnavvs',
#         'qdr2wp', 'dist2wp', 'qdrturn', 'dist2turn', 'inturn',
#         'orig', 'dest',
#         'bankdef', 'vsdef', 'cruisespd', 'turnphi',
#     ]
#
#     for k in keys:
#         if k in payload:
#             try:
#                 getattr(ap, k)[idx] = payload[k]
#             except Exception:
#                 # Be robust to unexpected shapes or read-only arrays
#                 pass
#
#     # Report per-aircraft autopilot attributes that were not included in the payload
#     try:
#         all_attrs = []
#         for a in dir(ap):
#             if a.startswith('__'):
#                 continue
#             try:
#                 val = getattr(ap, a)
#             except Exception:
#                 continue
#             if callable(val):
#                 continue
#             try:
#                 # consider only arrays/vectors that match aircraft count
#                 if hasattr(val, '__len__') and len(val) == len(traf.id):
#                     all_attrs.append(a)
#             except Exception:
#                 continue
#         packed_set = set(keys)
#         not_packed = sorted([a for a in all_attrs if a not in packed_set and a != 'route'])
#         if not_packed:
#             stack.stack(f"ECHO AP attributes not packed for {acid}: {', '.join(not_packed)}")
#     except Exception:
#         pass
#
#     return True
#
# def pack_traffic_idx(idx: int) -> dict:
#     """
#     Pack een minimale Traffic-snapshot voor aircraft-index `idx`.
#     Alleen de gevraagde velden + acid.
#     """
#
#     return {
#         'acid':   traf.id[idx],
#         'type':   traf.type[idx],
#         'lat':    traf.lat[idx],
#         'lon':    traf.lon[idx],
#         'alt':    traf.alt[idx],
#         'hdg':    traf.hdg[idx],
#         'trk':    traf.trk[idx],
#         'vs':     traf.vs[idx],
#         'selspd': traf.selspd[idx],
#         'selalt': traf.selalt[idx],
#         'selvs':  traf.selvs[idx],
#         'swlnav': bool(traf.swlnav[idx]),
#         'swvnav': bool(traf.swvnav[idx]),
#         'swvnavspd': bool(traf.swvnavspd[idx]),
#         'cas': traf.cas[idx]
#     }
#
#
# def unpack_traffic(payload: dict) -> bool:
#     """Very simple unpack: set the attributes on traf from the payload dict."""
#     acid = payload.get('acid')
#     if not acid:
#         return False
#
#     idx = traf.id2idx(acid)
#     if idx < 0:
#         return False
#
#     keys = [
#         'type', 'lat', 'lon', 'alt', 'hdg', 'trk', 'vs',
#         'selspd', 'selalt', 'selvs', 'swlnav', 'swvnav', 'swvnavspd','cas'
#     ]
#
#     for k in keys:
#         if k in payload:
#             try:
#                 getattr(traf, k)[idx] = payload[k]
#             except Exception:
#                 pass
#
#     return True
#
#
