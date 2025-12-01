
from collections import defaultdict
import pickle

import pandas as pd
from bluesky import network, stack, traf, sim


class PredictionHandler:


    @network.subscriber(topic='PREDICTION')
    def on_prediction_received(self, acid, wpt, wptime,flighttime, wptpredutc, parent_id, type, origin, work):
        """
        Each acid getting a new ETA will be added to aircraft needing to get a slot.
        """

        if self.aman_parent_id:
            return

        self.sim_id_parent = parent_id
        idxac = traf.id2idx(acid)
        estimatedcreatetime = wptime - flighttime
        if idxac == -1:
            if wpt in self.iafs:
                #determining errors at iaf
                lookahead = round(int(self.freezehorizon - flighttime) / 60)  # minutes
                abslookahead = lookahead
                if lookahead < 0:
                    lookahead = 0
                # print(acid, 'error should be generated')
                takeoff, dep_route, enroute, fir = self.errorgenerator.return_sample(acid, origin, lookahead=lookahead)
                if float(takeoff) != 0.0:
                    self.shiftflight.shift(acid, takeoff * 60)
                    #POPUP CODE

                    data = {'planningstate': 'ground', 'TP IAF': wptime, 'ETO_original':wptime, 'IAF': wpt, 'type': type, 'origin': '', 'LAf': '', 'count':0, 'Flighttime': flighttime, 'E_TO': takeoff, 'E_dep':dep_route, 'E_enroute':enroute, 'E_fir':fir, 'creation': sim.simt, 'lookahead':abslookahead}
                    self.Flights.loc[acid] = data

            elif acid in self.Flights.index:
                if '/RW' in wpt:
                    dest, runway = parse_destination(wpt)
                    data = {'planningstate': 'ground', 'TP ETA': wptime, 'runway':runway, 'type': type, 'origin': '', 'LAf': '','count':0, 'Flighttime': flighttime, 'minwork':work}

                elif self.firname in wpt:
                    data = {'FIR entry': wptime}

                elif 'ALTCROSS CLIMB' in wpt:
                    data = {'SID': wptime}

                elif 'ALTCROSS DESC' in wpt:
                    data = {}

                else:
                    print('something wrong with waypoints and prediction in aman')


                # Updates the existing row for acid
                for key, value in data.items():
                    self.Flights.at[acid, key] = value

                takeoff, dep_route, enroute, fir, abslookahead = 0, 0, 0, 0, 0  # to be disregarded later
            else:
                takeoff, dep_route, enroute, fir, abslookahead = 0,0,0,0,0# to be disregarded later
            self.not_spawned[acid].append((wpt, wptime,flighttime,estimatedcreatetime, wptpredutc, parent_id, type, origin, takeoff, dep_route, enroute, fir, abslookahead, work))

            # the above is future code for popups?

        elif acid in self.Flights.index:
            wptime = traf.ap.route[idxac].createtime + flighttime
            # print(f'{acid} at {wpt}')
            if wpt in self.iafs:
                # data = {'TP IAF': wptime, 'IAF': wpt , 'TPstate': 'updated iaf', 'ttlg': self.Flights.loc[acid,'EAT']-wptime}

                TMA = self.Flights.loc[acid, 'TMA']
                # 'TP ETA': wptime + TMA
                # data = {'TP IAF': wptime, 'IAF': wpt, 'TPstate': 'updated', 'TP ETA': wptime + TMA}

                data = {}

            elif '/RW' in wpt:
                dest, runway = parse_destination(wpt)
                idxac = traf.id2idx(acid)
                data = {'TP ETA': wptime, 'runway': runway, 'TPstate': 'updated including TMA'}

            elif self.firname in wpt:
                data = {'FIR entry': wptime} #time to fir entry from spawning

            elif 'ALTCROSS CLIMB' in wpt:
                data = {'SID': wptime}



            else:
                data = {}


            # Updates the existing row for acid

            for key, value in data.items():
                self.Flights.at[acid, key] = value

            # if '/RW' in wpt or ('TPstate' in data.keys() and data['TPstate'] == 'updated'):
            #     stack.stack('instruct_frozen')

        else:
            wptime = traf.ap.route[idxac].createtime + flighttime
            data = {'planningstate': 'new', 'runway': ''}


            if wpt in self.iafs:
                data = {'planningstate': 'new', 'TP IAF': wptime, 'IAF': wpt, 'type': type, 'origin': '', 'LAf': '', 'count': 0, 'swaps':0}

            elif '/RW' in wpt:
                dest, runway = parse_destination(wpt)
                data = {'planningstate': 'new', 'TP ETA': wptime, 'runway': runway, 'type': type, 'origin': '', 'LAf': '', 'count': 0, 'swaps':0}
            # print(acid,wpt,wptime)

            elif self.firname in wpt:
                data = {'FIR entry': wptime} #time to fir entry from spawning

            elif 'ALTCROSS CLIMB' in wpt:
                data = {'SID': wptime}


            # data['instruction'] = []
            if acid not in self.Flights.index:
                # Adds a new row for acid if it doesn't exist
                self.Flights.loc[acid] = {'runway': '', 'type': '', 'IAF': '', 'planningstate': '', 'origin': '', 'LAf': '', 'count': 0}
                self.Flights.loc[acid] = data
            else:
                # Updates the existing row for acid
                for key, value in data.items():
                    self.Flights.at[acid, key] = value


    # new aircraft spawned
    def create(self, n=1):
        """ Gets triggered everytime n number of new aircraft are created. """
        super().create(n)

        # Ensure this runs only in the main node.
        if traf.traf_parent_id and self.aman_parent_id is None:
            self.aman_parent_id = traf.traf_parent_id
            return
        if self.aman_parent_id:
            return

        for i in range(n):
            acid = traf.id[-1 - i]
            id = len(traf.id) - i
            if acid in self.not_spawned.keys():
                for prediction in self.not_spawned[acid]:
                    wpt, wptime, flighttime, estimatedcreatetime, wptpredutc, parent_id, type, origin, takeoff, dep_route, enroute, fir, abslookahead, work = prediction
                    wptime = sim.simt + flighttime

                    if wpt in self.iafs:
                        data = {'planningstate': 'new', 'TP IAF': wptime, 'ETO_original':wptime, 'IAF': wpt, 'type': type, 'origin': '', 'LAf': '', 'count':0, 'Flighttime': flighttime, 'E_TO': takeoff, 'E_dep':dep_route, 'E_enroute':enroute, 'E_fir':fir, 'creation': sim.simt, 'lookahead':abslookahead}

                    elif '/RW' in wpt:
                        dest, runway = parse_destination(wpt)
                        data = {'planningstate': 'new', 'TP ETA': wptime, 'runway':runway, 'type': type, 'origin': '', 'LAf': '','count':0, 'Flighttime': flighttime, 'minwork':work}

                    elif self.firname in wpt:
                        data = {'FIR entry': wptime}

                    elif 'ALTCROSS CLIMB' in wpt:
                        data = {'SID': wptime}

                    elif 'ALTCROSS DESC' in wpt:
                        data = {}

                    else:
                        print('something wrong with waypoints and prediction in aman')

                    # data['instruction'] = []
                    #add data to dataframe
                    if acid not in self.Flights.index:
                        # Adds a new row for acid if it doesn't exist
                        self.Flights.loc[acid] = {'runway': '', 'type': '', 'IAF': '', 'planningstate': '', 'origin': '', 'LAf': ''}
                        self.Flights.loc[acid] = data

                    else:
                        # Updates the existing row for acid
                        for key, value in data.items():
                            self.Flights.at[acid, key] = value
            else:
                print('popup created, should manage dataframe entry')

    @stack.command
    def usecache_aman(self):
        if not self.aman_parent_id:
            cache = self.open_cache()
            self.not_spawned = cache
            self.regenerate_errors()
            print('regenerate errors?')
            self.predictions_cache = cache
            self.use_cache = True


    def open_cache(self):
        try:
            # Open and load the predictions_cache file
            with open('predictions_cache.pkl', 'rb') as f:
                predictions = pickle.load(f)
            # Open and load the commands file
        except FileNotFoundError:
            # If either file is missing, return None for both
            return None, None
        return predictions


def parse_destination(wpt_name):
    try:
        # Create an instance of WptArg parser
        parser = stack.argparser.WptArg()

        # Parse the command string
        argstring = wpt_name + ", more arguments if any"
        parsed_name, remaining_string = parser.parse(argstring)

        # Check if the parsed name is a runway (look for the '/' pattern in parsed_name followed by "RW")
        if '/RW' in parsed_name:
            airport, runway = parsed_name.split('/')
            return airport, runway  # Return the airport and runway
        else:
            return wpt_name, None  # Return None if it's not a runway
    except ValueError:
        return None, None  # Return None if an error occurs, indicating not a valid waypoint or runway

