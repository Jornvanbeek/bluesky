# """
# The Arrival Manager (AMAN) plugin is designed to efficiently allocate arrival slots for aircraft based on
# their estimated times of arrival (ETAs) while ensuring necessary separation times. It dynamically updates
# air traffic every 5 seconds around designated areas around airports based on ETAs to anticipate aircraft arrivals.
# """
#
# from bluesky import core, stack, traf, navdb, net, network, sim
# from bluesky.tools.areafilter import Circle
# from bluesky.network.common import GROUPID_SIM
# from datetime import datetime
#
# from collections import defaultdict
# from plugins.RunwayConfigurations import RunwayConfiguration
#
#
# def init_plugin():
#     """Initializes the plugin and creates an instance of the ArrivalManager."""
#     AMAN = ArrivalManager()
#
#     # Configuration for the plugin, specifying its name and type.
#     config = {
#         'plugin_name': 'AMAN',
#         'plugin_type': 'sim'
#     }
#
#     return config
#
#
# class ArrivalManager(core.Entity):
#     """
#     Manages arrival logic for the Arrival Manager, assigning arrival slots
#     based on the estimated time of arrival at the destination waypoint.
#
#     Attributes:
#         acids_allocated (dict): Maps each destination to a dict that maps aircraft IDs to their allocated runway.
#         ETAs (dict): Maps each destination to a dict that maps aircraft IDs to their estimated times of arrival.
#         arrival_slots (dict): Maps each destination to a dict that maps aircraft IDs to their assigned arrival slots.
#         ATAs (dict): Maps each destination to a dict that maps aircraft IDs to their actual times of arrival.
#         separation_times (dict): Maps each destination to a dict that maps aircraft IDs to their separation times.
#         aircraft_in_database (dict): Maps each airport to a dict that maps aircraft IDs to their designated runways.
#         aman_area (dict): Stores the area around an airport where the aman will be initialised.
#         acid_to_get_slot (set): Set of aircraft IDs that need to receive an arrival slot.
#     """
#
#     def __init__(self):
#         super().__init__()
#
#         # The following four dictionaries are related by index
#         self.acids_allocated = defaultdict(lambda: defaultdict(list))
#         self.ETAs = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
#         self.arrival_slots = defaultdict(lambda: defaultdict(list))
#         self.ATAs = defaultdict(lambda: defaultdict(list))
#         self.separation_times = defaultdict(lambda: defaultdict(list))
#
#         # The aircraft in each airport will give the runway in which they will land
#         self.aircraft_in_database = defaultdict(lambda: defaultdict(str))
#
#         # Dictionary providing the delta_t of a specific flight(acid) allocated to a runway at an airport
#         # airports > runways > aircrafts > delta_t
#         self.delta_t_dict = defaultdict(lambda: defaultdict(lambda: defaultdict(defaultdict)))
#
#         self.aman_area = dict()
#         self.acid_to_get_slot = set()
#
#         self.counter_slots = 0
#         self.aman_parent_id = None
#         self.not_spawned = {}
#         self.runway_configurations = RunwayConfiguration()
#
#
#
#
#     @core.timed_function(name='on_traffic_in_area', dt=5)
#     def update(self):
#         """
#         Every 5 seconds update the AMANINFO data by checking whether there is traffic in the area around the airport.
#         """
#         if traf.traf_parent_id and self.aman_parent_id is None:
#             self.aman_parent_id = traf.traf_parent_id
#
#         if self.aman_parent_id:
#             return
#
#         self.on_traffic_in_area(self.acid_to_get_slot.copy())
#
#         # self.ATAs = self.arrival_slots
#
#         data = (self.acids_allocated, self.ETAs, self.arrival_slots, self.ATAs, self.delta_t_dict)
#         net.send('AMANINFO', data, GROUPID_SIM)
#
#     @stack.command
#     def on_traffic_in_area(self, acids):
#         """
#         Handles traffic in the area around the airport, assigning arrival slots to aircraft
#         as they enter the managed area.
#         """
#         num_acs = len(traf.ap.route)
#         # Check each acid in self.acid_to_get_slot if it needs to get a slot.
#         for i, acid in enumerate(acids):
#             # Get the airport and runway of arrival for the acid
#             dest = traf.ap.dest[traf.id2idx(acid)]
#             airport, runway = parse_destination(dest)
#
#             # Get the coordinates of the acid
#             idxac = traf.id2idx(acid)
#             point = traf.lat[idxac], traf.lon[idxac], traf.alt[idxac]
#
#             idxwp = traf.ap.route[idxac].wpname.index(dest)
#
#             # Check if the area around the airport is defined else, define the area.
#             try:
#                 self.aman_area[airport]
#             except KeyError:
#                 self.define_area(airport)
#
#             # Only runs when a flight is modified after its arrival slot has been fixed
#             if acid in self.acids_allocated[airport][runway] and acid in self.acid_to_get_slot:
#                 orderidx = self.acids_allocated[airport][runway].index(acid)
#                 eta = traf.ap.route[idxac].wptpredutc[idxwp]
#                 old_eta = self.ETAs[airport][runway][acid]
#                 self.ETAs[airport][runway][acid] = eta
#                 assigned_slot = self.arrival_slots[airport][runway][orderidx]
#                 delta_t = calc_delta_t(eta, assigned_slot)
#                 self.delta_t_dict[airport][runway][acid] = delta_t
#                 self.acid_to_get_slot.remove(acid)
#                 stack.stack(f'ECHO ---- ETA update for {acid} ----')
#                 # stack.stack(f'AMAN_SHOW EHAM, RW18R')
#
#             if self.aman_area[airport].checkInside(*point) and acid not in self.acids_allocated[airport][runway]:
#                 if airport and runway:
#                     # Assign a new arrival slot for the acid
#                     new_slot = self.allocate_slot(acid, dest, traf.ap.route[idxac].wptpredutc[idxwp])
#                     new_slot = datetime.fromtimestamp(new_slot, tz=None)
#
#                     stack.stack(f'ECHO {acid} assigned arrival slot at {dest} for {new_slot}')
#                     self.counter_slots += 1
#
#                 else:
#                     # If there is no airport or runway, now slot can be allocated
#                     stack.stack(
#                         f'For {acid} arriving at {dest}, no time slot can be given as there is tno runway specified.')
#
#                 # Aircraft ID can be removed as it got a slot if possible
#                 if acid in self.acid_to_get_slot:
#                     self.acid_to_get_slot.remove(acid)
#         # print(self.ETAs)
#         # # The following four dictionaries are related by index
#         # print(self.acids_allocated)
#         # print(self.ETAs)
#         # print(self.arrival_slots)
#         # print(self.ATAs)
#         # print(self.separation_times)
#         #
#         # # The aircraft in each airport will give the runway in which they will land
#         # print(self.aircraft_in_database)
#         #
#         # # Dictionary providing the delta_t of a specific flight(acid) allocated to a runway at an airport
#         # # airports > runways > aircrafts > delta_t
#         # print(self.delta_t_dict)
#         #
#         # print(self.aman_area)
#         # print(self.acid_to_get_slot)
#
#         if 'EHAM' in self.ATAs.keys():
#             print(self.ETAs['EHAM'])
#             # The following four dictionaries are related by index
#             print(self.acids_allocated['EHAM'])
#             print(self.ETAs['EHAM'])
#             print(self.arrival_slots['EHAM'])
#             print(self.ATAs['EHAM'])
#             print(self.separation_times['EHAM'])
#
#             # The aircraft in each airport will give the runway in which they will land
#             print(self.aircraft_in_database['EHAM'])
#
#             # Dictionary providing the delta_t of a specific flight(acid) allocated to a runway at an airport
#             # airports > runways > aircrafts > delta_t
#             print(self.delta_t_dict['EHAM'])
#
#             print(self.aman_area['EHAM'])
#             if acid:
#                 idxac = traf.id2idx(acid)
#                 print(traf.ap.route[idxac].iaf)
#
#
#
#
#
#
#         # if self.counter_slots == num_acs:
#         #     self.counter_slots = 0
#         #     stack.stack(f'ECHO ---- All Slots Assigned ----')
#         #     stack.stack(f'AMAN_SHOW EHAM, RW18R')
#
#     def define_area(self, airport, top=1e9, bottom=-1e9, radius=80):
#         """
#         Defines the area around the airport where arrival manager will be active. The area is defined as a
#         circle with a radius of 80 nm.
#         """
#
#         # Get airport index
#         idx = navdb.aptid.index(airport)
#
#         # Get latitude and longitude of the airport
#         lat = navdb.aptlat[idx]
#         lon = navdb.aptlon[idx]
#
#         # Define the coordinates and create the circle
#         coordinates = (lat, lon, radius)
#         self.aman_area[airport] = Circle(f"{airport}_horizon", coordinates, top, bottom)
#
#     @network.subscriber(topic='PREDICTION')
#     def on_prediction_received(self, acid, wpt, wptime, wptpredutc, parent_id):
#         """
#         Each acid getting a new ETA will be added to aircraft needing to get a slot.
#         """
#
#         # TODO: the following can maybe be used for the ATA
#         # stack.stack(f'{acid} AT {wpt} DO AMANwptcross {acid} {wpt}')
#
#         self.sim_id_parent = parent_id
#         idxac = traf.id2idx(acid)
#         if idxac == -1:
#             self.not_spawned[acid] = (wpt, wptime, wptpredutc, parent_id)
#         else:
#
#             idxwp = traf.ap.route[idxac].wpname.index(wpt)
#
#             if idxwp == len(traf.ap.route[idxac].wptime) - 1:
#                 self.acid_to_get_slot.add(acid)
#
#
#     def create(self, n=1):
#         """ Gets triggered everytime n number of new aircraft are created. """
#         super().create(n)
#
#         # Ensure this runs only in the main node.
#
#
#         for i in range(n):
#             acid = traf.id[-1 - i]
#             id = len(traf.id) - i
#             if acid in self.not_spawned.keys():
#                 self.acid_to_get_slot.add(acid)
#
#
#     def allocate_slot(self, acid, dest, eta):
#         """
#         Allocates an arrival slot based on the ETA, ensuring minimum separation time.
#         """
#         idx = 0
#         airport, runway = parse_destination(dest)
#
#         new_slot = eta
#
#         # Iterate through the existing slots to ensure the separation time is maintained
#         for i in range(len(self.arrival_slots[airport][runway])):
#
#             temp_leader = self.acids_allocated[airport][runway][i]
#             temp_follower = acid
#
#             current_separation_time = self.get_separation_time(temp_leader, temp_follower)
#
#             # If the new slot conflicts with an existing slot, adjust the new slot
#             differences = abs(new_slot - self.arrival_slots[airport][runway][i])
#
#             # --- if differences < self.separation_times[airport][runway][i]:
#             if differences < current_separation_time:
#                 new_slot = self.arrival_slots[airport][runway][i] + self.separation_times[airport][runway][i]
#
#         # Joining the allocated acids, and their slot times
#         acids_and_slots = [(self.arrival_slots[airport][runway][i], self.acids_allocated[airport][runway][i]) for i in range(len(self.arrival_slots[airport][runway]))]
#
#         # Sorting the entries in ascending order based on slot time
#         acids_and_slots = sorted(acids_and_slots, key=lambda x: x[0])
#
#         # Determining which aircraft in the allocated slots is the leader
#         leader = None
#         follower = acid
#         separation_time = self.runway_configurations.min_time_sep
#         for i in range(0, len(acids_and_slots)):
#             if new_slot < acids_and_slots[i][0]:
#                 leader = acids_and_slots[i-1][1]
#
#                 # Calculate actual required separation time once we know the leader
#                 separation_time = self.get_separation_time(leader, follower)
#                 break
#             elif i == len(acids_and_slots)-1:
#                 leader = acids_and_slots[-1][1]
#
#
#
#         # if abs(new_slot - eta) > 120:
#         #     pass # TODO: USE DIFFERENT RUNWAY IF POSSIBLE
#
#         # Check if aircraft already exists and remove its old slot.
#         if acid in list(self.aircraft_in_database[airport].keys()):
#             runway_old = self.aircraft_in_database[airport][acid]
#
#             # Finding the index of the acid to remove
#             if acid in self.acids_allocated[airport][runway_old]:
#                 idx = self.acids_allocated[airport][runway_old].index(acid)
#
#                 # Remove the acid from allocations dictionary
#
#                 self.acids_allocated[airport][runway_old].remove(acid)
#
#                 # Removing the times corresponding to the acid from the other dictionaries
#                 self.arrival_slots[airport][runway_old].pop(idx)
#                 self.ETAs[airport][runway_old][acid] = []
#                 self.separation_times[airport][runway_old].pop(idx)
#                 self.delta_t_dict[airport][runway_old][acid] = []
#
#             # Lastly removing acid from ac database
#             del self.aircraft_in_database[airport][acid]
#
#         # If ETA and assigned SLOT are valid, calculate delta t between ETA and assigned
#         if eta >= 0 and new_slot >= 0:
#             # Calculates delta_t between allocated slot and ETA
#             delta_t = calc_delta_t(eta, new_slot)
#             self.delta_t_dict[airport][runway][acid] = delta_t
#
#         # Update class attribute dictionaries with new aircraft id (acid) and times
#         self.acids_allocated[airport][runway].append(acid)
#         self.ETAs[airport][runway][acid] = eta
#         self.arrival_slots[airport][runway].append(new_slot)
#         self.separation_times[airport][runway].append(separation_time)
#         self.aircraft_in_database[airport][acid] = runway
#
#         self.ATAs[airport][runway].append(1)
#         return new_slot
#
#     @stack.command
#     def AMANwptcross(self, acid: str, wpt: str):
#         """Handles aircraft waypoint crossing, updating the actual time of arrival (ATA)."""
#         # TODO: This function is still not used and can be used to calculate the ATA
#
#         if self.aman_parent_id:
#             return
#
#         ata_timestamp = sim.utc.timestamp()
#         ata_datetime = datetime.fromtimestamp(ata_timestamp, tz=None)
#
#         airport, runway = parse_destination(wpt)
#         # Ensure the ATAs list is as long as the acids_allocated list.
#         while len(self.ATAs[airport][runway]) < len(self.acids_allocated[airport][runway]):
#             self.ATAs[airport][runway].append(-1)
#
#         if airport and runway:
#             idx = self.acids_allocated[airport][runway].index(acid)
#             self.ATAs[airport][runway][idx] = ata_timestamp
#             stack.stack(f'Echo For {acid} arriving at {wpt}, the ATA is {ata_datetime} seconds.')
#         else:
#             stack.stack(
#                 f'Echo For {acid} with ATA {ata_datetime} at {wpt}, the ATA can be plot as there is no runway specified.')
#
#     def reset(self):
#         """Reset the arrival manager when needed."""
#
#         # Define aman area
#         self.aman_area = dict()
#
#         # The aircraft which need to receive a slot
#         self.acid_to_get_slot = set()
#         self.counter_slots = 0
#         try:
#             if self.sim_id_parent:
#                 return
#         except:
#             print()
#         # The following four dictionaries are related by index
#         self.acids_allocated = defaultdict(lambda: defaultdict(list))
#         self.ETAs = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
#         self.arrival_slots = defaultdict(lambda: defaultdict(list))
#         self.separation_times = defaultdict(lambda: defaultdict(list))
#
#         # The aircraft in each airport will give the runway in which they will land
#         self.aircraft_in_database = defaultdict(lambda: defaultdict(str))
#         self.delta_t_dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
#
#     @stack.commandgroup
#     def aman_logging(self):
#         """ Controls the saving and logging of output data of the
#             AMAN + TP Implementation """
#
#         if bool(self.acids_allocated):
#             pass  # call function to log or something
#             return True, 'Logger has started'
#         else:
#             return True, ('No AMAN slots have been allocated, '
#                           'wait for the aircrafts to be within AMAN Range')
#
#     @aman_logging.subcommand
#     def save_aman(self, filename=None):
#         pass
#
#     @aman_logging.subcommand
#     def load_aman(self, filename=None):
#         pass
#
#
#     def get_separation_time(self, leader, follower):
#         if leader is not None and follower is not None:
#             leader_idx, follower_idx = traf.id2idx([leader, follower])
#             leader_type = traf.type[leader_idx]
#             follower_type = traf.type[follower_idx]
#             sep = self.runway_configurations.required_separation(leader_type=leader_type,
#                                                                              follower_type=follower_type, time=True)
#             return sep
#         else:
#             sep = self.runway_configurations.min_time_sep
#             return sep
#
#
#
# def parse_destination(wpt_name):
#     try:
#         # Create an instance of WptArg parser
#         parser = stack.argparser.WptArg()
#
#         # Parse the command string
#         argstring = wpt_name + ", more arguments if any"
#         parsed_name, remaining_string = parser.parse(argstring)
#
#         # Check if the parsed name is a runway (look for the '/' pattern in parsed_name followed by "RW")
#         if '/RW' in parsed_name:
#             airport, runway = parsed_name.split('/')
#             return airport, runway  # Return the airport and runway
#         else:
#             return wpt_name, None  # Return None if it's not a runway
#     except ValueError:
#         return None, None  # Return None if an error occurs, indicating not a valid waypoint or runway
#
#
# def calc_delta_t(eta, slot):
#     return slot - eta
#
#
# def runway_preference():
#     landing_runways = ['EHAM/RW04',
#                        'EHAM/RW06',
#                        'EHAM/RW09',
#                        'EHAM/RW18C',
#                        'EHAM/RW18R',
#                        'EHAM/RW22',
#                        'EHAM/RW24',
#                        'EHAM/RW27',
#                        'EHAM/RW36C',
#                        'EHAM/RW36R']
#
#     preference_list = []
