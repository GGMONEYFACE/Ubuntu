"""The list of open program windows, read from the X11 window manager with xprop."""

import re
import shutil
import subprocess

from . import x11

SKIP_TYPES = ("_NET_WM_WINDOW_TYPE_DESKTOP", "_NET_WM_WINDOW_TYPE_DOCK", "_NET_WM_WINDOW_TYPE_SPLASH",
              "_NET_WM_WINDOW_TYPE_TOOLBAR", "_NET_WM_WINDOW_TYPE_MENU", "_NET_WM_WINDOW_TYPE_NOTIFICATION")


class Window:
    def __init__(self, wid, title, wm_instance, wm_class, minimized):
        self.wid = wid
        self.title = title
        self.wm_instance = wm_instance
        self.wm_class = wm_class
        self.minimized = minimized
        self.active = False


def _xprop(*args):
    try:
        return subprocess.run(["xprop", *args], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _ids(line):
    return [int(h, 16) for h in re.findall(r"0x[0-9a-fA-F]+", line)]


def _string(out, prop):
    m = re.search(rf'^{prop}\([A-Z0-9_]+\) = (.*)$', out, re.M)
    if not m:
        return []
    # xprop already prints UTF-8; only quotes and backslashes are escaped
    return [re.sub(r"\\(.)", r"\1", s) for s in re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))]


def list_windows(exclude=()):
    """Normal program windows in stacking-list order. Blocking; call from a worker thread."""
    if not shutil.which("xprop"):
        return []
    root = _xprop("-root", "_NET_CLIENT_LIST", "_NET_ACTIVE_WINDOW")
    clients, active = [], 0
    for line in root.splitlines():
        if line.startswith("_NET_CLIENT_LIST"):
            clients = _ids(line)
        elif line.startswith("_NET_ACTIVE_WINDOW"):
            ids = _ids(line)
            active = ids[0] if ids else 0
    windows = []
    for wid in clients:
        if wid in exclude:
            continue
        out = _xprop("-id", hex(wid), "_NET_WM_NAME", "WM_NAME", "WM_CLASS", "_NET_WM_WINDOW_TYPE", "_NET_WM_STATE")
        if any(t in out for t in SKIP_TYPES) or "_NET_WM_STATE_SKIP_TASKBAR" in out:
            continue
        title = (_string(out, "_NET_WM_NAME") or _string(out, "WM_NAME") or [""])[0]
        cls = _string(out, "WM_CLASS") + ["", ""]
        w = Window(wid, title, cls[0], cls[1], "_NET_WM_STATE_HIDDEN" in out)
        w.active = wid == active
        windows.append(w)
    return windows


def activate(wid):
    # xdotool is what this was written against, and Kali has it. Ubuntu does not,
    # so fall back to the same request spoken directly to the window manager.
    if not _fire("windowactivate", str(wid)):
        x11.activate(wid)


def minimize(wid):
    if not _fire("windowminimize", str(wid)):
        x11.minimize(wid)


def _fire(*args):
    if not shutil.which("xdotool"):
        return False
    subprocess.Popen(["xdotool", *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True
