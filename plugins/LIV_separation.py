import re

import pandas as pd
import numpy as np
import bluesky as bs
# from plugins.readcsv import *
import math
from plugins.readxml import *

# dummy
wtc_sep = 1
recat_sep_threshold = 1


class LivSeparation:
    def __init__(self):
        self.min_radar_sep = 3 #2.5???  # NM
        self.min_time_sep = 72  # s

        self.icao_categories = load_recat_categories('plugins/RECAT_ACTYPE.csv')
        # self.ptas_data = load_aircraft_ptas_data('plugins/AircraftDB-ao[36].csv')
        # self.perfdata = perf_dataframe('plugins/AircraftDB-ao.csv')

        self.perfdata = perf_dataframe('plugins/AircraftDB-ap.xml')

        self.wtc_separation = {'A': {'A': 3,                  'B': 4,                  'C': 5,                  'D': 5,                  'E': 6,                  'F': 8},
                               'B': {'A': self.min_radar_sep, 'B': 3,                  'C': 4,                  'D': 4,                  'E': 5,                  'F': 7},
                               'C': {'A': self.min_radar_sep, 'B': self.min_radar_sep, 'C': 3,                  'D': 3,                  'E': 4,                  'F': 6},
                               'D': {'A': self.min_radar_sep, 'B': self.min_radar_sep, 'C': self.min_radar_sep, 'D': self.min_radar_sep, 'E': self.min_radar_sep, 'F': 5},
                               'E': {'A': self.min_radar_sep, 'B': self.min_radar_sep, 'C': self.min_radar_sep, 'D': self.min_radar_sep, 'E': self.min_radar_sep, 'F': 4},
                               'F': {'A': self.min_radar_sep, 'B': self.min_radar_sep, 'C': self.min_radar_sep, 'D': self.min_radar_sep, 'E': self.min_radar_sep, 'F': 3}}

        self.wtc_separation_buffer = {
            'A': {'A': 1.0, 'B': 0.4, 'C': 0.4, 'D': 1.4, 'E': 1.4, 'F': 0.0},
            'B': {'A': 1.0, 'B': 0.7, 'C': 0.7, 'D': 0.5, 'E': 0.5, 'F': 0.7},
            'C': {'A': 1.0, 'B': 0.7, 'C': 0.7, 'D': 0.5, 'E': 0.5, 'F': 0.7},
            'D': {'A': 1.2, 'B': 0.4, 'C': 0.4, 'D': 0.4, 'E': 0.4, 'F': 1.2},
            'E': {'A': 1.2, 'B': 0.4, 'C': 0.4, 'D': 0.4, 'E': 0.4, 'F': 1.2},
            'F': {'A': 0.7, 'B': 1.0, 'C': 1.0, 'D': 1.0, 'E': 1.0, 'F': 0.7}}

        self.recat_sep_threshold = {
            'A': {'A': 3.3, 'B': 4.3, 'C': 5.3, 'D': 5.2, 'E': 6.2, 'F': 8.7},
            'B': {'A': 3.3, 'B': 3.3, 'C': 4.3, 'D': 4.2, 'E': 5.2, 'F': 7.7},
            'C': {'A': 3.3, 'B': 3.3, 'C': 3.3, 'D': 3.2, 'E': 4.2, 'F': 6.7},
            'D': {'A': 3.3, 'B': 3.3, 'C': 3.3, 'D': 3.2, 'E': 5.7, 'F': 8.0},
            'E': {'A': 3.3, 'B': 3.3, 'C': 3.3, 'D': 3.2, 'E': 4.7, 'F': 8.0},
            'F': {'A': 3.7, 'B': 3.7, 'C': 3.7, 'D': 3.7, 'E': 3.7, 'F': 3.7}}

        # self.separation_time = {'A': {'A': 100, 'B': 110, 'C': 120, 'D': 130, 'E': 140, 'F': 150},
        #                         'B': {'A': self.min_time_sep, 'B': 111, 'C': 121, 'D': 131, 'E': 141, 'F': 151},
        #                         'C': {'A': self.min_time_sep, 'B': self.min_time_sep, 'C': 122, 'D': 132, 'E': 142,
        #                               'F': 152},
        #                         'D': {'A': self.min_time_sep, 'B': self.min_time_sep, 'C': self.min_time_sep,
        #                               'D': self.min_time_sep, 'E': self.min_time_sep, 'F': 153},
        #                         'E': {'A': self.min_time_sep, 'B': self.min_time_sep, 'C': self.min_time_sep,
        #                               'D': self.min_time_sep, 'E': self.min_time_sep, 'F': 154},
        #                         'F': {'A': self.min_time_sep, 'B': self.min_time_sep, 'C': self.min_time_sep,
        #                               'D': self.min_time_sep, 'E': self.min_time_sep, 'F': 155}}

    def get_icao_cat(self, icao):

        # icao = self.icao_categories.sample(axis=0).values[0][0]

        result = self.icao_categories[self.icao_categories['ACTYPE'] == icao]['RECAT'].iloc[0]

        return result

    def required_separation(self, leader_acid, leader_type, follower_acid, follower_type, wind_final = 0, wind_angle = 0):#, time=True):
        # Retrieves the required time or distance separation between leading and following aircraft type

        # leader_cat = self.get_icao_cat(leader_type)
        # follower_cat = self.get_icao_cat(follower_type)

        # if time:
            # sep = self.separation_time[leader_cat][follower_cat]

            # The following lines have been commented for the mean time, but can be uncommented
            # to use the dynamic liv calculation to find aircraft separation
            #sep = self.calc_liv_separation_typeA(leader_idx, follower_idx)
        sep = self.calc_liv_separation_typeB(leader_acid, leader_type, follower_acid, follower_type, wind_final, wind_angle)
        # print(sep, 'sep')

        # else:
        #
        #     sep = self.wtc_separation[leader_cat][follower_cat]
        return sep


    def calc_liv_separation_typeB(self, leader_acid, leader_type, follower_acid, follower_type, wind_final =0, wind_angle = 0):
        try:
            leader_cat = self.get_icao_cat(leader_type)
            follower_cat = self.get_icao_cat(follower_type)
        except:
            print(leader_type, follower_type, ' leader or follower is not found')
            leader_cat = self.get_icao_cat('B738')
            follower_cat = self.get_icao_cat('B738')


        wtc_separation = self.wtc_separation[leader_cat][follower_cat]
        wtc_separation_buffer = self.wtc_separation_buffer[leader_cat][follower_cat]
        minimum_liv_distance = 3  # NM 2.5????

        general_liv = round(minimum_liv_distance / 0.5) * 0.5
        # print(general_liv,'general liv')
        delta_liv = minimum_liv_distance - general_liv
        # print(delta_liv, 'delta liv')
        liv_distance = max(general_liv, wtc_separation) + wtc_separation_buffer + delta_liv

        w = wind_final # Wind speed in knots in direction of the runway #TODO connect calculation to the wind class in bluesky
        q = wind_angle  # Wind Angle with respect to runway # TODO

        #todo: which acid and type?? follower?
        ptas = self.ptas_calc(follower_acid, follower_type, wtc_separation)  # Average predicted true airspeed for follower aircraft
        # print(ptas,'ptas')
        try:
            cgs = -w * np.cos(q) + np.sqrt(ptas**2 - (w * np.sin(q))**2)
            liv = round(liv_distance / cgs * 3600,1)
        except TypeError:
            liv = 100.001
        if math.isnan(liv):
            liv = 100.001
        #source: srd-asap
        #zoeken: pTAS,LIV_distance, CGS, TBS, RECAT, minimum LIV, WTC separation buffer
        # ptas: predicted True Airspeed, = max(wtc_distance, min liv distance, integer), type, operator
        # LIV_distance: default = 3, range = 2.5-12
        # liv distance = MAX(general liv, wtc distance) + WTC buffer + delta LIV
        # general liv = round(min liv distance/0.5) *0.5
        # delta_liv = minimumLIV distance - general LIV
        # WTC separation buffer: default = 0, range = 0-2. Same for LIV buffer
        # minimum LIV: default = 72, range = 60-90

        # - minimum_LIV_distance: according
        # to
        # ASAP - SR - HMI - 152. - WTC_separation_distance: according
        # to
        # ASAP - SR - IBP - 66. - WTC_separation_buffer: according
        # to
        # ASAP - SR - IBP - 151.
        # print(liv_distance, 'liv_distance')
        # print(liv, 'liv')


        return liv

    def ptas_calc(self, acid, type, distance_to_rwy=3):
        # ac_name = bs.traf.id[follower_idx]
        # follower_type = bs.traf.type[follower_idx]

        # ac_name = "KLM345"
        # follower_type = "B738"
        # #

        pattern = re.compile("([a-zA-Z]+)([0-9]+)")
        try:
            airline_code, aircraft_number = pattern.match(acid).groups()
        except AttributeError:
            # print("-------------- ",acid)
            airline_code = 'default'

        if type in self.perfdata['type'].values:
            row = self.perfdata.loc[self.perfdata['type'] == type]

            if airline_code in row['airline'].values:
                row = row.loc[row['airline'] == airline_code]
                ptas = row[f'tas_{distance_to_rwy}'].iloc[0]
            else:
                #print("Airline not found in ptas data for this aircraft type, average of all airlines will be used")
                row = row.loc[row['airline'] == 'default']
                ptas = row[f'tas_{distance_to_rwy}'].iloc[0]
        else:
            print('Aircraft type not present in ptas data')
            ptas = None
            return ptas

        return ptas


