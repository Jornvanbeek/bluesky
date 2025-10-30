
#
# import numpy as np
# from bluesky import core, stack, traf
# from bluesky.core import plugin
# from bluesky.traffic import Traffic
# from bluesky.traffic.autopilot import Autopilot
#
# def init_plugin():
#
#     mc_plugin = MachCrossoverPlugin()
#
#     # 3) Return a config dict so BlueSky knows this is a sim plugin
#     config = {
#         'plugin_name': 'mach_crossover',
#         'plugin_type': 'sim',
#     }
#     return config
#
#
# class MachCrossoverPlugin(core.Entity):
#
#     def __init__(self):
#         super().__init__()
#         print("[MachCrossoverPlugin] Created plugin manager")
#         # stack.stack('IMPLEMENTATION Traffic Traffic')
#         self.original_update = Autopilot.update
#         Autopilot.update = self.update
#         with self.settrafarrays():
#             self.mcruise  = np.array([])
#             self.mdescent = np.array([])
#             self.casdesc  = np.array([])
#
#     def create(self, n=1):
#         # Traffic.create() will do all the standard array expansions
#         super().create(n)
#         # Expand your custom arrays
#         self.mcruise[-n:]  = [0.78 for _ in range(n)]
#         self.mdescent[-n:] = [0.76 for _ in range(n)]
#         self.casdesc[-n:]  = [280 for _ in range(n)]
#         # print("[MachTraffic] create() called for", n, "new aircraft")
#
#     def update(self):
#         print('update autopilot')
#         self.original_update(traf.ap)
#
#     @stack.command
#     def setmachx(self, acid, mcruise, mdescent, casdesc):
#         """
#         Stack command to set Mach-crossover parameters for a given aircraft.
#
#         Usage:
#           SETMACHX <ACID> <mcruise> <mdescent> <casdesc>
#         e.g.:
#           SETMACHX KLM123 0.80 0.76 280
#         """
#         idx = traf.id2idx(acid)
#         if idx < 0:
#             return False, f"Aircraft {acid} not found."
#
#         try:
#             mcr = float(mcruise)
#             mds = float(mdescent)
#             cds = float(casdesc)
#         except ValueError:
#             return False, "Usage: SETMACHX ACID mcruise mdescent casdesc (floats)"
#
#         # We assume our traffic object is already replaced by MachTraffic,
#         # so these arrays exist.
#         traf.mcruise[idx]  = mcr
#         traf.mdescent[idx] = mds
#         traf.casdesc[idx]  = cds
#
#         return True, (
#             f"Set MachX for {acid}: mcruise={mcr}, "
#             f"mdescent={mds}, casdesc={cds}"
#         )




# import numpy as np
# # Import the global bluesky objects. Uncomment the ones you need
# from bluesky import core, stack, traf  #, settings, navdb, sim, scr, tools
# from bluesky.traffic import Autopilot
# def init_plugin():
#     """
#     Called once by BlueSky when loading the plugin.
#     We return a config dict so BlueSky recognizes us as a 'sim' plugin.
#     Then we do 'IMPLEMENTATION Autopilot MachCrossoverAP' so that
#     new references to Autopilot => MachCrossoverAP.
#     """
#     crossover = MachCrossoverAP()
#     # Replace the default Autopilot with our subclass:
#     stack.stack("IMPLEMENTATION Autopilot MachCrossoverAP")
#
#     config = {
#         'plugin_name': 'mach_crossover_ap',
#         'plugin_type': 'sim',
#     }
#
#     return config
#
# class Autopilot(Autopilot):
#
#     def __init__(self):
#         super().__init__()

























