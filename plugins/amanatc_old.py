# amanatc.py
from bluesky import core, stack, traf, sim
# from plugins.AMANtwo import AMAN  # Import the global reference from AMANtwo
from bluesky.core import plugin
from bluesky.test.tcp.test_simple import test_pos
from bluesky.tools.aero import kts, ft
import pandas as pd
from bluesky.tools.geo import kwikpos, qdrpos
from bluesky.tools.geo import kwikqdrdist
from bluesky.traffic.route import Route
import math

#
# def init_plugin():
#     config = {
#         'plugin_name': 'amanATC',
#         'plugin_type': 'sim'
#     }
#     # Create an instance of the class below so BlueSky recognizes it as a plugin
#     atc_plugin = ATC()
#     return config

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


    def reset(self):
        super().reset()
        self.aman = plugin.Plugin.plugins['AMANTWO'].imp.AMAN
        self.aman.Flights['instruction'] = None
        self.aman.Flights['AMANstate'] = ' '
        self.aman.Flights['TPstate'] = ' '
        self.aman.Flights['count'] = 0
        self.aman.Flights['count'] = self.aman.Flights['count'].astype(int)



    #misschien deze aansturen na elke time update van aman
    @stack.command
    def instruct_frozen(self):
        """
        Loops over frozen flights and issues instructions based on TTLG range:
          1) [-120, 120]: speed instruction
          2) [120, 240]: speed + dogleg
          3) > 240: speed + holding
          4) < -120: direct
        """
        # Get flights that are frozen
        frozen_flights = self.aman.Flights[self.aman.Flights['planningstate'] == 'frozen']
        # here is the possibility of filtering frozen flights for ttlg>approach margin
        if self.aman.instruct:
            sim.hold()
            for acid, row in frozen_flights.iterrows():
                # try:
                if pd.isna(row['ttlg']):
                    continue  # skip if TTLG is NaN or missing
                elif pd.isna(row['AMANstate']):
                    self.instruct(acid, ttlg=row['ttlg'])

                elif row['TPstate'] == 'updated':
                    self.instruct(acid, ttlg=row['ttlg'])

                elif row['AMANstate'] == 'direct not enough':
                    self.instruct(acid, ttlg=row['ttlg'])


                else:
                    continue


            if not (self.aman.Flights['TPstate'] == 'busy').any():
                sim.fastforward()

                # except Exception as e:
                #     # log the error and keep going
                #     print(f"Error processing flight {acid}: {e}")
                #     print('instruction error at:')
                #     print(acid, row['AMANstate'])
                #
                #     continue


    @stack.command
    def instruct(self,acid, ttlg=None):
        idx = traf.id2idx(acid)
        alt = traf.alt[idx]/ft

        #functions for filtering aircraft within FIR
        # inside    = areafilter.checkInside(name, traf.lat, traf.lon, traf.alt)
        # ids       = set(np.array(traf.id)[inside])

        if ttlg is None:
            ttlg = self.aman.Flights.loc[acid, 'ttlg']
        to_eto = self.aman.Flights.loc[acid, 'ETO IAF'] - sim.simt
        if to_eto < self.aman.nearby_threshold:
            # print('only hold possible')
            amanstate = 'nearby'
            self.aman.Flights.at[acid, 'AMANstate'] = amanstate
            if ttlg >= self.aman.early_approach_margin and self.aman.Flights.loc[acid, 'TPstate'] == 'updated':
                # self.hold(acid,ttlg)
                print('hold')
                self.holding(acid)


        elif alt <=self.handover_alt:
            if ttlg <= -self.aman.late_approach_margin: # if ttlg is less than -120: shorten route (flighttime must be reduced)
                # 4) Direct
                self.shorten(acid, ttlg)
            elif ttlg >= self.aman.early_approach_margin: # if ttlg is larger than 120: delay (120 secs must be found)
                self.delay(acid, ttlg)


            #minor speed changes which usually are done
            #               110
            elif ttlg + self.aman.approach_aim > self.aman.tight_margin: # if ttlg + aim (generally 90 secs early) is larger than
                self.delay(acid, ttlg, minor = True)
                #           70
            elif ttlg + self.aman.approach_aim  < - self.aman.tight_margin:

                self.shorten(acid, ttlg)

        elif alt > self.handover_alt: # count + 1 for calling adjacent center?
            if ttlg <= -self.aman.late_adjacent_threshold:
                self.shorten(acid, ttlg)
            elif ttlg >= self.aman.early_adjacent_threshold:
                idx = traf.id2idx(acid)
                selspd = traf.selspd[idx] / kts
                if selspd > 4.:
                    self.delay(acid, ttlg)
                else:
                    self.delay_mach(acid)


    # def hold(self, acid, ttlg):



    def delay(self, acid, ttlg, minor = False):
        idx = traf.id2idx(acid)
        selspd = traf.selspd[idx]/kts
        minclean = 200.

        #todo!!!
        # minclean per type
        amanstate = self.aman.Flights.loc[acid]['AMANstate']

        if selspd > 4. and amanstate != 'minclean': #essentially if cas regime
            required_spd = self.reqspd(acid,ttlg, idx)
            if required_spd > selspd:
                print(f'wrong calc for speed instruction, {acid} {ttlg} {required_spd} {selspd} ')
            if required_spd > minclean:
                self.aman.Flights.at[acid, 'count'] += 1
                # stack.stack(f'SETDESCENTSPD {acid} {required_spd}')
                stack.stack(f'SPD {acid} {required_spd}')
                stack.stack(f'ECHO {acid} {required_spd}')
                instruction = round(required_spd,0)
                amanstate = 'reduced_speed'
                # print(acid, required_spd, selspd)
            else:
                self.aman.Flights.at[acid, 'count'] += 1
                # stack.stack(f'SETDESCENTSPD {acid} {minclean}')
                stack.stack(f'SPD {acid} {minclean}')
                stack.stack(f'ECHO {acid} {minclean}')
                instruction = round(minclean,0)
                amanstate = 'minclean'
                # set status to minspd
                # if minor == False:
                #     amanstate = 'minclean + dogleg'
                #
                #     self.dogleg(acid, minclean, required_spd)

            self.storeinstruction(acid, instruction)
        elif selspd >4. and amanstate == 'minclean' and minor == False:
            # print(acid, ttlg)
            instruction = round(self.dogleg(acid, ttlg),0)


            amanstate = 'minc dogl'



            self.storeinstruction(acid, instruction)
        self.aman.Flights.at[acid, 'AMANstate'] = amanstate


    def delay_mach(self, acid):
        self.aman.Flights.at[acid, 'count'] += 1 # maybe +2 due to required phone call to adjacent center?
        mach = self.aman.mach_reduction
        stack.stack(f'REDUCE_MACH {acid} {mach}')
        amanstate = 'mach_reduced'
        self.storeinstruction(acid, round(mach,2))
        self.aman.Flights.at[acid, 'AMANstate'] = amanstate



    def dogleg(self, acid, ttlg):
        self.aman.Flights.at[acid, 'count'] += 1
        trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)
        # reqdist = trackmiles*(minclean/required_spd)
        reqdist = self.reqdist(acid, ttlg, trackmiles)
        if reqdist < trackmiles:
            print('dogleg makes route shorter, please validate method')
            return 9999
        self.replacewaypoint(acid, direct_dist, reqdist, trackmiles, direct_qdr)
        return reqdist - trackmiles



    @stack.command
    def shorten(self, acid, ttlg):
        if type(ttlg) == str:
            ttlg = int(ttlg)

        currentstate = self.aman.Flights.loc[acid]['AMANstate']
        amanstate = currentstate
        trackmiles, direct_qdr, direct_dist = self.findtrackmiles(acid)
        if currentstate not in ['direct not enough', 'max_casdesc']:

            if abs(trackmiles - direct_dist) < 0.1:
                amanstate = 'direct not enough'
                # instruction =
                # self.storeinstruction(acid, round(instruction, 1))
            else:

                reqdist = self.reqdist(acid, ttlg, trackmiles)
                if reqdist < direct_dist:
                    reqdist = direct_dist
                    amanstate = 'direct not enough'
                    self.directiaf(acid)
                else:
                    amanstate = 'direct'
                    self.replacewaypoint(acid, direct_dist, reqdist, trackmiles, direct_qdr)

        if currentstate == 'direct not enough':

            idx = traf.id2idx(acid)
            reqspd = round(self.reqspd(acid, ttlg, idx),0)
            selspd = traf.selspd[idx] / kts

            if reqspd < selspd:
                print('check speed up function')
                instruction = 99999
                self.storeinstruction(acid, instruction)

            elif reqspd > selspd:

                # find out max speed from mach
                maxspd = self.aman.Flights.loc[acid]['max_casdesc']
                if reqspd > maxspd:
                    self.aman.Flights.at[acid, 'count'] += 1
                    # stack.stack(f'SETDESCENTSPD {acid} {minclean}')
                    stack.stack(f'SPD {acid} {maxspd}')
                    stack.stack(f'ECHO incrdesc_max {acid} {maxspd}')
                    instruction = maxspd
                    amanstate = 'max_casdesc'
                else:
                    self.aman.Flights.at[acid, 'count'] += 1
                    # stack.stack(f'SETDESCENTSPD {acid} {minclean}')
                    stack.stack(f'SPD {acid} {reqspd}')
                    stack.stack(f'ECHO incrdesc {acid} {reqspd}')
                    instruction = reqspd
                    amanstate = 'direct not enough'


            self.storeinstruction(acid, instruction)


        self.aman.Flights.at[acid, 'AMANstate'] = amanstate

    def directiaf(self, acid):
        instruction = 'direct'
        iaf = self.aman.Flights.loc[acid, 'IAF']
        stack.stack(f'DIRECT {acid} {iaf}')
        self.storeinstruction(acid, instruction)

        self.aman.Flights.at[acid, 'count'] += 1

    def replacewaypoint(self, acid, direct_dist, reqdist, trackmiles, direct_qdr):
        instruction = reqdist - trackmiles
        acrte = Route._routes[acid]

        idx = traf.id2idx(acid)

        # iaf = self.findiaf(acid)
        iaf = self.aman.Flights.loc[acid, 'IAF']

        h = math.sqrt( (reqdist*0.5)**2 - (direct_dist*0.5)**2 )

        alpha = 180*math.atan(h/direct_dist)/math.pi

        lat, lon = qdrpos(traf.lat[idx], traf.lon[idx], direct_qdr +alpha, 0.5*reqdist)
        # print(lat, lon)
        # print(h, alpha)
        # print(traf.lat[idx], traf.lon[idx])
        # print(0.5*reqdist)

        iaf_index = acrte.wpname.index(iaf)
        alt = traf.alt[idx]
        iaf_alt = acrte.wpalt[iaf_index]
        wpt_alt = (alt+iaf_alt)/2
        # print(iaf_alt)
        # print(alt)
        wpt_alt = round(wpt_alt/ft,0)
        stack.stack(f'ADDWPT {acid} {lat} {lon} ,{wpt_alt} , , , {iaf}')
        acrte = Route._routes[acid]
        newwp = acrte.wpname[iaf_index-1]
        # print(newwp)
        # stack.stack(f'ECHO {newwp}')
        stack.stack(f'DIRECT_index {acid} {iaf_index}')
        # print(acrte.wpname)


        # for baksteen behaviour: two options: - direct to intermediate, or intermediate with alt constraint (= curr alt + iaf alt /2)

        #
        # print(trackmiles, direct_dist, reqdist, h, alpha)
        # print()
        # stack.stack(f'DIRECT {acid} {acrte}')

        self.storeinstruction(acid, round(instruction,1))

        self.aman.Flights.at[acid, 'count'] += 1 #should be two!!


    @stack.command
    def direct_index(self,acid,iaf_index):

        acrte = Route._routes[acid]
        # print(acrte.wpname)
        newwp = acrte.wpname[int(iaf_index)] # iaf index goes +1 when waypoint is added before
        # stack.stack(f'ECHO {acid} {newwp}')
        stack.stack(f'DIRECT {acid} {newwp}')


    def reqspd(self,acid, ttlg, idx):
        aim_ttlg = ttlg + self.aman.approach_aim
        to_eto = self.aman.Flights.loc[acid]['ETO IAF']-sim.simt
        # idx = traf.id2idx(acid)
        selspd = traf.selspd[idx]
        return (selspd - (aim_ttlg/to_eto)*selspd)/kts

    def reqdist(self,acid, ttlg, planned_dist):
        aim_ttlg = ttlg + self.aman.approach_aim
        to_eto = self.aman.Flights.loc[acid]['ETO IAF']
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
        print(trackmiles, direct_qdr, direct_dist)

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
                print(acid, acrte.wpname, trackmiles )

        # Route.before(acid, iaf, 'ADDWPT', )

    # def get_coordinate_along_route(ac_lat, ac_lon, iaf_lat, iaf_lon,
    #                                direct_distance, wp_lats, wp_lons,
    #                                route_distance, required_distance):
    #
    #
    #
    #     return newwp_lat, newwp_lon

    # @stack.command
    # def dogleg(self, acid):
    #     """
    #     Adds a small vector/dogleg in the route to absorb extra time.
    #     """
    #     print(f"Dogleg for {acid}")
    #     # Example: a heading change or waypoint insertion
    #     # stack.stack(f"DIRECT {acid} NEWWAYPOINT")



    @stack.command
    def dct(self, acid, ttlg):
        """
        Shortcut or direct routing to help the aircraft catch up if behind schedule.
        """
        print(f"Direct for {acid}")
        amanstate = 'direct'
        self.aman.Flights.at[acid, 'AMANstate'] = amanstate
        # Example: a direct to final or to a closer waypoint
        # stack.stack(f"DIRECT {acid} SHORTCUT_FIX")

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


    # @stack.command
    # def printtraf(self, acid, attrib):
    #     idx = traf.id2idx(acid)
    #     arr = getattr(traf, attrib, None)
    #     if arr is None:
    #         stack.stack(f"ECHO Attribute {attrib} not found")
    #         return
    #
    #     value = arr[idx]
    #     if attrib in ['tas', 'cas', 'gs']:
    #         kts = 0.514444  # 1 knot = 0.514444 m/s
    #         value /= kts
    #     stack.stack(f"ECHO {value}")
    #
    # @stack.command
    # def printap(self, acid, attrib):
    #     idx = traf.id2idx(acid)
    #     arr = getattr(traf.ap, attrib, None)
    #     if arr is None:
    #         stack.stack(f"ECHO Attribute {attrib} not found")
    #         return
    #
    #     value = arr[idx]
    #     if attrib in ['tas', 'cas', 'gs']:
    #         kts = 0.514444  # 1 knot = 0.514444 m/s
    #         value /= kts
    #     stack.stack(f"ECHO {value}")
    #
    #
    # @stack.command
    # def determine_delay_options(self,acid):
    #     #
    #     # if mach_crossover:
    #     if self.crossover == None:
    #         self.init_crossover()
    #     else:
    #         idx = traf.id2idx(acid)
    #         phase = self.crossover.flight_phase[idx]
    #         print(phase)
    #
    # def update_all_phases(self):
    #     for idx in len(self.crossover.flight_phase):
    #         phase = self.crossover.flight_phase[idx]
    #         acid = traf.idx
    #
    #         self.aman.Flights.at[acid, 'phase'] = phase
    #
    # def init_crossover(self):
    #
    #     try:
    #         self.crossover = plugin.Plugin.plugins['MACH_CROSSOVER'].imp.CROSSOVER
    #     except:
    #         self.crossover = None

    # #misschien deze aansturen na elke time update van aman
    # @stack.command
    # def instruct_frozen(self):
    #     """
    #     Loops over frozen flights and issues instructions based on TTLG range:
    #       1) [-120, 120]: speed instruction
    #       2) [120, 240]: speed + dogleg
    #       3) > 240: speed + holding
    #       4) < -120: direct
    #     """
    #     # Get flights that are frozen
    #     frozen_flights = self.aman.Flights[self.aman.Flights['planningstate'] == 'frozen']
    #
    #     for acid, row in frozen_flights.iterrows():
    #
    #         if pd.isna(row['ttlg']):
    #             continue  # skip if TTLG is NaN or missing
    #         else:
    #
    #             self.instruct(acid,row)
    #
    # @stack.command
    # def instruct(self,acid, row = None):
    #     if row is None:
    #         row = self.aman.Flights[acid]
    #     ttlg = row['ttlg']  # time to lose or gain
    #
    #     if ttlg < -self.aman.approach_margin:
    #         # 4) Direct
    #         self.direct(acid, ttlg)
    #     elif ttlg > self.aman.approach_margin:
    #
    #         self.speed_instruction(acid,row)
    #
    #
    # @stack.command
    # def speed_instruction(self, acid, row):
    #     """
    #     Issues a speed instruction to the given aircraft.
    #     You can base the speed on how much time needs to be gained or lost (ttlg).
    #     """
    #     ttlg = row['ttlg']
    #     # print(f"Speed instruction for {acid}, TTLG={ttlg}")
    #     # Example: if you need to lose time, slow down; if you need to gain time, speed up
    #     # This is just a placeholder. Replace with your logic.
    #     # stack.stack(f"SPD {acid} 220")
    #     idx = traf.id2idx(acid)
    #     selspd = traf.selspd[idx]/kts
    #     minclean = 200.
    #     if selspd > 4.: #essentially if cas regime
    #         required_spd = self.reqspd(acid,row)
    #         if required_spd > minclean:
    #             stack.stack(f'SETDESCENTSPD {acid} {required_spd}')
    #             print(acid, required_spd, selspd)
    #         else:
    #             stack.stack(f'SETDESCENTSPD {acid} {minclean}')
    #             print(acid, minclean, required_spd, selspd)
    #             # percentage_left =
    #
    #
    #





