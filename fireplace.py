#!/usr/bin/env python3
import argparse
import os
import signal
import sys
import time
from dataclasses import dataclass
from typing import Optional


_COLOR_MODE: str = os.getenv("FIREPLACE_COLOR", "auto")


def _use_color() -> bool:
    mode = (_COLOR_MODE or "auto").strip().lower()
    if mode == "never":
        return False
    if mode == "always":
        return True

    # auto
    if os.getenv("NO_COLOR") is not None:
        return False
    if not sys.stdout.isatty():
        return False
    term = (os.getenv("TERM") or "").strip().lower()
    if term in {"", "dumb"}:
        return False
    return True


def _color(text: str, code: str) -> str:
    if not _use_color():
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def _green(text: str) -> str:
    return _color(text, "32")


def _red(text: str) -> str:
    return _color(text, "31")


def _read_uptime_seconds() -> Optional[float]:
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            first = f.read().strip().split()[0]
        return float(first)
    except Exception:
        return None


def _sleep_with_sigint(seconds: float) -> None:
    end = time.monotonic() + max(0.0, seconds)
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.2, remaining))


@dataclass(frozen=True)
class RelayConfig:
    pin: int
    active_low: bool


# Inland RPI 4-channel relay shield == Keyestudio KS0212
# Documented BCM relay control pins: 4, 22, 6, 26
#
# Purpose-based names:
# - low_flame: "main burner ON" request (R-W). If HIGH is not asserted, this is effectively "low".
# - high_flame: "high flame" request (G-W), only after burner is on.
# - aux_1/aux_2: spare channels.
#
# Physical relay positions (confirmed on the installed Pi):
# - low_flame is the 1st physical relay (furthest from the USB ports)
# - high_flame is the 2nd physical relay (one closer to the USB ports)
#
# Logic level (confirmed on the installed Pi):
# - ACTIVE-HIGH: relay energizes (LED/click) during the CLI's CLOSE-ACTIVATE phase without --active-low.
KNOWN_RELAYS: dict[str, int] = {
    "low_flame": 4,
    "high_flame": 22,
    "aux_1": 6,
    "aux_2": 26,
}

PHYSICAL_RELAY_NOTES: dict[str, str] = {
    "low_flame": "physical relay #1 (furthest from USB ports)",
    "high_flame": "physical relay #2 (next closer to USB ports)",
    "aux_1": "physical relay #3 (closer to USB ports)",
    "aux_2": "physical relay #4 (closest to USB ports)",
}

# Backward-compatible / convenience aliases.
RELAY_ALIASES: dict[str, str] = {
    # Explicit burner naming
    "main_burner": "low_flame",
    "main": "low_flame",
    # Legacy pin-encoded names
    "relay_gpio4": "low_flame",
    "relay_gpio22": "high_flame",
    "relay_gpio6": "aux_1",
    "relay_gpio26": "aux_2",
    # Pin shorthand
    "gpio4": "low_flame",
    "gpio22": "high_flame",
    "gpio6": "aux_1",
    "gpio26": "aux_2",
    "r4": "low_flame",
    "r22": "high_flame",
    "r6": "aux_1",
    "r26": "aux_2",
}


def _relay_name_for_pin(pin: int) -> str:
    for name, p in KNOWN_RELAYS.items():
        if p == pin:
            return name
    return f"gpio{pin}"


def _resolve_relay_ref(value: Optional[str | int]) -> Optional[int]:
    if value is None:
        return None

    # argparse may already parse ints for --pin-*.
    if isinstance(value, int):
        return value

    s = str(value).strip()
    if not s:
        return None

    if s in RELAY_ALIASES:
        s = RELAY_ALIASES[s]

    if s in KNOWN_RELAYS:
        return KNOWN_RELAYS[s]

    try:
        return int(s)
    except ValueError as e:
        raise SystemExit(
            f"Unknown relay '{s}'. Use one of: {', '.join(sorted(KNOWN_RELAYS.keys()))} (or a BCM pin number)"
        ) from e


