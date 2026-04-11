# FreeCAD Weekly Smart Launcher

This bash script automates the management of FreeCAD Weekly AppImages on Linux.

## Universal Compatibility
This script is designed to be **distro-agnostic**. It features an adaptive dependency manager that works on the vast majority of Linux distributions, including:
* **Debian / Ubuntu / Mint / Pop!_OS** (using `apt`)
* **Fedora / Red Hat / CentOS** (using `dnf`)
* **Arch Linux / Manjaro** (using `pacman`)
* **openSUSE** (using `zypper`)

## Features
- **Auto-Update**: Checks GitHub for the latest Weekly build.
- **Smart Link**: Uses a symlink so your shortcuts never break.
- **Desktop Integration**: Automatically creates a menu entry with the FreeCAD icon.
- **Safety**: Checks for disk space before downloading and handles dependencies like `jq`.
- **System Notifications**: Tells you when an update is being downloaded.

## How to use
1. Download the script: `update_freecad.sh`
2. Make it executable: `chmod +x update_freecad.sh`
3. Run it: `./update_freecad.sh`

After the first run, you can just launch FreeCAD from your application menu!
