import numpy as np

from bluesky import stack, navdb
from bluesky.tools import geo
import json
from pathlib import Path

from bluesky import stack
from shapely.geometry import Polygon
from plugins.ARA_settings import DEFAULT_POLYGON, HELI_CORRIDOR, HELIPORT_LOCATION, TRANSIT_CORRIDOR



# DEFAULT_GEOJSON_PATH = (
#     Path(__file__).resolve().parent
#     / "plugins"
#     / "water_polygons_detail.geojson"
# )
#
# POLYGON_PREFIX = "WATER"
# Maak één keer de ARA polygon aan.
DEFAULT_AREA = Polygon(
    [(lon, lat) for lat, lon in DEFAULT_POLYGON]
)


class DefineArea:
    def __init__(self, name="DRONEAREA", polygon=None):
        self.name = name
        self.polygon = polygon.copy() if polygon is not None else DEFAULT_POLYGON.copy()
        self.drawn = False
        self.draw()

    def draw(self):
        """Draw the area polygon and helicopter corridors in BlueSky."""
        if self.drawn:
            return

        area_points = ",".join( f"{lat:.6f},{lon:.6f}" for lat, lon in self.polygon )

        stack.stack(f"POLY {self.name},{area_points}")
        for i in range(len(HELI_CORRIDOR)):
            color = ['RED', 'MAGENTA', 'ORANGE']
            self.draw_heli_corridor( f"HELI_route)_{i}", HELI_CORRIDOR[i], color[i] )
        for i in range(len(TRANSIT_CORRIDOR)):

            self.draw_heli_corridor( f"TRANSIT_route)_{i}", TRANSIT_CORRIDOR[i], 'YELLOW' )

        stack.stack(f'DEFWPT EHTP {HELIPORT_LOCATION[0]} {HELIPORT_LOCATION[1]} AIRPORT')
        self.draw_ilt_boxes()
        self.drawn = True
        # print('drawn?')

    @staticmethod
    def draw_heli_corridor(name, corridor, color):
        """Draw every corridor segment as a separate red line."""
        for index, segment in enumerate(corridor, start=1):
            start_lat, start_lon, end_lat, end_lon = segment
            segment_name = f"{name}_{index}"
            stack.stack(f"LINE {segment_name}, "f"{start_lat:.6f},{start_lon:.6f}, "f"{end_lat:.6f},{end_lon:.6f}")
            # if name == "HELI_INBOUND":
            stack.stack(f"COLOR {segment_name},{color}")
            # else:
            #     stack.stack(f"COLOR {segment_name},GREEN")



    # @staticmethod
    # def route_to_bluesky_string(start, end):
    #     """Convert a start/end route to a BlueSky POLY coordinate string."""
    #     start_lat, start_lon = start
    #     end_lat, end_lon = end
    #     return f"{start_lat:.6f},{start_lon:.6f},{end_lat:.6f},{end_lon:.6f}"


    def random_position(self, max_tries=1000, polygon=None, rng=None):
        """Return one random point inside the area polygon or a provided polygon."""
        if polygon is None:
            polygon = self.polygon

        lats = [lat for lat, _ in polygon]
        lons = [lon for _, lon in polygon]
        lat_min, lat_max = min(lats), max(lats)
        lon_min, lon_max = min(lons), max(lons)
        if rng == None:
            rng = np.random
        for _ in range(max_tries):
            lat = rng.uniform(lat_min, lat_max)
            lon = rng.uniform(lon_min, lon_max)
            if self.point_in_polygon(lat, lon, polygon):
                return float(lat), float(lon)

        return float(np.mean(lats)), float(np.mean(lons))

    def draw_ilt_boxes(self):
        """Draw ILT flight boxes as red polygons."""
        try:
            from plugins.ARA_settings import ILT_BOXES, RANDOMDRONE_BOXES
            for i, box in enumerate(ILT_BOXES + RANDOMDRONE_BOXES):
                box_points = ",".join(f"{lat:.6f},{lon:.6f}" for lat, lon in box)
                stack.stack(f"POLY ILT_BOX_{i},{box_points}")
                stack.stack(f"COLOR ILT_BOX_{i},RED")
        except ImportError:
            pass

    def point_in_polygon(self, lat, lon, polygon=None):
        """Return True if the point is inside the polygon."""
        if polygon is None:
            polygon = self.polygon
        
        inside = False
        j = len(polygon) - 1

        for i, (lat_i, lon_i) in enumerate(polygon):
            lat_j, lon_j = polygon[j]
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