import numpy as np

from bluesky import stack
from bluesky.tools import geo


DEFAULT_POLYGON = [
    (51.985612, 4.023460),
    (51.988545, 4.010898),
    (51.989066, 4.005452),
    (51.988903, 4.002173),
    (51.988715, 4.000010),
    (51.985761, 3.985297),
    (51.984454, 3.981825),
    (51.981322, 3.977855),
    (51.970613, 3.966059),
    (51.964985, 3.962057),
    (51.959684, 3.960983),
    (51.954049, 3.962342),
    (51.949101, 3.965228),
    (51.920460, 3.982560),
    (51.918769, 3.984909),
    (51.918269, 3.986501),
    (51.917563, 3.988861),
    (51.917438, 3.990375),
    (51.916138, 4.000439),
    (51.920455, 4.019517),
    (51.933026, 4.071131),
    (51.932712, 4.087382),
    (51.930696, 4.101658),
    (51.931615, 4.105291),
    (51.935942, 4.108482),
    (51.931253, 4.146592),
    (51.925375, 4.165289),
    (51.919887, 4.171231),
    (51.914072, 4.182636),
    (51.931305, 4.226330),
    (51.938270, 4.209995),
    (51.947630, 4.185324),
    (51.961098, 4.159858),
    (51.972373, 4.135653),
    (51.977637, 4.121854),
    (51.983870, 4.101565),
    (51.984647, 4.096350),
    (51.986394, 4.085720),
    (51.994661, 4.047281),
    (51.986947, 4.037760),
    (51.987839, 4.033220),
    (51.987150, 4.027784),
]


# Fixed helicopter route points.
HELI_START = (51.961383,4.154409)
HELI_LANDING = (51.956948,4.025361)
HELI_EXIT = (51.9897,4.049731)



class DefineArea:
    def __init__(self, name="DRONEAREA", polygon=None):
        self.name = name
        self.polygon = polygon.copy() if polygon is not None else DEFAULT_POLYGON.copy()
        self.drawn = False
        self.draw()

    def draw(self):
        """Draw the area polygon in BlueSky."""
        if self.drawn:
            return

        area_points = ",".join(f"{lat:.6f},{lon:.6f}" for lat, lon in self.polygon)
        heli_inbound = self.route_to_bluesky_string(HELI_START, HELI_LANDING)
        heli_outbound = self.route_to_bluesky_string(HELI_LANDING, HELI_EXIT)

        stack.stack(f"POLY {self.name},{area_points}")
        stack.stack(f"POLY HELI_INBOUND,{heli_inbound}")
        stack.stack(f"POLY HELI_OUTBOUND,{heli_outbound}")

        self.drawn = True


    @staticmethod
    def route_to_bluesky_string(start, end):
        """Convert a start/end route to a BlueSky POLY coordinate string."""
        start_lat, start_lon = start
        end_lat, end_lon = end
        return f"{start_lat:.6f},{start_lon:.6f},{end_lat:.6f},{end_lon:.6f}"


    def random_position(self, max_tries=1000):
        """Return one random point inside the area polygon."""
        lats = [lat for lat, _ in self.polygon]
        lons = [lon for _, lon in self.polygon]
        lat_min, lat_max = min(lats), max(lats)
        lon_min, lon_max = min(lons), max(lons)

        for _ in range(max_tries):
            lat = np.random.uniform(lat_min, lat_max)
            lon = np.random.uniform(lon_min, lon_max)
            if self.point_in_polygon(lat, lon):
                return float(lat), float(lon)

        return float(np.mean(lats)), float(np.mean(lons))

    def generate_aircraft(
            self, acid: str, type: str,
            start_lat: float, start_lon: float,
            end_lat: float, end_lon: float,
            alt: float, speed: float,
            heading: float = None,
    ):
        """Generate one aircraft and route it to a generated end waypoint."""
        if heading is None:
            heading, _ = geo.qdrdist(start_lat, start_lon, end_lat, end_lon)

        waypoint_name = f"{acid}END"

        stack.stack(
            f"CRE {acid},{type},{start_lat:.6f},{start_lon:.6f},"
            f"{heading:.1f},{alt:.0f},{speed:.1f}"
        )
        stack.stack(f"DEFWPT {waypoint_name},{end_lat:.6f},{end_lon:.6f}")
        stack.stack(f"ADDWPT {acid},{waypoint_name}")

        return waypoint_name

    def point_in_polygon(self, lat, lon):
        """Return True if the point is inside the polygon."""
        inside = False
        j = len(self.polygon) - 1

        for i, (lat_i, lon_i) in enumerate(self.polygon):
            lat_j, lon_j = self.polygon[j]
            crosses_lon = (lon_i > lon) != (lon_j > lon)

            if crosses_lon:
                lat_at_lon = (lat_j - lat_i) * (lon - lon_i) / (lon_j - lon_i) + lat_i
                if lat < lat_at_lon:
                    inside = not inside

            j = i

        return inside



# Shared area instance.
# Import this object in other plugins to use the same polygon and drawn state.
define_area = DefineArea()