def load_recat_categories(cat_file='RECAT_ACTYPE.csv'):
    df = pd.read_csv(cat_file, delimiter=';')
    df = df.drop('WTC', axis=1)
    return df


# def load_aircraft_ptas_data(filename='AircraftDB-ao[36].csv'):
#     df = pd.read_csv(filename)
#     df.rename(columns={'performance_name': 'airline_icao'}, inplace=True)
#     return df


def metres_to_nm(m):
    return m / 1852


def calc_layer_ground_dist(df: pd.DataFrame, angle: float = 3.0
                           ) -> pd.DataFrame:
    """Calculate the ground distance for each air layer.

    Given the angle at which an aircraft descends, this function
    determines how much distance the aircraft travels in each
    air layer.

    Args:
        df (pandas.DataFrame): Hi-res weather data for a single
            timestamp.  # TODO this is currently still using dummy data, simply a range of altitudes
        angle (float, optional): The constant angle at which an
            aircraft descends. Defaults to 3.0.

    Returns:
        pandas.DataFrame: Hi-res weather data with added information
            on ground distances.
    """

    # Sort air layers starting from ground (40)
    df = df.sort_values("altitude", ignore_index=True)

    # Calculate maximum altitude for each measurement
    altitude_nm = df["altitude"].apply(metres_to_nm)
    altitude_max = (altitude_nm + altitude_nm.shift(-1))

    # Calculate ground distance for each layer given the angle
    df["ground_dist_end"] = altitude_max / np.tan(np.radians(angle))
    df["ground_dist_start"] = df["ground_dist_end"].shift(1).fillna(0)

    return df


if __name__ == '__main__':
    alts = range(100, 2100, 100)
    whdgs = [180] * len(alts)
    wspds = [15] * len(alts)

    example_data = {
        'altitude': alts,
        'whdg': whdgs,
        'wspd': wspds
    }

    example_df = pd.DataFrame(example_data)
    output = calc_layer_ground_dist(example_df)

    separation = LivSeparation()

    leader = "A"
    follower = "A"


    final = separation.get_icao_cat('A320')
    print(final)
