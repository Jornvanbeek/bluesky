"""
Minimal Working Example plugin for testing parent<->child node messaging latency.

What it does:
- TPTEST START: sets DT 1 on main, starts a child node.
- When the child is added: loads this plugin on the child, sets DT 1 on the child,
  and automatically sends 100 ping messages.
- Child replies with small random data.
- Prints easy-to-read latency lines in seconds.

Commands (in BlueSky console):
- TPTEST START
- TPTEST PING [n]        (default n=1)
- TPTEST SPAM n dt       (send n pings, spaced by dt seconds; dt default 0.1)
- TPTEST STOP            (only forgets child id; does not kill node)
"""

import time
import numpy as np

from bluesky import core, stack, net, network
from bluesky.core import signal
from bluesky.network.common import genid, GROUPID_SIM


def init_plugin():
    global tptest
    tptest = TPTest()
    return {
        "plugin_name": "TPTEST",
        "plugin_type": "sim",
    }


def _now_ns() -> int:
    return time.time_ns()


def _s(dt_ns: int) -> float:
    return dt_ns / 1e9


def _get_my_node_id() -> bytes:
    for attr in ("get_id", "get_my_id", "get_node_id", "nodeid", "myid", "id"):
        if hasattr(net, attr):
            v = getattr(net, attr)
            try:
                out = v() if callable(v) else v
                if isinstance(out, (bytes, bytearray)) and len(out) > 0:
                    return bytes(out)
            except Exception:
                pass
    return b""


class TPTest(core.Entity):
    def __init__(self):
        super().__init__()
        self.child_id: bytes = b""
        self.parent_id: bytes = b""
        self.seq: int = 0

    @stack.commandgroup
    def tptest(self):
        return True, "TPTEST: START | PING [n] | SPAM n dt | STOP"

    @tptest.subcommand
    def start(self):
        """Start child + set DT 1 + auto send 100."""
        if self.child_id:
            return True, f"Child already exists: {self.child_id!r}"

        # DT 1 on main
        stack.stack("DT 1")
        stack.stack('OP')

        self.parent_id = _get_my_node_id()
        self.child_id = genid(GROUPID_SIM)
        net.addnodes(1, self.child_id)

        return True, f"Starting child {self.child_id!r} (parent {self.parent_id!r})"

    @signal.subscriber(topic="node-added")
    def on_node_added(self, node_id):
        if not self.child_id or node_id != self.child_id:
            return

        self.parent_id = _get_my_node_id()

        # Load plugin on child + let it learn parent + DT 1 on child
        stack.forward("PLUGIN TPTEST", target_id=self.child_id)
        stack.forward("TPTEST CLAIM", target_id=self.child_id)
        stack.forward("DT 1", target_id=self.child_id)
        stack.forward("FF", target_id=self.child_id)

        # Auto-run: 100 messages as fast as possible
        self.ping(100)

    @tptest.subcommand
    def claim(self):
        # runs on child
        self.parent_id = stack.sender()

    @tptest.subcommand
    def stop(self):
        self.child_id = b""
        return True, "TPTEST stopped (child id cleared)."

    @tptest.subcommand
    def ping(self, n: int = 1):
        if not self.child_id:
            return False, "No child. Use TPTEST START first."

        if not self.parent_id:
            self.parent_id = _get_my_node_id()

        batch0 = _now_ns()
        for _ in range(int(n)):
            self.seq += 1
            t0 = _now_ns()
            msg = {
                "t0_ns": t0,
                "batch0_ns": batch0,
                "seq": self.seq,
                "parent_id": self.parent_id,
            }

            # elapsed since *batch* start shows how send time spreads out
            print(f"MAIN: sent message {self.seq}, t={_s(t0 - batch0):.3f}s (since batch start)")
            net.send("TPTEST_PING", msg, self.child_id)

        return True, f"Sent {int(n)} ping(s)."

    @tptest.subcommand
    def spam(self, n: int, dt: float = 0.1):
        if not self.child_id:
            return False, "No child. Use TPTEST START first."

        n = int(n)
        dt = float(dt)

        for _ in range(n):
            self.ping(1)
            time.sleep(dt)

        return True, f"Sent {n} ping(s) with dt={dt}s."

    @network.subscriber(topic="TPTEST_PING")
    def on_ping_child(self, *, t0_ns=0, batch0_ns=0, seq=-1, parent_id=b"", **kwargs):
        # running on main? ignore
        if self.child_id:
            return

        t_recv = _now_ns()
        t0 = int(t0_ns or 0)
        seq_i = int(seq if seq is not None else -1)
        batch0 = int(batch0_ns or t0)

        reply_to = parent_id or self.parent_id or GROUPID_SIM

        print(
            f"TP: received message {seq_i}, t={_s(t_recv - batch0):.3f}s (batch), "
            f"elapsed={_s(t_recv - t0):.3f}s (since send)"
        )

        # tiny work
        rnd = np.random.random(5).tolist()

        pong = {
            "t0_ns": t0,
            "batch0_ns": batch0,
            "seq": seq_i,
            "t_child_recv_ns": t_recv,
            "rnd": rnd,
        }

        net.send("TPTEST_PONG", pong, reply_to)

        t_sent = _now_ns()
        print(
            f"TP: returned message {seq_i}, t={_s(t_sent - batch0):.3f}s (batch), "
            f"elapsed={_s(t_sent - t0):.3f}s (since send)"
        )

    @network.subscriber(topic="TPTEST_PONG")
    def on_pong_main(self, *, t0_ns=0, batch0_ns=0, seq=-1, **kwargs):
        # only meaningful on main
        if not self.child_id:
            return

        t_main = _now_ns()
        t0 = int(t0_ns or 0)
        seq_i = int(seq if seq is not None else -1)
        batch0 = int(batch0_ns or t0)

        print(
            f"MAIN: received return {seq_i}, t={_s(t_main - batch0):.3f}s (batch), "
            f"elapsed={_s(t_main - t0):.3f}s (since send)"
        )