from bluesky import core, stack, traf





def init_plugin():
    config = {
        'plugin_name': 'HOLDING',
        'plugin_type': 'sim'
    }
    plugin_inst = HoldingPattern()
    return config


class HoldingPattern(core.Entity):
    @stack.command
    def holdiaf(self, acid, ttlg, iaf, to_eto=None, direction="R"):
        """
        Holding pattern voor exact ttlg seconden op het opgegeven iaf-fix.
        """
        #to eto should be in seconds
        acid = acid.upper()
        iaf = iaf.upper()
        ttlg = float(ttlg)
        if to_eto:
            to_eto = float(to_eto) - 30
        else: to_eto = 0.0
        turn_time = 60.0
        total_turn_time = 2 * turn_time

        # Compute current selected heading and add 180° for relative turn
        idx = traf.id2idx(acid)
        current_hdg = traf.hdg[idx]
        # Determine turn direction: right (R) or left (L)
        turn_sign = 1 if direction.upper() == "R" else -1
        turn_angle = 90.0 * turn_sign
        # Initial 90° turn to start hold
        first_hdg = (current_hdg + turn_angle) % 360.0

        stack.stack(f"DELAY {to_eto} BANK {acid} 40")
        stack.stack(f"DELAY {to_eto} HDG {acid} {first_hdg:.1f}")
        # Complete racetrack: 180° back inbound
        second_hdg = (first_hdg + turn_angle) % 360.0
        stack.stack(f"DELAY {to_eto + 15} HDG {acid} {second_hdg:.1f}")
        # Final 90° turn before direct to IAF
        direct_turn_hdg = (second_hdg + turn_angle) % 360.0

        stack.stack(f"DELAY {to_eto + 0.5*ttlg} HDG {acid} {direct_turn_hdg:.1f}")
        stack.stack(f"DELAY {to_eto + 0.5*ttlg} DIRECT {acid} {iaf}")

        stack.stack(f"DELAY {to_eto + 0.5*ttlg + 90} BANK {acid} 25")