# """
# mach_crossover_ap.py
#
# A minimal plugin that replaces the default Autopilot with our 'MachCrossoverAP'.
# It holds Mach above a certain altitude, or CAS below it.
#
# Usage:
#  1) Place this file in plugins/ so BlueSky can find it.
#  2) Start BlueSky and type:
#        > loadplugin mach_crossover_ap
#     This will:
#        - do "IMPLEMENTATION Autopilot MachCrossoverAP"
#        - override the normal Autopilot with MachCrossoverAP
#  3) Optionally use:
#        > SETMACHX <ACID> <mcruise> <mdescent> <casdesc>
#     to change Mach-crossover parameters for a given aircraft.
# """
#
# import numpy as np
#
# from bluesky import core, stack, traf
# from bluesky.core import plugin
# from bluesky.traffic import Autopilot
#
# def init_plugin():
#     """
#     Called once by BlueSky when loading the plugin.
#     We return a config dict so BlueSky recognizes us as a 'sim' plugin.
#     Then we do 'IMPLEMENTATION Autopilot MachCrossoverAP' so that
#     new references to Autopilot => MachCrossoverAP.
#     """
#     crossover = MachCrossoverAP()
#     # Replace the default Autopilot with our subclass:
#     stack.stack("IMPLEMENTATION Autopilot MachCrossoverAP")
#
#     config = {
#         'plugin_name': 'mach_crossover_ap',
#         'plugin_type': 'sim',
#     }
#
#     return config
#
#
# class MachCrossoverAP(core.Entity):
#     """
#     A subclass of the Autopilot that adds Mach-crossover arrays and
#     overrides the update() function with our Mach-crossover logic.
#     """
#
#     def __init__(self):
#         super().__init__()
#         # Create new arrays in settrafarrays() context:
#         with self.settrafarrays():
#             self.mcruise  = np.array([])  # default cruise Mach
#             self.mdescent = np.array([])  # descent Mach
#             self.casdesc  = np.array([])  # descent CAS (knots)
#         print('trafarrays set')
#
#     def create(self, n=1):
#         """
#         Called automatically when new aircraft are created.
#         We expand our arrays and set default values.
#         """
#         super().create(n)
#         self.mcruise[-n:] = [0.78 for _ in range(n)]
#         self.mdescent[-n:] = [0.76 for _ in range(n)]
#         self.casdesc[-n:] = [280 for _ in range(n)]
#         print('create')
#
#     def delete(self, idx):
#         """
#         Called automatically when aircraft are deleted.
#         Remove their entries from our arrays.
#         """
#         super().delete(idx)
#         idx = np.atleast_1d(idx)
#         idx.sort()
#         idx = idx[::-1]  # delete highest indices first
#
#         with self.settrafarrays():
#             for i in idx:
#                 self.mcruise  = np.delete(self.mcruise,  i)
#                 self.mdescent = np.delete(self.mdescent, i)
#                 self.casdesc  = np.delete(self.casdesc,  i)
#
#     def update(self):
#         """
#         Called once every simulation step by BlueSky.
#         - First run the normal autopilot logic (super().update()).
#         - Then override the selected speed 'selspd' to do Mach-crossover:
#              * If altitude > FL100, hold Mach if CAS < casdesc, else hold casdesc
#              * If altitude <= FL100, clamp to min(250, casdesc)
#         """
#         super().update()  # let standard autopilot do its headings, LNAV, etc.
#
#         # For convenience:
#         ft  = core.ft
#         kts = core.kts
#
#         for i in range(self.ntraf):
#             alt_ft  = self.alt[i] / ft
#             cas_kts = self.cas[i] / kts
#
#             # Get our arrays for this aircraft:
#             md = self.mdescent[i]    # e.g. 0.76 (Mach)
#             cd = self.casdesc[i]     # e.g. 280 knots
#
#             if alt_ft > 10000:
#                 # Above 10,000 ft: if current CAS < casdesc => hold Mach, else hold casdesc
#                 if cas_kts < cd:
#                     # BlueSky uses negative speeds to represent Mach hold.
#                     self.selspd[i] = -md
#                 else:
#                     # Switch to that CAS in m/s
#                     self.selspd[i] = cd * kts
#             else:
#                 # Below 10,000 ft => clamp to min(250, casdesc)
#                 final_ias_kts = min(250, cd)
#                 self.selspd[i] = final_ias_kts * kts
#
#     @stack.command
#     def setmachx(self, acid, mcruise, mdescent, casdesc):
#         """
#         SETMACHX <ACID> <mcruise> <mdescent> <casdesc>
#
#         Example:
#           SETMACHX KLM123 0.80 0.76 280
#         """
#         # Convert ACID to index:
#         idx = traf.id2idx(acid)
#         if idx < 0:
#             return False, f"Aircraft {acid} not found."
#
#         # Parse floats:
#         try:
#             mcr = float(mcruise)
#             mds = float(mdescent)
#             cds = float(casdesc)
#         except ValueError:
#             return False, "Usage: SETMACHX <ACID> <mcruise> <mdescent> <casdesc> (floats)"
#
#         # Set the arrays:
#         self.mcruise[idx]  = mcr
#         self.mdescent[idx] = mds
#         self.casdesc[idx]  = cds
#
#         return True, (
#             f"[mach_crossover_ap] Set MachX for {acid}: mcruise={mcr}, "
#             f"mdescent={mds}, casdesc={cds}"
#         )
# #
# # """
# # Mach_Crossover.py
# #
# # Example plugin with two classes:
# #  1) MachTraffic(Traffic)
# #     - Our custom Traffic subclass
# #     - Stores Mach cross-over arrays
# #     - Overrides update_airspeed() to do the custom logic
# #
# #  2) MachCrossoverPlugin(core.Entity)
# #     - The 'plugin manager' class
# #     - Defines stack commands
# #     - Possibly other plugin logic (on_activate, on_deactivate, etc.)
# #
# # We link them together in init_plugin() using:
# #   stack.stack('IMPLEMENTATION Traffic MachTraffic')
# # """
# #
# # import numpy as np
# # from bluesky import core, stack, traf
# # from bluesky.core import plugin
# # from bluesky.traffic import Traffic
# #
# # def init_plugin():
# #     """
# #     Called once by BlueSky when loading the plugin.
# #     Return a config dict so BlueSky recognizes us as a 'sim' plugin.
# #
# #     We'll do:
# #       IMPLEMENTATION Traffic MachTraffic
# #     so that newly created aircraft use MachTraffic instead of the default Traffic.
# #     """
# #     # 1) We cause new references to Traffic => MachTraffic
# #
# #
# #     # 2) Create an instance of the plugin manager class (if needed)
# #     mc_plugin = MachCrossoverPlugin()
# #
# #     # 3) Return a config dict so BlueSky knows this is a sim plugin
# #     config = {
# #         'plugin_name': 'mach_crossover',
# #         'plugin_type': 'sim',
# #     }
# #     return config
# #
# #
# # class MachTraffic(Traffic):
# #     """
# #     Subclass of Traffic for Mach crossover logic.
# #
# #     - override create(), delete() to maintain new arrays
# #     - override update_airspeed() to impose Mach-based logic
# #     """
# #
# #     def __init__(self):
# #         super().__init__()
# #         # Add arrays
# #         print(' machtraffic init called')
# #         with self.settrafarrays():
# #             self.mcruise  = np.array([])
# #             self.mdescent = np.array([])
# #             self.casdesc  = np.array([])
# #
# #     def create(self, n=1):
# #         """
# #         Called automatically when new aircraft are created.
# #         Expand the arrays for those new aircraft.
# #         """
# #         super().create(n)
# #         self.mcruise[-n:] = [0.78 for _ in range(n)]
# #         self.mdescent[-n:] = [0.76 for _ in range(n)]
# #         self.casdesc[-n:] = [280 for _ in range(n)]
# #         print('created in machtraffic')
# #
# #     def delete(self, idx):
# #         """
# #         Called automatically when aircraft are deleted.
# #         Remove the corresponding entries in our arrays.
# #         """
# #         super().delete(idx)
# #         idx = np.atleast_1d(idx)
# #         idx.sort()
# #         idx = idx[::-1]
# #         with self.settrafarrays():
# #             for i in idx:
# #                 self.mcruise  = np.delete(self.mcruise,  i)
# #                 self.mdescent = np.delete(self.mdescent, i)
# #                 self.casdesc  = np.delete(self.casdesc,  i)
# #
# #     def update_airspeed(self):
# #         """
# #         Override the autopilot speed logic to do Mach-crossover.
# #
# #         1) Let the normal autopilot run first (super().update_airspeed()).
# #         2) Then, for each aircraft, decide whether to hold Mach or CAS
# #            based on altitude, CAS, etc.
# #         """
# #         # 1) Normal autopilot logic
# #         super().update_airspeed()
# #
# #         # 2) Adjust speeds as desired
# #         ft  = core.ft
# #         kts = core.kts
# #         for i in range(self.ntraf):
# #             alt_ft  = self.alt[i] / ft
# #             cas_kts = self.cas[i] / kts
# #
# #             md = self.mdescent[i]  # e.g. 0.76
# #             cd = self.casdesc[i]   # in kts
# #
# #             if alt_ft > 10000:
# #                 # If CAS < cd => hold Mach
# #                 if cas_kts < cd:
# #                     self.selspd[i] = -md  # negative => Mach hold
# #                 else:
# #                     self.selspd[i] = cd * kts
# #             else:
# #                 # Below 10000 => clamp to min(250, cd)
# #                 final_ias_kts = min(250, cd)
# #                 self.selspd[i] = final_ias_kts * kts
# #
# #
# # class MachCrossoverPlugin(core.Entity):
# #     """
# #     A separate plugin 'manager' that can define stack commands, etc.
# #     Inheriting from core.Entity means we can do plugin-type tasks
# #     without interfering with the core Traffic system.
# #
# #     This is useful if inheriting from Traffic directly for the plugin
# #     breaks stack commands or plugin lifecycle events.
# #     """
# #
# #     def __init__(self):
# #         super().__init__()
# #         stack.stack('IMPLEMENTATION MachTraffic Traffic')
# #         print("[MachCrossoverPlugin] Created plugin manager")
# #
# #     @stack.command
# #     def setmachx(self, acid, mcruise, mdescent, casdesc):
# #         """
# #         Stack command to set Mach-crossover parameters for a given aircraft.
# #
# #         Usage:
# #           SETMACHX <ACID> <mcruise> <mdescent> <casdesc>
# #         e.g.:
# #           SETMACHX KLM123 0.80 0.76 280
# #         """
# #         idx = traf.id2idx(acid)
# #         if idx < 0:
# #             return False, f"Aircraft {acid} not found."
# #
# #         try:
# #             mcr = float(mcruise)
# #             mds = float(mdescent)
# #             cds = float(casdesc)
# #         except ValueError:
# #             return False, "Usage: SETMACHX ACID mcruise mdescent casdesc (floats)"
# #
# #         # We assume our traffic object is already replaced by MachTraffic,
# #         # so these arrays exist.
# #         traf.mcruise[idx]  = mcr
# #         traf.mdescent[idx] = mds
# #         traf.casdesc[idx]  = cds
# #
# #         return True, (
# #             f"Set MachX for {acid}: mcruise={mcr}, "
# #             f"mdescent={mds}, casdesc={cds}"
# #         )
# #
# #
# # # """
# # # Mach_Crossover.py
# # #
# # # Single-class plugin that:
# # #  - Inherits from Traffic,
# # #  - Overrides update_airspeed() to apply Mach-crossover logic,
# # #  - Stores new arrays (mcruise, mdescent, casdesc),
# # #  - Provides a stack command SETMACHX to set per-aircraft values,
# # #  - Calls IMPLEMENTATION so that new traffic references use this class.
# # # """
# # #
# # # import numpy as np
# # # from bluesky import core, stack, traf
# # # from bluesky.core import plugin
# # # from bluesky.traffic import Traffic
# # #
# # # def init_plugin():
# # #     """
# # #     BlueSky calls this once when loading the plugin.
# # #     Return a config dict so BlueSky recognizes us as a 'sim' plugin.
# # #
# # #     We'll also do 'IMPLEMENTATION Traffic MachCrossover' so that any new
# # #     references to 'Traffic' become our custom MachCrossover class.
# # #     """
# # #     global crossoverplugin
# # #     crossoverplugin = MachCrossover()
# # #     config = {
# # #         'plugin_name': 'mach_crossover',
# # #         'plugin_type': 'sim',
# # #     }
# # #
# # #     # Tell BlueSky to replace the normal Traffic class with ours
# # #     stack.stack('IMPLEMENTATION Traffic MachCrossover')
# # #
# # #     return config
# # #
# # # class MachCrossover(core.Entity):
# # #     """
# # #     Our single plugin class that inherits from Traffic.
# # #     We override update_airspeed() using the 'selected' snippet,
# # #     and store new arrays for Mach-crossover parameters.
# # #     """
# # #
# # #     def __init__(self):
# # #         super().__init__()
# # #         with self.settrafarrays():
# # #             self.mcruise  = np.array([])  # Optional "cruise Mach"
# # #             self.mdescent = np.array([])  # Descent Mach
# # #             self.casdesc  = np.array([])  # Descent CAS (knots)
# # #
# # #     def create(self, n =1):
# # #         """
# # #         Override create() so that if new aircraft are added,
# # #         we also expand mcruise[], mdescent[], casdesc[] with default values.
# # #         """
# # #
# # #         super().create(n)
# # #
# # #         # Append default Mach/cas to new aircraft
# # #
# # #         self.mcruise[-n:]  =[0.78 for _ in range(n)]
# # #         self.mdescent[-n:] = [0.76 for _ in range(n)]
# # #         self.casdesc[-n:]  =[280 for _ in range(n)]
# # #
# # #     def delete(self, idx):
# # #         """
# # #         Remove the corresponding entries in our arrays
# # #         when aircraft are deleted.
# # #         """
# # #         super().delete(idx)
# # #         idx = np.atleast_1d(idx)
# # #         idx.sort()
# # #         idx = idx[::-1]  # delete highest indices first
# # #
# # #
# # #         for i in idx:
# # #             self.mcruise  = np.delete(self.mcruise, i)
# # #             self.mdescent = np.delete(self.mdescent, i)
# # #             self.casdesc  = np.delete(self.casdesc, i)
# # #
# # #     def update_airspeed(self):
# # #         """
# # #         Override the autopilot speed update to implement Mach-crossover logic.
# # #
# # #         Steps:
# # #           1) Run the normal autopilot logic (super().update_airspeed()) first.
# # #           2) For each aircraft:
# # #              - If altitude > FL100:
# # #                  * If CAS < casdesc => hold descent Mach (negative => Mach in BlueSky)
# # #                  * Else => hold casdesc
# # #              - If altitude <= FL100 => clamp to 250 or casdesc, whichever is lower.
# # #         """
# # #         super().Traffic.update_airspeed()
# # #         print('update airspeed called')
# # #
# # #         # from bluesky import core  # to access core.ft, core.kts
# # #         for i in range(self.ntraf):
# # #             alt_ft    = self.alt[i] / core.ft
# # #             cas_kts   = self.cas[i] / core.kts
# # #             mach_des  = self.mdescent[i]
# # #             cas_des   = self.casdesc[i]
# # #
# # #             if alt_ft > 10000:
# # #                 # If CAS < descent CAS => hold Mach
# # #                 if cas_kts < cas_des:
# # #                     self.selspd[i] = -mach_des  # negative => Mach hold
# # #                 else:
# # #                     # Switch to that CAS
# # #                     self.selspd[i] = cas_des * core.kts
# # #             else:
# # #                 # Below FL100 => clamp to 250 or descent CAS
# # #                 final_ias_kts = min(250, cas_des)
# # #                 self.selspd[i] = final_ias_kts * core.kts
# # #
# # #         print(self.selspd)
# # #
# # #     @stack.command
# # #     def setmachx(self, acid, mcruise, mdescent, casdesc):
# # #         """
# # #         Stack command to set Mach-crossover parameters for an aircraft.
# # #         Usage:
# # #             SETMACHX <ACID> <mcruise> <mdescent> <casdesc>
# # #         Example:
# # #             SETMACHX KLM123 0.80 0.76 280
# # #         """
# # #         idx = traf.id2idx(acid)
# # #         if idx < 0:
# # #             return False, f"Aircraft {acid} not found."
# # #
# # #         try:
# # #             mcr = float(mcruise)
# # #             mds = float(mdescent)
# # #             cds = float(casdesc)
# # #         except ValueError:
# # #             return False, "Usage: SETMACHX ACID mcruise mdescent casdesc (floats)"
# # #
# # #         self.mcruise[idx]  = mcr
# # #         self.mdescent[idx] = mds
# # #         self.casdesc[idx]  = cds
# # #
# # #         return True, (
# # #             f"{acid} Mach-crossover updated => "
# # #             f"mcruise={mcr}, mdescent={mds}, casdesc={cds}"
# # #         )
# # #
# # #
# # # # """
# # # # Mach_Crossover.py
# # # #
# # # # A simple plugin that:
# # # #  - Creates an Entity named MachCrossover
# # # #  - Stores Mach-crossover parameters (mcruise, mdescent, casdesc) per aircraft
# # # #  - Each timestep, forces the airspeed to mimic Mach-crossover logic
# # # #  - Provides a stack command SETMACHX to set per-aircraft values
# # # # """
# # # #
# # # # import numpy as np
# # # #
# # # # # Import BlueSky core objects
# # # # from bluesky import core, stack
# # # # from bluesky.core import plugin
# # # #
# # # # def init_plugin():
# # # #     """
# # # #     Plugin initialization function. BlueSky calls this once when loading.
# # # #     Return a config dict so BlueSky recognizes us as a 'sim' plugin.
# # # #     """
# # # #     config = {
# # # #         'plugin_name': 'mach_crossover',
# # # #         'plugin_type': 'sim',
# # # #     }
# # # #     # Instantiate our entity
# # # #     mc = MachCrossover()
# # # #     return config
# # # #
# # # # class MachCrossover(core.Entity):
# # # #     """
# # # #     A single-class plugin that stores Mach-crossover parameters
# # # #     and enforces them each timestep in the update() function.
# # # #     """
# # # #
# # # #     def __init__(self):
# # # #         super().__init__()
# # # #
# # # #         # Create new per-aircraft arrays for storing Mach-crossover data
# # # #         with self.settrafarrays():
# # # #             self.mcruise  = np.array([])  # example: not used in the logic below, but you can store it
# # # #             self.mdescent = np.array([])  # descent Mach
# # # #             self.casdesc  = np.array([])  # descent CAS (kts)
# # # #
# # # #     def create(self, n=1):
# # # #         """
# # # #         Called automatically when new aircraft are created.
# # # #         We expand our arrays and set default values.
# # # #         """
# # # #         super().create(n)   # always call parent create first
# # # #         with self.settrafarrays():
# # # #             self.mcruise  = np.append(self.mcruise,  [0.78]*n)
# # # #             self.mdescent = np.append(self.mdescent, [0.76]*n)
# # # #             self.casdesc  = np.append(self.casdesc,  [280]*n)
# # # #
# # # #     def delete(self, idx):
# # # #         """
# # # #         Called automatically when aircraft are deleted.
# # # #         Remove their entries from our arrays.
# # # #         """
# # # #         super().delete(idx)
# # # #         idx = np.atleast_1d(idx)
# # # #         idx.sort()
# # # #         idx = idx[::-1]  # reverse so we delete highest indices first
# # # #
# # # #         with self.settrafarrays():
# # # #             for i in idx:
# # # #                 self.mcruise  = np.delete(self.mcruise,  i)
# # # #                 self.mdescent = np.delete(self.mdescent, i)
# # # #                 self.casdesc  = np.delete(self.casdesc,  i)
# # # #
# # # #     @core.timed_function(name='machx', dt=1.0)
# # # #     def update(self):
# # # #         """
# # # #         Called every 'dt' seconds (here 1s).
# # # #         We enforce Mach-crossover logic by directly setting self.selspd[i].
# # # #         """
# # # #         from bluesky import core
# # # #         ft  = core.ft
# # # #         kts = core.kts
# # # #
# # # #         for i in range(self.ntraf):
# # # #             alt_ft  = self.alt[i] / ft
# # # #             cas_kts = self.cas[i] / kts
# # # #
# # # #             mach_des = self.mdescent[i]
# # # #             cas_des  = self.casdesc[i]
# # # #
# # # #             # Simple Mach-crossover logic:
# # # #             # 1) Above 10k ft: hold Mach until CAS >= cas_des, then hold cas_des
# # # #             # 2) Below 10k ft: clamp to 250 or cas_des, whichever is lower
# # # #             if alt_ft > 10000:
# # # #                 if cas_kts < cas_des:
# # # #                     # Mach hold => store as negative Mach
# # # #                     self.selspd[i] = -mach_des
# # # #                 else:
# # # #                     # Switch to descent CAS
# # # #                     self.selspd[i] = cas_des * kts
# # # #             else:
# # # #                 # Below FL100 => clamp speed to 250 or cas_des
# # # #                 final_ias_kts = min(250, cas_des)
# # # #                 self.selspd[i] = final_ias_kts * kts
# # # #
# # # #     @stack.command
# # # #     def setmachx(self, acid: 'acid', mcruise: float, mdescent: float, casdesc: float):
# # # #         """
# # # #         Stack command:
# # # #           SETMACHX <acid> <mcruise> <mdescent> <casdesc>
# # # #
# # # #         Example:
# # # #           SETMACHX KLM123 0.80 0.76 280
# # # #         """
# # # #         i = acid  # 'acid' is already converted to an index by the annotation
# # # #         self.mcruise[i]  = mcruise
# # # #         self.mdescent[i] = mdescent
# # # #         self.casdesc[i]  = casdesc
# # # #
# # # #         return True, (
# # # #             f"Set MachX for aircraft {self.id[i]} => "
# # # #             f"mcruise={mcruise}, mdescent={mdescent}, casdesc={casdesc}"
# # # #         )
# # # #
# # # #
# # # #
# # # # # """
# # # # # Mach_Crossover.py
# # # # #
# # # # # Example plugin that adds Mach-crossover arrays (mcruise, mdescent, casdesc)
# # # # # to a Traffic subclass, similarly to how trajectory_predictor_new does it for Route.
# # # # # """
# # # # #
# # # # # import numpy as np
# # # # #
# # # # # from bluesky import core, stack, traf
# # # # # from bluesky.core import plugin
# # # # # from bluesky.traffic import Traffic
# # # # # from bluesky import sim
# # # # #
# # # # # def init_plugin():
# # # # #     """
# # # # #     Called by BlueSky when the plugin is loaded.
# # # # #     Return a config dict so BlueSky recognizes us as a 'sim' plugin.
# # # # #     """
# # # # #     config = {
# # # # #         'plugin_name': 'mach_crossover',
# # # # #         'plugin_type': 'sim'
# # # # #     }
# # # # #     # We create a plugin entity (MachCrossoverPlugin) so we can define stack commands, etc.
# # # # #     mc_plugin = MachCrossoverPlugin()
# # # # #     return config
# # # # #
# # # # #
# # # # # class Traffic(Traffic):
# # # # #     """
# # # # #     Custom Traffic class that inherits from BlueSky's Traffic.
# # # # #     Similar to how 'trajectory_predictor_new' extends Route.
# # # # #
# # # # #     We add new arrays:
# # # # #       - mcruise[i]  : Cruise Mach
# # # # #       - mdescent[i] : Descent Mach
# # # # #       - casdesc[i]  : Descent CAS (kts)
# # # # #     Then override update_airspeed() to do a simple Mach-crossover:
# # # # #       - Above FL100: hold descent Mach until current CAS >= casdesc, then switch to holding casdesc
# # # # #       - Below FL100: clamp to 250 KIAS (or casdesc, whichever is lower)
# # # # #     """
# # # # #
# # # # #     def __init__(self):
# # # # #         super().__init__()
# # # # #         # Create empty arrays for Mach-crossover parameters
# # # # #         with self.settrafarrays():
# # # # #             self.mcruise = np.array([])
# # # # #             self.mdescent = np.array([])
# # # # #             self.casdesc = np.array([])
# # # # #
# # # # #     def create(self, *args, **kwargs):
# # # # #         """
# # # # #         Override create() so that if new aircraft are added,
# # # # #         we also expand mcruise[], mdescent[], and casdesc[].
# # # # #         """
# # # # #         # Determine how many new aircraft are created
# # # # #         nnew = 1
# # # # #         if 'n' in kwargs:
# # # # #             nnew = kwargs['n']
# # # # #
# # # # #         # Call the original create() to add the aircraft
# # # # #         super().create(*args, **kwargs)
# # # # #
# # # # #         # Now expand our new arrays for these newly created aircraft
# # # # #         with self.settrafarrays():
# # # # #             self.mcruise = np.append(self.mcruise, [0.78] * nnew)  # default cruise Mach
# # # # #             self.mdescent = np.append(self.mdescent, [0.76] * nnew)  # default descent Mach
# # # # #             self.casdesc = np.append(self.casdesc, [280] * nnew)  # default descent CAS
# # # # #
# # # # #     def delete(self, idx):
# # # # #         """
# # # # #         Override delete() to remove the corresponding entries in our new arrays.
# # # # #         """
# # # # #         super().delete(idx)
# # # # #         idx = np.atleast_1d(idx)
# # # # #         idx.sort()
# # # # #         idx = idx[::-1]  # reverse so we delete from highest to lowest
# # # # #
# # # # #         with self.settrafarrays():
# # # # #             for i in idx:
# # # # #                 self.mcruise = np.delete(self.mcruise, i)
# # # # #                 self.mdescent = np.delete(self.mdescent, i)
# # # # #                 self.casdesc = np.delete(self.casdesc, i)
# # # # #
# # # # #     def update_airspeed(self):
# # # # #         """
# # # # #         Override the autopilot speed update to implement Mach-crossover logic.
# # # # #
# # # # #         Steps:
# # # # #           1) Run the normal autopilot logic (super().update_airspeed()) first.
# # # # #           2) For each aircraft:
# # # # #              - If altitude > FL100:
# # # # #                 * If CAS < casdesc => hold descent Mach
# # # # #                 * Else => hold casdesc
# # # # #              - If altitude <= FL100 => clamp to 250 or casdesc, whichever is lower.
# # # # #         """
# # # # #         # First do normal autopilot speed logic
# # # # #         super().update_airspeed()
# # # # #
# # # # #         from bluesky import core  # to access core.ft, core.kts
# # # # #         for i in range(self.ntraf):
# # # # #             alt_ft = self.alt[i] / core.ft
# # # # #             cas_kts = self.cas[i] / core.kts
# # # # #
# # # # #             descent_mach = self.mdescent[i]
# # # # #             descent_cas = self.casdesc[i]  # in knots
# # # # #
# # # # #             if alt_ft > 10000:
# # # # #                 # If CAS < descent CAS => hold Mach (store as negative => Mach in BlueSky)
# # # # #                 if cas_kts < descent_cas:
# # # # #                     self.selspd[i] = -descent_mach
# # # # #                 else:
# # # # #                     # Switch to that CAS in m/s
# # # # #                     self.selspd[i] = descent_cas * core.kts
# # # # #             else:
# # # # #                 # Below 10,000 ft => clamp speed to 250 KIAS or the descent CAS, whichever is lower
# # # # #                 final_ias_kts = min(descent_cas, 250)
# # # # #                 self.selspd[i] = final_ias_kts * core.kts
# # # # #
# # # # #
# # # # #
# # # # #
# # # # #
# # # # # class MachCrossoverPlugin(core.Entity):
# # # # #     """
# # # # #     This plugin entity can define any stack commands or additional logic.
# # # # #     For example, a command to set each aircraft's Mach-crossover values.
# # # # #     """
# # # # #
# # # # #     def __init__(self):
# # # # #         super().__init__()
# # # # #         stack.stack('IMPLEMENTATION Traffic Traffic')
# # # # #
# # # # #     @stack.command
# # # # #     def setmachx(self, acid, mcruise, mdescent, casdesc):
# # # # #         """
# # # # #         SETMACHX ACID mcruise mdescent casdesc
# # # # #
# # # # #         Example:
# # # # #             SETMACHX KLM123 0.80 0.76 280
# # # # #
# # # # #         This sets the Mach-crossover parameters for aircraft `acid`.
# # # # #         """
# # # # #         # Convert to floats
# # # # #         try:
# # # # #             mcr = float(mcruise)
# # # # #             mds = float(mdescent)
# # # # #             cds = float(casdesc)
# # # # #         except ValueError:
# # # # #             return False, "Usage: SETMACHX ACID mcruise mdescent casdesc (all numeric)"
# # # # #
# # # # #         idx = traf.id2idx(acid)
# # # # #         if idx < 0:
# # # # #             return False, f"Aircraft {acid} not found."
# # # # #
# # # # #         # Set the arrays
# # # # #         traf.mcruise[idx] = mcr
# # # # #         traf.mdescent[idx] = mds
# # # # #         traf.casdesc[idx] = cds
# # # # #
# # # # #         return True, f"Mach-crossover updated for {acid}: mcruise={mcr}, mdescent={mds}, casdesc={cds}"
# # # # #
# # # # #
# # # # #
# # # # # # """
# # # # # # Mach_Crossover.py
# # # # # #
# # # # # # A plugin that replaces the default traffic object with MyTraffic, which:
# # # # # #  - Inherits from traffic.Traffic
# # # # # #  - Adds arrays for mcruise[], mdescent[], casdesc[]
# # # # # #  - Overrides create(), delete(), update_airspeed() to handle those arrays
# # # # # #  - Provides a stack command SETMACHX to set Mach-crossover parameters.
# # # # # # """
# # # # # #
# # # # # # import numpy as np
# # # # # #
# # # # # # from bluesky import core, stack, traf
# # # # # # from bluesky.core import plugin
# # # # # # from bluesky.traffic import Traffic
# # # # # #
# # # # # #
# # # # # # def init_plugin():
# # # # # #     """
# # # # # #     Called when the plugin is loaded.
# # # # # #     Return a config dict so BlueSky recognizes us as a plugin entity.
# # # # # #     """
# # # # # #     config = {
# # # # # #         'plugin_name': 'mach_crossover',
# # # # # #         'plugin_type': 'sim'
# # # # # #     }
# # # # # #     # Create the plugin instance
# # # # # #     mc_plugin = MachCrossoverPlugin()
# # # # # #     return config
# # # # # #
# # # # # #
# # # # # # class Traffic(Traffic):
# # # # # #     """
# # # # # #     Custom traffic class that inherits from BlueSky's Traffic.
# # # # # #     We add new arrays for Mach crossover parameters:
# # # # # #         mcruise[i]   = cruise Mach
# # # # # #         mdescent[i]  = descent Mach
# # # # # #         casdesc[i]   = descent CAS (in knots)
# # # # # #     """
# # # # # #
# # # # # #     def __init__(self):
# # # # # #         super().__init__()
# # # # # #         with self.settrafarrays():
# # # # # #             self.mcruise = np.array([])
# # # # # #             self.mdescent = np.array([])
# # # # # #             self.casdesc = np.array([])
# # # # # #
# # # # # #     def create(self, *args, **kwargs):
# # # # # #         """
# # # # # #         Override create() so that if new aircraft are added,
# # # # # #         we also expand mcruise[], mdescent[], casdesc[] for them.
# # # # # #         """
# # # # # #         # Number of new aircraft we are creating
# # # # # #         nnew = 1
# # # # # #         if 'n' in kwargs:
# # # # # #             nnew = kwargs['n']  # sometimes traffic.create() is called with n=...
# # # # # #
# # # # # #         # Call the original create() to add the aircraft
# # # # # #         super().create(*args, **kwargs)
# # # # # #
# # # # # #         # Expand our arrays for new aircraft with default values
# # # # # #         with self.settrafarrays():
# # # # # #             self.mcruise = np.append(self.mcruise, [0.78] * nnew)  # example default
# # # # # #             self.mdescent = np.append(self.mdescent, [0.76] * nnew)
# # # # # #             self.casdesc = np.append(self.casdesc, [280] * nnew)
# # # # # #
# # # # # #     def delete(self, idx):
# # # # # #         """
# # # # # #         Override delete() to remove the corresponding entries from our arrays.
# # # # # #         idx = index or list of indices of the aircraft to delete
# # # # # #         """
# # # # # #         super().delete(idx)
# # # # # #         # Make sure idx is a list/array
# # # # # #         idx = np.atleast_1d(idx)
# # # # # #         idx.sort()
# # # # # #         idx = idx[::-1]  # reverse, so we delete from highest to lowest
# # # # # #
# # # # # #         with self.settrafarrays():
# # # # # #             for i in idx:
# # # # # #                 self.mcruise = np.delete(self.mcruise, i)
# # # # # #                 self.mdescent = np.delete(self.mdescent, i)
# # # # # #                 self.casdesc = np.delete(self.casdesc, i)
# # # # # #
# # # # # #     def update_airspeed(self):
# # # # # #         """
# # # # # #         Override the airspeed update to demonstrate simple Mach-crossover logic:
# # # # # #           - Above FL100: fly descent Mach until CAS >= casdesc[], then switch to casdesc
# # # # # #           - Below FL100: clamp 250 KIAS (or if casdesc < 250, keep that).
# # # # # #         """
# # # # # #         # First call the original autopilot logic
# # # # # #         super().update_airspeed()
# # # # # #
# # # # # #         # Then override speeds as needed
# # # # # #         for i in range(self.ntraf):
# # # # # #             altitude_ft = self.alt[i] / core.ft
# # # # # #             cas_kts = self.cas[i] / core.kts
# # # # # #
# # # # # #             # Our stored Mach / speed
# # # # # #             m_des = self.mdescent[i]
# # # # # #             casdes = self.casdesc[i]
# # # # # #
# # # # # #             if altitude_ft > 10000:
# # # # # #                 # If CAS < desired descent CAS, hold Mach
# # # # # #                 # (In BlueSky’s logic, we store Mach as a negative number in selspd[].)
# # # # # #                 if cas_kts < casdes:
# # # # # #                     self.selspd[i] = -m_des  # negative => Mach
# # # # # #                 else:
# # # # # #                     # Switch to that CAS
# # # # # #                     self.selspd[i] = casdes * core.kts
# # # # # #             else:
# # # # # #                 # Below 10000 ft, clamp to 250 or the descent CAS, whichever is lower
# # # # # #                 final_ias_kts = min(casdes, 250)
# # # # # #                 self.selspd[i] = final_ias_kts * core.kts
# # # # # #
# # # # # #
# # # # # # #
# # # # # # # Now we make a plugin Entity that replaces sim.traf with our MyTraffic.
# # # # # # #
# # # # # #
# # # # # #
# # # # # #
# # # # # # class MachCrossoverPlugin(core.Entity):
# # # # # #     def __init__(self):
# # # # # #         super().__init__()
# # # # # #         # We'll store a reference to the old traffic object,
# # # # # #         # so that if the plugin is deactivated, we can restore it if desired.
# # # # # #         self.old_traf = None
# # # # # #
# # # # # #     def on_activate(self):
# # # # # #         """
# # # # # #         Called when plugin is activated.
# # # # # #         Replace the global sim.traf with our MyTraffic subclass.
# # # # # #         """
# # # # # #         # sim = self.sim
# # # # # #         # self.old_traf = sim.traf  # store the original
# # # # # #         # sim.traf = MyTraffic()
# # # # # #         print("[mach_crossover] Replaced default Traffic with MyTraffic.")
# # # # # #
# # # # # #     # def on_deactivate(self):
# # # # # #         """
# # # # # #         Optionally restore the old traffic object if we want a clean revert.
# # # # # #         """
# # # # # #         # if self.old_traf is not None:
# # # # # #         #     self.sim.traf = self.old_traf
# # # # # #         #     print("[mach_crossover] Restored original Traffic object.")
# # # # # #
# # # # # #     @stack.command
# # # # # #     def setmachx(self, acid, mcruise, mdescent, casdesc):
# # # # # #         """
# # # # # #         Stack command: SETMACHX ACID mcruise mdescent casdesc
# # # # # #         Example:
# # # # # #             SETMACHX KLM123 0.80 0.76 280
# # # # # #         """
# # # # # #         # sim = self.sim
# # # # # #         try:
# # # # # #             mcr = float(mcruise)
# # # # # #             mds = float(mdescent)
# # # # # #             cds = float(casdesc)
# # # # # #         except ValueError:
# # # # # #             return False, "Usage: SETMACHX ACID mcruise mdescent casdesc (floats)"
# # # # # #
# # # # # #         i = traf.id2idx(acid)
# # # # # #         if i < 0:
# # # # # #             return False, f"Aircraft {acid} not found."
# # # # # #
# # # # # #         traf.mcruise[i] = mcr
# # # # # #         traf.mdescent[i] = mds
# # # # # #         traf.casdesc[i] = cds
# # # # # #
# # # # # #         return True, (
# # # # # #             f"[mach_crossover] {acid} -> mcruise={mcr}, mdescent={mds}, casdesc={cds}."
# # # # # #         )