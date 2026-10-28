"""Volume and device control.

pactl is the interface this was written against (PulseAudio, or PipeWire's
pulse server). A default Ubuntu install has PipeWire and WirePlumber's wpctl,
but not the pactl binary, so the radio was silent there.
"""

import json
import re
import shutil
import subprocess


class Device:
    def __init__(self, name, description, volume, muted):
        self.name = name
        self.description = description
        self.volume = volume  # percent, 0-150
        self.muted = muted


class AudioState:
    """A snapshot: the default output and input plus every device to choose from."""

    def __init__(self, sinks=(), sources=(), sink=None, source=None):
        self.sinks = list(sinks)
        self.sources = list(sources)
        self.sink = sink
        self.source = source

    @property
    def available(self):
        return self.sink is not None or self.source is not None


def _run(*args, timeout=3):
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _devices(kind):
    try:
        entries = json.loads(_run("-f", "json", "list", kind) or "[]")
    except json.JSONDecodeError:
        return []
    devices = []
    for e in entries:
        if kind == "sources" and (e.get("monitor_source") or e["name"].endswith(".monitor")):
            continue  # "monitor of ..." loopbacks are not real inputs
        channels = [c.get("value_percent", "0%") for c in e.get("volume", {}).values()]
        levels = [int(c.rstrip("%")) for c in channels if c.rstrip("%").isdigit()]
        devices.append(Device(e["name"], e.get("description", e["name"]),
                              round(sum(levels) / len(levels)) if levels else 0, bool(e.get("mute"))))
    return devices


# Which tool the last successful read used. Device names are not interchangeable:
# pactl uses a Pulse name, wpctl a numeric id.
_backend = None


def read_state():
    """Query the audio server. Blocking; call from a worker thread."""
    global _backend
    if shutil.which("pactl"):
        state = _read_pactl()
        if state.available:
            _backend = "pactl"
            return state
    if shutil.which("wpctl"):
        state = _read_wpctl()
        if state.available:
            _backend = "wpctl"
            return state
    return AudioState()


def _read_pactl():
    sinks = _devices("sinks")
    sources = _devices("sources")
    default_sink = _run("get-default-sink").strip()
    default_source = _run("get-default-source").strip()
    sink = next((d for d in sinks if d.name == default_sink), sinks[0] if sinks else None)
    source = next((d for d in sources if d.name == default_source), sources[0] if sources else None)
    return AudioState(sinks, sources, sink, source)


def _wpctl(*args, timeout=3):
    try:
        return subprocess.run(["wpctl", *args], capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _parse_wpctl(text):
    """Sinks and sources from `wpctl status`. Cameras live under Video and are ignored."""
    section = None
    kind = None
    sinks, sources = [], []
    default_sink = default_source = None
    for line in text.splitlines():
        head = line.strip()
        if head.startswith("Audio"):
            section, kind = "audio", None
            continue
        if head.startswith(("Video", "Settings", "PipeWire")):
            section, kind = None, None
            continue
        if section != "audio":
            continue
        if "Sinks:" in line:
            kind = "sinks"
            continue
        if "Sources:" in line:
            kind = "sources"
            continue
        if any(label in line for label in ("Devices:", "Filters:", "Streams:")):
            kind = None
            continue
        if kind is None:
            continue
        match = re.search(r"(\d+)\.\s+(.*)$", line)
        if not match:
            continue
        desc = match.group(2).strip()
        volume, muted = 0, False
        vol = re.search(r"\[vol:\s*([0-9.]+)([^\]]*)\]", desc)
        if vol:
            volume = round(float(vol.group(1)) * 100)
            muted = "MUTED" in vol.group(2)
            desc = desc[:vol.start()].strip()
        if desc.lower().startswith("monitor of "):
            continue
        dev = Device(match.group(1), desc, volume, muted)
        (sinks if kind == "sinks" else sources).append(dev)
        if "*" in line.split(".", 1)[0]:
            if kind == "sinks":
                default_sink = dev
            else:
                default_source = dev
    sink = default_sink or (sinks[0] if sinks else None)
    source = default_source or (sources[0] if sources else None)
    return AudioState(sinks, sources, sink, source)


def _read_wpctl():
    return _parse_wpctl(_wpctl("status"))


def _fire(*args):
    """Changes are sent without waiting so the knobs never stall the animation."""
    try:
        subprocess.Popen(list(args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def _use_wpctl():
    if _backend == "wpctl":
        return True
    if _backend == "pactl":
        return False
    return shutil.which("wpctl") and not shutil.which("pactl")


def set_volume(kind, percent):
    percent = f"{int(percent)}%"
    if _use_wpctl():
        target = "@DEFAULT_AUDIO_SINK@" if kind == "sink" else "@DEFAULT_AUDIO_SOURCE@"
        _fire("wpctl", "set-volume", target, percent)
        return
    target = "@DEFAULT_SINK@" if kind == "sink" else "@DEFAULT_SOURCE@"
    _fire("pactl", f"set-{kind}-volume", target, percent)


def set_mute(kind, muted):
    flag = "1" if muted else "0"
    if _use_wpctl():
        target = "@DEFAULT_AUDIO_SINK@" if kind == "sink" else "@DEFAULT_AUDIO_SOURCE@"
        _fire("wpctl", "set-mute", target, flag)
        return
    target = "@DEFAULT_SINK@" if kind == "sink" else "@DEFAULT_SOURCE@"
    _fire("pactl", f"set-{kind}-mute", target, flag)


def set_default(kind, name):
    if _use_wpctl():
        _fire("wpctl", "set-default", str(name))
        return
    _fire("pactl", f"set-default-{kind}", name)
