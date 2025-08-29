# amanatc.py
from textwrap import shorten



from bluesky import core, stack, traf, sim, HOLD
# from plugins.AMANtwo import AMAN  # Import the global reference from AMANtwo
from bluesky.core import plugin
from bluesky.plugins.sectorcount import update
from bluesky.test.tcp.test_simple import test_pos
from bluesky.tools.aero import kts, ft, nm
import pandas as pd
from bluesky.tools.geo import kwikpos, qdrpos, kwikdist
from bluesky.tools.geo import kwikqdrdist
from bluesky.traffic.route import Route
import math


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
        self.mach_threshold = 0
        self.handover_alt = 260.*100
        self.aman.Flights['instruction'] = None
        self.aman.Flights['AMANstate'] = ' '
        self.aman.Flights['TPstate'] = ' '
        self.aman.Flights['count'] = 0
        self.aman.Flights['count'] = self.aman.Flights['count'].astype(int)
        self.aman.Flights['instruction'] = self.aman.Flights['instruction'].astype(object)
        self.aman.Flights['TPstate'] = self.aman.Flights['TPstate'].astype(object)
        self.aman.Flights['AMANstate'] = self.aman.Flights['AMANstate'].astype(object)
        self.aman.Flights['tp_time'] = None
        self.aman.Flights['selspd'] = None
        self.aman.Flights['dogleg'] = None
        self.aman.Flights['dogleg'] = self.aman.Flights['dogleg'].astype(bool)
        self.aman.Flights['direct'] = None
        self.aman.Flights['holding'] = None
        self.aman.Flights['earliest'] = False


    def reset(self):
        super().reset()
        self.aman = plugin.Plugin.plugins['AMANTWO'].imp.AMAN
        self.aman.Flights['instruction'] = None
        self.aman.Flights['AMANstate'] = ' '
        self.aman.Flights['TPstate'] = ' '
        self.aman.Flights['count'] = 0
        self.aman.Flights['count'] = self.aman.Flights['count'].astype(int)



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
                for acid, row in frozen_flights.iterrows():
                    # try:
                    if pd.isna(row['ttlg']):
                        continue
                    if row.get('TPstate') == 'busy' or row.get('TPstate') == 'instructed':
                        continue
                    else:

                        required = self.instruction_required(acid,row)
                        self.aman.Flights.loc[acid, 'required'] = required
                        if required:
                            # print(self.ac_instructions)
                            # self.instructions.append(*self.ac_instructions)
                            # stack.stack(*self.ac_instructions)
                            # stack.stack(f'ECHO instruction stacked {acid}')
                            self.aman.Flights.loc[acid, 'TPstate'] = 'instructed'
                            self.aman.Flights.at[acid, 'count'] +=1
                stack.stack(*self.instructions)

                frozen_flights = self.aman.Flights[self.aman.Flights['planningstate'] == 'frozen']
                busy_exists = (frozen_flights['TPstate'] == 'busy').any()
                instructed_exists = (frozen_flights['TPstate'] == 'instructed').any()
                # required_exists = (
                #     frozen_flights['required'].fillna(False).astype(bool).any()
                #     if 'required' in frozen_flights.columns else False)
                required_exists = (frozen_flights['required'].astype('boolean').fillna(False).any())


                self.aman.totwohtml()
                self.aman.Flights.to_pickle('flights.pkl')

                # break
                if not busy_exists and not required_exists and not instructed_exists:
                    # break

            # break only when all aircraft tp state is updated, and required is false
            # calculate workload only for last added instructions
                    if self.ff:
                        sim.fastforward()
                    elif self.rtf >1.:
                        sim.dtmult(self.rtf)
                    elif not self.ff and self.rtf<=1.:
                        sim.op()

            #if no instruction required in dataframe
            # set ff



    @stack.command
    def instruction_required(self,acid, row = None):
        if row is None:
            row = self.aman.Flights.loc[acid]
        ttlg = row['ttlg']
        idx = traf.id2idx(acid)
        alt = traf.alt[idx]/ft
        count = self.aman.Flights.loc[acid,'count']
        self.ac_instructions = []
        #nearby aircraft.
        to_eto = self.aman.Flights.loc[acid, 'ETO IAF'] - sim.simt
        if to_eto < self.aman.nearby_threshold:
            if ttlg >= self.aman.early_approach_margin:
                # holding
                print('holding')
                self.aman.Flights.loc[acid, 'holding'] = True

        # uco aircraft
        elif alt <= self.handover_alt:
            #speed up
            if ttlg < 0:
                if row['earliest'] == True:
                    return False

                if ttlg <= -self.aman.late_approach_margin:
                    self.shorten(acid, ttlg)
                    print(f'{acid} shorten 1')
                    return True
                elif ttlg + self.aman.approach_aim  <= - self.aman.tight_margin and count <= self.aman.tighter_count:
                    self.shorten(acid, ttlg)
                    print(f'{acid} shorten 2 ')
                    return True

            #delay
            elif ttlg>0:
                if ttlg >= self.aman.early_approach_margin:  # if ttlg is larger than 120: delay (120 secs must be found)
                    self.delay(acid, ttlg)
                    print(f'{acid} delay 1')
                    return True

                elif ttlg + self.aman.approach_aim > self.aman.tight_margin and count <= self.aman.tighter_count: # if ttlg + aim (generally 90 secs early) is larger than
                    if abs(row['selspd'] - row['min_casdesc']) < 1: # if the aircraft speed is nearly at minimum, or at minimum, then minor speed adjustments must never be done, can prevent infinite loop
                        return False
                    self.delay(acid, ttlg, minor = True)
                    print(f'{acid} delay 2, ttlg: {ttlg}, {self.aman.approach_aim}, {self.aman.tight_margin}')
                    return True


        # at adjacent center
        elif alt > self.handover_alt:
            if ttlg <= -self.aman.late_adjacent_threshold:
                if row['earliest'] == True:
                    return False
                self.shorten(acid, ttlg, minor = True)
                print(f'{acid} shorten adjacent')
                return True
            elif ttlg >= self.aman.early_adjacent_threshold:
                idx = traf.id2idx(acid)
                selspd = traf.selspd[idx] / kts
                if selspd > 4.:
                    self.delay(acid, ttlg)
                    print(f'{acid} delay adjacent')
                    return True
                elif pd.isna(row['selspd']):
                    self.delay_mach(acid)
                    print(f'{acid} delay mach')
                    return True

        return False


    # done?
    def delay(self, acid, ttlg, minor = False):
        idx = traf.id2idx(acid)
        selspd = traf.selspd[idx] / kts
        minclean = self.aman.Flights.loc[acid, 'min_casdesc']
        required_spd = round(self.reqspd(acid, ttlg, idx), 0)

        if selspd > minclean and required_spd > minclean:
                selspd = required_spd
                self.instructions.append(f'SPD {acid} {selspd}')
                self.aman.Flights.loc[acid, 'selspd'] = selspd
        elif selspd > minclean and required_spd <= minclean:
            selspd = minclean
            self.instructions.append(f'SPD {acid} {selspd}')
            self.aman.Flights.loc[acid, 'selspd'] = selspd
            # if minor == False:
            #     self.dogleg(acid,ttlg)

        else:
            selspd = minclean
            if minor == False:
                self.dogleg(acid,ttlg)









    # done?
    def delay_mach(self, acid):
        mach = self.aman.mach_reduction
        self.instructions.append(f'REDUCE_MACH {acid} {mach}')
        self.aman.Flights.at[acid, 'selspd'] = mach
        print(mach)



    #done?
    @stack.command
    def dogleg(self, acid, ttlg):

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
        print(self.instructions)



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

            else:
                # shorter using dogleg logic
                self.replacewaypoint(acid, direct_dist, reqdist, trackmiles, direct_qdr)
                self.aman.Flights.at[acid, 'dogleg'] = True


        if speed:
            idx = traf.id2idx(acid)
            reqspd = round(self.reqspd(acid, ttlg, idx),0)
            selspd = traf.selspd[idx] / kts

            if reqspd < selspd:
                print('check speed up function')
                return

            elif reqspd > selspd:

                # find out max speed from mach
                maxspd = self.aman.Flights.loc[acid]['max_casdesc']
                if reqspd > maxspd:
                    self.instructions.append(f'SPD {acid} {maxspd}')
                    self.aman.Flights.loc[acid, 'required'] = False
                    self.aman.Flights.loc[acid, 'selspd'] = maxspd
                    self.aman.Flights.loc[acid, 'earliest'] = True


                else:
                    self.instructions.append(f'SPD {acid} {reqspd}')
                    self.aman.Flights.loc[acid, 'selspd'] = reqspd


    def directiaf(self, acid):

        iaf = self.aman.Flights.loc[acid, 'IAF']
        self.instructions.append(f'DIRECT {acid} {iaf}')
        self.aman.Flights.loc[acid, 'direct'] = True


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

        hypothenuse = (reqdist**2 + direct_dist)/(2*reqdist)
        opposing = reqdist - hypothenuse
        if opposing < 0:
            print('wrong replacewaypoint')
            return
        alpha = math.degrees(math.atan2(opposing, direct_dist))

        print(reqdist, direct_dist)
        print(hypothenuse, opposing, alpha)
        lat,lon = qdrpos(traf.lat[idx], traf.lon[idx], direct_dist+alpha, hypothenuse)


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


