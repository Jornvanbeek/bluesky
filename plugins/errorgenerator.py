import random

import hashlib
import numpy as np
from scipy.stats import johnsonsu, norm
import pickle
import pandas as pd
import matplotlib.pyplot as plt


class ErrorGenerator:
    def __init__(self):

        # setting distributions
        self.outside_fir = None
        self.inside_fir = None
        self.dep_route = None
        # self.departure
        self.stats = None
        self.departure_route_title = 'SID_rel'
        self.stddev_withinfir = 1.5 # %
        self.cop_pdf = (-0.1840341263226265, 1.3898584120283286, -0.22623562655786733, 9.968335882486613)
        self.PDF_file = 'plugins/PDF.pkl'
        self.load_distributions(self.PDF_file)
        self.seed = 2


    def load_distributions(self, file):
        with open(file, 'rb') as f:
            df = pickle.load(f)

        # alleen doen als 'airport' nog kolom is
        if 'airport' in df.columns:
            df = df.set_index('airport')

        # pak alleen integer lookahead kolommen
        lookahead_cols = [c for c in df.columns if not isinstance(c, str)]

        # maak een nette MultiIndex Series met (airport, lookahead) -> celwaarde
        s = df[lookahead_cols].stack()

        # bouw records als vaste tuples en zet die om naar een DataFrame
        records = s.apply(
            lambda x: (
                float(x[0][0]),  # a
                float(x[0][1]),  # b
                float(x[0][2]),  # loc
                float(x[0][3]),  # scale
                int(x[1]),  # samplesize
                johnsonsu(x[0][0], x[0][1], loc=x[0][2], scale=x[0][3])  # frozen dist
            )
        )

        dist_df = pd.DataFrame.from_records(
            records.values,
            index=s.index,
            columns=['a', 'b', 'loc', 'scale', 'samplesize', 'distribution']
        )
        dist_df.index.names = ['airport', 'lookahead']

        # optioneel: wide view met alleen distributies (airports x lookahead)
        dist_wide = dist_df['distribution'].unstack()
        self.stats = dist_df

        # departure-route per airport uit kolom self.departure_route_title
        params_series = df[self.departure_route_title] # ((a,b,loc,scale), n) -> (a,b,loc,scale)

        a, b, loc, scale = zip(*params_series.tolist())
        dep = pd.DataFrame({'a': a, 'b': b, 'loc': loc, 'scale': scale}, index=params_series.index)
        dep['distribution'] = [johnsonsu(aa, bb, loc=ll, scale=ss) for aa, bb, ll, ss in zip(a, b, loc, scale)]
        self.dep_route = dep  # index=airport; kolommen: a,b,loc,scale,distribution




        a, b, loc, scale = self.cop_pdf
        self.outside_fir = johnsonsu(a, b, loc=loc, scale=scale)
        self.inside_fir = norm(loc=0, scale=self.stddev_withinfir) # distributions in percentage




    def sample(self, rng, dist):
        return dist.rvs(random_state=rng )


    def return_sample(self,acid, airport, lookahead = 0):

        rng = self._rng(acid) #rng is the same for each sample of the flight, should only change between different global seeds

        if lookahead >0:
            takeoffdist = self.stats.loc[(airport,lookahead),'distribution']
            takeoff = self.sample(rng,takeoffdist )
        else:
            takeoff = 0

        #dep_route

        if airport in self.dep_route.index:
            dep_route_dist = self.dep_route.loc[airport, 'distribution']
            dep_route = self.sample(rng, dep_route_dist)
        else:
            dep_route = 0


        enroute = self.sample(rng, self.outside_fir)
        fir = self.sample(rng, self.inside_fir)


        return takeoff, dep_route, enroute, fir
        # time, %,%,%
        # approx enroute/fir at handover alt



    def _rng(self, acid: str, component: str = "") -> np.random.Generator:
        """
        Maak een deterministische RNG gebaseerd op (GLOBAL_SEED, acid, component).
        Hierdoor krijg je altijd dezelfde reeks voor hetzelfde vliegtuig.
        """
        key = f"{self.seed}|{acid}|{component}"
        h = hashlib.sha256(key.encode("utf-8")).digest()
        seed_int = int.from_bytes(h[:8], "big")  # neem 64 bits uit de hash
        return np.random.default_rng(seed_int)









    def plot_distribution(self, airport: str, lookahead: int, samples: int = 5000, show_hist: bool = True):
        """
        Plot de distributie voor een specifieke airport en lookahead.
        - airport: bijv. 'EBBR'
        - lookahead: bijv. 10
        - samples: aantal random samples voor histogram
        - show_hist: als True, histogram + PDF; anders alleen PDF
        """

        # Haal frozen distribution op
        if self.stats is None:
            raise ValueError("Distributions not loaded. Call load_distributions first.")

        dist = self.stats.loc[(airport, lookahead), 'distribution']

        # X-range gebaseerd op percent-point function (robuste grenzen)
        x_min, x_max = dist.ppf([0.005, 0.995])
        x = np.linspace(x_min, x_max, 500)

        # Plot PDF
        plt.figure()
        plt.plot(x, dist.pdf(x), label="PDF")

        if show_hist:
            samples_arr = dist.rvs(size=samples)
            plt.hist(samples_arr, bins=60, density=True, alpha=0.5, label="Samples")
            a_hat, b_hat, loc_hat, scale_hat = johnsonsu.fit(samples_arr)
            dist_fit = johnsonsu(a_hat, b_hat, loc=loc_hat, scale=scale_hat)
            plt.plot(x, dist_fit.pdf(x), "--", label="Fitted PDF")

        plt.title(f"{airport} – lookahead {lookahead} min")
        plt.xlabel("Error [min]")
        plt.ylabel("Density")
        plt.legend()
        plt.tight_layout()
        plt.show()



