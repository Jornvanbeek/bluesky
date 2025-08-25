"""
Plugin: NODES discovery (simplified)
Adds a stack command `NODES` that prints every BlueSky node id the plugin can
find (current, discovered, and anything exposed by bs.net).
"""

import bluesky as bs
from bluesky import stack
from bluesky.network.common import seqidx2id

# Store every node id we learn about
_KNOWN_NODES: set[bytes] = set()

def _parent_server_id(node_id: bytes) -> bytes:
    return node_id[:-1] + seqidx2id(0)

def _group_info(node_id: bytes) -> tuple[bool, bytes | None]:
    try:
        parent = _parent_server_id(node_id)
        servers = getattr(bs.net, 'servers', None)
        if servers is not None and parent in servers:
            return True, parent
    except Exception:
        pass
    return False, None

def _collect_runtime_nodes():
    """Best-effort sweep of bs.net to gather node ids currently known."""
    try:
        # Active node id (this process)
        act = getattr(bs.net, 'act_id', None)
        if act:
            _KNOWN_NODES.add(act)
    except Exception:
        pass

    # Probe a few likely containers without assuming a specific BlueSky version
    for attr in ('nodes', 'clients', 'node_ids', 'all_nodes', 'known_nodes'):
        try:
            obj = getattr(bs.net, attr, None)
        except Exception:
            obj = None
        if not obj:
            continue
        try:
            if isinstance(obj, dict):
                _KNOWN_NODES.update(obj.keys())
            elif isinstance(obj, (list, set, tuple)):
                _KNOWN_NODES.update(obj)
        except Exception:
            # Ignore unexpected shapes
            pass


def _on_node_added(node_id: bytes):
    """Signal handler for newly discovered nodes."""
    try:
        _KNOWN_NODES.add(node_id)
    except Exception:
        pass


def _on_node_removed(node_id: bytes):
    """Optional: prune nodes when they disappear (if signal exists)."""
    try:
        _KNOWN_NODES.discard(node_id)
    except Exception:
        pass


def init_plugin():
    """BlueSky plugin entrypoint."""
    # Subscribe to discovery signals if present (best-effort, version-safe)
    try:
        bs.net.node_added.connect(_on_node_added)
    except Exception:
        pass
    try:
        bs.net.node_removed.connect(_on_node_removed)
    except Exception:
        pass

    # Do an initial sweep so `NODES` works immediately
    _collect_runtime_nodes()

    return {
        'plugin_name': 'NODES_DISCOVERY',
        'plugin_type': 'sim',
    }


@stack.command
def nodes():
    """
    Print all known node IDs.

    Usage:
      NODES  -> lists every node id this plugin can find
    """
    # Refresh knowledge right before printing
    _collect_runtime_nodes()

    if not _KNOWN_NODES:
        try:
            bs.scr.echo("NODES: no nodes found.")
        except Exception:
            pass
        return

    try:
        node_list = sorted(_KNOWN_NODES)
    except Exception:
        node_list = list(_KNOWN_NODES)

    act = getattr(bs.net, 'act_id', None)

    grouped_lines = []
    ungrouped_lines = []

    for i, nid in enumerate(node_list):
        try:
            is_grouped, parent = _group_info(nid)
            flag = "[THIS]" if nid == act else "     "
            if is_grouped:
                line = f"{i}: {nid!r}  {flag}  group={parent!r}"
                grouped_lines.append(line)
            else:
                line = f"{i}: {nid!r}  {flag}  group=UNGROUPED"
                ungrouped_lines.append(line)
        except Exception:
            # Fallback if _group_info or formatting fails
            try:
                flag = "[THIS]" if nid == act else "     "
                line = f"{i}: {nid!r}  {flag}  group=UNGROUPED"
                ungrouped_lines.append(line)
            except Exception:
                pass

    try:
        bs.scr.echo("NODES (this node marked [THIS])")
        if grouped_lines:
            bs.scr.echo("-- Grouped --")
            for line in grouped_lines:
                bs.scr.echo(line)
        if ungrouped_lines:
            bs.scr.echo("-- Ungrouped --")
            for line in ungrouped_lines:
                bs.scr.echo(line)
    except Exception:
        pass

    @stack.command
    def killungrouped(idx: int):
        """
        Kill an UNGROUPED node by index from the NODES list using stack.forward.
        Usage:
          KILLUNGROUPED <index>
        """
        _collect_runtime_nodes()
        try:
            node_list = sorted(_KNOWN_NODES)
        except Exception:
            node_list = list(_KNOWN_NODES)

        if not node_list:
            try:
                bs.scr.echo("KILLUNGROUPED: no nodes found.")
            except Exception:
                pass
            return

        if idx < 0 or idx >= len(node_list):
            try:
                bs.scr.echo(f"KILLUNGROUPED: invalid index {idx}, valid range 0..{len(node_list) - 1}")
            except Exception:
                pass
            return

        target_id = node_list[idx]
        is_grouped, _ = _group_info(target_id)
        if is_grouped:
            try:
                bs.scr.echo(f"KILLUNGROUPED: node {target_id!r} is grouped — refusing to kill.")
            except Exception:
                pass
            return

        try:
            # Send QUIT to that node directly
            stack.forward('QUIT', target_id=target_id)
            try:
                bs.scr.echo(f"KILLUNGROUPED: forwarded QUIT to {target_id!r}")
            except Exception:
                pass
        except Exception as e:
            try:
                bs.scr.echo(f"KILLUNGROUPED: failed to forward QUIT to {target_id!r}: {e}")
            except Exception:
                pass