# amanatc.py
from textwrap import shorten

from PIL.ImageChops import difference
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
                if sim.state != HOLD:
                    self.rtf = sim.dtmult
                    self.ff = sim.ffmode

                sim.hold()
                # while True:
                self.aman.update_times()

                delay = frozen_flights[frozen_flights['ttlg'] > self.aman.early_approach_margin]
                shorten = frozen_flights[frozen_flights['ttlg'] < - self.aman.late_approach_margin]
                delay = delay.dropna(subset=['ttlg'])
                shorten = shorten.dropna(subset=['ttlg'])

                for acid, row in delay.iterrows():
                    self.delay(acid, float(row['ttlg']))

                for acid, row in shorten.iterrows():
                    self.shorten(acid, float(row['ttlg']))

                #TODO
                # evt small instructions
                # update TP
                # adjacent mach

    @network.subscriber(topic='PREDICTION')  # , to_group=GROUPID_SIM)
    def on_prediction_received(self, acid, wpt, wptime, flighttime, wptpredutc, parent_id, type, origin, work):
        if acid in self.Flights.index:
            idxac = traf.id2idx(acid)
            wptime = traf.ap.route[idxac].createtime + flighttime
            # print(f'{acid} at {wpt}')
            if wpt in self.iafs:
                # data = {'TP IAF': wptime, 'IAF': wpt , 'TPstate': 'updated iaf', 'ttlg': self.Flights.loc[acid,'EAT']-wptime}

                TMA = self.Flights.loc[acid, 'TMA']
                # 'TP ETA': wptime + TMA
                data = {'TP IAF': wptime, 'IAF': wpt, 'TPstate': 'updated',
                        'ttlg': self.Flights.loc[acid, 'EAT'] - wptime, 'TP ETA': wptime + TMA}

                for key, value in data.items():
                    self.Flights.at[acid, key] = value

                self.aman.update_times()

                ttlg = self.aman.Flights.loc[acid, 'ttlg']
                # todo check if aircraft needs new instruction

    def delay(self, acid, delay):













    # done?
    def delay(self, acid, ttlg, minor = False):
        idx = traf.id2idx(acid)
        selspd = traf.selspd[idx] / kts
        minclean = self.aman.Flights.loc[acid, 'min_casdesc']
        required_spd = round(self.reqspd(acid, ttlg, idx), 0)

        if selspd > minclean and required_spd > minclean:
                selspd = required_spd
                # self.instructions.append(f'SPD {acid} {selspd}')
                # print("Selspd 1: ", selspd)
                # traf.ap.selspdcmd(idx, selspd*kts)
                self.sendspeedcmd(acid, selspd)
                self.add_instruction(acid, selspd, 'spd delay')

                self.aman.Flights.loc[acid, 'selspd'] = selspd
                print("Selspd 1: ", selspd)
        elif selspd > minclean and required_spd <= minclean:
            selspd = minclean
            # self.instructions.append(f'SPD {acid} {selspd}')
            # traf.ap.selspdcmd(idx, selspd*kts)
            self.aman.Flights.loc[acid, 'selspd'] = selspd
            self.sendspeedcmd(acid, selspd)
            self.add_instruction(acid,selspd, 'spd delay')

            # if minor == False:
            #     self.dogleg(acid,ttlg)

        else:
            selspd = minclean
            if minor == False:
                self.dogleg(acid,ttlg)



        instructed = 'delay' + speed/dogleg/mach/holding
        self.aman.Flights.at[acid, state] = instructed


    @stack.command
    def shorten(self, acid, ttlg, minor = False):
        if type(ttlg) == str:
            ttlg = int(ttlg)


        speed = False
        trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)

        # if direct does not significantly change the miles, go to speed instruction
        if abs(trackmiles - direct_dist) < 0.1:
            speed = True

        else:

            reqdist = self.reqdist(acid, ttlg, trackmiles)
            #if required distance is shorter than direct, also go to speed instruction
            if reqdist < direct_dist:


                self.directiaf(acid)
                # speed will be done next iteration
                self.add_instruction(acid, 'iaf', 'direct')

            else:
                # shorter using dogleg logic
                self.replacewaypoint(acid, direct_dist, reqdist, trackmiles, direct_qdr)
                self.aman.Flights.at[acid, 'dogleg'] = True
                self.add_instruction(acid,(trackmiles, reqdist), 'shortened dogleg')


        if speed:
            idx = traf.id2idx(acid)
            reqspd = round(self.reqspd(acid, ttlg, idx),0)
            selspd = traf.selspd[idx] / kts

            if reqspd < selspd:
                print('check speed up function')
                return

            elif reqspd > selspd:
                print('reqspd selspd: ',reqspd, selspd)
                # find out max speed from mach
                maxspd = self.aman.Flights.loc[acid]['max_casdesc']
                if reqspd > maxspd:
                    # self.instructions.append(f'SPD {acid} {maxspd}')
                    # traf.ap.selspdcmd(idx, maxspd*kts)
                    self.aman.Flights.loc[acid, 'required'] = False
                    self.aman.Flights.loc[acid, 'selspd'] = maxspd
                    self.aman.Flights.loc[acid, 'earliest'] = True
                    self.sendspeedcmd(acid, maxspd)
                    self.add_instruction(acid, maxspd, 'maxspd')


                else:
                    # self.instructions.append(f'SPD {acid} {reqspd}')
                    # traf.ap.selspdcmd(idx, selspd*kts)
                    self.aman.Flights.loc[acid, 'selspd'] = reqspd
                    self.sendspeedcmd(acid, reqspd)
                    self.add_instruction(acid,reqspd, 'speed up')

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


    def satisfactory_instruction(self):
        store result



    def delay_mach(self, acid):
        mach = self.aman.mach_reduction
        self.instructions.append(f'REDUCE_MACH {acid} {mach}')
        # deze moet nog aangepast
        self.aman.Flights.at[acid, 'selspd'] = mach
        print(mach)
        self.add_instruction(acid, mach, 'mach')
        return False



    @stack.command
    def dogleg(self, acid, ttlg):

        ttlg = float(ttlg)

        trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)
        print('dogleg trackmiles: ', trackmiles, direct_qdr, direct_dist)
        # reqdist = trackmiles*(minclean/required_spd)
        reqdist = self.reqdist(acid, ttlg, trackmiles)
        if reqdist < trackmiles:
            print('dogleg makes route shorter, please validate method')
            return
        print('reqdist: ', reqdist)
        reqdist = (reqdist - trackmiles) * self.aman.dogleg_multiplyer + trackmiles
        self.replacewaypoint(acid, direct_dist, reqdist, trackmiles, direct_qdr)
        self.aman.Flights.loc[acid, 'dogleg'] = True
        self.add_instruction(acid,(trackmiles, reqdist), 'dogleg')
        # print(self.instructions)

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
        print('sendspeed: ', speed)
        traf.ap.selspdcmd(idx, speed * kts)
        self.instructions.append(f'SPEED {acid} {speed}')

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

