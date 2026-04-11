# freecad-weekly-launcher
FreeCAD Weekly Smart Launcher & Updater
A smart Bash script for Linux designed to automate the downloading, updating, and launching of FreeCAD Weekly Builds (AppImage format).

Why use this script?
If you use FreeCAD Weekly builds, you know the drill: go to GitHub, find the latest release, download a huge file, make it executable, and manually update your menu shortcuts. This script turns that entire process into a single click.

Key Features
Auto-Update: Checks the official FreeCAD GitHub repository for the latest Weekly build every time you launch it.

Smart File Management:

Downloads new versions as hidden files to keep your folders clutter-free.

Maintains a Symbolic Link (FreeCAD.AppImage) so your shortcuts always point to the newest version.

Desktop Integration: Automatically generates a .desktop file and downloads the official icon so FreeCAD appears in your application menu.

System Notifications: Sends native desktop notifications to keep you informed about download progress or potential issues.

High Compatibility: Automatically detects and installs the jq dependency on most distributions (Ubuntu/Debian, Fedora, Arch, openSUSE).

Safety First: Performs a disk space check before starting any download.

Quick Start
Download the script: Get the update_freecad.sh file.

Make it executable:

Bash
chmod +x update_freecad.sh
Run it:

Bash
./update_freecad.sh
After the first run, FreeCAD will open, and you will find a "FreeCAD Weekly" entry in your system's application launcher for future use.

Requirements
curl & wget (usually pre-installed)

jq (automatically installed by the script if missing)

libnotify (for desktop notifications)
