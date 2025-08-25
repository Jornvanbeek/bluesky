# """
# The Arrival Manager (AMAN) plugin is designed to efficiently allocate arrival slots for aircraft based on
# their estimated times of arrival (ETAs) while ensuring necessary separation times. It dynamically updates
# air traffic every 5 seconds around designated areas around airports based on ETAs to anticipate aircraft arrivals.
# """
# from logging import currentframe, error
#
# from numpy.ma.core import swapaxes
# from setuptools.dist import sequence
#
# from bluesky import core, stack, traf, navdb, net, network, sim
# from bluesky.tools.areafilter import Circle
# from bluesky.network.common import GROUPID_SIM
# from datetime import datetime
#
# from collections import defaultdict
# from plugins.RunwayConfigurations import RunwayConfiguration
# from plugins.LIV_separation import LivSeparation
# import pandas as pd
# pd.set_option('display.max_columns', None)
# pd.set_option('display.max_rows', None)
# pd.set_option('display.width', 250)
# import math
# import webbrowser
# import os
# import time
# import random
#
#
#
# #from bluesky.ui.palette import initialized
# #from plugins.trajectory_predictor_new import total_pred_signals
#
#
# def init_plugin():
#     """Initializes the plugin and creates an instance of the ArrivalManager."""
#
#     addbefore = ADDBEFORE()
#
#     # Configuration for the plugin, specifying its name and type.
#     config = {
#         'plugin_name': 'ADDBEFORE',
#         'plugin_type': 'sim'
#     }
#
#     return config
#
#
#
#
#
#
#
#
# class ADDBEFORE(core.Entity):
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
#         # Define the column names
#         columns = ['ACID', 'planningstate', 'ttlg', 'to eto', 'type', 'LIV', 'ETA', 'ETO IAF', 'IAF', 'runway', 'EAT', 'slot', 'TMA flighttime', 'EAT adherence', 'LAS', 'LAf', 'origin']
#
#         self.Flights = pd.DataFrame(columns = columns)
#         self.Flights.set_index('ACID', inplace=True)
#
#         self.iafs = ['ARTIP', 'SUGOL', 'RIVER']
#
#         self.not_spawned = defaultdict(list)
#         self.aman_parent_id = None
#         self.planninghorizon = 40*60
#         self.freezehorizon = 14*60
#         self.TMA_scan = 5*60 #only aircraft within 5 mins of the tma get checked if they are in the tma
#         self.separation = 75
#         self.LIV_separation = LivSeparation()
#         self.cntrlz = None          # planning times backup
#
#
#
#
#     # update of planningstates, core functionality
#     @core.timed_function(dt=10)
#     def update_planningstate(self):
#         if self.aman_parent_id:
#             return
#
#         self.update_times()
#         self.origin()
#         self.preplan()
#         self.assignslots()
#         self.update_times()
#         self.freeze()
#         self.tma()
#         self.update_times()
#
#
#
#     # def preplan(self):
#     #     self.Flights.loc[(self.Flights['planningstate'] == 'new') & ((self.Flights['ETO IAF'] - sim.simt) < self.planninghorizon), 'planningstate'] = 'preplanned'
#     #     # planningstate goes from new to preplanned if the amount of flighttime until the eto iaf is less than the planning horizon
#
#     def preplan(self):
#         # 1) Find flights that go from 'new' to 'preplanned'
#         mask_new_to_preplan = (
#                 (self.Flights['planningstate'] == 'new')
#                 & ((self.Flights['ETO IAF'] - sim.simt) < self.planninghorizon)
#         )
#
#         # 2) Update their planningstate
#         self.Flights.loc[mask_new_to_preplan, 'planningstate'] = 'preplanned'
#
#         # 3) Color those newly preplanned flights
#         newly_preplanned = self.Flights[mask_new_to_preplan]
#         for idx in newly_preplanned.index:
#             stack.stack(f"COLOR {idx} 0,150,255")
#
#
#     def assignslots(self):
#         if self.aman_parent_id:
#             return
#
#         for runway in self.Flights['runway'].unique():
#             # Filter frozen and preplanned flights for the current runway
#             frozen_flights = self.Flights.query("planningstate == 'frozen' and runway == @runway")
#             preplanned_flights = self.Flights.query("planningstate == 'preplanned' and runway == @runway").sort_values(by='ETA')
#
#             # Initialize last assigned variables
#             if not frozen_flights.empty:
#                 max_row = frozen_flights.loc[frozen_flights['slot'].idxmax()]
#                 last_assigned_slot, last_assigned_flight, last_assigned_type = max_row['slot'], max_row.name, max_row['type']
#             else:
#                 last_assigned_slot = last_assigned_flight = last_assigned_type = None
#
#
#             # Iterate over the filtered DataFrame and calculate slots
#             for idx, row in preplanned_flights.iterrows():
#                 if last_assigned_slot is None:
#                     # First flight's slot is its ETA
#                     slot = row['ETA']
#                     separation = 0
#                 else:
#                     # Subsequent flight's slot is the last slot + separation
#
#                     separation = self.LIV_separation.required_separation(last_assigned_flight, last_assigned_type, idx, row['type'])
#                     slot = max(last_assigned_slot + separation, row['ETA'])
#
#                 # Update the slot in the DataFrame
#                 self.Flights.loc[idx, ['slot', 'EAT', 'LIV', 'LAS', 'LAf']] = [
#                     slot,
#                     slot - row['TMA flighttime'],
#                     separation,
#                     last_assigned_slot,
#                     last_assigned_flight,
#                 ]
#                 stack.stack(f'COLOR {idx} 0,150,255')  # Retaining stack logic
#
#                 # Update last assigned variables
#                 last_assigned_slot, last_assigned_flight, last_assigned_type = slot, idx, row['type']
#
#
#         self.Flights = self.Flights.sort_values(by=['slot', 'ETA'], ascending=False)
#
#
#
#
#     def freeze(self):
#         for runway, runway_df in self.Flights.groupby('runway'):
#             # Freeze aircraft with flighttime < 14 minutes and preplanned within this runway
#             newfrozen = runway_df[(runway_df['planningstate'] == 'preplanned') & ((runway_df['ETO IAF'] - sim.simt) < self.freezehorizon)]
#             # Get the maximum slot of the newfrozen aircraft within this runway
#             max_slot_newfrozen = newfrozen['slot'].max()
#
#             # Select all preplanned flights with a slot smaller than max_slot_newfrozen within this runway
#             preplanned_before_max_slot = runway_df[(runway_df['planningstate'] == 'preplanned') & (runway_df['slot'] < max_slot_newfrozen)]
#
#
#             # Set their planningstate to 'frozen'
#             self.Flights.loc[newfrozen.index, 'planningstate'] = 'frozen'
#             self.Flights.loc[preplanned_before_max_slot.index, 'planningstate'] = 'frozen'
#             self.color(newfrozen, '100,255,100')
#             self.color(preplanned_before_max_slot, '100,255,100')
#
#
#     def tma(self):
#         for flight in self.Flights[(self.Flights['planningstate'] == 'frozen') & (
#                 (self.Flights['ETO IAF'] - sim.simt) < self.TMA_scan)].index:
#             idxac = traf.id2idx(flight)
#             iaf = self.Flights.loc[flight]['IAF']
#             if idxac > -1:
#                 if traf.ap.route[idxac].iactwp > traf.ap.route[idxac].wpname.index(iaf):
#                     self.Flights.at[flight, 'planningstate'] = 'TMA'
#                     self.Flights.at[flight, 'ETO adherence'] = sim.simt - self.Flights.loc[flight]['ETO IAF']
#                     # self.printflights()
#         self.color(self.Flights.loc[self.Flights['planningstate'] == 'TMA'], '230,230,230')
#
#
#
#
#
# # ___________________________________ PREDICTOR FUNCTIONS
#     # new prediction received
#     @network.subscriber(topic='PREDICTION')
#     def on_prediction_received(self, acid, wpt, wptime,flighttime, wptpredutc, parent_id, type):
#         """
#         Each acid getting a new ETA will be added to aircraft needing to get a slot.
#         """
#         if self.aman_parent_id:
#             return
#         self.sim_id_parent = parent_id
#         idxac = traf.id2idx(acid)
#         estimatedcreatetime = wptime - flighttime
#         if idxac == -1:
#             self.not_spawned[acid].append((wpt, wptime,flighttime,estimatedcreatetime, wptpredutc, parent_id, type))
#             # dest, runway = parse_destination(wpt)
#             # self.Flights.loc[acid] = {'planningstate': 'ground', 'ETA': wptime, 'runway': runway, 'type': type}
#             # the above is future code for popups?
#         else:
#             wptime = traf.ap.route[idxac].createtime + flighttime
#             data = {'planningstate': 'new', 'runway': ''}
#
#
#             if wpt in self.iafs:
#                 data = {'planningstate': 'new', 'ETO IAF': wptime, 'IAF': wpt, 'type': type, 'origin': '', 'LAf': ''}
#
#             elif '/RW' in wpt:
#                 dest, runway = parse_destination(wpt)
#                 data = {'planningstate': 'new', 'ETA': wptime, 'runway': runway, 'type': type, 'origin': '', 'LAf': ''}
#             # print(acid,wpt,wptime)
#
#             if acid not in self.Flights.index:
#                 # Adds a new row for acid if it doesn't exist
#                 self.Flights.loc[acid] = {'runway': '', 'type': '', 'IAF': '', 'planningstate': '', 'origin': '', 'LAf': ''}
#                 self.Flights.loc[acid] = data
#             else:
#                 # Updates the existing row for acid
#                 for key, value in data.items():
#                     self.Flights.at[acid, key] = value
#
#
#     # new aircraft spawned
#     def create(self, n=1):
#         """ Gets triggered everytime n number of new aircraft are created. """
#         super().create(n)
#
#         # Ensure this runs only in the main node.
#         if traf.traf_parent_id and self.aman_parent_id is None:
#             self.aman_parent_id = traf.traf_parent_id
#             return
#
#         for i in range(n):
#             acid = traf.id[-1 - i]
#             id = len(traf.id) - i
#             if acid in self.not_spawned.keys():
#                 for prediction in self.not_spawned[acid]:
#                     wpt, wptime, flighttime, estimatedcreatetime, wptpredutc, parent_id, type = prediction
#                     wptime = sim.simt + flighttime
#
#                     if wpt in self.iafs:
#                         data = {'planningstate': 'new', 'ETO IAF': wptime, 'IAF': wpt, 'type': type, 'origin': '', 'LAf': '', 'Flighttime': flighttime}
#                     elif '/RW' in wpt:
#                         dest, runway = parse_destination(wpt)
#                         data = {'planningstate': 'new', 'ETA': wptime, 'runway':runway, 'type': type, 'origin': '', 'LAf': '', 'Flighttime': flighttime}
#
#                     else:
#                         print('something wrong with waypoints and prediction in aman')
#
#                     #add data to dataframe
#                     if acid not in self.Flights.index:
#                         # Adds a new row for acid if it doesn't exist
#                         self.Flights.loc[acid] = {'runway': '', 'type': '', 'IAF': '', 'planningstate': '', 'origin': '', 'LAf': ''}
#                         self.Flights.loc[acid] = data
#                     else:
#                         # Updates the existing row for acid
#                         for key, value in data.items():
#                             self.Flights.at[acid, key] = value
#
#
#
#
#     def delete(self, idx):
#         super().delete(idx)
#         if self.aman_parent_id:
#             return
#         else:
#             for id in idx:
#                 acid = traf.id[id]
#                 if acid in self.Flights.index:
#                     self.Flights.at[acid, 'planningstate'] = 'deleted'
#
#
#
#
# # ----------------------------------------------------------- misc functions
#     def origin(self):
#         # sadly, cannot be run in create, since orig is not set yet. this function is called in the update function
#         for flight in self.Flights[(self.Flights['origin'] == '')].index:
#             idxac = traf.id2idx(flight)
#
#             if idxac == -1:
#                 continue
#             else:
#                 try:
#                     origin =traf.ap.orig[idxac]
#                     self.Flights.at[flight, 'origin'] = origin
#
#                 except:
#                     continue
#
#
#
#     def update_times(self):
#         if self.aman_parent_id:
#             return
#         self.Flights['TMA flighttime'] = self.Flights['ETA'] - self.Flights['ETO IAF']
#         self.Flights['to eto'] = round((self.Flights['ETO IAF'] - sim.simt) / 60, 0)
#         self.Flights['ttlg'] = self.Flights['EAT'] - self.Flights['ETO IAF']
#
#
#     def color(self, df, rgb):
#         if self.aman_parent_id:
#             return
#         # Iterate over the filtered DataFrame and calculate slots
#         for idx in df.index:
#             stack.stack('COLOR ' + idx +' '+ rgb)
#
#
#
# #--------------------------------------------------------------
#     #planning functions
#
#     @stack.command
#     def freezehorizon(self, minutes):
#         self.freezehorizon = 60.* minutes
#         self.update_planningstate()
#
#     @stack.command
#     def planninghorizon(self, minutes):
#         self.planninghorizon = 60.* minutes
#         if self.planninghorizon < self.freezehorizon:
#             self.planninghorizon = self.freezehorizon + 60*1.
#
#
#     @stack.command
#     def newplanningtimes(self):
#         self.cntrlz = self.Flights.copy(deep=True)
#         self.Flights.loc[(self.Flights['planningstate'] == 'frozen')] = 'preplanned'
#         self.update_planningstate()
#         self.htmlflights()
#
#     @stack.command
#     def previousplanningtimes(self):
#         if self.cntrlz:
#             self.Flights = self.cntrlz.copy(deep=True)
#             self.update_planningstate()
#             self.htmlflights()
#         else:
#             stack.stack('ECHO no previous planning times known')
#
# #--------------------------------------------------------------
#     #exporting functions
#
#
#     @stack.command
#     def printflights(self, key=None):
#         if self.aman_parent_id:
#             return
#         if key is None:
#             # Print the entire DataFrame
#             print(self.Flights)
#         else:
#             # Check if the key is a valid column in the DataFrame
#             if key in self.Flights.columns:
#                 print(self.Flights[key])
#
#     @stack.command
#     def storeflights(self):
#         if self.aman_parent_id:
#             return
#         if traf.traf_parent_id and self.aman_parent_id is None:
#             self.aman_parent_id = traf.traf_parent_id
#             return
#         self.printflights()
#         self.pickleflights()
#         self.Flights.to_csv('dataframe.txt', sep=',', index=True)
#
#     @stack.command
#     def pickleflights(self):
#         if self.aman_parent_id:
#             return
#         self.Flights.to_pickle('flights.pkl')
#         # Flights = pd.read_pickle('flights.pkl')
#
#     @stack.command
#     def htmlflights(self):
#         if self.aman_parent_id:
#             return
#
#         # Save as HTML with fixed headers
#         Flights_hhmmss = self.Flights.copy()
#         columns_to_transform = ['ETA', 'ETO IAF', 'EAT', 'slot', 'LAS']
#         for col in columns_to_transform:
#             Flights_hhmmss[col] = Flights_hhmmss[col].apply(lambda x: None if pd.isna(x) else f"{int(x // 3600):02}:{int((x % 3600) // 60):02}:{int(x % 60):02}")
#
#
#
#         # Save as HTML with fixed headers and index included
#         html = Flights_hhmmss.to_html(classes='table table-bordered', index=True)
#         html_with_style = f"""
#         <html>
#         <head>
#         <style>
#             .table {{
#                 border-collapse: collapse;
#                 width: 100%;
#             }}
#             .table th {{
#                 position: sticky;
#                 top: 0;
#                 background: #f1f1f1;
#             }}
#             .table th, .table td {{
#                 border: 1px solid black;
#                 padding: 8px;
#                 text-align: left;
#             }}
#         </style>
#         </head>
#         <body>
#         {html}
#         </body>
#         </html>
#         """
#         output_path = "output.html"
#
#         # Write to file
#         with open(output_path, "w") as f:
#             f.write(html_with_style)
#
#         # Automatically open in the browser
#         webbrowser.open(f"file://{os.path.abspath(output_path)}")
#
#     @stack.command
#     def totwohtml(self):
#
#         if self.aman_parent_id:
#             return
#
#             # Split Flights into two subsets based on runway
#         Flights_hhmmss = self.Flights.copy()
#         Flights_hhmmss.rename(columns={'runway': 'rwy'}, inplace=True)
#         Flights_hhmmss.rename(columns={'TMA flighttime': 'TMA'}, inplace=True)
#         if 'rwy' in Flights_hhmmss.columns:
#             Flights_hhmmss['rwy'] = Flights_hhmmss['rwy'].str[3:]  # Remove first 3 characters
#
#         # Convert specified columns to integers
#         columns_to_convert = ['ttlg', 'to eto', 'TMA']
#         for col in columns_to_convert:
#             if col in Flights_hhmmss.columns:
#                 Flights_hhmmss[col] = Flights_hhmmss[col].fillna(0).astype(int)  # Convert to int, handling NaN
#
#         # Transform specified columns to HH:MM:SS
#         columns_to_transform = ['ETA', 'ETO IAF', 'EAT', 'slot', 'LAS']
#         for col in columns_to_transform:
#             if col in Flights_hhmmss.columns:
#                 Flights_hhmmss[col] = Flights_hhmmss[col].apply(
#                     lambda x: None if pd.isna(x) else f"{int(x // 3600):02}:{int((x % 3600) // 60):02}:{int(x % 60):02}"
#                 )
#
#         # Split data into RWY27 and RWY18C
#         Flights_RWY27 = Flights_hhmmss[Flights_hhmmss['rwy'] == '27']
#         Flights_RWY18C = Flights_hhmmss[Flights_hhmmss['rwy'] == '18C']
#
#         # Generate HTML tables for each runway
#         html_RWY27 = Flights_RWY27.to_html(classes='table table-bordered', index=True)
#         html_RWY18C = Flights_RWY18C.to_html(classes='table table-bordered', index=True)
#
#         # HTML layout for two tables side by side
#         html_with_style = f"""
#         <html>
#         <head>
#         <style>
#             .table {{
#                 border-collapse: collapse;
#                 width: 100%;
#                 font-size: 12px; /* Smaller font for tables */
#             }}
#             .table th {{
#                 position: sticky;
#                 top: 0;
#                 background: #f1f1f1;
#             }}
#             .table th, .table td {{
#                 border: 1px solid black;
#                 padding: 4px; /* Reduce padding for cells */
#                 text-align: left;
#             }}
#             .container {{
#                 display: flex;
#                 flex-direction: row;
#                 justify-content: space-between;
#                 gap: 10px; /* Smaller gap between tables */
#                 overflow-x: auto; /* Allow horizontal scrolling if needed */
#             }}
#             .table-container {{
#                 width: 48%; /* Reduce the width of each table container */
#             }}
#         </style>
#         </head>
#         <body>
#         <div class="container">
#             <div class="table-container">
#                 <h3>Runway RWY27</h3>
#                 {html_RWY27}
#             </div>
#             <div class="table-container">
#                 <h3>Runway RWY18C</h3>
#                 {html_RWY18C}
#             </div>
#         </div>
#         </body>
#         </html>
#         """
#         output_path = "output.html"
#
#         # Write to file
#         with open(output_path, "w") as f:
#             f.write(html_with_style)
#
#         # Automatically open in the browser
#         webbrowser.open(f"file://{os.path.abspath(output_path)}")
#
#     @core.timed_function(dt=100 )
#     def autohtmlflights(self):
#         if not sim.ffmode:
#             # self.htmlflights()
#             self.totwohtml()
#     @core.timed_function(dt=1000) #is approx every 10 sec in ff mode
#     def autohtmlflightsff(self):
#         # self.time = time.time()
#         # if self.previoustime - self.time < 60:
#         if sim.ffmode:
#             # self.htmlflights()
#             self.totwohtml()
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
#     @stack.command
#     def randomspeedinstruction(self, n, group='preplanned', seed=42):
#         """
#         Randomly selects 'n' aircraft from the specified 'group' (default 'preplanned')
#         and issues a random speed (between 150 and 350) instruction to each.
#         Uses a fixed random seed to ensure reproducibility.
#         """
#         # Set the seed for reproducible "random" results
#         random.seed(seed)
#
#         # Filter flights by planningstate (group), e.g. 'preplanned'
#         eligible_flights = self.Flights[self.Flights['planningstate'] == group].index.tolist()
#
#         # Clamp n if it’s greater than the number of eligible flights
#         n = min(int(n), len(eligible_flights))
#
#         # Randomly pick n flights
#         selected_flights = random.sample(eligible_flights, n)
#         print(selected_flights)
#
#         # For each flight, create a random speed between 150 and 350, then send it
#         for acid in selected_flights:
#             spd_cmd = random.randint(150, 350)
#             stack.stack(f"SPD {acid} {spd_cmd}")
#
#
#     @stack.command
#     def addbefore(self, acid: str, next_wpt: str, new_wpt: str):
#         """
#         Inserts a waypoint before an existing waypoint in the route.
#         Usage: addbefore ACID NEXT_WPT NEW_WPT_OR_COORDS
#         - ACID: aircraft identifier
#         - NEXT_WPT: the waypoint before which to insert
#         - NEW_WPT_OR_COORDS: either a waypoint name or "lat,lon" coordinate pair
#         """
#         # Check if new_wpt is a coordinate pair
#         if ',' in new_wpt:
#             lat_str, lon_str = new_wpt.split(',', 1)
#             lat = lat_str.strip()
#             lon = lon_str.strip()
#             # Insert the coordinate waypoint before the specified waypoint
#             stack.stack(f"ADDWPT {acid} {lat} {lon} , , , , {next_wpt}")
#         else:
#             # Insert the named waypoint before the specified waypoint
#             stack.stack(f"ADDWPT {acid} {new_wpt} , , , , {next_wpt}")
#
#
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
#         # #todo list
#         # basic aman
#         #
#
#         # dataframe according to slottimes: maybe eat?
# # shorten scenario
# # change method of data setting due to future warning
#         # define separation times
#         # handle popups
# # export dataframe
#         # planned status to TMA in tma
#         # remove aman from tp node
#         # define ltfm, eetn, lybe origs
#         # individual performance of aircraft in scenario generator
#
#
#
#         # read and import runways
#         # change route if runway is changed
# # export dataframe
#         # set horizons function
#         # EAT adherence
#         # check what happens if same runway but later slot gets frozen earlier
#
#
#
#         # total
#         # atc based on ttlg etc
#         # swap function
#         # expedite margin function
#         # visualization
#         # check scenario generator if it is the same as info in so6 file. (replacing aircraft is verified, not validated)
#
#
#
#
#
#
