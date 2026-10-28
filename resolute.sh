#!/bin/sh
# Start the Resolute desk in place of XFCE's desktop (xfdesktop).
# XFCE's window manager keeps running, so programs still open in normal windows.
# When the desk is closed, the normal XFCE desktop is brought back.

cd "$(dirname "$(readlink -f "$0")")" || exit 1

# Ubuntu (and a VMware guest installed from it) is a Wayland session that still
# runs XWayland on $DISPLAY. Qt would open a Wayland window, which cannot become
# the desktop. Pin the X11 plugin whenever an X server is there. A plain X
# session, such as the VirtualBox Kali guest this was built on, already uses it.
if [ -n "${DISPLAY:-}" ] && [ -z "${RESOLUTE_QT_PLATFORM:-}" ]; then
    export QT_QPA_PLATFORM=xcb
fi

# No X server at all: there is nothing for the mask to attach to.
if [ -z "${DISPLAY:-}" ]; then
    warning="Resolute needs an X11 display. This session does not have one, so the desk cannot become the desktop and open programs will not appear in the letter slots.
For the full desk, log in to an Xfce session on X11: run ./setup-x11.sh to set it up."
    printf 'Warning: %s\n' "$warning" >&2
    if command -v notify-send >/dev/null 2>&1; then
        notify-send -a Resolute -i dialog-warning -t 15000 "Resolute needs X11" "$warning" >/dev/null 2>&1 &
    fi
elif [ "${XDG_SESSION_TYPE:-}" = "wayland" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
    # XWayland is enough for the desk itself. Native Wayland programs are not X
    # clients, so the letter slots cannot see them. Say so, without a notification
    # at every login.
    echo "Resolute is using XWayland. Programs that use Wayland directly will not appear in the letter slots, and this desktop's own panel may stay on top. For the full desk, run ./setup-x11.sh and log in to Xfce on X11." >&2
fi

if [ "$1" = "--autostart" ]; then
    # At login XFCE may start its own desktop just after us (or, with a saved session, not at all).
    # Start straight away, and for the first 20 seconds replace xfdesktop if it turns up.
    shift
    restore_xfdesktop=1
    (
        for _ in $(seq 40); do
            pgrep -x xfdesktop >/dev/null 2>&1 && xfdesktop --quit
            sleep 0.5
        done
    ) &
elif pgrep -x xfdesktop >/dev/null 2>&1; then
    xfdesktop --quit
    restore_xfdesktop=1
fi

python3 -m resolute "$@"
status=$?

if [ -n "$restore_xfdesktop" ]; then
    setsid xfdesktop >/dev/null 2>&1 &
fi
exit $status
