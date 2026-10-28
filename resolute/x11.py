"""Talk to the running X session directly.

Resolute is an X11 mask over a session that is already logged in: it does not
start Xorg or a window manager. These helpers are how it becomes that session's
desktop and how it switches the session's other windows.

VirtualBox's Kali guest is a plain X session with xdotool installed, so the
older shell-outs were enough. A bare-metal Ubuntu desktop is Wayland plus
XWayland, and it does not ship xdotool. libX11 is there whenever X is.
"""

import ctypes
import re
import shutil
import subprocess

# ClientMessage, from X.h. The event struct matches libX11's LP64 layout:
# 4-byte ints are padded so the following pointer or long sits on 8 bytes.
_CLIENT_MESSAGE = 33
_SUBSTRUCTURE = 0x00180000  # SubstructureNotifyMask | SubstructureRedirectMask

_lib = None
_error_handler = None


class _XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


def _xlib():
    """libX11, with the default fatal error handler replaced.

    A window can close between the moment the letter slots list it and the
    moment it is activated. The default X error handler aborts the process.
    """
    global _lib, _error_handler
    if _lib is None:
        _lib = ctypes.CDLL("libX11.so.6")
        _lib.XOpenDisplay.restype = ctypes.c_void_p
        _lib.XDefaultRootWindow.restype = ctypes.c_ulong
        _lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        _lib.XInternAtom.restype = ctypes.c_ulong
        _lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        _lib.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
        _lib.XFlush.argtypes = [ctypes.c_void_p]
        _lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        _lib.XLowerWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        _lib.XMoveResizeWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        _lib.XGetGeometry.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        _lib.XTranslateCoordinates.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                               ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        _lib.XIconifyWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int]
        _lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        handler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(lambda *_: 0)
        _error_handler = handler  # ctypes would drop it, and the next X error would call freed code
        _lib.XSetErrorHandler(handler)
    return _lib


def _open():
    dpy = _xlib().XOpenDisplay(None)
    return dpy or None


def _close(dpy):
    lib = _xlib()
    lib.XSync(dpy, False)  # deliver any error from these requests to our handler, not a later one
    lib.XCloseDisplay(dpy)


def _atom(dpy, name):
    return _xlib().XInternAtom(dpy, name.encode(), False)


def _send(dpy, window, message, data):
    event = _XClientMessageEvent()
    event.type = _CLIENT_MESSAGE
    event.send_event = 1
    event.display = dpy
    event.window = window
    event.message_type = _atom(dpy, message)
    event.format = 32
    for i, value in enumerate(data):
        event.data[i] = value
    root = _xlib().XDefaultRootWindow(dpy)
    _xlib().XSendEvent(dpy, root, False, _SUBSTRUCTURE, ctypes.byref(event))
    _xlib().XFlush(dpy)


def _xprop_set(wid, fmt, prop, value):
    # One property per invocation. A second -set in the same command is parsed
    # as a query, the command fails, and neither property is written.
    if not shutil.which("xprop"):
        return
    subprocess.run(["xprop", "-id", str(int(wid)), "-f", prop, fmt, "-set", prop, value],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def claim_desktop(wid):
    """Mark a window as the desktop, and ask the compositor not to unredirect it.

    The type has to be set before the window is mapped: mutter (Ubuntu's
    compositor) and a current xfwm only read it then. xfwm on a real GPU, and
    VMware's 3D driver, also unredirect a window that covers the screen, which
    paints it above every other window. VirtualBox never did that.
    """
    _xprop_set(wid, "32a", "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_DESKTOP")
    _xprop_set(wid, "32c", "_NET_WM_BYPASS_COMPOSITOR", "2")


def pin_below(wid):
    """Keep the desk at the bottom of the stack once it is on screen."""
    dpy = _open()
    if dpy is None:
        return
    lib = _xlib()
    try:
        below = _atom(dpy, "_NET_WM_STATE_BELOW")
        skip_taskbar = _atom(dpy, "_NET_WM_STATE_SKIP_TASKBAR")
        skip_pager = _atom(dpy, "_NET_WM_STATE_SKIP_PAGER")
        sticky = _atom(dpy, "_NET_WM_STATE_STICKY")
        attention = _atom(dpy, "_NET_WM_STATE_DEMANDS_ATTENTION")
        # _NET_WM_STATE carries two atoms per message. 1 = add, 0 = remove.
        # Mutter marks a newly mapped desktop window as demanding attention,
        # which flashes the panel; a desktop should not.
        _send(dpy, int(wid), "_NET_WM_STATE", [1, below, skip_taskbar, 1, 0])
        _send(dpy, int(wid), "_NET_WM_STATE", [1, skip_pager, sticky, 1, 0])
        _send(dpy, int(wid), "_NET_WM_STATE", [0, attention, 0, 1, 0])
        lib.XLowerWindow(dpy, int(wid))
        lib.XFlush(dpy)
    finally:
        _close(dpy)


def activate(wid):
    """Ask the window manager to raise a window. EWMH _NET_ACTIVE_WINDOW."""
    dpy = _open()
    if dpy is None:
        return
    try:
        _send(dpy, int(wid), "_NET_ACTIVE_WINDOW", [1, 0, 0, 0, 0])
    finally:
        _close(dpy)


def minimize(wid):
    dpy = _open()
    if dpy is None:
        return
    lib = _xlib()
    try:
        lib.XIconifyWindow(dpy, int(wid), 0)
        lib.XFlush(dpy)
    finally:
        _close(dpy)


def move_resize(wid, x, y, w, h):
    dpy = _open()
    if dpy is None:
        return
    lib = _xlib()
    try:
        lib.XMoveResizeWindow(dpy, int(wid), int(x), int(y), int(w), int(h))
        lib.XFlush(dpy)
    finally:
        _close(dpy)


def client_geometry(wid):
    """The window's rectangle in root-window pixels, or None."""
    dpy = _open()
    if dpy is None:
        return None
    lib = _xlib()
    try:
        root = ctypes.c_ulong()
        x = ctypes.c_int()
        y = ctypes.c_int()
        w = ctypes.c_uint()
        h = ctypes.c_uint()
        border = ctypes.c_uint()
        depth = ctypes.c_uint()
        if not lib.XGetGeometry(dpy, int(wid), ctypes.byref(root), ctypes.byref(x), ctypes.byref(y),
                                ctypes.byref(w), ctypes.byref(h), ctypes.byref(border), ctypes.byref(depth)):
            return None
        child = ctypes.c_ulong()
        rx = ctypes.c_int()
        ry = ctypes.c_int()
        lib.XTranslateCoordinates(dpy, int(wid), root.value, 0, 0, ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(child))
        return rx.value, ry.value, w.value, h.value
    finally:
        _close(dpy)


def primary_rect():
    """The primary output as (x, y, width, height) in X pixels, or None.

    Qt's idea of the screen comes from the monitor's reported size in
    millimetres. VMware's virtual display and some laptop panels report a size
    that makes Qt cover only a corner of the real screen. xrandr reports the
    pixels X is actually scanning out.
    """
    if not shutil.which("xrandr"):
        return None
    try:
        out = subprocess.run(["xrandr", "--query"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = None
    for line in out.splitlines():
        match = re.match(r"^(\S+) connected (primary )?(\d+)x(\d+)\+(\d+)\+(\d+)", line)
        if not match:
            continue
        rect = (int(match.group(5)), int(match.group(6)), int(match.group(3)), int(match.group(4)))
        if match.group(2):
            return rect
        found = found or rect
    return found