#old method
        # h = math.sqrt( (reqdist*0.5)**2 - (direct_dist*0.5)**2 )
        # alpha = math.atan2(h, direct_dist*0.5)
        # alpha = math.degrees(alpha)
        # lat, lon = qdrpos(traf.lat[idx], traf.lon[idx], direct_qdr +alpha, 0.5*reqdist)

        # opposing = math.sqrt((reqdist**2 - direct_dist**2)/2)
        # alpha = math.atan2(opposing, direct_dist)
        # hypothenuse = math.sqrt(opposing**2 + direct_dist**2)

        hypothenuse = (reqdist**2 + direct_dist**2)/(2*reqdist)
        opposing = reqdist - hypothenuse
        if opposing < 0:
            print('wrong replacewaypoint')
            return
        alpha = math.degrees(math.atan2(opposing, direct_dist))

        print(reqdist, direct_dist)
        print(hypothenuse, opposing, alpha)
        lat,lon = qdrpos(traf.lat[idx], traf.lon[idx], direct_qdr+alpha, hypothenuse)


        # print(lat, lon)
        # print(h, alpha)
        # print(traf.lat[idx], traf.lon[idx])
        # print(0.5*reqdist)





        try:
            iaf_index = acrte.wpname.index(iaf)
        except ValueError:
            print(iaf, acid)
            iaf_index = acrte.wpname.index(iaf)
        alt = traf.alt[idx]
        iaf_alt = acrte.wpalt[iaf_index]

        qdrcheck, distcheck = kwikqdrdist(acrte.wplat[iaf_index], acrte.wplon[iaf_index], lat, lon)

        qdrcheck_next, distcheck_next = kwikqdrdist(acrte.wplat[iaf_index], acrte.wplon[iaf_index], acrte.wplat[iaf_index +1], acrte.wplon[iaf_index+1])




        if abs(qdrcheck - qdrcheck_next) < 90 or abs(qdrcheck -qdrcheck_next) >270:
            alpha = -alpha
            lat, lon = qdrpos(traf.lat[idx], traf.lon[idx], direct_qdr + alpha, hypothenuse)


#old method
        # wpt_alt = (alt+iaf_alt)/2
        wpt_alt = math.tan(math.radians(self.aman.descent_angle)) * opposing*nm

        wpt_alt = wpt_alt + iaf_alt
        wpt_alt = min(wpt_alt, alt) # make sure that new wp alt is not above current altitude
        wpt_alt = round(wpt_alt,0)


        idx = traf.id2idx(acid)
        latac = traf.lat[idx]
        lonac = traf.lon[idx]
        iafindex = acrte.wpname.index(iaf)
        disttoiaf = kwikdist(lat, lon, acrte.wplat[iafindex], acrte.wplon[iafindex])

        disttonewwp = kwikdist(latac, lonac, lat, lon)

        if abs(reqdist - (disttoiaf + disttonewwp)) > 1:
            print('replacewaypoint incorrect: ', reqdist, disttoiaf, disttonewwp, lat, lon)

        print('replacewaypoint: ', reqdist, disttoiaf + disttonewwp, disttoiaf, disttonewwp, lat, lon, latac, lonac,acrte.wplat[iafindex], acrte.wplon[iafindex] )


        newwp_name = f'DOGLEG{acid}'
        if newwp_name in acrte.wpname:
            acrte.delwpt(idx, newwp_name)
        # Route.addwptstack(f'ADDWPT {acid} {lat} {lon} ,{wpt_alt} , , , {iaf}')
        newwp_index = acrte.addwpt(idx, newwp_name, 0, lat, lon, alt= wpt_alt, beforewp=iaf) # must be in meters

        Route.direct(idx, newwp_name)

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
