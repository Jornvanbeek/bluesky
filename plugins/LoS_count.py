import numpy as np

from bluesky import core, net, sim, stack, traf
from bluesky.core import timed_function
from bluesky.tools import geo
from bluesky.tools.aero import ft, nm


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

        # Separation limits
        self.los_radius = 5.0 * nm
        self.los_dh = 1000.0 * ft

        self.collision_radius = 0.1 * nm
        self.collision_dh = 100.0 * ft

        # Active events: pair -> event information
        self.active_los = {}
        self.active_collisions = {}

        # Finished events
        self.finished_los = []
        self.finished_collisions = []

    def reset(self):
        self.active_los = {}
        self.active_collisions = {}
        self.finished_los = []
        self.finished_collisions = []

    @timed_function(dt=1.0)
    def detect(self):
        """Check every second which aircraft pairs are in LoS or collision."""

        if traf.ntraf < 2:
            return

        # Horizontal distance matrix in nautical miles
        _, distance_nm = geo.kwikqdrdist_matrix(
            np.asmatrix(traf.lat),
            np.asmatrix(traf.lon),
            np.asmatrix(traf.lat),
            np.asmatrix(traf.lon),
        )

        horizontal_distance = np.asarray(distance_nm) * nm

        # Vertical distance matrix in metres
        vertical_distance = np.abs(
            traf.alt.reshape((-1, 1)) - traf.alt.reshape((1, -1))
        )

        current_los = {}
        current_collisions = {}

        # Only check each pair once: i < j
        for i in range(traf.ntraf):
            for j in range(i + 1, traf.ntraf):
                pair = (traf.id[i], traf.id[j])
                horizontal = float(horizontal_distance[i, j])
                vertical = float(vertical_distance[i, j])

                if horizontal < self.los_radius and vertical < self.los_dh:
                    current_los[pair] = horizontal

                if (
                    horizontal < self.collision_radius
                    and vertical < self.collision_dh
                ):
                    current_collisions[pair] = horizontal

        self.update_events(
            current_los,
            self.active_los,
            self.finished_los,
        )

        self.update_events(
            current_collisions,
            self.active_collisions,
            self.finished_collisions,
        )

    def update_events(self, current_pairs, active_events, finished_events):
        """Start new events, update minimum distance, and finish old events."""

        current_time = float(sim.simt)

        # Start new events
        for pair, distance in current_pairs.items():
            if pair not in active_events:
                active_events[pair] = {
                    'acid1': pair[0],
                    'acid2': pair[1],
                    't_begin': current_time,
                    't_end': None,
                    'min_distance_m': distance,
                }

        # Update minimum distance for active events
        for pair, distance in current_pairs.items():
            if distance < active_events[pair]['min_distance_m']:
                active_events[pair]['min_distance_m'] = distance

        # Finish events that are no longer active
        for pair in list(active_events.keys()):
            if pair not in current_pairs:
                event = active_events.pop(pair)
                event['t_end'] = current_time
                finished_events.append(event)

    @stack.command
    def losresults(self):
        los_count = len(self.finished_los) + len(self.active_los)
        collision_count = (
            len(self.finished_collisions) + len(self.active_collisions)
        )

        los_events_nm = []
        for event in self.finished_los:
            event_nm = event.copy()
            event_nm['min_distance_nm'] = round(event_nm.pop('min_distance_m') / nm, 2)
            los_events_nm.append(event_nm)

        collision_events_nm = []
        for event in self.finished_collisions:
            event_nm = event.copy()
            event_nm['min_distance_nm'] = round(event_nm.pop('min_distance_m') / nm, 2)
            collision_events_nm.append(event_nm)

        return True, (
            f'LoS count: {los_count}\n'
            f'Collision count: {collision_count}\n'
            f'Finished LoS events: {los_events_nm}\n'
            f'Finished collision events: {collision_events_nm}'
        )

    @stack.command
    def setlosradius(self, radius_nm: float):
        self.los_radius = radius_nm * nm

    @stack.command
    def setlosdh(self, dh_ft: float):
        self.los_dh = dh_ft * ft

    @stack.command
    def setcollisionradius(self, radius_nm: float):
        self.collision_radius = radius_nm * nm

    @stack.command
    def setcollisiondh(self, dh_ft: float):
        self.collision_dh = dh_ft * ft

    @stack.command
    def sendresult(self):
        """Send only the total counts to the Monte Carlo plugin."""

        los_count = len(self.finished_los) + len(self.active_los)
        collision_count = (
            len(self.finished_collisions) + len(self.active_collisions)
        )

        result = {
            'LoS_count': los_count,
            'collision_count': collision_count,
            'RNG': int(np.random.get_state()[1][0]),
        }

        sender = stack.sender()
        net.send('MONTECARLORESULTS', result, sender)
