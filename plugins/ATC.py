# amanatc.py


from bluesky import core, stack, traf, sim, HOLD, network, net
from bluesky import server
# from plugins.AMANtwo import AMAN  # Import the global reference from AMANtwo
from bluesky.core import plugin
from bluesky.plugins.sectorcount import update
from bluesky.test.tcp.test_simple import test_pos
from bluesky.tools.aero import kts, ft, nm, crossoveralt
import pandas as pd
from bluesky.tools.geo import kwikpos, qdrpos, kwikdist, qdrdist
from bluesky.tools.geo import kwikqdrdist
from bluesky.traffic.route import Route
import math
import time
from collections import defaultdict

from plugins.amanhelpers.aman_settings import instruct, mach_threshold, handover_alt, max_dogleg_ratio
# from plugins.scenario_generator import scenario


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
        self.mach_threshold = mach_threshold
        self.handover_alt = handover_alt
        self.max_dogleg_ratio = max_dogleg_ratio
        self.aman.Flights['instruction'] = None
        self.aman.Flights['TPstate'] = ' '
        self.aman.Flights['count'] = 0
        self.aman.Flights['count'] = self.aman.Flights['count'].astype(int)
        self.aman.Flights['updates'] = 0
        self.aman.Flights['updates'] = self.aman.Flights['updates'].astype(int)
        self.aman.Flights['instruction'] = self.aman.Flights['instruction'].astype(object)
        self.aman.Flights['TPstate'] = self.aman.Flights['TPstate'].astype(object)
        self.aman.Flights['swaps'] = 0
        self.aman.Flights['swaps'] = self.aman.Flights['swaps'].astype(int)




        self.aman.Flights['selspd'] = None
        self.aman.Flights['dogleg'] = None
        self.aman.Flights['dogleg'] = self.aman.Flights['dogleg'].astype(bool)
        self.aman.Flights['direct'] = None
        self.aman.Flights['holding'] = None
        self.aman.Flights['earliest'] = False


        self.instructionlist = {}
        self.instructions = []
        self.active_instructions = {} # acid: delay/short + dogleg/speed/mach


    def reset(self):
        super().reset()
        self.crossover = None#this gives some errors with initialization
        # plugin.Plugin.plugins['MACH_CROSSOVER'].imp.CROSSOVER
        self.aman = plugin.Plugin.plugins['AMANTWO'].imp.AMAN
        self.predictor = plugin.Plugin.plugins['NEWTP'].imp.predictor

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


                self.aman.update_times()

                frozen_flights = frozen_flights.dropna(subset=['ttlg'])


                delay = frozen_flights['ttlg'] > self.aman.early_approach_margin
                shorten = frozen_flights['ttlg'] < -self.aman.late_approach_margin
                has_active_instr = frozen_flights.index.isin(self.active_instructions.keys())
                instruct = frozen_flights[(delay | shorten) & ~has_active_instr]


                if len(instruct) > 0:
                    if sim.state != HOLD:
                        self.rtf = sim.dtmult
                        self.ff = sim.ffmode

                    sim.hold()

                    sim.simdt = 0.02


                    for acid, row in instruct.iterrows():
                        self.determine_scenario(acid, float(row['ttlg']))

                    if len(self.active_instructions) == 0:
                        if self.ff:
                            sim.fastforward()
                        elif self.rtf > 1.:
                            sim.dtmult(self.rtf)
                        elif not self.ff and self.rtf <= 1.:
                            sim.op()
                        sim.simdt = 1.0


    def determine_scenario(self, acid, ttlg):
        if self.predictor.parent_id:
            return
        idx = traf.id2idx(acid)
        if idx == -1:
            return
        if self.aman.Flights.loc[acid]['holding'] == True:
            return
        selspd = traf.selspd[idx] / kts
        maxspd = self.aman.Flights.loc[acid]['max_casdesc']
        minspd = self.aman.Flights.loc[acid]['min_casdesc']
        alt = traf.alt[idx]/ft
        to_iaf = self.aman.Flights.loc[acid, 'ETO IAF'] - sim.simt
        vs = traf.vs[idx]
        trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)
        if abs(ttlg) <= self.aman.instruction_margin:
            # print('ttlg within instruction margin')
            return
        if acid in self.active_instructions.keys():
            # print('acid in active_instructions ', acid)
            return

        #standard scenarios
        if alt < self.handover_alt and vs < 0.5:

            # scenario 2: speedup
            if ttlg <= -self.aman.late_approach_margin:

                # print(f'{acid} needs speed up {ttlg}')
                if abs(trackmiles - direct_dist) > 1: #essentially direct == False
                    self.dogleg(acid, ttlg)
                elif abs(maxspd - selspd) > 1:
                    self.speed(acid, ttlg)
                else:
                    ETA = self.reset_ETA(acid)
                    self.aman.replan_late(acid, ETA=ETA)
                    # print(f'replanning {acid}')

            #scenario 3: delay
            elif ttlg > self.aman.early_approach_margin:
                dogleg_given = self.aman.Flights.loc[acid, 'dogleg']
                curr_dogleg_ok = pd.isna(dogleg_given) or (float(dogleg_given) < self.max_dogleg_ratio)
                if abs(minspd - selspd) > 1:
                    self.speed(acid, ttlg)
                elif to_iaf > self.aman.nearby_threshold and direct_dist*self.max_dogleg_ratio > (trackmiles +1) and curr_dogleg_ok: # and ttlg < max dogleg?
                    self.dogleg(acid, ttlg)
                elif to_iaf < self.aman.nearby_threshold and to_iaf > 0.5 * self.aman.nearby_threshold and ttlg < (self.aman.early_approach_margin + 20):
                    self.dogleg(acid, ttlg)
                elif to_iaf < self.aman.nearby_threshold and ttlg >= (self.aman.early_approach_margin + 20) and self.aman.Flights.loc[acid]['holding'] != True:

                    iaf = self.aman.Flights.loc[acid, 'IAF']
                    line = f'HOLDING AT {acid} {iaf} {ttlg}'
                    stack.stack(line)
                    self.store_delay(acid, ttlg, delaytype='holdingtime')
                    self.instruction_correct(acid, itype='holding')


                    # stack.stack(f'START_UPDATE {acid}')
                    # self.start_update(acid)
                    # stack.forward(line, target_id=self.predictor.child_id)

                    # print(f'HOLDING AT {acid} {iaf} {ttlg}')
                    stack.stack(f'ECHO HOLDING {acid} at {iaf}')
                    self.aman.Flights.at[acid, 'holding'] = True



            #scenario 4: adjacent
        elif ttlg > self.aman.early_adjacent_threshold and alt > self.handover_alt: # delay
            instrspd = self.aman.Flights.loc[acid]['selspd']
            if instrspd > minspd or pd.isna(instrspd):
                self.speed_at_entry(acid, minspd, ttlg)
                # sim.hold()
                # stack.forward('HOLD', target_id=self.predictor.child_id)
                # print('holding because of early', acid)
            elif selspd < 4. and abs(instrspd - minspd) < 1:
                self.delay_mach(acid)
                # sim.hold()
                # stack.forward('HOLD', target_id=self.predictor.child_id)
                # print('holding because of mach', acid)
            elif selspd > 4. and abs(instrspd - minspd) > 1 and vs < 0.0:
                self.minspeed(acid, minspd)

        elif ttlg < - self.aman.late_adjacent_threshold and alt > self.handover_alt:
            instrspd = self.aman.Flights.loc[acid]['selspd']
            if instrspd < maxspd or pd.isna(instrspd):
                if abs(trackmiles - direct_dist) > 1:  # if not direct
                    self.speed_at_entry(acid, maxspd, ttlg, direct = True)
                else:
                    self.speed_at_entry(acid, maxspd, ttlg)
                # sim.hold()
                # stack.forward('HOLD', target_id=self.predictor.child_id)
                # print('holding because of late', acid)
            elif abs(trackmiles - direct_dist) > 1:  # if not direct
                self.dogleg(acid, ttlg)
            elif selspd >4. and abs(maxspd - selspd) > 1:
                self.speed(acid, ttlg)
                #add removal of conditional at FL260?
            elif abs(trackmiles - direct_dist) < 1 and selspd >4. and abs(maxspd - selspd) < 1:
                ETA = self.reset_ETA(acid)
                self.aman.replan_late(acid, ETA=ETA)
                # print(f'replanning {acid}')
                #remove conditionals
        # elif ttlg > self.aman.early_adjacent_threshold:  # delay
        #     if selspd < 4. and pd.isna(self.aman.Flights.loc[acid]['selspd']):
        #         self.delay_mach(acid)
        #     else:
        #         if selspd >4. and abs(minspd - selspd) > 1:
        #             self.speed(acid, ttlg)
        #         elif direct_dist*self.max_dogleg_ratio > (trackmiles +1): # and ttlg < max dogleg?
        #             self.dogleg(acid, ttlg)
        #
        #
        # elif ttlg <= -self.aman.late_adjacent_threshold: # speed up
        #     if selspd < 4. and abs(trackmiles - direct_dist) > 1: # if not direct
        #         self.dogleg(acid, ttlg)
        #         print('adjacent speed up dogleg', ttlg)
        #     else:
        #         if selspd >4. and abs(maxspd - selspd) > 1:
        #             self.speed(acid, ttlg)
        #         elif abs(trackmiles - direct_dist) > 1: # if not direct
        #             self.dogleg(acid, ttlg)
        #             print('adjacent speed up dogleg in mach', ttlg)
        #         elif selspd >4. and abs(maxspd - selspd) <= 1:
        #             ETA = self.reset_ETA(acid)
        #             self.aman.replan_late(acid, ETA=ETA)
        #             print(f'replanning {acid}')
        #         elif selspd <4. and abs(trackmiles - direct_dist) > 1:
        #             ETA = self.reset_ETA(acid)
        #             self.aman.replan_late(acid, ETA=ETA)
        #             print(f'replanning {acid}')
        # #else: no update needed


    def reset_ETA(self, acid):
        ETA_reset = self.aman.Flights.loc[acid, 'ETO_original'] + self.aman.Flights.loc[acid, 'TMA'] + self.aman.Flights.loc[acid, 'Time error']
        # self.aman.FLights.at[acid, 'ETA_reset'] = ETA_reset
        return ETA_reset

    @network.subscriber(topic='PREDICTION')  # , to_group=GROUPID_SIM)
    def on_prediction_received(self, acid, wpt, wptime, flighttime, wptpredutc, parent_id, type, origin, work, t0):
        if acid in self.aman.Flights.index:
            idxac = traf.id2idx(acid)
            if idxac != -1 and acid in self.active_instructions:

                wptime = traf.ap.route[idxac].createtime + flighttime

                previous_iaftime = self.aman.Flights.loc[acid]['TP IAF']

                if wpt in self.aman.iafs:
                    # print("prediction received", acid, (time.time_ns() - t0) / 1e6, "ms")
                    TMA = self.aman.Flights.loc[acid, 'TMA']
                    # 'TP ETA': wptime + TMA
                    data = {'TP IAF': wptime, 'IAF': wpt, 'TPstate': 'updated', 'TP ETA': wptime + TMA}
                    for key, value in data.items():
                        self.aman.Flights.at[acid, key] = value
                    ttlg = self.aman.Flights.loc[acid, 'ttlg']
                    # print('ttlg updated? previous: ',acid, ttlg)

                    self.aman.update_times()


                    ttlg = self.aman.Flights.loc[acid, 'ttlg']
                    # print('updated ttlg: ',acid, ttlg)

                    delay = data['TP IAF'] - previous_iaftime
                    self.store_delay(acid, delay)
                    # print("prediction received and stored ", acid, (time.time_ns() - t0) / 1e6, "ms")
                    self.check_tp_update(acid, ttlg)

                    # print(f'received tp update{acid}')


    def store_delay(self, acid, delay, delaytype=None):
        if delaytype is None:
            delaytype = self.active_instructions[acid]

        # Accumulate delay per instruction type (e.g. 'delay speed', 'delay dogleg', 'short speed', ...)
        if delaytype not in self.aman.Flights.columns:
            self.aman.Flights[delaytype] = 0.0
        if pd.isna(self.aman.Flights.at[acid, delaytype]):
            self.aman.Flights.at[acid, delaytype] = 0.0
        self.aman.Flights.at[acid, delaytype] += delay

        # Ensure totaldelay and totalspeedup exist and are floats
        if 'totaldelay' not in self.aman.Flights.columns:
            self.aman.Flights['totaldelay'] = 0.0
        if 'totalspeedup' not in self.aman.Flights.columns:
            self.aman.Flights['totalspeedup'] = 0.0
        if pd.isna(self.aman.Flights.at[acid, 'totaldelay']):
            self.aman.Flights.at[acid, 'totaldelay'] = 0.0
        if pd.isna(self.aman.Flights.at[acid, 'totalspeedup']):
            self.aman.Flights.at[acid, 'totalspeedup'] = 0.0

        # Positive delay is added to totaldelay, negative to totalspeedup
        if delay > 0:
            self.aman.Flights.at[acid, 'totaldelay'] += delay
        if delay <= 0:
            self.aman.Flights.at[acid, 'totalspeedup'] += delay



    def check_tp_update(self, acid, ttlg):

        instruction_margin = self.aman.instruction_margin
        if self.aman.Flights.at[acid, 'updates'] - self.aman.Flights.at[acid, 'count'] > self.aman.max_updates:
            instruction_margin = min(self.aman.instruction_margin * 2, self.aman.early_approach_margin)
        elif self.aman.Flights.at[acid, 'updates'] - self.aman.Flights.at[acid, 'count'] > 2*self.aman.max_updates:
            instruction_margin = min(self.aman.instruction_margin * 3, self.aman.early_approach_margin)
        itype = self.active_instructions[acid]
        if abs(ttlg) <= instruction_margin:
            self.instruction_correct(acid)
            return
        if 'mach' in itype:
            self.instruction_correct(acid)
            return

        if 'delay' in itype and ttlg < -instruction_margin: # essentially: delay instructed, but it was too much, so now a speed or dogleg must be given that is more correct
            ttlg = 0.97*ttlg # to make sure it converges
            # print(f're-applying delay instruction {acid} {ttlg} {self.active_instructions}')
            self.reapply_instruction(acid, ttlg, itype)

        elif 'short' in itype and ttlg > instruction_margin:  # short instructed, but too much. keep same type of instruction
            ttlg = 0.97 * ttlg  # to make sure it converges
            # print(f're-applying short instruction {acid} {ttlg} {self.active_instructions}')
            self.reapply_instruction( acid, ttlg, itype)

        elif 'delay' in itype and ttlg > instruction_margin:  # delay given, but not sufficient
            # try to increase the same type of instruction if there is still room
            idx = traf.id2idx(acid)
            selspd = traf.selspd[idx] / kts
            minspd = self.aman.Flights.loc[acid]['min_casdesc']

            try:
                trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)
            except:
                print(acid, selspd, itype, ttlg)
                self.aman.totwohtml()
                trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)

            if 'speed' in itype and abs(minspd - selspd) > 1:
                # more speed reduction possible
                self.speed(acid, ttlg)
            elif 'dogleg' in itype and direct_dist*self.max_dogleg_ratio > (trackmiles +1):
                # more dogleg possible within configured ratio
                self.dogleg(acid, ttlg)
                # print('more dogleg from tp update')
            else:
                # no additional delay possible with this type: close instruction and re-evaluate scenario
                self.instruction_correct(acid)
                self.determine_scenario(acid, ttlg)

        elif 'short' in itype and ttlg < -instruction_margin:  # speed-up not sufficient
            idx = traf.id2idx(acid)
            selspd = traf.selspd[idx] / kts
            maxspd = self.aman.Flights.loc[acid]['max_casdesc']
            trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)

            # try another instruction of the same type if possible
            if 'dogleg' in itype and abs(trackmiles - direct_dist) > 1:
                # still shortcut distance to gain
                self.dogleg(acid, ttlg)
                # print('more dogleg from tp update number two')
            elif 'speed' in itype and abs(maxspd - selspd) > 1:
                # still margin to increase speed
                self.speed(acid, ttlg)
            else:
                # no more room with this type: close instruction and re-evaluate scenario
                self.instruction_correct(acid)
                self.determine_scenario(acid, ttlg)

        elif 'adjacent' in itype:
            self.instruction_correct(acid)
            # sim.hold()
            # stack.forward('HOLD', target_id=self.predictor.child_id)
            #
            # print('received update of adjacent ', acid, ttlg)
        else:
            # print(f'instruction correct {acid}')
            self.instruction_correct(acid)
            # self.determine_scenario(acid, ttlg)
            # print(f'completed {acid}')


    def reapply_instruction(self,acid, ttlg, itype):
        if 'dogleg' in itype or 'direct' in itype:
            self.dogleg(acid, ttlg)
            # print('reapply dogleg')
        elif 'speed' in itype:
            self.speed(acid, ttlg)
        elif 'mach' in itype:
            # mach wordt afgesloten en scenario opnieuw bepaald
            self.instruction_correct(acid)
            self.determine_scenario(acid, ttlg)

    def instruction_correct(self, acid, itype=None):
        if itype is None:
            itype = self.active_instructions.pop(acid)
        if 'dogleg' in itype or 'holding' in itype:
            self.aman.Flights.at[acid, 'count'] += 2
        else:
            self.aman.Flights.at[acid,'count'] += 1


        col = f"n_instr_{itype.strip().replace(' ', '_')}"
        if col not in self.aman.Flights.columns:
            # New column is appended at the end of the DataFrame.
            self.aman.Flights[col] = 0
            self.aman.Flights[col] = self.aman.Flights[col].astype(int)

        # Initialize if NaN for this row
        if pd.isna(self.aman.Flights.at[acid, col]):
            self.aman.Flights.at[acid, col] = 0

        # Increment per-itype count
        self.aman.Flights.at[acid, col] += 1




        if len(self.active_instructions) == 0:
            if self.ff:
                sim.fastforward()
            elif self.rtf > 1.:
                sim.dtmult(self.rtf)
            elif not self.ff and self.rtf <= 1.:
                sim.op()
            sim.simdt = 1.0


    @stack.command
    def start_update(self,acid):
        t0 = time.time_ns()
        self.predictor.update(acid, t0)

        iaf = self.aman.Flights.loc[acid, 'IAF']
        # stack.forward(f'AT {acid} {iaf} DO DELAY 20 DEL {acid}', target_id=self.predictor.child_id)
        # print(f'START UPDATE FOR {acid}')
        # print(self.active_instructions)

        if pd.isna(self.aman.Flights.at[acid, 'updates']):
            self.aman.Flights.at[acid, 'updates'] = 0
        self.aman.Flights.at[acid,'updates'] += 1

        if self.aman.Flights.at[acid, 'updates'] > 50:
            self.debug_updates(acid)


    def dogleg(self, acid, ttlg):
        # print('ttlg in dogleg: ', ttlg)
        ttlg = float(ttlg)*self.aman.dogleg_multiplyer # make sure it lowballs the instruction for some margin

        trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)

        reqdist = self.reqdist(acid, ttlg, trackmiles)
        if reqdist - direct_dist < 1:
            self.directiaf(acid)
            instr = 'direct'
        else:
            if direct_dist*self.max_dogleg_ratio < reqdist:
                reqdist = direct_dist*self.max_dogleg_ratio
            self.replacewaypoint(acid, direct_dist, reqdist, trackmiles, direct_qdr)
            self.aman.Flights.loc[acid, 'dogleg'] = round(reqdist/direct_dist,3)
            instr = 'dogleg'

        if ttlg > 0:
            instrtype = 'delay'
        else:
            instrtype = 'short'
        self.active_instructions[acid]= f'{instrtype} {instr}'  # acid: delay/short + dogleg/speed/mach
        self.start_update(acid)


    def speed(self,acid, ttlg):
        idx = traf.id2idx(acid)
        reqspd = round(self.reqspd(acid, ttlg, idx), 0)
        selspd = traf.selspd[idx] / kts
        minspd = self.aman.Flights.loc[acid, 'min_casdesc']
        maxspd = self.aman.Flights.loc[acid, 'max_casdesc']

        if ttlg > 0:
            if reqspd > selspd:
                to_eto = self.aman.Flights.loc[acid]['ETO IAF'] - sim.simt
                print(f'ERROR IN SPEED CALCULATION {acid} {ttlg} {selspd} {reqspd} {to_eto}')
            if reqspd < minspd:
                instruct = minspd
            else:
                instruct = reqspd
        elif ttlg <0:
            if reqspd < selspd:
                to_eto = self.aman.Flights.loc[acid]['ETO IAF'] - sim.simt
                print(f'ERROR IN SPEED CALCULATION {acid} {ttlg} {selspd} {reqspd} {to_eto}')
            if reqspd > maxspd:
                instruct = maxspd
            else:
                instruct = reqspd

        self.aman.Flights.loc[acid, 'selspd'] = instruct
        self.sendspeedcmd(acid, instruct)


        if ttlg > 0:
            instrtype = 'delay'
        else:
            instrtype = 'short'
        self.active_instructions[acid]= instrtype+' speed'
        self.start_update(acid)

    def delay_mach(self,acid):
        mach = self.aman.mach_reduction
        # self.instructions.append(f'REDUCE_MACH {acid} {mach}')
        idx = traf.id2idx(acid)
        self.aman.Flights.at[acid, 'selspd'] = mach
        # traf.selspd[idx] += -mach
        traf.mcruise[idx] = traf.mcruise[idx] - float(mach)
        traf.mdescent[idx] = traf.mdescent[idx] - float(mach)
        traf.selspd[idx] = traf.selspd[idx] - float(mach)

        self.active_instructions[acid]= 'delay'+' mach'
        self.start_update(acid)

    def speed_at_entry(self, acid, spd, ttlg, direct = False):
        idx = traf.id2idx(acid)
        selspd = traf.selspd[idx] / kts

        self.aman.Flights.loc[acid, 'selspd'] = spd
        targalt = self.handover_alt * ft
        cmdtext = f"SENDSPEEDCMD {acid} {spd}"
        traf.cond.ataltcmd(idx, targalt, cmdtext)

        if direct:
            # stack.stack(f'{acid} ATALT {self.handover_alt} DIRECTIAF {acid}')
            iaf = self.aman.Flights.loc[acid, 'IAF']
            cmdtext = f"DIRECT {acid} {iaf}"
            traf.cond.ataltcmd(idx, targalt, cmdtext)
            self.aman.Flights.loc[acid, 'direct'] = True

        # if ttlg > 0:
        #     instrtype = 'delay'
        # else:
        #     instrtype = 'short'
        #deze dingen werken niet vanwege hoe check tp update is
        self.active_instructions[acid]= 'adjacent'
        self.start_update(acid)

    def minspeed(self, acid, spd):
        idx = traf.id2idx(acid)

        self.aman.Flights.loc[acid, 'selspd'] = spd
        self.sendspeedcmd(acid, spd)

        self.active_instructions[acid] = 'delay speed'
        self.start_update(acid)

    @stack.command
    def directiaf(self, acid):
        idxac = traf.id2idx(acid)
        iaf = self.aman.Flights.loc[acid, 'IAF']
        # self.instructions.append(f'DIRECT {acid} {iaf}')

        traf.ap.route[idxac].direct(idxac,iaf)
        self.aman.Flights.loc[acid, 'direct'] = True

    @stack.command
    def sendspeedcmd(self, acid, speed):
        #speed in knots
        speed = float(speed)
        idx = traf.id2idx(acid)
        # print('sendspeed: ', speed)
        traf.ap.selspdcmd(idx, speed * kts)
        # self.instructions.append(f'SPEED {acid} {speed}')
        if hasattr(traf, "user_spdcmd"):
            traf.user_spdcmd[idx] = True

    @stack.command
    def testselspd(self, acid, speed):
        speed = float(speed)
        idx = traf.id2idx(acid)
        # print('sendspeed: ', speed)
        traf.ap.selspdcmd(idx, speed * kts)
        print(traf.selspd[idx])
        # stack.stack(f"PRINTSELSPD {acid}")

    @stack.command
    def printselspd(self,acid):
        idx = traf.id2idx(acid)
        print("same object:", self.user_spdcmd is traf.user_spdcmd)
        print("len self:", len(self.user_spdcmd), "len traf:", len(traf.user_spdcmd))
        # print(traf.user_spdcmd)
        print(traf.user_spdcmd[idx])
        # traf.user_spdcmd[idx] = True
        # print(traf.user_spdcmd[idx])

    @stack.command
    def printactive(self):
        print(self.active_instructions)

    @stack.command
    def replacewaypoint(self, acid, direct_dist, reqdist, trackmiles, direct_qdr):
        # instruction = str(reqdist) - trackmiles

        direct_dist = float(direct_dist)
        reqdist = float(reqdist)
        trackmiles = float(trackmiles)
        direct_qdr = float(direct_qdr)
        acrte = Route._routes[acid]
        idx = traf.id2idx(acid)
        # iaf = self.findiaf(acid)
        iaf = self.aman.Flights.loc[acid, 'IAF']
        latac = traf.lat[idx]
        lonac = traf.lon[idx]
        iaf_index = acrte.wpname.index(iaf)
        alt = traf.alt[idx]
        iaf_alt = acrte.wpalt[iaf_index]

        lat, lon, alpha, hypothenuse, opposing = self.determine_wpt(acid, reqdist, direct_dist, trackmiles, direct_qdr, acrte, iaf_index)

        disttoiaf = kwikdist(lat, lon, acrte.wplat[iaf_index], acrte.wplon[iaf_index])
        disttonewwp = kwikdist(latac, lonac, lat, lon)

        if abs(reqdist - (disttoiaf + disttonewwp)) > 1:
            # print('replacewaypoint incorrect: ',acid, reqdist, disttoiaf + disttonewwp, disttoiaf, disttonewwp, lat, lon)
            # print('correcting new waypoint')
            error = reqdist - (disttoiaf + disttonewwp)
            corrected_reqdist = reqdist + error
            lat, lon, alpha, hypothenuse, opposing = self.determine_wpt(acid, corrected_reqdist, direct_dist, trackmiles,
                                                                        direct_qdr, acrte, iaf_index)

            disttoiaf = kwikdist(lat, lon, acrte.wplat[iaf_index], acrte.wplon[iaf_index])
            disttonewwp = kwikdist(latac, lonac, lat, lon)
            # if abs(reqdist - (disttoiaf + disttonewwp)) > 1:
                # print('replacewaypoint STILL incorrect: ', acid, corrected_reqdist, disttoiaf + disttonewwp, disttoiaf, disttonewwp,
                #       lat, lon)



        wpt_alt = math.tan(math.radians(self.aman.descent_angle)) * opposing * nm
        wpt_alt = wpt_alt + iaf_alt
        wpt_alt = min(wpt_alt, alt)  # make sure that new wp alt is not above current altitude
        wpt_alt = round(wpt_alt, 0)

        newwp_name = f'DOGLEG{acid}'
        if newwp_name in acrte.wpname:
            acrte.delwpt(idx, newwp_name)
        # Route.addwptstack(f'ADDWPT {acid} {lat} {lon} ,{wpt_alt} , , , {iaf}')
        newwp_index = acrte.addwpt(idx, newwp_name, 0, lat, lon, alt=wpt_alt, beforewp=iaf)  # must be in meters

        Route.direct(idx, newwp_name)


    def determine_wpt(self,acid, reqdist, direct_dist, trackmiles, direct_qdr, acrte, iaf_index):
        idx = traf.id2idx(acid)
        hypothenuse = (reqdist ** 2 + direct_dist ** 2) / (2 * reqdist)
        opposing = reqdist - hypothenuse
        if opposing < 0:
            # print(f'wrong replacewaypoint {acid}, {opposing}, {reqdist}, {direct_dist}, {trackmiles}')
            return
        alpha = math.degrees(math.atan2(opposing, direct_dist))

        lat, lon = qdrpos(traf.lat[idx], traf.lon[idx], direct_qdr + alpha, hypothenuse)


        qdrcheck, distcheck = kwikqdrdist(acrte.wplat[iaf_index], acrte.wplon[iaf_index], lat, lon)

        qdrcheck_next, distcheck_next = kwikqdrdist(acrte.wplat[iaf_index], acrte.wplon[iaf_index],
                                                    acrte.wplat[iaf_index + 1], acrte.wplon[iaf_index + 1])

        if abs(qdrcheck - qdrcheck_next) < 90 or abs(qdrcheck - qdrcheck_next) > 270:
            alpha = -alpha
            lat, lon = qdrpos(traf.lat[idx], traf.lon[idx], direct_qdr + alpha, hypothenuse)
        return lat, lon, alpha, hypothenuse, opposing

    def reqspd(self,acid, ttlg, idx):
        aim_ttlg = ttlg + self.aman.approach_aim
        to_eto = self.aman.Flights.loc[acid]['ETO IAF'] - sim.simt
        # idx = traf.id2idx(acid)
        selspd = traf.selspd[idx]
        return (selspd - (aim_ttlg/to_eto)*selspd)/kts

    def reqdist(self,acid, ttlg, planned_dist):
        aim_ttlg = ttlg + self.aman.approach_aim
        to_eto = self.aman.Flights.loc[acid, 'ETO IAF'] - sim.simt
        dist = planned_dist + planned_dist*(aim_ttlg/to_eto)  #aim ttlg will be negative if speed up required
        return dist


    def holding(self, acid, ttlg):
        idx = traf.id2idx(acid)

