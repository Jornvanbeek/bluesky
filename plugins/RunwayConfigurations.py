import pandas as pd
class RunwayConfiguration:
    def __init__(self, current_peak_type='Inbound peak', current_runways=None):
        self.current_peak_type = current_peak_type # outbound, inbound, off
        self.current_runways = {"Landing": (),
                                "Starting": ()} if current_runways is None else current_runways
        self.icao_categories = self.load_recat_categories()

        self.separation_dist = {}
        self.separation_time = {}

        self.min_radar_sep = 3  # NM
        self.min_time_sep = 90  # s

        self.load_separation_dicts()

        self.available_runways = {"Inbound peak": {"Available runways": {"Landing": ("18R", "27"),
                                                                         "Starting": ("24")},
                                                   "Times": [('0540', '0720'),
                                                             ('0900', '0940'),
                                                             ('1100', '1200'),
                                                             ('1320', '1420'),
                                                             ('1620', '1800')
                                                             ]
                                                   },

                                  "Outbound peak": {"Available runways": {"Landing": ("18R"),
                                                                          "Starting": ("24", "18L")},
                                                    "Times": [('0500', '0540'),
                                                              ('0720', '0900'),
                                                              ('0940', '1100'),
                                                              ('1200', '1320'),
                                                              ('1420', '1540'),
                                                              ('1840', '2010')]
                                                    },

                                  "Off-peak": {"Available runways": {"Landing": ("18R"),
                                                                     "Starting": ("24")},
                                               "Times": [('0430', '0500'),
                                                         ('1540', '1620'),
                                                         ('1800', '1840'),
                                                         ('2010', '2030')]
                                               }
                                  }


        self.landing_rwys = self.available_runways[self.current_peak_type]["Available runways"]["Landing"]
        self.starting_rwys = self.available_runways[self.current_peak_type]["Available runways"]["Starting"]

        self.peak_times = sorted(sum([dic['Times'] for name, dic in self.available_runways.items()], []))
        self.peak_types = [name for time in self.peak_times for name, dic in self.available_runways.items() if
                           time in dic["Times"]]

    def load_recat_categories(self, cat_file='plugins/RECAT_ACTYPE.csv'):
        df = pd.read_csv(cat_file, delimiter=';')
        df = df.drop('WTC', axis=1)
        return df

    def load_separation_dicts(self):
        categories = ['A', 'B', 'C', 'D', 'E', 'F']

        min_radar_sep = self.min_radar_sep   # NM
        min_time_sep = self.min_time_sep

        self.separation_dist = {'A': {'A': 3,            'B': 4,                'C': 5,             'D': 5,             'E': 6,             'F': 8},
                               'B': {'A': min_radar_sep, 'B': 3,                'C': 4,             'D': 4,             'E': 5,             'F': 7},
                               'C': {'A': min_radar_sep, 'B': min_radar_sep,    'C': 3,             'D': 3,             'E': 4,             'F': 6},
                               'D': {'A': min_radar_sep, 'B': min_radar_sep,    'C': min_radar_sep, 'D': min_radar_sep, 'E': min_radar_sep, 'F': 5},
                               'E': {'A': min_radar_sep, 'B': min_radar_sep,    'C': min_radar_sep, 'D': min_radar_sep, 'E': min_radar_sep, 'F': 4},
                               'F': {'A': min_radar_sep, 'B': min_radar_sep,    'C': min_radar_sep, 'D': min_radar_sep, 'E': min_radar_sep, 'F': 3}
                               }

        self.separation_time = {'A':{'A': 100,            'B': 110,             'C': 120,             'D': 130,             'E': 140,             'F': 150},
                               'B': {'A': min_time_sep, 'B': 111,             'C': 121,             'D': 131,             'E': 141,             'F': 151},
                               'C': {'A': min_time_sep, 'B': min_time_sep,  'C': 122,             'D': 132,             'E': 142,             'F': 152},
                               'D': {'A': min_time_sep, 'B': min_time_sep,  'C': min_time_sep,  'D': min_time_sep,  'E': min_time_sep,  'F': 153},
                               'E': {'A': min_time_sep, 'B': min_time_sep,  'C': min_time_sep,  'D': min_time_sep,  'E': min_time_sep,  'F': 154},
                               'F': {'A': min_time_sep, 'B': min_time_sep,  'C': min_time_sep,  'D': min_time_sep,  'E': min_time_sep,  'F': 155}
                               }



    def get_icao_cat(self, icao):
        result = self.icao_categories[self.icao_categories['ACTYPE'] == icao]['RECAT'].iloc[0]
        return result


    def required_separation(self, leader_type, follower_type, time=True):
        # Retrieves the required time or distance separation between leading and following aircraft type
        leader_cat = self.get_icao_cat(leader_type)
        follower_cat = self.get_icao_cat(follower_type)

        if time:
            sep = self.separation_time[leader_cat][follower_cat]
        else:
            sep = self.separation_dist[leader_cat][follower_cat]
        return sep


    def convert_recat_to_liv(self):
        pass










if __name__ == "__main__":
    configuration = RunwayConfiguration('Inbound peak')
    result = configuration.get_icao_cat('B737')

    print(result)



