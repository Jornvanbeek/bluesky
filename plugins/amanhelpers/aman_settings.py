
#file to keep a better overview of aman settings

#note that some of these, which are to be varied, can be found in amantwo as stack commands
# the reason is to change the settings easily in scenario files, or through the stack at startup


max_dogleg_ratio = 1.4
# freezehorizon = 14 * 60
# freezehorizon = 16 * 60
freezehorizon = 20 * 60
capacity = 36#34 #aircraft per hour, if no LIV, per runway (actual capacity +2)
popup_planner ='FCFS'
# popup_planner = 'DELAY'
error_multiplicator = (1.0,1.0,1.0,1.0)
# error_multiplicator = (0,0,0,0)

iafs = ['ARTIP', 'SUGOL', 'RIVER']
firname = 'FIRNL'

planninghorizon = freezehorizon + 15*60
TMA_scan = 5 * 60  # only aircraft within 5 mins of the tma get checked if they are in the tma
standard_visible_altitude = 13000  # (FL130)
visible_altitude_specific = {'EGSH': 10000, 'EGSS': 10000,'EGLC': 10000, 'EDDL': 2000, 'EDDW':2000, 'EBBR':1000, 'EDDV':5000}
# separation = 75
standard_early = 60  # seconds that ASAP plans early if there is no slot taken before the slot being planned, make negative?
late_approach_margin = 120
early_approach_margin = 120  # s
instruction_margin = 20 # allowed error by ATC from expected eat
approach_aim = 0  # 90 seconds before eat if an instruction is given is the aim (make negative)
late_adjacent_threshold = 2 * 60  # if an aircraft is late then this is the threshold before communicating to an adjacent center
early_adjacent_threshold = 2 * 60  # if an aircraft is early, then this is the ttlg threshold before communicating to an adjacent center, make negative?
instruct = True # easy setting to disable all instructions to frozen aircraft
mach_reduction = 0.04
max_speedup = 25  # knots
max_slowdown = 50  # knots
abs_minspd = 190  # knots outside of tma
nearby_threshold = 180  # seconds before iaf, no more instructions possible
dogleg_multiplyer = 0.99
descent_angle = 3.0  # degrees

max_timegain_popup = 2 *60 # if this is not possible because aircraft not spawned: replan. if airborne: normal check
expected_delay_percentile = 75

mach_threshold = 0
handover_alt = 260.0 * 100  # ft (FL260)

max_updates = 10
print_updates = True
TP_DT = 3.0 #s

#amount of instructions per type of instruction given to each aircraft
count_normal = 1
count_dogleg = 2
count_holding = 4

dynamic_LIV = False

separation = round(60*60/capacity,0)

# error multiplicator for different error types: departure time, departure route, enroute, within fir


# ErrorGenerator settings (used by plugins/errorgenerator.py)
# Only settings that have concrete defaults (not None) live here.
errorstart = 26.0*60 #start of error application. must be before freeze horizon
max_groundspeed_factor = 1.5
min_groundspeed_factor = 0.5
departure_route_title = 'SID_rel'
stddev_withinfir = 1.5  # %
# JohnsonSU params: (a, b, loc, scale)
cop_pdf = (-0.1840341263226265, 1.3898584120283286, -0.22623562655786733, 9.968335882486613)
PDF_file = 'plugins/PDF.pkl'