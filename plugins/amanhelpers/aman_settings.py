#file to keep a better overview of aman settings

iafs = ['ARTIP', 'SUGOL', 'RIVER']
firname = 'FIRNL'
planninghorizon = 40*60
freezehorizon = 25 * 60
TMA_scan = 5 * 60  # only aircraft within 5 mins of the tma get checked if they are in the tma
visible_altitude = 0  # (FL100)
# separation = 75
standard_early = 60  # seconds that ASAP plans early if there is no slot taken before the slot being planned, make negative?
late_approach_margin = 120
early_approach_margin = 120  # s, make negative?
instruction_margin = 20 # allowed error by ATC from expected eat
tight_margin = 20  # if only a speed instruction is required, in the first instruction, for optimization purposes, from aim
tighter_count = 10  # if aircraft has 1 or 0 instructions: tight approach margin is used
approach_aim = 0  # 90 seconds before eat if an instruction is given is the aim (make negative)
late_adjacent_threshold = 5 * 60  # if an aircraft is late then this is the threshold before communicating to an adjacent center
early_adjacent_threshold = 5 * 60  # if an aircraft is early, then this is the ttlg threshold before communicating to an adjacent center, make negative?
instruct = True # easy setting to disable all instructions to frozen aircraft
mach_reduction = 0.04
max_speedup = 25  # knots
max_slowdown = 50  # knots
abs_minspd = 190  # knots outside of tma
nearby_threshold = 120  # seconds before iaf, no more instructions possible
dogleg_multiplyer = 0.99
descent_angle = 3.0  # degrees




TP_DT = 3.0 #s



dynamic_LIV = False
capacity = 34 #aircraft per hour, if no LIV
separation = round(60*60/capacity,0)



