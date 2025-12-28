Fireplace CLI (Heat & Glo IntelliFire IPI relay control)

Purpose
- Control a Heat & Glo IntelliFire IPI fireplace using a Raspberry Pi and a mechanical relay HAT.
- The fireplace does NOT accept a permanent short as a valid call; it expects wall-control-like behavior (momentary qualified closure).

Project contents
- fireplace.py: Python CLI that implements the timing model (boot guard + qualified pulse + optional maintained-call pattern)
- test_relays.sh: Interactive relay click/LED test (safe to run with the relay shield NOT connected to the fireplace)

Hardware used
- Raspberry Pi host name: fireplace
- Relay HAT: Inland “RPI 4 channel-Relay Shield” (SONGLE relays). This corresponds to Keyestudio KS0212.

Relay shield documentation (pinout)
- Keyestudio KS0212 wiki: https://wiki.keyestudio.com/KS0212_keyestudio_RPI_4-channel_Relay_Shield
- BCM GPIO mapping for the 4 relays: 4, 22, 6, 26
- We confirmed audibly that all four channels click on this unit.

Relay naming (used by fireplace.py)
- low_flame  -> BCM 4
- high_flame -> BCM 22
- aux_1      -> BCM 6
- aux_2      -> BCM 26

Confirmed physical relay positions (on the installed Pi)
- low_flame is the 1st physical relay (furthest from the USB ports)
- high_flame is the 2nd physical relay (one closer to the USB ports)

Terminology note
- The fireplace has a "main burner ON" call (R-W) and an optional "HIGH flame" call (G-W).
- When the burner is ON but HIGH is not asserted, that state is effectively the "low flame" mode.

Relay polarity (active-low vs active-high)
- Some relay hats energize on GPIO HIGH, others on GPIO LOW.
- For this KS0212/Inland shield, the vendor sample code toggles pins HIGH/LOW; in practice the safest approach is:
	- Default to ACTIVE-HIGH (omit --active-low).
	- Only use --active-low if you observe that the relay is ON when the CLI says OPEN.
- The helper scripts default to ACTIVE-HIGH now, and can be forced to run active-low if needed.

Confirmed for THIS installed shield
- ACTIVE-HIGH confirmed: the relay LED/click occurs during the printed CLOSE-ACTIVATE phase when running without --active-low.

Fireplace control terminals (Heat & Glo IntelliFire IPI)
- User interface is the R / W / G terminal block.
- W is the common/return.
- R–W: request main burner ON.
- G–W: request HIGH flame (only after burner is on).

Key findings from the provided context PDF (why we pulse)
- IPI sources ~8.3V DC open-circuit between R and W.
- Shorting R–W collapses voltage (input is sensed), but:
	- A permanent R–W short does NOT ignite.
	- R–W through 2.2k resistor is also rejected.
- Scope discovery: the IPI module injects a periodic diagnostic pulse to detect a valid wall control.
	- Static shorts/static loads are treated as faults and ignored.
- Bottom line: the Pi must emulate wall-control behavior (a qualified edge), not just continuity.

Wiring rules (SAFETY)
- Use only the relay’s COM and NO contacts.
- Do NOT use NC contacts.
- Do NOT inject any external voltage into R/W/G.

Suggested relay wiring
- Channel for Main burner: relay COM -> W, relay NO -> R
- Channel for High flame (optional): relay COM -> W, relay NO -> G

Timing model (from PDF)
- Boot guard: keep relay OPEN for ~12 seconds after Pi boot/reset (avoid detection window).
- Ignition request: CLOSE relay for ~200–300 ms (pulse), then OPEN.
- If unit drops without maintained call: use maintained-call pattern:
	- OPEN 1s
	- CLOSE 250ms
	- OPEN 250ms
	- CLOSE and HOLD while flame desired
	- OPEN to shut down

How to test the relay shield (not connected to fireplace)
- cd ~/fireplace-cli
- ./test_relays.sh
	- Defaults to pins 4,22,6,26 and guides you pin-by-pin.
	- Optional: ./test_relays.sh "4,22,6,26" 900 2.0 1.0 2.0 1.0 both

How to run the CLI (examples)
- Show known relay names:
	- python3 fireplace.py list-relays
- Dry run (no GPIO toggling):
	- python3 fireplace.py ignite --main-relay low_flame --dry-run
- Real ignition pulse (after wiring and choosing the correct polarity):
	- python3 fireplace.py ignite --main-relay low_flame
	- python3 fireplace.py ignite --main-relay low_flame --active-low
- Maintained-call mode:
	- python3 fireplace.py ignite --main-relay low_flame --maintained

Environment variable option
- export FIREPLACE_MAIN_RELAY=low_flame
- export FIREPLACE_HIGH_RELAY=high_flame
- export FIREPLACE_ACTIVE_LOW=1   (only if needed)
- python3 fireplace.py ignite

Local web UI (simple front-end)
- A minimal local-only web server that calls fireplace.py for you.
- Runs on 127.0.0.1:8080 by default.

Install and run
- cd ~/fireplace-cli
- python3 -m pip install -r requirements-web.txt
- python3 web_ui.py
- Open: http://127.0.0.1:8080

Environment variables
- FIREPLACE_WEB_HOST (default: 127.0.0.1)
- FIREPLACE_WEB_PORT (default: 8080)
