import numpy as np

from bluesky import core, sim, stack
from plugins.define_area import (
    define_area,
    HELI_START,
    HELI_LANDING,
    HELI_EXIT,
)



def init_plugin():
    global heli_generator
    heli_generator = HeliGenerator()

    return {
        "plugin_name": "HELI_GENERATOR",
        "plugin_type": "sim",
    }


class HeliGenerator(core.Entity):

    def __init__(self):
        super().__init__()
        self.heli_number = 0
        self.define_area = define_area

        self.heli_type = "EC35"
        self.speed = 120.0       # KTS
        self.altitude = 500.0    # FT
        self.flights_per_hour = 2
        self.max_ground_time = 10.0  # minutes

    def reset(self):
        self.heli_number = 0

    @stack.command
    def genheli(
            self,
            flights_per_hour: int,
            max_ground_time: float = 10.0,  # minutes
            speed: float = 120.0,           # KTS
            altitude: float = 500.0,        # FT
            heli_type: str = "EC35",
    ):
        """Schedule heli flights for one hour, then schedule itself again."""
        self.flights_per_hour = int(flights_per_hour)
        self.max_ground_time = float(max_ground_time)
        self.speed = speed
        self.altitude = altitude
        self.heli_type = heli_type

        for _ in range(self.flights_per_hour):
            start_delay = np.random.uniform(0.0, 3600)
            ground_time = np.random.uniform(0.0, self.max_ground_time * 60.0)

            stack.stack(
                f"SCHEDULE {sim.simt + start_delay:.1f} "
                f"SCHEDULEHELI {ground_time:.1f}"
            )

        stack.stack(
            f"SCHEDULE {sim.simt + 3600:.1f} "
            f"GENHELI {self.flights_per_hour} {self.max_ground_time:.1f} "
            f"{self.speed:.1f} {self.altitude:.1f} {self.heli_type}"
        )

        return True

    @stack.command
    def scheduleheli(self, ground_time: float):
        """Create one inbound heli flight from the fixed start point to the landing point."""
        self.heli_number += 1
        acid = f"HEL{self.heli_number:04d}"

        start_lat, start_lon = HELI_START
        land_lat, land_lon = HELI_LANDING

        waypoint = self.define_area.generate_aircraft(
            acid=acid,
            type=self.heli_type,
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=land_lat,
            end_lon=land_lon,
            alt=self.altitude,
            speed=self.speed,
        )

        stack.stack(f"COLOR {acid},ORANGE")
        stack.stack(f"AT {acid},{waypoint} DO SCHEDULERETURN {acid} {float(ground_time):.1f}")

        return True

    @stack.command
    def schedulereturn(self, acid: str, ground_time: float):
        """After landing, wait on ground and schedule the outbound heli flight."""
        stack.stack(f"DEL {acid}")
        stack.stack(f"SCHEDULE {sim.simt + float(ground_time):.1f} SCHEDULERETURNFLIGHT")

        return True

    @stack.command
    def schedulereturnflight(self):
        """Create one outbound heli flight from the landing point to the fixed exit point."""
        self.heli_number += 1
        acid = f"HEL{self.heli_number:04d}"

        land_lat, land_lon = HELI_LANDING
        exit_lat, exit_lon = HELI_EXIT

        waypoint = self.define_area.generate_aircraft(
            acid=acid,
            type=self.heli_type,
            start_lat=land_lat,
            start_lon=land_lon,
            end_lat=exit_lat,
            end_lon=exit_lon,
            alt=self.altitude,
            speed=self.speed,
        )

        stack.stack(f"COLOR {acid},ORANGE")
        stack.stack(f"AT {acid},{waypoint} DO DEL {acid}")

        return True
