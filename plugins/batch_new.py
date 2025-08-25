

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

from OpenGL.raw.GL.APPLE.vertex_program_evaluators import glIsVertexAttribEnabledAPPLE

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
        'plugin_name': 'AMANBATCH',
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

        super().__init__()

        self.max_nnodes = min(cpu_count(), settings.max_nnodes)
        # Main DataFrame to track scenarios
        self.df = pd.DataFrame(columns=['scenario', 'node', 'seed', 'holdtime', 'status'])
        self.df.index.name = 'name'

        # self.server_id = genid(groupid=GROUPID_SIM, seqidx=0)

        self.server_id = genid(groupid=GROUPID_SIM, seqidx=0)
        self.max_group_idx = 1
        self.usecache = False



    @stack.command
    def montecarlo(self, scenarioname, n, holdtime='48:00:00', usecache= True):
        self.usecache = usecache
        for i in range(int(n)):
            name = f'MC_{i}'
            # Add new scenario row with backlog status
            self.df.loc[name] = {
                'scenario': scenarioname,
                'node': None,
                'seed': i,
                'holdtime': holdtime,
                'status': 'backlog'
            }
        self.control_batch()
        stack.stack(f'ECHO {self.df[self.df["status"] == "backlog"].index.tolist()}')


    @stack.command
    def batchscen(self, scenarioname, name=None, holdtime='48:00:00'):  # add holdtime?
        # Determine a unique name
        if name is None:
            name = scenarioname
        i = 1
        while name in self.df.index:
            stack.stack(f'ECHO {name} already exists')
            if name.endswith(f'_{i - 1}'):
                name = name[:-(len(str(i - 1)) + 1)]
            name = f'{name}_{i}'
            i += 1
            stack.stack(f'ECHO new name is {name}')
        # Add to DataFrame
        self.df.loc[name] = {
            'scenario': scenarioname,
            'node': None,
            'seed': None,
            'holdtime': holdtime,
            'status': 'backlog'
        }
        self.control_batch()


    @stack.command
    def printbatch(self, attrib):
        arr = getattr(self, attrib, None)
        if arr is None:
            stack.stack(f"ECHO Attribute {attrib} not found")

        else:

            stack.stack(f"ECHO {arr}")

    def control_batch(self):
        # if sim.state in (HOLD,INIT,END):
        #     if stack.get_scenname() == "":
        #         self.send_to_main()

                

        maxnew = (self.max_nnodes - len(self.children)) // 2 -1 #-1 is for the main running node
        added_nodes = 0
        # Iterate over backlog entries in DataFrame
        for name in list(self.df.index[self.df['status'] == 'backlog']):
            node = self.addnode(name)
            # Update DataFrame with assigned node and status
            self.df.at[name, 'node'] = node
            self.df.at[name, 'status'] = 'running'
            added_nodes += 1
            if added_nodes >= maxnew:
                stack.stack(f'ECHO maximum nodes added: {maxnew}')
                stack.stack(f'ECHO backlog: {self.df.index[self.df["status"] == "backlog"].tolist()}')
                break

    def addnode(self, name):
        child_id = genid(GROUPID_SIM)

        self.max_group_idx += 1
        child_id = genid(net.node_id[:-1], seqidx=self.max_group_idx)
        net.addnodes(1, child_id)
        # net.run()

        self.children[child_id] = self.df.loc[name, 'scenario']
        self.names[child_id] = name
        # self.avail_nodes.add(self.child_id)

        return child_id


    @stack.command
    def sendscen(self, node):
        name = self.names[node]
        scenario = self.df.loc[name, 'scenario']
        if scenario and name:
            self.forward_messages(node)
        else:
            stack.stack(f'ECHO {node} has no scenario or name: {scenario} {name}')

    def send_another(self, child):
        backlog = list(self.df.index[self.df['status'] == 'backlog'])
        if len(backlog) > 0:
            name = backlog[0]
            self.names[child] = name
            self.children[child] = name
            self.df.at[name, 'node'] = child
            self.df.at[name, 'status'] = 'running'
            self.sendscen(child)
        else:
            stack.stack(f'ECHO final scenario is running')


    def forward_messages(self, node):
        name = self.names[node]
        scenario = self.df.loc[name, 'scenario']
        holdtime = self.df.loc[name, 'holdtime']


        stack.forward(f'SCEN {name}', target_id=node)
        #
        if self.usecache:
            stack.forward('USECACHE', target_id=node)
        else:
            stack.forward(f'PCALL {scenario}', target_id=node)
        stack.forward(f'DELAY {holdtime} BATCHES FINISH', target_id=node)
        stack.forward('FF', target_id=node)
        stack.forward('DT 0.5', target_id=node)



    @signal.subscriber(topic='node-added')
    def on_node_added(self, node_id):
        """ Gets triggered everytime a new node is added. """

        # Check if the added node is the child node to start the predict method.
        if node_id in self.children.keys():
            stack.forward('BATCHES CLAIM', target_id=node_id)
            scr.echo('BATCH successfully started.')

            self.sendscen(node_id)
            # Mark as sent
            name = self.names[node_id]
            self.df.at[name, 'status'] = 'sent'


    @stack.commandgroup
    def batches(self):
        """Controls predictor parent and child simulations."""

        # Check if the child prediction node is running.
        if self.children:
            return True, 'BATCH has started'
        else:
            return True, 'No BATCH process running yet'

    @batches.subcommand
    def claim(self):
        """Automatically called by the parent process to identify the child process's owner."""
        self.parent_id = stack.sender()
        # traf.traf_parent_id = self.parent_id
        print('My batchparent is', self.parent_id)

    #

    @batches.subcommand
    def finish(self):
        sender = stack.sender()
        # If called in child context, forward finish to parent and reset
        if not self.children and self.parent_id:
            stack.forward('BATCHES FINISH', target_id=self.parent_id)
            #some code here to save metrics

            stack.stack('RESET')
        # Called in parent context: mark scenario done and clear assignment
        if sender in self.children:
            name = self.names[sender]
            # Update DataFrame status to done
            self.df.at[name, 'status'] = 'done'
            # Clear assignment but keep child entry
            self.children[sender] = None
            stack.stack(f'ECHO Scenario {name} done on node {sender}')

            self.send_another(sender)
            print(self.df)


        # else:
        #     stack.stack(f'ECHO No active scenario for node {sender}')