#old method
        # wpt_alt = (alt+iaf_alt)/2
        wpt_alt = math.tan(math.radians(self.aman.descent_angle)) * opposing*nm

        wpt_alt = wpt_alt + iaf_alt
        wpt_alt = min(wpt_alt, alt) # make sure that new wp alt is not above current altitude
        wpt_alt = round(wpt_alt/ft,0)


        idx = traf.id2idx(acid)
        latac = traf.lat[idx]
        lonac = traf.lon[idx]
        iafindex = acrte.wpname.index(iaf)
        disttoiaf = kwikdist(lat, lon, acrte.wplat[iafindex], acrte.wplon[iafindex])

        disttonewwp = kwikdist(latac, lonac, lat, lon)

        if abs(reqdist - (disttoiaf + disttonewwp)) > 1:
            print('replacewaypoint incorrect: ', reqdist, disttoiaf, disttonewwp, lat, lon)

        print('replacewaypoint: ', reqdist, disttoiaf + disttonewwp, disttoiaf, disttonewwp, lat, lon, latac, lonac,acrte.wplat[iafindex], acrte.wplon[iafindex] )

        self.instructions.append(f'ADDWPT {acid} {lat} {lon} ,{wpt_alt} , , , {iaf}')
        acrte = Route._routes[acid]
        newwp = acrte.wpname[iaf_index-1]
        # print(newwp)
        # stack.stack(f'ECHO {newwp}')
        self.instructions.append(f'DIRECT_index {acid} {iaf_index}')
        # print(acrte.wpname)




    @stack.command
    def direct_index(self,acid,iaf_index):

        acrte = Route._routes[acid]
        # print(acrte.wpname)
        newwp = acrte.wpname[int(iaf_index)] # iaf index goes +1 when waypoint is added before
        # stack.stack(f'ECHO {acid} {newwp}')
        stack.stack(f'DIRECT {acid} {newwp}')


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

    def storeinstruction(self,acid, instruction):
        if type(instruction) == float:
            instruction = round(instruction,2)
        if type(self.aman.Flights.loc[acid]['instruction']) == list:
            self.aman.Flights.at[acid, 'instruction'].append(instruction)
        else:
            self.aman.Flights.at[acid, 'instruction'] = [instruction]

        self.aman.Flights.at[acid, 'TPstate'] = 'busy'


        # if type(self.aman.Flights.loc[acid,'tp_time']) == list:
        #     self.aman.Flights.loc[acid, 'tp_time'].append(sim.simt)
        #
        # else:
        #     self.aman.Flights.at[acid, 'tp_time'] = [sim.simt]


    @stack.command
    def miles(self,acid):
        acrte = Route._routes[acid]
        idx = traf.id2idx(acid)

        wpdirfrom = []
        wpdistto = []

        qdr, dist = kwikqdrdist(traf.lat[idx], traf.lon[idx],
                                acrte.wplat[acrte.iactwp], acrte.wplon[acrte.iactwp])

        wpdirfrom.append(qdr)  # [deg]
        wpdistto.append(dist)  # [nm]  distto is in nautical miles

        for i in range(acrte.iactwp, len(acrte.wpname) - 1):
            qdr,dist = kwikqdrdist(acrte.wplat[i]  ,acrte.wplon[i],
                                acrte.wplat[i+1],acrte.wplon[i+1])
            wpdirfrom.append(qdr)    # [deg]
            wpdistto.append(dist) #[nm]  distto is in nautical miles
            # print(acrte.wpname[i])
            if acrte.wpname[i+1] == self.aman.Flights.loc[acid, 'IAF']:
                direct_qdr, direct_dist = kwikqdrdist(traf.lat[idx], traf.lon[idx],
                                        acrte.wplat[i+1], acrte.wplon[i+1])

                break
        trackmiles = sum(wpdistto)
        # print(trackmiles, direct_qdr, direct_dist)

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
            casdesc = 250. # clear basic number to figure out that this is standard
        max_casdesc = round(float(casdesc) + self.aman.max_speedup)
        min_casdesc = round(float(casdesc) - self.aman.max_slowdown)
        self.aman.Flights.at[acid, 'casdesc'] = float(casdesc)
        self.aman.Flights.at[acid, 'max_casdesc'] = max_casdesc
        self.aman.Flights.at[acid, 'min_casdesc'] = min_casdesc




    @stack.command
    def holding(self, acid, direction="R"):
        """
        Holding pattern voor exact ttlg seconden op het opgegeven iaf-fix.
        """
        iaf =self.aman.Flights.loc[acid, 'IAF']

        ttlg = self.aman.Flights.loc[acid, 'ttlg']
        to_eto = self.aman.Flights.loc[acid, 'ETO IAF'] - sim.simt
        acid = acid.upper()
        iaf = iaf.upper()
        ttlg = float(ttlg)
        if to_eto:
            to_eto = float(to_eto) - 30 # to be able to do the holding properly before reaching the IAF
        else:
            to_eto = 0.0
        turn_time = 60.0
        total_turn_time = 2 * turn_time

        # Compute current selected heading and add 180° for relative turn
        idx = traf.id2idx(acid)
        current_hdg = traf.hdg[idx]
        # Determine turn direction: right (R) or left (L)
        turn_sign = 1 if direction.upper() == "R" else -1
        turn_angle = 90.0 * turn_sign
        # Initial 90° turn to start hold
        first_hdg = (current_hdg + turn_angle) % 360.0

        stack.stack(f"DELAY {to_eto} BANK {acid} 40")
        stack.stack(f"DELAY {to_eto} HDG {acid} {first_hdg:.1f}")
        # Complete racetrack: 180° back inbound
        second_hdg = (first_hdg + turn_angle) % 360.0
        stack.stack(f"DELAY {to_eto + 15} HDG {acid} {second_hdg:.1f}")
        # Final 90° turn before direct to IAF
        direct_turn_hdg = (second_hdg + turn_angle) % 360.0

        stack.stack(f"DELAY {to_eto + 0.5 * ttlg} HDG {acid} {direct_turn_hdg:.1f}")
        stack.stack(f"DELAY {to_eto + 0.5 * ttlg} DIRECT {acid} {iaf}")

        stack.stack(f"DELAY {to_eto + 0.5 * ttlg + 90} BANK {acid} 25")

        self.storeinstruction(acid, "hold")


        self.aman.Flights.at[acid, 'AMANstate'] = "holding"
        self.aman.Flights.at[acid, 'count'] += 1

