from bluesky import core, stack, scr, traf, sim, net, network
from bluesky.network import context as ctx
import pandas as pd
from datetime import datetime




def init_plugin():
    """Initializes the plugin and creates an instance of the Predictor."""

    # Create an instance of the Predictor class
    global MC
    MC = monte_carlo()

    # Configuration for the plugin, specifying its name and type.
    config = {
        'plugin_name': 'MONTECARLO',
        'plugin_type': 'sim',
    }
    return config



class monte_carlo(core.Entity):

    def __init__(self):
        super().__init__()

        self.nodes = []
        self.maxnodes = 0
        self.parent = b''
        self.active_nodes = set()
        self._seq = 0
        self.batch = pd.DataFrame(columns=['scenario', 'run', 'seed', 'usecache', 'node', 'status', 'maxtime', 'starttime','endtime','elapsed'])


    @stack.command
    def montecarlo(self, scenario: str, runs:int, maxnodes:int, usecache:bool=False, startseed:int=0, maxtime='5:00:00'):
        rows = []
        for i in range(int(runs)):
            rows.append({
                'scenario': scenario,
                'run': i,
                'seed': startseed + i,
                'usecache': usecache,
                'node': None,
                'status': 'backlog',
                'maxtime': maxtime
            })

        self.batch = pd.concat([self.batch, pd.DataFrame(rows)])
        self.maxnodes = maxnodes
        self.start()

    def start(self):
        reqnodes= min(self.maxnodes, len(self.batch))
        actnodes = len(self.active_nodes)
        newnodes = reqnodes - actnodes
        if newnodes != 0:
            ids = self._make_node_ids(newnodes)
            self.nodes = self.nodes + ids
            net.send(b'ADDNODES', dict(count=newnodes, node_ids=ids), net.server_id)


    @network.subscriber(topic='node-added')
    def on_node_added(self, node_id):
        if node_id in self.nodes:
            self.sendscen(node_id)
            self.active_nodes.add(node_id)

    def sendscen(self,node_id):
        selected_scen = self.batch.index[self.batch['status'].eq('backlog')]
        if len(selected_scen) == 0:
            stack.forward('RESET', target_id=node_id)
            stack.stack('ECHO holding one of the nodes, make sure data gets stored!')
            return

        job_id = selected_scen[0]
        row = self.batch.loc[job_id]
        scenario = row['scenario']
        run = row['run']
        seed = row['seed']
        usecache = row['usecache']
        maxtime = row['maxtime']

        self.batch.at[job_id, 'status'] = 'running'
        self.batch.at[job_id, 'node'] = node_id
        self.batch.at[job_id, 'starttime'] = datetime.now()
        self.batch.at[job_id, 'endtime'] = pd.NaT
        self.batch.at[job_id, 'elapsed'] = 0.0

        stack.forward('RESET', target_id=node_id)
        stack.forward('MC CLAIM', target_id=node_id)
        stack.forward(f'SCEN {run}_{scenario}', target_id=node_id)
        stack.forward(f'SEED {seed}', target_id=node_id)
        if usecache:
            stack.forward(f'USECACHE {scenario}', target_id=node_id)
        else:
            stack.forward(f'PCALL {scenario}', target_id=node_id)
        stack.forward(f'SCHEDULE {maxtime} MC FINISHED', target_id=node_id)
        stack.forward('DT 0.5', target_id=node_id)
        stack.forward(f'SEED {seed}', target_id=node_id)


    @stack.commandgroup
    def MC(self):
        return True

    @MC.subcommand
    def claim(self):
        self.parent = stack.sender()

    @MC.subcommand
    def finished(self):
        if self.parent:
            stack.forward('MC FINISHED', target_id=self.parent)
        else:
            node = stack.sender()
            if not self.parent and node in self.nodes:
                stack.forward('SENDRESULT', target_id=node)
                self.sendscen(node)


    @network.subscriber(topic='MONTECARLORESULTS')
    def results(self, **data):
        print('received results: ', data)
        if not self.parent:
            from_node = ctx.sender_id
            mask = (self.batch['node'] == from_node) & (self.batch['status'] == 'running')
            if not mask.any():
                stack.stack('ECHO no running job for this node')
                return

            job_id = self.batch.index[mask][0]
            for k in data.keys():
                if k not in self.batch.columns:
                    self.batch[k] = pd.NA

            for k, v in data.items():
                self.batch.at[job_id, k] = v

            self.batch.at[job_id, 'status'] = 'done'
            end = datetime.now()
            self.batch.at[job_id, 'endtime'] = end
            start = self.batch.at[job_id, 'starttime']
            if pd.notna(start):
                self.batch.at[job_id, 'elapsed'] = (end - start).total_seconds()

            self.printdf()
            self.storedf()
            self.df_to_html()



    @stack.command
    def getresults(self, targetnode:int=0):
        stack.forward('SENDRESULT', target_id=self.nodes[targetnode])

    def _make_node_ids(self, n: int):
        """Return n full IDs under this server, last byte in 0xF0..0xFF."""
        base = net.server_id[:-1]  # 4-byte group/server prefix
        ids = []
        for i in range(n):
            last = 0xF0 + ((self._seq + i) % 16)  # 240..255
            ids.append(base + bytes([last]))
        self._seq = (self._seq + n) % 16
        return ids



    @stack.command
    def printdf(self):

        now = datetime.now()
        if 'starttime' in self.batch.columns:
            running = self.batch['status'] == 'running'
            self.batch.loc[running, 'elapsed'] = (
                    now - self.batch.loc[running, 'starttime']
            )
        print(self.batch)
        print(self.summary())

    def summary(self):
        """Geef batch + extra rijen ['min','mean','max'] terug zonder self.batch te wijzigen."""
        df = self.batch.copy()

        # live elapsed voor running
        if 'starttime' in df.columns and 'status' in df.columns:
            now = datetime.now()
            running = df['status'].eq('running')
            df.loc[running, 'elapsed'] = (now - df.loc[running, 'starttime'])

        num = df.apply(lambda c: pd.to_numeric(c, errors='coerce'))

        summary = pd.DataFrame(index=['min', 'mean', 'max'], columns=df.columns, dtype='float64')
        if not num.empty:
            summary.loc['min', num.columns] = num.min(skipna=True)
            summary.loc['mean', num.columns] = num.mean(skipna=True)
            summary.loc['max', num.columns] = num.max(skipna=True)

        return pd.concat([df, summary], axis=0)


    @stack.command
    def sendresult_example(self):
        result = {'LLDA': 300, 'Instructions': 2, 'work': 1, 'delay energy': 69}
        sender = stack.sender()
        print('sendresult')
        net.send('MONTECARLORESULTS',result, sender)
        #example of function that can be placed in other plugin to emit results, automatically get added to dataframe

    def storedf(self, path = "montecarlo_batch.pkl"):
        self.batch.to_pickle(path)


    @stack.command
    def df_to_html(self, path: str = "montecarlo.html"):
        """Exporteer de batch-DataFrame naar een nette HTML-tabel."""
        df = self.batch.copy()

        # Datetimes naar string
        for col in ("starttime", "endtime"):
            if col in df.columns:
                df[col] = (
                    pd.to_datetime(df[col], errors="coerce")
                    .dt.strftime("%Y-%m-%d %H:%M:%S")
                )

        # Elapsed naar HH:MM:SS
        if "elapsed" in df.columns:
            # Probeer als Timedelta, anders als seconden
            td = pd.to_timedelta(df["elapsed"], errors="coerce")
            # voor NaT: probeer numeriek als seconden
            mask = td.isna()
            if mask.any():
                sec = pd.to_numeric(df.loc[mask, "elapsed"], errors="coerce")
                td.loc[mask] = pd.to_timedelta(sec, unit="s")
            # als nog NaT, zet naar 0
            td = td.fillna(pd.Timedelta(0))
            df["elapsed"] = td.apply(lambda x: str(x).split(".")[0])  # zonder microsec

        # Bytes in 'node' leesbaar maken
        if "node" in df.columns:
            def _fmt_node(x):
                if pd.isna(x):
                    return ""
                if isinstance(x, (bytes, bytearray)):
                    return repr(x)
                return str(x)

            df["node"] = df["node"].apply(_fmt_node)

        # HTML-tabel
        table_html = df.to_html(classes="table table-bordered", index=True)

        # Simulatietijd bovenaan
        sim_sec = int(sim.simt) if hasattr(sim, "simt") else 0
        sim_hhmmss = f"{sim_sec // 3600:02d}:{(sim_sec % 3600) // 60:02d}:{sim_sec % 60:02d}"

        # Stijl + pagina
        html = f"""
           <html>
           <head>
           <meta charset="utf-8" />
           <style>
               .container {{
                   padding: 12px;
               }}
               .table {{
                   border-collapse: collapse;
                   font-size: 12px;
                   white-space: nowrap;
               }}
               .table th {{
                   position: sticky;
                   top: 0;
                   background: #f1f1f1;
               }}
               .table th, .table td {{
                   border: 1px solid #000;
                   padding: 4px 6px;
                   text-align: left;
               }}
           </style>
           </head>
           <body>
             <div class="container">
               <h3>MonteCarlo batch — simtime: {sim_hhmmss}</h3>
               {table_html}
             </div>
           </body>
           </html>
           """

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