class Relay:
    def __init__(self, cfg: RelayConfig, *, dry_run: bool) -> None:
        self._cfg = cfg
        self._dry_run = dry_run
        self._dev = None

        if not dry_run:
            try:
                from gpiozero import OutputDevice  # type: ignore
            except Exception as e:
                raise RuntimeError(
                    "gpiozero is required on the Pi (sudo apt install python3-gpiozero), or use --dry-run"
                ) from e

            # Relay hats are often active-low. `active_high` means: drive pin high to turn ON.
            active_high = not cfg.active_low
            self._dev = OutputDevice(cfg.pin, active_high=active_high, initial_value=False)

    def open(self) -> None:
        if self._dry_run:
            name = _relay_name_for_pin(self._cfg.pin)
            print(f"[dry-run] relay(pin={self._cfg.pin} name={name}) -> {_red('OPEN-DEACTIVATE')}")
            return
        assert self._dev is not None
        self._dev.off()

    def close(self) -> None:
        if self._dry_run:
            name = _relay_name_for_pin(self._cfg.pin)
            print(f"[dry-run] relay(pin={self._cfg.pin} name={name}) -> {_green('CLOSE-ACTIVATE')}")
            return
        assert self._dev is not None
        self._dev.on()


def _guard_after_boot(min_uptime_seconds: float, *, dry_run: bool) -> None:
    if min_uptime_seconds <= 0:
        return

    uptime = _read_uptime_seconds()
    if uptime is None:
        if dry_run:
            print(f"[dry-run] cannot read /proc/uptime; skipping boot guard ({min_uptime_seconds}s)")
        return

    remaining = min_uptime_seconds - uptime
    if remaining > 0:
        print(f"Boot guard: waiting {remaining:.1f}s to avoid IPI detection window")
        _sleep_with_sigint(remaining)


def cmd_pulse(relay: Relay, *, pulse_ms: int) -> None:
    relay.open()
    relay.close()
    _sleep_with_sigint(pulse_ms / 1000.0)
    relay.open()


def cmd_hold(relay: Relay, *, hold_seconds: Optional[float]) -> None:
    relay.open()
    relay.close()
    if hold_seconds is None:
        print("Holding relay closed; Ctrl+C to release")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        _sleep_with_sigint(hold_seconds)
    relay.open()


def cmd_maintained(relay: Relay, *, hold_seconds: Optional[float]) -> None:
    # Pattern from PDF:
    # OPEN 1 s
    # CLOSE 250 ms
    # OPEN 250 ms
    # CLOSE and HOLD while flame desired
    relay.open()
    _sleep_with_sigint(1.0)

    relay.close()
    _sleep_with_sigint(0.250)

    relay.open()
    _sleep_with_sigint(0.250)

    relay.close()
    if hold_seconds is None:
        print("Maintained call active; Ctrl+C to shut down")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        _sleep_with_sigint(hold_seconds)
    relay.open()


def cmd_probe(
    *,
    pins: list[int],
    active_low: bool,
    pulse_ms: int,
    open_seconds: float,
    close_seconds: Optional[float],
    post_open_seconds: float,
    dry_run: bool,
) -> None:
    if not pins:
        raise SystemExit("probe requires at least one pin")

    print("Probing pins (watch LEDs / listen for relay click). Ensure NOTHING is wired to the fireplace while probing.")
    for pin in pins:
        relay_name = _relay_name_for_pin(pin)
        relay = Relay(RelayConfig(pin=pin, active_low=active_low), dry_run=dry_run)
        close_for = float(close_seconds) if close_seconds is not None else (pulse_ms / 1000.0)

        # Fail-safe: ensure deactivated before any activation.
        relay.open()
        if open_seconds > 0:
            print(f"Pin {pin} ({relay_name}): {_red('OPEN-DEACTIVATE')} for {open_seconds:.2f}s")
            _sleep_with_sigint(open_seconds)

        relay.close()
        print(f"Pin {pin} ({relay_name}): {_green('CLOSE-ACTIVATE')} for {close_for:.2f}s")
        _sleep_with_sigint(close_for)

        relay.open()
        if post_open_seconds > 0:
            print(f"Pin {pin} ({relay_name}): {_red('OPEN-DEACTIVATE')} for {post_open_seconds:.2f}s")
            _sleep_with_sigint(post_open_seconds)