# HELPER FUNCTIONS




    @stack.command
    def printroute(self, acid, attrib):
        acrte = Route._routes[acid]
        arr = getattr(acrte, attrib, None)
        if arr is None:
            stack.stack(f"ECHO Attribute {attrib} not found")
        stack.stack(f"ECHO {arr}")

    @stack.command
    def debug_updates(self, acid):
        """Print detailed debug info when updates counter gets too high."""

        try:
            idx = traf.id2idx(acid)
            if idx < 0:
                print(f'[ATC DEBUG] {acid}: not in traf anymore')
                return

            # Basisdata uit AMAN
            ttlg = self.aman.Flights.loc[acid, 'ttlg']
            min_casdesc = self.aman.Flights.loc[acid, 'min_casdesc']
            max_casdesc = self.aman.Flights.loc[acid, 'max_casdesc']
            iaf = self.aman.Flights.loc[acid, 'IAF']

            # Huidige snelheid in knopen
            selspd_knots = float(traf.selspd[idx]) / kts

            # Hoogtes in ft
            alt_ft = float(traf.alt[idx]) / ft
            selalt_ft = float(traf.selalt[idx]) / ft

            # Route / waypoints
            acrte = Route._routes[acid]
            iactwp = acrte.iactwp
            current_wp_name = acrte.wpname[iactwp] if 0 <= iactwp < len(acrte.wpname) else 'UNKNOWN'

            # Trackmiles & direct distance
            trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)

            # Route lengte opnieuw opbouwen met kwikdist
            lat_ac = float(traf.lat[idx])
            lon_ac = float(traf.lon[idx])
            route_len_nm = 0.0

            # AC -> huidige actieve wp
            route_len_nm += kwikdist(lat_ac, lon_ac,
                                     acrte.wplat[iactwp],
                                     acrte.wplon[iactwp])

            # Huidige wp -> IAF langs route
            for i in range(iactwp, len(acrte.wpname) - 1):
                route_len_nm += kwikdist(acrte.wplat[i], acrte.wplon[i],
                                         acrte.wplat[i+1], acrte.wplon[i+1])
                if acrte.wpname[i+1] == iaf:
                    break

            # Dogleg ratio (trackmiles / direct distance)
            dogleg_ratio = None
            if direct_dist and direct_dist > 0:
                dogleg_ratio = trackmiles / direct_dist

            # reqdist en reqspd voor huidige ttlg
            reqdist = None
            reqspd = None
            if pd.notna(ttlg):
                reqdist = self.reqdist(acid, float(ttlg), trackmiles)
                reqspd = self.reqspd(acid, float(ttlg), idx)  # al in knopen

            print('================ ATC DEBUG UPDATES =================')
            print(f'ACID: {acid}')
            print(f'updates: {self.aman.Flights.at[acid, "updates"]}')
            print(f'ttlg: {ttlg}')
            print(f'selspd (knots): {selspd_knots}')
            print(f'min_casdesc / max_casdesc (knots): {min_casdesc} / {max_casdesc}')
            print(f'altitude (ft): {alt_ft}')
            print(f'selected altitude (ft): {selalt_ft}')
            print(f'current wp index: {iactwp}')
            print(f'current wp name: {current_wp_name}')
            print(f'IAF: {iaf}')
            print(f'direct_dist (nm): {direct_dist}')
            print(f'trackmiles (nm): {trackmiles}')
            print(f'route_len_nm (kwikdist AC->IAF): {route_len_nm}')
            print(f'dogleg_ratio (trackmiles/direct_dist): {dogleg_ratio}')
            print(f'reqdist (nm) for current ttlg: {reqdist}')
            print(f'reqspd (knots) for current ttlg: {reqspd}')
            print('====================================================')

        except Exception as e:
            print(f'[ATC DEBUG] Error while debugging {acid}: {e}')




    def findtrackmiles(self, acid):
        acrte = Route._routes[acid]
        idx = traf.id2idx(acid)

        wpdirfrom = []
        wpdistto = []

        qdr, dist = kwikqdrdist(traf.lat[idx], traf.lon[idx],
                                acrte.wplat[acrte.iactwp], acrte.wplon[acrte.iactwp])

        wpdirfrom.append(qdr)  # [deg]
        wpdistto.append(dist)  # [nm]  distto is in nautical miles
        if acrte.wpname[acrte.iactwp] == self.aman.Flights.loc[acid, 'IAF']:
            return dist, qdr, dist
        else: # if the next wp is the iaf, no shortcut can be taken
            for i in range(acrte.iactwp, len(acrte.wpname) - 1):
                qdr,dist = kwikqdrdist(acrte.wplat[i]  ,acrte.wplon[i],
                                    acrte.wplat[i+1],acrte.wplon[i+1])
                wpdirfrom.append(qdr)  # [deg]
                wpdistto.append(dist)  # [nm]  distto is in nautical miles
                # print(acrte.wpname[i])
                if acrte.wpname[i + 1] == self.aman.Flights.loc[acid, 'IAF']:
                    direct_qdr, direct_dist = kwikqdrdist(traf.lat[idx], traf.lon[idx],
                                                          acrte.wplat[i +1], acrte.wplon[i +1])

                    break
            trackmiles = sum(wpdistto)
            try:
                return trackmiles, direct_qdr, direct_dist
            except:
                print('findtrackmiles atc: ',acid, acrte.wpname, trackmiles )
                print(i)
                print(acrte.wpname[i])
                print(acrte.wpname[i+1])
                print(self.aman.Flights.loc[acid, 'IAF'])
                print(direct_qdr)
                print(direct_dist)


        # Route.before(acid, iaf, 'ADDWPT', )


    def calculate_wp(self, reqlen, directdist, alpha):
        """
        Solve for B using the formula:
          B = (X^2 - C^2) / (2*(X - C*cos(alpha)))
        Note: alpha should be provided in radians.
        """
        X = reqlen
        C = directdist
        denom = 2 * (X - C * math.cos(alpha))
        if abs(denom) < 1e-9:
            raise ValueError("Denominator is too close to zero; check the inputs.")
        return (X ** 2 - C ** 2) / denom




    @stack.command
    def set_speed(self, acid, mcruise=None, cascruise=None, mdescent=None, casdesc=None, mclimb=None, casclimb=None,
                  max_casdesc=None):
        if casdesc is None:
            casdesc = 250.
        max_casdesc = round(float(casdesc) + self.aman.max_speedup)
        min_casdesc = round(float(casdesc) - self.aman.max_slowdown)
        self.aman.Flights.at[acid, 'casdesc'] = float(casdesc)
        self.aman.Flights.at[acid, 'max_casdesc'] = max_casdesc
        self.aman.Flights.at[acid, 'min_casdesc'] = min_casdesc
        stack.stack(f'FLIGHT_SPEEDS {acid} {mcruise} {cascruise} {mdescent} {casdesc} {mclimb} {casclimb}')
