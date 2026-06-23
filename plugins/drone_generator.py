import numpy as np

from bluesky import core, sim, stack
from plugins.define_area import define_area


def init_plugin():
    global drone_generator
    drone_generator = DroneGenerator()

    return {
        "plugin_name": "DRONE_GENERATOR",
        "plugin_type": "sim",
    }


class DroneGenerator(core.Entity):

    def __init__(self):
        super().__init__()
        self.drone_number = 0
        self.define_area = define_area

        self.drone_type = "Phan4"
        self.speedmin = 10.0
        self.speedmax = 20.0
        self.altitude = 500.0

    def reset(self):
        self.drone_number = 0
        self.define_area.drawn = False

    @stack.command
    def gendrones(
            self,
            n: int,
            speedmin: float = 10.0,    # KTS
            speedmax: float = 20.0,   # KTS
            altitude: float = 500.0,  # FT
            drone_type: str = "Phan4",
    ):
        """Generate random drone flights inside the shared area."""
        self.speedmin = speedmin
        self.speedmax = speedmax
        self.altitude = altitude
        self.drone_type = drone_type

        if not self.define_area.drawn:
            self.define_area.draw()

        for _ in range(int(n)):
            self.generate_one_drone()

        return True

    def generate_one_drone(self):
        """Generate one drone with a random start and end point."""
        self.drone_number += 1

        acid = f"DRN{self.drone_number:04d}"

        start_lat, start_lon = self.define_area.random_position()
        end_lat, end_lon = self.define_area.random_position()
        speed = np.random.uniform(self.speedmin, self.speedmax)

        waypoint = self.define_area.generate_aircraft( acid=acid, type=self.drone_type, start_lat=start_lat,
                       start_lon=start_lon, end_lat=end_lat, end_lon=end_lon, alt=self.altitude, speed=speed )

        stack.stack(f"AT {acid},{waypoint} DO REPLACEDRONE {acid}")

    @stack.command
    def replacedrone(self, acid: str):
        stack.stack(f"DEL {acid}")

        rounded_time = round(float(sim.simt) / 5.0) * 5.0
        t_create = rounded_time + 5.0

        stack.stack(
            f"SCHEDULE {t_create:.1f} GENDRONES 1 "
            f"{self.speedmin:.1f} {self.speedmax:.1f} "
            f"{self.altitude:.1f} {self.drone_type}"
        )