# amanatc.py
from textwrap import shorten

from PIL.ImageChops import difference
from casadi.tools.structure3 import correct_vector_indexing
from jedi.debug import speed
from scipy.optimize import direct

from bluesky import core, stack, traf, sim, HOLD, network
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
        self.mach_threshold = 0
        self.handover_alt = 260.*100 # moet naar amansettings
        self.max_dogleg_ratio = 1.8
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

                # while True:
                self.aman.update_times()

                frozen_flights = frozen_flights.dropna(subset=['ttlg'])

                # instructie-criteria: delay OF shorten
                delay = frozen_flights['ttlg'] > self.aman.early_approach_margin
                shorten = frozen_flights['ttlg'] < -self.aman.late_approach_margin

                # exclude aircraft that already have an active instruction/prediction update pending
                has_active_instr = frozen_flights.index.isin(self.active_instructions.keys())

                instruct = frozen_flights[(delay | shorten) & ~has_active_instr]

                if len(instruct) >0:
                    # print('instruct: ', instruct)
                    if sim.state != HOLD:
                        self.rtf = sim.dtmult
                        self.ff = sim.ffmode

                    sim.hold()

                    for acid, row in instruct.iterrows():
                        self.determine_scenario(acid, float(row['ttlg']))


                    if len(self.active_instructions) == 0:
                        if self.ff:
                            sim.fastforward()
                        elif self.rtf > 1.:
                            sim.dtmult(self.rtf)
                        elif not self.ff and self.rtf <= 1.:
                            sim.op()

                #TODO
                # evt small instructions
                # update TP




    def determine_scenario(self, acid, ttlg):
        idx = traf.id2idx(acid)
        selspd = traf.selspd[idx] / kts
        maxspd = self.aman.Flights.loc[acid]['max_casdesc']
        minspd = self.aman.Flights.loc[acid]['min_casdesc']
        alt = traf.alt[idx]/ft
        to_iaf = self.aman.Flights.loc[acid, 'ETO IAF'] - sim.simt
        vs = traf.vs[idx]
        trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)
        #standard scenarios
        if alt < self.handover_alt and vs < 0.5:

            # scenario 2: speedup
            if ttlg <= -self.aman.late_approach_margin:

                if abs(trackmiles - direct_dist) > 1: #essentially direct == False
                    self.dogleg(acid, ttlg)
                elif abs(maxspd - selspd) > 1:
                    self.speed(acid, ttlg)
                else:
                    ETA = self.reset_ETA(acid)
                    self.aman.replan_late(acid, ETA=ETA)
                    print(f'replanning {acid}')

            #scenario 3: delay
            elif ttlg > self.aman.early_approach_margin:
                if abs(minspd - selspd) > 1:
                    self.speed(acid, ttlg)
                elif to_iaf > self.aman.nearby_threshold and direct_dist*self.max_dogleg_ratio > (trackmiles +1): # and ttlg < max dogleg?
                    self.dogleg(acid, ttlg)
                # todo add holding

            #scenario 4: adjacent
        elif ttlg > self.aman.early_adjacent_threshold: # delay
            if selspd < 4. and pd.isna(self.aman.Flights.loc[acid]['selspd']):
                self.delay_mach(acid)
            else:
                if abs(minspd - selspd) > 1:
                    self.speed(acid, ttlg)
                elif direct_dist*self.max_dogleg_ratio > (trackmiles +1): # and ttlg < max dogleg?
                    self.dogleg(acid, ttlg)

        elif ttlg <= -self.aman.late_adjacent_threshold: # speed up
            if selspd < 4. and pd.isna(self.aman.Flights.loc[acid]['selspd']):
                self.dogleg(acid, ttlg)
            else:
                if abs(minspd - selspd) > 1:
                    self.speed(acid, ttlg)
                elif direct_dist*self.max_dogleg_ratio > (trackmiles +1): # and ttlg < max dogleg?
                    self.dogleg(acid, ttlg)

        # else: no update needed






    def reset_ETA(self, acid):
        ETA_reset = self.aman.Flights.loc[acid, 'ETO_original'] + self.aman.Flights.loc[acid, 'TMA'] + self.aman.Flights.loc[acid, 'Time error']
        # self.aman.FLights.at[acid, 'ETA_reset'] = ETA_reset
        return ETA_reset

    @network.subscriber(topic='PREDICTION')  # , to_group=GROUPID_SIM)
    def on_prediction_received(self, acid, wpt, wptime, flighttime, wptpredutc, parent_id, type, origin, work):
        if acid in self.aman.Flights.index:
            idxac = traf.id2idx(acid)
            if idxac != -1 and acid in self.active_instructions:
                wptime = traf.ap.route[idxac].createtime + flighttime
                previous_wptime = self.aman.Flights.loc[acid]['TP IAF']

                if wpt in self.aman.iafs:

                    TMA = self.aman.Flights.loc[acid, 'TMA']
                    # 'TP ETA': wptime + TMA
                    data = {'TP IAF': wptime, 'IAF': wpt, 'TPstate': 'updated',
                            'ttlg': self.aman.Flights.loc[acid, 'EAT'] - wptime, 'TP ETA': wptime + TMA}

                    for key, value in data.items():
                        self.aman.Flights.at[acid, key] = value

                    self.aman.update_times()

                    ttlg = self.aman.Flights.loc[acid, 'ttlg']
                    # todo check if aircraft needs new instruction
                    self.check_tp_update(acid, ttlg)
                    print(f'received tp update{acid}')


    def check_tp_update(self, acid, ttlg):
        itype = self.active_instructions[acid]

        if 'delay' in itype and ttlg < -self.aman.instruction_margin: # essentially: delay instructed, but it was too much, so now a speed or dogleg must be given that is more correct
            ttlg = 0.9*ttlg # to make sure it converges
            self.reapply_instruction(self,acid, ttlg, itype)

        elif 'short' in itype and ttlg > self.aman.instruction_margin:  # short instructed, but too much. keep same type of instruction
            ttlg = 0.9 * ttlg  # to make sure it converges
            self.reapply_instruction(self, acid, ttlg, itype)


        elif 'delay' in itype and ttlg > self.aman.instruction_margin:  # delay given, but not sufficient
            # try to increase the same type of instruction if there is still room
            idx = traf.id2idx(acid)
            selspd = traf.selspd[idx] / kts
            minspd = self.aman.Flights.loc[acid]['min_casdesc']

            trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)


            if 'speed' in itype and abs(minspd - selspd) > 1:
                # more speed reduction possible
                self.speed(acid, ttlg)
            elif 'dogleg' in itype and direct_dist*self.max_dogleg_ratio > (trackmiles +1):
                # more dogleg possible within configured ratio
                self.dogleg(acid, ttlg)
            else:
                # no additional delay possible with this type: close instruction and re-evaluate scenario
                self.instruction_correct(acid)
                self.determine_scenario(acid, ttlg)



        elif 'short' in itype and ttlg < -self.aman.instruction_margin:  # speed-up not sufficient
            idx = traf.id2idx(acid)
            selspd = traf.selspd[idx] / kts
            maxspd = self.aman.Flights.loc[acid]['max_casdesc']
            trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)

            # try another instruction of the same type if possible
            if 'dogleg' in itype and abs(trackmiles - direct_dist) > 1:
                # still shortcut distance to gain
                self.dogleg(acid, ttlg)
            elif 'speed' in itype and abs(maxspd - selspd) > 1:
                # still margin to increase speed
                self.speed(acid, ttlg)
            else:
                # no more room with this type: close instruction and re-evaluate scenario
                self.instruction_correct(acid)
                self.determine_scenario(acid, ttlg)



        else:
            print(f'instruction correct {acid}')
            self.instruction_correct(acid)
            self.determine_scenario(acid, ttlg)
            print(f'completed {acid}')

    def reapply_instruction(self,acid, ttlg, itype):
        if 'dogleg' in itype or 'direct' in itype:
            self.dogleg(acid, ttlg)
        elif 'speed' in itype:
            self.speed(acid, ttlg)
        elif 'mach' in itype:
            # mach wordt afgesloten en scenario opnieuw bepaald
            self.instruction_correct(acid)
            self.determine_scenario(acid, ttlg)

    def instruction_correct(self, acid):
        self.active_instructions.pop(acid)
        self.aman.Flights.at[acid,'count'] += 1
        # todo store delay type (calc in pred received)

        if len(self.active_instructions) == 0:
            if self.ff:
                sim.fastforward()
            elif self.rtf > 1.:
                sim.dtmult(self.rtf)
            elif not self.ff and self.rtf <= 1.:
                sim.op()



    def start_update(self,acid):
        self.predictor.update(acid)
        iaf = self.aman.Flights.loc[acid, 'IAF']
        stack.forward(f'AT {acid} {iaf} DO DELAY 10 DEL {acid}', target_id=self.predictor.child_id)
        print(f'START UPDATE FOR {acid}')
        print(self.active_instructions)

        if pd.isna(self.aman.Flights.at[acid, 'updates']):
            self.aman.Flights.at[acid, 'updates'] = 0
        self.aman.Flights.at[acid,'updates'] += 1

    def dogleg(self, acid, ttlg):
        ttlg = float(ttlg)*self.aman.dogleg_multiplyer # make sure it lowballs the instruction for some margin

        trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)

        reqdist = self.reqdist(acid, ttlg, trackmiles)
        if reqdist - direct_dist < 1:
            self.directiaf(acid)
        else:
            if direct_dist*self.max_dogleg_ratio < reqdist:
                reqdist = direct_dist*self.max_dogleg_ratio
            self.replacewaypoint(acid, direct_dist, reqdist, trackmiles, direct_qdr)
            self.aman.Flights.loc[acid, 'dogleg'] = round(reqdist/direct_dist,3)

        if ttlg > 0:
            instrtype = 'delay'
        else:
            instrtype = 'short'
        self.active_instructions[acid]= instrtype+' dogleg'  # acid: delay/short + dogleg/speed/mach
        self.start_update(acid)

    def speed(self,acid, ttlg):
        idx = traf.id2idx(acid)
        reqspd = round(self.reqspd(acid, ttlg, idx), 0)
        selspd = traf.selspd[idx] / kts
        minspd = self.aman.Flights.loc[acid, 'min_casdesc']
        maxspd = self.aman.Flights.loc[acid, 'max_casdesc']

        if ttlg > 0:
            if reqspd < minspd:
                instruct = minspd
            else:
                instruct = reqspd
        elif ttlg <0:
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
        self.instructions.append(f'REDUCE_MACH {acid} {mach}')

        self.aman.Flights.at[acid, 'selspd'] = mach


        self.active_instructions[acid]= 'delay'+' mach'
        self.start_update(acid)









    def directiaf(self, acid):
        idxac = traf.id2idx(acid)
        iaf = self.aman.Flights.loc[acid, 'IAF']
        # self.instructions.append(f'DIRECT {acid} {iaf}')

        traf.ap.route[idxac].direct(idxac,iaf)
        self.aman.Flights.loc[acid, 'direct'] = True

    def sendspeedcmd(self, acid, speed):
        #speed in knots
        speed = float(speed)
        idx = traf.id2idx(acid)
        # print('sendspeed: ', speed)
        traf.ap.selspdcmd(idx, speed * kts)
        # self.instructions.append(f'SPEED {acid} {speed}')



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


        hypothenuse = (reqdist ** 2 + direct_dist ** 2) / (2 * reqdist)
        opposing = reqdist - hypothenuse
        if opposing < 0:
            print(f'wrong replacewaypoint {acid}, {opposing}, {reqdist}, {direct_dist}, {trackmiles}')
            return
        alpha = math.degrees(math.atan2(opposing, direct_dist))

        # print(reqdist, direct_dist)
        # print(hypothenuse, opposing, alpha)
        lat, lon = qdrpos(traf.lat[idx], traf.lon[idx], direct_qdr + alpha, hypothenuse)

        try:
            iaf_index = acrte.wpname.index(iaf)
        except ValueError:
            print(iaf, acid)
            iaf_index = acrte.wpname.index(iaf)
        alt = traf.alt[idx]
        iaf_alt = acrte.wpalt[iaf_index]

        qdrcheck, distcheck = kwikqdrdist(acrte.wplat[iaf_index], acrte.wplon[iaf_index], lat, lon)

        qdrcheck_next, distcheck_next = kwikqdrdist(acrte.wplat[iaf_index], acrte.wplon[iaf_index],
                                                    acrte.wplat[iaf_index + 1], acrte.wplon[iaf_index + 1])

        if abs(qdrcheck - qdrcheck_next) < 90 or abs(qdrcheck - qdrcheck_next) > 270:
            alpha = -alpha
            lat, lon = qdrpos(traf.lat[idx], traf.lon[idx], direct_qdr + alpha, hypothenuse)

        wpt_alt = math.tan(math.radians(self.aman.descent_angle)) * opposing * nm

        wpt_alt = wpt_alt + iaf_alt
        wpt_alt = min(wpt_alt, alt)  # make sure that new wp alt is not above current altitude
        wpt_alt = round(wpt_alt, 0)

        idx = traf.id2idx(acid)
        latac = traf.lat[idx]
        lonac = traf.lon[idx]
        iafindex = acrte.wpname.index(iaf)
        disttoiaf = kwikdist(lat, lon, acrte.wplat[iafindex], acrte.wplon[iafindex])

        disttonewwp = kwikdist(latac, lonac, lat, lon)

        if abs(reqdist - (disttoiaf + disttonewwp)) > 5:
            print('replacewaypoint incorrect: ', reqdist, disttoiaf, disttonewwp, lat, lon)


        newwp_name = f'DOGLEG{acid}'
        if newwp_name in acrte.wpname:
            acrte.delwpt(idx, newwp_name)
        # Route.addwptstack(f'ADDWPT {acid} {lat} {lon} ,{wpt_alt} , , , {iaf}')
        newwp_index = acrte.addwpt(idx, newwp_name, 0, lat, lon, alt=wpt_alt, beforewp=iaf)  # must be in meters

        Route.direct(idx, newwp_name)




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

# HELPER FUNCTIONS


    @stack.command
    def printroute(self, acid, attrib):
        acrte = Route._routes[acid]
        arr = getattr(acrte, attrib, None)
        if arr is None:
            stack.stack(f"ECHO Attribute {attrib} not found")



        stack.stack(f"ECHO {arr}")

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