def _parse_pin(value: str) -> int:
    try:
        return int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError("pin must be an integer GPIO (BCM numbering)") from e


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--main-relay",
        default=os.getenv("FIREPLACE_MAIN_RELAY"),
        help=(
            "Main relay by name (e.g. low_flame) or BCM pin. Env: FIREPLACE_MAIN_RELAY. "
            f"Known: {', '.join(sorted(KNOWN_RELAYS.keys()))}"
        ),
    )
    common.add_argument(
        "--high-relay",
        default=os.getenv("FIREPLACE_HIGH_RELAY"),
        help=(
            "High-flame relay by name (e.g. high_flame) or BCM pin. Env: FIREPLACE_HIGH_RELAY. "
            f"Known: {', '.join(sorted(KNOWN_RELAYS.keys()))}"
        ),
    )
    common.add_argument(
        "--pin-main",
        type=_parse_pin,
        default=os.getenv("FIREPLACE_PIN_MAIN"),
        help="(Legacy) BCM GPIO pin for Main relay channel (COM=W, NO=R). Env: FIREPLACE_PIN_MAIN",
    )
    common.add_argument(
        "--pin-high",
        type=_parse_pin,
        default=os.getenv("FIREPLACE_PIN_HIGH"),
        help="(Legacy) BCM GPIO pin for High-flame relay channel (COM=W, NO=G). Env: FIREPLACE_PIN_HIGH",
    )
    common.add_argument(
        "--active-low",
        action="store_true",
        default=(os.getenv("FIREPLACE_ACTIVE_LOW", "").strip().lower() in {"1", "true", "yes", "y"}),
        help=(
            "Set only if your relay turns ON when GPIO is LOW (inverted polarity). "
            "Env: FIREPLACE_ACTIVE_LOW=1"
        ),
    )
    common.add_argument(
        "--boot-guard-seconds",
        type=float,
        default=12.0,
        help="Wait until system uptime >= this value before any closure (default: 12s)",
    )
    common.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default=os.getenv("FIREPLACE_COLOR", "auto"),
        help="Colorize output (auto uses TTY detection; env: FIREPLACE_COLOR; respects NO_COLOR)",
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions instead of toggling GPIO",
    )

    p = argparse.ArgumentParser(
        prog="fireplace",
        description="Heat & Glo IntelliFire IPI relay controller (momentary qualified closure)",
        allow_abbrev=False,
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    list_relays = sub.add_parser("list-relays", help="Show known relay names and their BCM pins")
    list_relays.add_argument("--json", action="store_true", help="Output JSON")

    ignite = sub.add_parser("ignite", help="Momentary ignition request (qualified pulse)", parents=[common])
    ignite.add_argument("--pulse-ms", type=int, default=250, help="Pulse width in ms (default: 250)")
    ignite.add_argument(
        "--maintained",
        action="store_true",
        help="Use maintained-call pattern then hold (for units that drop without a maintained call)",
    )
    ignite.add_argument(
        "--hold-seconds",
        type=float,
        default=None,
        help="How long to hold the call (default: forever until Ctrl+C)",
    )

    on = sub.add_parser("on", help="Close and hold main relay (not recommended during detection window)", parents=[common])
    on.add_argument("--hold-seconds", type=float, default=None)

    off = sub.add_parser("off", help="Open main relay", parents=[common])

    high = sub.add_parser("high", help="Close and hold high-flame relay", parents=[common])
    high.add_argument("--hold-seconds", type=float, default=None)

    low = sub.add_parser("low", help="Open high-flame relay", parents=[common])

    pulse_high = sub.add_parser("pulse-high", help="Pulse high-flame relay (rare; usually use hold)", parents=[common])
    pulse_high.add_argument("--pulse-ms", type=int, default=250)

    probe = sub.add_parser("probe", help="Probe GPIO pins to find which relay channel they drive", parents=[common])
    probe.add_argument(
        "--pins",
        default="4,22,6,26",
        help="Comma-separated BCM pins to toggle (default matches KS0212 shield mapping)",
    )
    probe.add_argument("--pulse-ms", type=int, default=300, help="Pulse width in ms (default: 300)")
    probe.add_argument(
        "--open-seconds",
        type=float,
        default=0.0,
        help="How long to stay OPEN-DEACTIVATE before the activation (default: 0.0)",
    )
    probe.add_argument(
        "--close-seconds",
        type=float,
        default=None,
        help="How long to stay CLOSED (overrides --pulse-ms). Useful for polarity testing.",
    )
    probe.add_argument(
        "--post-open-seconds",
        type=float,
        default=0.5,
        help="How long to stay OPEN-DEACTIVATE after the activation (default: 0.5)",
    )

    return p


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)

    global _COLOR_MODE
    if hasattr(args, "color"):
        _COLOR_MODE = str(getattr(args, "color"))
    else:
        _COLOR_MODE = os.getenv("FIREPLACE_COLOR", "auto")

    if args.cmd == "list-relays":
        if args.json:
            import json

            print(json.dumps(KNOWN_RELAYS, indent=2, sort_keys=True))
        else:
            print("Known relays (name -> BCM pin):")
            for name in sorted(KNOWN_RELAYS.keys()):
                note = PHYSICAL_RELAY_NOTES.get(name)
                if note:
                    print(f"- {name} -> {KNOWN_RELAYS[name]} ({note})")
                else:
                    print(f"- {name} -> {KNOWN_RELAYS[name]}")
            print("You can also pass a BCM pin directly (e.g. --main-relay 4).")
        return 0

    if args.cmd == "probe":
        pins = [p.strip() for p in str(args.pins).split(",") if p.strip()]
        cmd_probe(
            pins=[_parse_pin(p) for p in pins],
            active_low=bool(args.active_low),
            pulse_ms=int(args.pulse_ms),
            open_seconds=float(args.open_seconds),
            close_seconds=args.close_seconds,
            post_open_seconds=float(args.post_open_seconds),
            dry_run=bool(args.dry_run),
        )
        return 0

    main_pin = _resolve_relay_ref(args.main_relay) or _resolve_relay_ref(args.pin_main)
    high_pin = _resolve_relay_ref(args.high_relay) or _resolve_relay_ref(args.pin_high)

    needs_main = args.cmd in {"ignite", "on", "off"}
    needs_high = args.cmd in {"high", "low", "pulse-high"}

    main_relay = None
    if needs_main:
        if main_pin is None:
            raise SystemExit(
                "Set --main-relay (preferred) / --pin-main, or FIREPLACE_MAIN_RELAY / FIREPLACE_PIN_MAIN"
            )
        main_relay = Relay(
            RelayConfig(pin=int(main_pin), active_low=bool(args.active_low)), dry_run=bool(args.dry_run)
        )

    high_relay = None
    if needs_high:
        if high_pin is None:
            raise SystemExit(
                "Set --high-relay (preferred) / --pin-high, or FIREPLACE_HIGH_RELAY / FIREPLACE_PIN_HIGH"
            )
        high_relay = Relay(
            RelayConfig(pin=int(high_pin), active_low=bool(args.active_low)), dry_run=bool(args.dry_run)
        )

    # Fail-safe: OPEN any relay we're about to use.
    if main_relay is not None:
        main_relay.open()
    if high_relay is not None:
        high_relay.open()

    # Only apply the IPI boot guard for commands that interact with the fireplace call.
    if args.cmd in {"ignite", "on", "off"}:
        _guard_after_boot(float(args.boot_guard_seconds), dry_run=bool(args.dry_run))

    if args.cmd == "ignite":
        assert main_relay is not None
        if args.maintained:
            cmd_maintained(main_relay, hold_seconds=args.hold_seconds)
        else:
            cmd_pulse(main_relay, pulse_ms=args.pulse_ms)
        return 0

    if args.cmd == "on":
        assert main_relay is not None
        cmd_hold(main_relay, hold_seconds=args.hold_seconds)
        return 0

    if args.cmd == "off":
        assert main_relay is not None
        main_relay.open()
        return 0

    if args.cmd in {"high", "low", "pulse-high"}:
        assert high_relay is not None

        if args.cmd == "high":
            cmd_hold(high_relay, hold_seconds=args.hold_seconds)
            return 0
        if args.cmd == "low":
            high_relay.open()
            return 0
        if args.cmd == "pulse-high":
            cmd_pulse(high_relay, pulse_ms=args.pulse_ms)
            return 0

    raise SystemExit(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    # Make Ctrl+C responsive even while sleeping.
    signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        # Ensure relays are opened on exit when possible.
        print("Interrupted")
        raise SystemExit(130)
