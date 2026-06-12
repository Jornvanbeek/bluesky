import numpy as np

from bluesky import core, stack
from bluesky.tools import geo


def init_plugin():
    global aircraft_generator
    aircraft_generator = AircraftGenerator()

    return {
        "plugin_name": "AIRCRAFT_GENERATOR",
        "plugin_type": "sim",
    }


class AircraftGenerator(core.Entity):

    def __init__(self):
        super().__init__()
        self.aircraft_number = 0
        self.area_drawn = False

    def reset(self):
        self.aircraft_number = 0
        self.area_drawn = False

    @stack.command
    def genaircraft(
            self,
            n: int,
            size: float = 100.0,       # Total width and height in NM
            speedmin: float = 200.0,   # KTS
            speedmax: float = 300.0,   # KTS
            altitude: float = 10000.0, # FT
            lat: float = 52.3086,      # Schiphol
            lon: float = 4.7639,       # Schiphol
    ):
        """
        Generate random flights inside a square around Schiphol.

        The global NumPy random seed is used.
        """
        if not self.area_drawn:
            self.draw_square(lat, lon, size)

        for _ in range(int(n)):
            self.aircraft_number += 1

            acid = f"GEN{self.aircraft_number:04d}"
            waypoint = f"END{self.aircraft_number:04d}"

            # Generate two independent points inside the square
            start_lat, start_lon = self.random_position(lat, lon, size)
            end_lat, end_lon = self.random_position(lat, lon, size)

            heading, _ = geo.qdrdist(
                start_lat,
                start_lon,
                end_lat,
                end_lon,
            )

            speed = np.random.uniform(speedmin, speedmax)

            stack.stack(
                f"CRE {acid},B789,"
                f"{start_lat:.6f},{start_lon:.6f},"
                f"{heading:.1f},{altitude:.0f},{speed:.1f}"
            )

            stack.stack(
                f"DEFWPT {waypoint},{end_lat:.6f},{end_lon:.6f}"
            )

            stack.stack(
                f"ADDWPT {acid},{waypoint}"
            )

            stack.stack(
                f"AT {acid},{waypoint} DO REPLACEAIRCRAFT {acid}"
            )

        return True


    def draw_square(self, center_lat, center_lon, size_nm):
        """Draw the square area with BlueSky's POLY command."""

        half_size = size_nm / 2.0

        lat_offset = half_size / 60.0
        lon_offset = half_size / (
            60.0 * np.cos(np.radians(center_lat))
        )

        north = center_lat + lat_offset
        south = center_lat - lat_offset
        east = center_lon + lon_offset
        west = center_lon - lon_offset

        stack.stack(
            f"POLY TESTAREA,"
            f"{north:.6f},{west:.6f},"
            f"{north:.6f},{east:.6f},"
            f"{south:.6f},{east:.6f},"
            f"{south:.6f},{west:.6f}"
        )

    @stack.command
    def replaceaircraft(self, acid: str):
        stack.stack(f"DEL {acid}")
        stack.stack("GENAIRCRAFT 1")

    @staticmethod
    def random_position(center_lat, center_lon, size_nm):
        """Return one uniformly distributed random position inside a square."""

        half_size = size_nm / 2.0

        # Uniform offsets in NM
        north_offset = np.random.uniform(-half_size, half_size)
        east_offset = np.random.uniform(-half_size, half_size)

        # Approximate conversion from NM to degrees
        random_lat = center_lat + north_offset / 60.0

        random_lon = center_lon + east_offset / (
            60.0 * np.cos(np.radians(center_lat))
        )

        return float(random_lat), float(random_lon)