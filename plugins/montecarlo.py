import bluesky
from bluesky import core, stack, scr, traf, sim, net, network, plugins
from bluesky.network import context as ctx
import pandas as pd
from datetime import datetime
import webbrowser
import os
from plugins.amanhelpers import aman_settings




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
        self.amansettings = aman_settings
        self.opened = False
        self.remove_when_done = True
        self.multiple_mc = []
        self.multiple_mc_called = []

    def reset(self):
        super().reset()
        self._kill_all_nodes()
        self.nodes = []
        self.maxnodes = 0
        self.parent = b''
        self.active_nodes = set()
        self._seq = 0
        self.batch = pd.DataFrame(
            columns=['scenario', 'run', 'seed', 'usecache', 'node', 'status', 'maxtime', 'starttime', 'endtime',
                     'elapsed'])
        self.amansettings = aman_settings
        self.opened = False
        self.remove_when_done = True
        self.nextmc()

    @stack.command
    def addmultiplemc(self, *parts: str):
        # accepteert: ADDMULTIPLEMC MONTECARLO scen 100 8 ...
        # en maakt er weer één string commando van
        cmd = " ".join(parts).strip()
        if cmd:
            self.multiple_mc.append(cmd)

    @stack.command
    def nextmc(self):
        if len(self.multiple_mc) >0:
            com = self.multiple_mc.pop()
            print(com)
            stack.stack(f'ECHO {com}')
            self.multiple_mc_called.append(com)
            stack.stack(com)


    @stack.command
    def montecarlo(self, scenario: str, runs:int, maxnodes:int, usecache:bool=False, cachename:str='predictions_cache', startseed:int=0, maxtime='5:00:00', title=None):
        rows = []
        for i in range(int(runs)):
            rows.append({
                'scenario': scenario,
                'run': i,
                'seed': startseed + i,
                'usecache': usecache,
                'cachename': cachename,
                'node': None,
                'status': 'backlog',
                'maxtime': maxtime
            })
        if title:
            self.title = title
        else:
            self.title = f'{scenario}_{self.amansettings.popup_planner}_FH{int(self.amansettings.freezehorizon/60)}_S{startseed}_R{runs}'

        self.batch = pd.concat([self.batch, pd.DataFrame(rows)])
        self.maxnodes = maxnodes
        self.start()

    def start(self):
        remaining = int(self.batch['status'].isin(['backlog']).sum())
        # Goal: keep exactly self.maxnodes active nodes while there is still backlog.
        # Any surplus nodes will be idled by `sendscen()` (it sends RESET when no backlog).
        if remaining > 0:
            reqnodes = int(self.maxnodes)
        else:
            reqnodes = 0

        actnodes = len(self.active_nodes)
        newnodes = reqnodes - actnodes

        if newnodes > 0:
            ids = self._make_node_ids(newnodes)
            self.nodes = self.nodes + ids
            for nid in ids:
                self.active_nodes.add(nid)
            net.send(b'ADDNODES', dict(count=newnodes, node_ids=ids), net.server_id)

        # If complete and there is a queued next MC command, reset to continue the queue
        if remaining == 0 and len(self.active_nodes) == 0 and len(self.multiple_mc) > 0:
            stack.stack('RESET')


    @network.subscriber(topic='node-added')
    def on_node_added(self, node_id):
        if node_id in self.nodes:
            self.sendscen(node_id)
            # self.active_nodes.add(node_id)
        # else: send quit command?

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
        cachename = row['cachename']
        maxtime = row['maxtime']

        self.batch.at[job_id, 'status'] = 'running'
        self.batch.at[job_id, 'node'] = node_id
        self.batch.at[job_id, 'starttime'] = datetime.now()
        self.batch.at[job_id, 'endtime'] = pd.NaT
        self.batch.at[job_id, 'elapsed'] = 0.0

        stack.forward('RESET', target_id=node_id)
        stack.forward('MC CLAIM', target_id=node_id)
        stack.forward(f'SCEN {seed}_{scenario}', target_id=node_id)
        stack.forward(f'SEED {seed}', target_id=node_id)
        if usecache:
            stack.forward(f'USECACHE {scenario} {cachename}', target_id=node_id)
        else:
            stack.forward(f'PCALL {scenario}', target_id=node_id)
        stack.forward(f'SCHEDULE {maxtime} MC FINISHED', target_id=node_id)
        stack.forward('DT 1', target_id=node_id)
        stack.forward(f'SEED {seed}', target_id=node_id)


    @stack.commandgroup
    def MC(self):
        return True

    @MC.subcommand
    def claim(self):
        self.parent = stack.sender()

    @MC.subcommand
    def stopnode(self):
        # do scen stopped + oldname
        sim.quit()

    @MC.subcommand
    def finished(self):
        if self.parent:
            # stack.stack('SENDRESULT') this command does not work, as the sendresult function would have no destination to send to
            stack.forward('MC FINISHED', target_id=self.parent)

        else:
            node = stack.sender()
            if not self.parent and node in self.nodes:
                stack.forward('SENDRESULT', target_id=node)
                # self.sendscen(node)
                # self.removenode(node)
                # if self.remove_when_done:
                #     self.removenode(node)
                #     self.start()
                # else:
                #     stack.forward('COMPLETEHOLD', target_id=node)
                #     stack.forward('DT 1', target_id=node)
                #     self.active_nodes.remove(node)
                #     self.start()


    @network.subscriber(topic='MONTECARLORESULTS')
    def results(self, **data):
        print('received results: ')
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

            # self.printdf()
            self.storedf()
            self.df_to_html()

            self.removenode(from_node)
            self.start()


    @stack.command
    def getresults(self, targetnode:int=0):
        stack.forward('SENDRESULT', target_id=self.nodes[targetnode])

    # def _make_node_ids(self, n: int):
    #     """Return n full IDs under this server, last byte in 0xF0..0xFF."""
    #     base = net.server_id[:-1]  # 4-byte group/server prefix
    #     ids = []
    #     for i in range(n):
    #         last = 0xF0 + ((self._seq + i) % 16)  # 240..255
    #         ids.append(base + bytes([last]))
    #     self._seq = (self._seq + n) % 16
    #     return ids

    def _make_node_ids(self, n: int):
        """
        Return n unique node ids by varying the last byte.
        Uses a safe high-byte pool to avoid reserved/odd ids.
        """
        base = net.server_id[:-1]  # keep server prefix
        used = set(self.nodes) | set(self.active_nodes) | set(getattr(net, "nodes", set()))

        POOL_START = 0xC0  # 192
        POOL_END = 0xFF  # 255 inclusive
        SKIP = {0x81}  # if this one is used by some child node in your setup

        ids = []
        # self._seq is your rolling counter; keep it, but map into the pool
        offset = self._seq

        # pool size excluding skips
        pool = [b for b in range(POOL_START, POOL_END + 1) if b not in SKIP]
        pool_size = len(pool)

        tries = 0
        while len(ids) < n and tries < pool_size + n + 10:
            last = pool[offset % pool_size]
            cand = base + bytes([last])
            offset += 1
            tries += 1

            if cand in used or cand in ids:
                continue
            ids.append(cand)

        self._seq = offset  # advance seq

        if len(ids) < n:
            raise RuntimeError(
                f"Not enough free node IDs in pool {hex(POOL_START)}..{hex(POOL_END)} "
                f"(requested {n}, got {len(ids)})."
            )

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

        # Coerce everything to numeric; non-numeric becomes NaN. Force float to avoid bool dtype warnings.
        num = df.apply(lambda c: pd.to_numeric(c, errors="coerce")).astype("float64")

        summary = pd.DataFrame(index=["min", "mean", "max"], columns=df.columns, dtype="float64")
        if not num.empty:
            # Only fill columns that actually have at least one numeric value
            num_cols = [c for c in num.columns if num[c].notna().any()]
            if num_cols:
                summary.loc["min", num_cols] = num[num_cols].min(skipna=True)
                summary.loc["mean", num_cols] = num[num_cols].mean(skipna=True)
                summary.loc["max", num_cols] = num[num_cols].max(skipna=True)

        return pd.concat([df, summary], axis=0)


    @stack.command
    def sendresult_example(self):
        result = {'LLDA': 300, 'Instructions': 2, 'work': 1, 'delay energy': 69}
        sender = stack.sender()
        # print('sendresult')
        net.send('MONTECARLORESULTS',result, sender)
        #example of function that can be placed in other plugin to emit results, automatically get added to dataframe

    def storedf(self, path: str = "Montecarlo/"):
        """Store the batch DataFrame as a pickle, including the current title in the filename."""
        # Ensure output directory exists
        os.makedirs(path, exist_ok=True)
        filename = f"{self.title}.pkl"
        self.batch.to_pickle(os.path.join(path, filename))

    # @core.timed_function(dt= 5)
    # def autohtml(self):
    #     if self.predictor.parent_id:
    #         return
    #     self.df_to_html()

    @stack.command
    def df_to_html(self, path: str = "Montecarlo/"):
        """Exporteer de batch-DataFrame naar een nette HTML-tabel."""
        if self.parent:
            return
        df = self.summary().copy()

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
               <h3>{self.title} — simtime: {sim_hhmmss}</h3>
               {table_html}
             </div>
           </body>
           </html>
           """
        output_path = path + self.title +'.html'
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
            if not self.opened:
                webbrowser.open(f"file://{os.path.abspath(output_path)}")
                self.opened = True


    @stack.command
    def removenode(self, node_id):
        # node_id = self.active_nodes.pop()
        # print(f"Removing node {node_id}")
        # net.send(b'QUIT', to_group=node_id)
        stack.forward('PREDICTOR STOPNODE', target_id=node_id)
        stack.forward('MC STOPNODE', target_id=node_id)
        net.nodes.discard(node_id)
        net.node_removed.emit(node_id)
        self.active_nodes.remove(node_id)
        self.nodes.remove(node_id)




    def _kill_all_nodes(self):
        """Stop all nodes known to Montecarlo."""
        # Combine bookkeeping sources, avoid modifying during iteration
        all_nodes = list(set(self.nodes) | set(self.active_nodes))

        for node_id in all_nodes:
            try:
                # print(f"[MC] killing node {node_id}")
                stack.forward('PREDICTOR STOPNODE', target_id=node_id)
                stack.forward('MC STOPNODE', target_id=node_id)
            except Exception:
                pass

        # Best-effort GUI cleanup
        for node_id in all_nodes:
            try:
                net.nodes.discard(node_id)
                net.node_removed.emit(node_id)
            except Exception:
                pass

        # Local bookkeeping
        self.nodes.clear()
        self.active_nodes.clear()