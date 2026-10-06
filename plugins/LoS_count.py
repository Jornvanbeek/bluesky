from copy import deepcopy

import numpy as np

from bluesky import core, net, sim, stack, traf
from bluesky.core import timed_function
from bluesky.traffic.asas.detection import ConflictDetection
from bluesky.traffic.performance.openap import coeff
from bluesky.tools import geo
from bluesky.tools.aero import ft, nm
from plugins.ARA_settings import LOS_SETTINGS, SEPARATION_LEVELS
from plugins import ARA_settings
from bluesky.core import plugin
# from plugins.flight_scheduler import  counters



def init_plugin():
    global los_counter
    los_counter = LoSCounter()
    return {
        'plugin_name': 'LOS_COUNT',
        'plugin_type': 'sim',
    }


class LoSCounter(core.Entity):

    def __init__(self):
        super().__init__()
        self.separation_levels = deepcopy(SEPARATION_LEVELS)
        self.level_names = tuple(self.separation_levels.keys())
        self.detection_dt = float(LOS_SETTINGS.get("detection_dt", 1.0))
        self.protection_zone_draw_factor = float(LOS_SETTINGS["protection_zone_draw_factor"])
        self.protection_zone_aircraft = set()
        self.protection_zones_shown = False
        self.previous_positions = {}
        self.reset_events()
        # self.scheduler = plugin.Plugin.plugins['AMANTWO'].imp.AMAN
        self.scheduler = plugin.Plugin.plugins['SCHEDULER'].imp.scheduler #its very important that in settings, scheduler is imported first as a plugin!!!

    def reset(self):
        self.reset_events()
        self.protection_zone_aircraft = set()
        self.protection_zones_shown = False
        self.previous_positions = {}

    def reset_events(self):
        self.active_events = {level_name: {} for level_name in self.level_names}
        self.finished_events = {level_name: [] for level_name in self.level_names}


    @timed_function(dt=1.0)
    def detect(self):
        """Check every second which aircraft pairs are inside each level."""
        self.update_protection_zones()
        if traf.ntraf < 2:
            self.update_previous_positions()
            return

        horizontal_distance, vertical_distance = self.distance_matrices()
        current_events = {level_name: {} for level_name in self.level_names}
        largest_radius = self.first_level_max_radius()

        for i in range(traf.ntraf):
            for j in range(i + 1, traf.ntraf):
                horizontal = float(horizontal_distance[i, j])
                if horizontal > 2.0 * largest_radius:
                    continue

                vertical = float(vertical_distance[i, j])
                self.detect_pair(i, j, horizontal, vertical, current_events)

        for level_name in self.level_names:
            self.update_events(
                current_events[level_name],
                self.active_events[level_name],
                self.finished_events[level_name],
                level_name,
            )
        self.update_previous_positions()

    def distance_matrices(self):
        _, distance_nm = geo.kwikqdrdist_matrix(
            np.asmatrix(traf.lat),
            np.asmatrix(traf.lon),
            np.asmatrix(traf.lat),
            np.asmatrix(traf.lon),
        )
        horizontal_distance = np.asarray(distance_nm) * nm
        vertical_distance = np.abs(traf.alt.reshape((-1, 1)) - traf.alt.reshape((1, -1)))
        return horizontal_distance, vertical_distance

    def detect_pair(self, index1, index2, horizontal, vertical, current_events):
        pair = (traf.id[index1], traf.id[index2])
        category_pair = self.aircraft_category_pair(index1, index2)
        pair_type = f"{category_pair[0]}-{category_pair[1]}"

        for level_name in self.level_names:
            criteria = self.separation_levels[level_name]
            radius = self.get_radius(criteria, category_pair)
            dh = self.get_dh(criteria, category_pair)
            interpolate = bool(criteria.get("interpolate", False))
            inside, min_distance = self.check_separation(
                index1, index2, horizontal, vertical, radius, dh, interpolate
            )

            if not inside:
                break
            current_events[level_name][pair] = (min_distance, pair_type)

    def aircraft_category(self, index):
        """Classify aircraft using OpenAP performance arrays."""
        lifttype = traf.perf.lifttype[index]
        engnum = traf.perf.engnum[index]

        if lifttype == coeff.LIFT_ROTOR:
            if int(engnum) > 2:
                return 'drone'
            return 'heli'
        return 'fixedwing'

    def aircraft_category_pair(self, index1, index2):
        cat1 = self.aircraft_category(index1)
        cat2 = self.aircraft_category(index2)
        return self.ordered_pair(cat1, cat2)

    def ordered_pair(self, value1, value2):
        if value1 <= value2:
            return value1, value2
        return value2, value1

    def get_radius(self, criteria, category_pair):
        """Return the horizontal radius for one separation level."""
        if 'radius_by_pair' in criteria:
            return float(criteria['radius_by_pair'][category_pair])
        return float(criteria['radius'])

    def get_dh(self, criteria, category_pair):
        """Return the vertical separation dh for one separation level."""
        if 'dh_by_pair' in criteria:
            return float(criteria['dh_by_pair'][category_pair])
        return float(criteria.get('dh', 0))

    def first_level_max_radius(self):
        first_level = self.separation_levels[self.level_names[0]]
        return self.max_radius(first_level)

    def max_radius(self, criteria):
        if 'radius_by_pair' in criteria:
            return max(criteria['radius_by_pair'].values())
        return float(criteria['radius'])

    def check_separation(self, index1, index2, horizontal, vertical, radius, dh, interpolate):
        """Check direct and interpolated membership in a separation level."""
        if horizontal < radius and vertical < dh:
            return True, horizontal
        if not interpolate:
            return False, horizontal

        speed1 = float(traf.gs[index1])
        speed2 = float(traf.gs[index2])
        if horizontal > 4.0 * max(speed1, speed2) * self.detection_dt:
            return False, horizontal
        return self.check_interpolated_separation(index1, index2, radius, dh)

    def check_interpolated_separation(self, index1, index2, radius, dh):
        """Check membership at the closest point of approach between samples."""
        acid1 = traf.id[index1]
        acid2 = traf.id[index2]
        if acid1 not in self.previous_positions or acid2 not in self.previous_positions:
            return False, float("inf")

        lat1_prev, lon1_prev, alt1_prev = self.previous_positions[acid1]
        lat2_prev, lon2_prev, alt2_prev = self.previous_positions[acid2]
        lat1_now, lon1_now, alt1_now = traf.lat[index1], traf.lon[index1], traf.alt[index1]
        lat2_now, lon2_now, alt2_now = traf.lat[index2], traf.lon[index2], traf.alt[index2]

        ref_lat = lat1_now
        ref_lon = lon1_now
        p1_prev = self.position_to_xyz(lat1_prev, lon1_prev, alt1_prev, ref_lat, ref_lon)
        p2_prev = self.position_to_xyz(lat2_prev, lon2_prev, alt2_prev, ref_lat, ref_lon)
        p1_now = self.position_to_xyz(lat1_now, lon1_now, alt1_now, ref_lat, ref_lon)
        p2_now = self.position_to_xyz(lat2_now, lon2_now, alt2_now, ref_lat, ref_lon)

        relative_start = p1_prev - p2_prev
        relative_end = p1_now - p2_now
        relative_motion = relative_end - relative_start
        motion_norm_squared = float(np.dot(relative_motion, relative_motion))

        if motion_norm_squared == 0.0:
            closest = relative_end
        else:
            tau = -float(np.dot(relative_start, relative_motion)) / motion_norm_squared
            closest = relative_start + min(1.0, max(0.0, tau)) * relative_motion

        closest_horizontal = float(np.hypot(closest[0], closest[1]))
        closest_vertical = abs(float(closest[2]))
        within_pz = closest_horizontal < radius and closest_vertical < dh, closest_horizontal
        # if within_pz[0]:
        #     if radius < 5:
        #         sim.hold()
        #         print('collision')
        #         print(within_pz)
        #
        #         print(acid1, acid2)
        #         print(closest_horizontal, radius)
        #         print(lat1_prev, lon1_prev, alt1_prev)
        #         print(lat2_prev, lon2_prev, alt2_prev)
        #         print(lat1_now, lon1_now, alt1_now)
        #         print(lat2_now, lon2_now, alt2_now)
        return within_pz

    def position_to_xyz(self, lat, lon, alt, ref_lat, ref_lon):
        """Convert lat/lon/alt to local Cartesian coordinates [m]."""
        x = (lon - ref_lon) * 60.0 * nm * np.cos(np.radians(ref_lat))
        y = (lat - ref_lat) * 60.0 * nm
        return np.array([x, y, alt], dtype=float)

    def update_previous_positions(self):
        """Store current aircraft positions for the next interpolation step."""
        current_aircraft = set(traf.id)
        self.previous_positions = {
            acid: position
            for acid, position in self.previous_positions.items()
            if acid in current_aircraft
        }
        for index, acid in enumerate(traf.id):
            self.previous_positions[acid] = (
                float(traf.lat[index]),
                float(traf.lon[index]),
                float(traf.alt[index]),
            )

    def update_protection_zones(self):
        """Set BlueSky protection zone radius for newly created aircraft."""
        self.protection_zone_aircraft.intersection_update(set(traf.id))
        if traf.ntraf == 0:
            return

        if not self.protection_zones_shown:
            stack.stack('SHOWPZ')
            self.protection_zones_shown = True

        conflict_detection = ConflictDetection.instance()
        protection_zone_level = self.separation_levels[self.level_names[0]]
        for index, acid in enumerate(traf.id):
            if acid in self.protection_zone_aircraft:
                continue

            category = self.aircraft_category(index)
            matching_radii = [
                radius
                for pair, radius in protection_zone_level["radius_by_pair"].items()
                if category in pair
            ]
            if not matching_radii:
                continue

            conflict_detection.rpz[index] = self.protection_zone_draw_factor * min(matching_radii)
            conflict_detection.global_rpz = False
            self.protection_zone_aircraft.add(acid)

    def update_events(self, current_pairs, active_events, finished_events, level_name=None):
        """Start new events, update minimum distance, and finish old events."""
        current_time = float(sim.simt)
        trigger_event = ARA_settings.SIMULATION_SETTINGS.get('sim_hold')
        trigger_pair = ARA_settings.SIMULATION_SETTINGS.get('pair_type')

        for pair, (distance, pair_type) in current_pairs.items():
            if pair not in active_events:
                active_events[pair] = {
                    'acid1': pair[0],
                    'acid2': pair[1],
                    'pair_type': pair_type,
                    't_begin': current_time,
                    't_end': None,
                    'min_distance_m': distance,
                }
                if ARA_settings.SIMULATION_SETTINGS['hold'] == True and level_name == trigger_event and trigger_pair == 'drone-heli':
                    sim.hold()
                    print(f"HOLD: {level_name} event between {pair_type} ({pair[0]}-{pair[1]})")
            elif distance < active_events[pair]['min_distance_m']:
                active_events[pair]['min_distance_m'] = distance

        for pair in list(active_events.keys()):
            if pair not in current_pairs:
                event = active_events.pop(pair)
                event['t_end'] = current_time
                finished_events.append(event)

    def count_types(self, finished_events, active_events):
        """Count events per aircraft pair type."""
        counts = {}
        for event in finished_events + list(active_events.values()):
            pair_type = event['pair_type']
            counts[pair_type] = counts.get(pair_type, 0) + 1
        return counts

    def count_all_levels(self):
        """Return counts per level for both active and finished events."""
        counts = {}
        for level_name in self.level_names:
            counts[level_name] = len(self.finished_events[level_name]) + len(self.active_events[level_name])
        return counts

    def serialize_events(self, level_name):
        """Convert finished events for display/output."""
        events = []
        for event in self.finished_events[level_name]:
            event_nm = event.copy()
            event_nm['min_distance_nm'] = round(event_nm.pop('min_distance_m') / nm, 2)
            events.append(event_nm)
        return events



    @stack.command
    def sendresult(self):
        """Send totals and type counts to the Monte Carlo plugin."""
        level_counts = self.count_all_levels()
        level_type_counts = {
            level_name: self.count_types(self.finished_events[level_name], self.active_events[level_name])
            for level_name in self.level_names
        }
        result = {'ACTUALSEED': ARA_settings.ara_seed}
        result['demand'] = str(ARA_settings.demand)
        result['scheduled_time'] = ARA_settings.SIMULATION_SETTINGS['default_maxtime']
        result['ILT_drones'] = self.scheduler.counters['ilt']
        result['NHV_helis'] = self.scheduler.counters['heli']
        result['random_drones'] = self.scheduler.counters['random']
        result['Transit_helis'] = self.scheduler.counters['transit']

        # for level_name, count in level_counts.items():
        #     result[f'{level_name}_count'] = count

        # Get all possible pair types from the separation levels configuration
        all_pair_types = set()
        for level_name in self.level_names:
            criteria = self.separation_levels[level_name]
            if 'radius_by_pair' in criteria:
                for pair in criteria['radius_by_pair'].keys():
                    pair_type = f"{pair[0]}-{pair[1]}"
                    if pair[0] == 'heli' and pair[1] == 'heli':
                        continue
                    else:
                        all_pair_types.add(pair_type)

        # Ensure all pair types are included for each level, with 0 if they didn't occur
        for level_name, counts in level_type_counts.items():
            for pair_type in all_pair_types:
                result[f'{level_name}_{pair_type}'] = counts.get(pair_type, 0)

        sender = stack.sender()
        net.send('MONTECARLORESULTS', result, sender)




    @stack.command
    def losresults(self):
        """Show counts and minimum distances for every separation level."""
        result_lines = []

        for level_name in self.level_names:
            finished_events = self.finished_events[level_name]
            active_events = self.active_events[level_name]

            all_events = (
                    finished_events
                    + list(active_events.values())
            )

            type_counts = self.count_types(
                finished_events,
                active_events,
            )

            result_lines.append(
                f'{level_name}: {len(all_events)} events'
            )
            result_lines.append(
                f'  By type: {type_counts}'
            )

            if not all_events:
                result_lines.append(
                    '  Minimum distances: none'
                )
                continue

            result_lines.append(
                '  Minimum distances:'
            )

            sorted_events = sorted(
                all_events,
                key=lambda event: event['min_distance_m'],
            )

            for event in sorted_events:
                status = (
                    'active'
                    if event['t_end'] is None
                    else 'finished'
                )

                minimum_distance_m = event['min_distance_m']
                minimum_distance_nm = minimum_distance_m / nm

                result_lines.append(
                    f"    {event['acid1']}-{event['acid2']} "
                    f"({event['pair_type']}, {status}): "
                    f"{minimum_distance_m:.2f} m "
                    f"({minimum_distance_nm:.4f} NM)"
                )

        print('\n'.join(result_lines))