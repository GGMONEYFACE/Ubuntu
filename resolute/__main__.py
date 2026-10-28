"""Run the Resolute desk: python3 -m resolute [--windowed] [--screenshot FILE]"""

import argparse
import os
import signal
import sys


def _prefer_x11():
    """Use the X11 Qt plugin whenever an X server is reachable.

    Ubuntu's desktop is Wayland, but it keeps XWayland on $DISPLAY. Qt prefers
    Wayland then, and a Wayland window cannot mark itself as the desktop or see
    the session's other windows. VirtualBox Kali is already a plain X session,
    so forcing the plugin changes nothing there. RESOLUTE_QT_PLATFORM overrides.
    """
    override = os.environ.get("RESOLUTE_QT_PLATFORM")
    if override:
        os.environ["QT_QPA_PLATFORM"] = override
        return
    if os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


_prefer_x11()

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from .app import DeskWindow


def main():
    parser = argparse.ArgumentParser(prog="resolute", description="A desktop shaped like a roll-top desk.")
    parser.add_argument("--windowed", action="store_true", help="run in a normal window instead of as the desktop")
    parser.add_argument("--screenshot", metavar="FILE", help="render one frame to FILE and exit")
    parser.add_argument("--open", choices=["documents", "programs", "files", "menu", "note", "sketch"], help="with --screenshot: open this first")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Resolute")
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    win = DeskWindow(windowed=args.windowed or bool(args.screenshot))
    if args.screenshot:
        win.resize(1920, 1080)
        win.show()
        if args.open == "documents":
            win.documents.open()
        elif args.open == "programs":
            win.programs.open()
        elif args.open == "files":
            win.files.open()
        elif args.open == "note":
            win.toggle_note()
        elif args.open == "sketch":
            win.lift_sketch()

        def snap():
            for _ in range(60):
                win.tick()
            if args.open == "menu":
                win.menu.popup_at(win.mapToGlobal(win.rect().topLeft()))
                win.menu.grab().save(args.screenshot)
            else:
                win.grab().save(args.screenshot)
            app.quit()
        QTimer.singleShot(1500, snap)  # give the window and audio poller time to report
    elif args.windowed:
        win.resize(1600, 900)
        win.show()
    else:
        win.winId()  # create the native window so it can be typed before mapping
        win.make_desktop_window()
        screen = app.primaryScreen().geometry()
        win.setGeometry(screen)
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