# the following commands are to include the main node in the sim, this gives rather much problems




    #
    #
    # @batches.subcommand
    # def finishmain(self):
    #     if self.children and 'main' in self.children:
    #         stack.stack('RESET')
    #         sender = 'main'
    #         name = self.names[sender]
    #         # Update DataFrame status to done
    #         self.df.at[name, 'status'] = 'done'
    #         # Clear assignment but keep child entry
    #         self.children[sender] = None
    #         stack.stack(f'ECHO Scenario {name} done on node {sender}')
    #
    #         self.send_to_main()
    #
    #         print(self.df)
    #
    #
    # def send_to_main(self):
    #     backlog = list(self.df.index[self.df['status'] == 'backlog'])
    #     if len(backlog) > 0:
    #         name = backlog[0]
    #
    #
    #
    #         scenario = self.df.loc[name, 'scenario']
    #         if scenario and name:
    #             self.names['main'] = name
    #             self.children['main'] = name
    #             self.df.at[name, 'node'] = 'main'
    #             self.df.at[name, 'status'] = 'running'
    #             setname = f'SCEN {name}'
    #             msg = f'PCALL {scenario}'
    #             stack.stack(f'ECHO main, new scen: {scenario} {name}')
    #             stack.stack(setname)
    #             # stack.stack(msg)
    #
    #             stack.stack('USECACHE')
    #             # schedule finish in parent after holdtime
    #             holdtime = self.df.loc[name, 'holdtime']
    #             stack.stack(f'DELAY {holdtime} BATCHES FINISHMAIN')
    #             # stack.stack('FF')
    #             stack.stack('HOLD')
    #         else:
    #
    #
    #             stack.stack('HOLD')
    #             stack.stack(f'ECHO {name} has no scenario or name: {scenario} {name}')