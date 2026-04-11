<img width="1095" height="349" alt="FreeCAD_launcher" src="https://github.com/user-attachments/assets/0b81ee80-622b-4d9f-9b83-d445af8ca72b" />


# FreeCAD Smart Launcher

A Bash utility for Linux designed to manage, update, and launch both Stable and Weekly FreeCAD AppImages.
<img width="723" height="460" alt="INTERFACE" src="https://github.com/user-attachments/assets/d2b4fd7c-86c1-4e87-a9d7-02d8165c7706" />

---

## Features

- **Dual-Version Management** 
  Easily switch between Stable (production) and Weekly (development) builds.

- **Automatic Updates** 
  Detects and downloads the latest releases directly from GitHub.

- **Smart Storage** 
  - Stores files in `~/Applications` 
  - Uses symbolic links for consistency 
  - Automatically cleans up obsolete versions 

- **Desktop Integration** 
  Creates a desktop entry in: ~/.local/share/applications

---


## Installation

### Option 1 : Quick Install (Recommended)

Paste this command into your terminal to install and configure everything automatically:


```bash
curl -fsSL [https://raw.githubusercontent.com/deltahedra3d/freecad-launcher/main/freecad_launcher.sh](https://raw.githubusercontent.com/deltahedra3d/freecad-launcher/main/freecad_launcher.sh) | bash
```
### Option 2 : Manual

#### 1. Download the script

wget [https://github.com/deltahedra3d/freecad-weekly-launcher/raw/refs/heads/main/freecad_launcher.sh](https://github.com/deltahedra3d/freecad-weekly-launcher/raw/refs/heads/main/freecad_launcher.sh)

#### 2. Make it executable

`chmod +x freecad_launcher.sh`

#### 3. Run it

`./freecad_launcher.sh`

On first launch, the script will:

* Create required directories
* Download FreeCAD
* Set up a desktop shortcut

---

## Dependencies

### No manual installation required

The script is designed to be **Universal**. On the first run, it automatically detects your distribution's package manager and prompts to install any missing tools (`jq`, `zenity`, `curl`, `wget`).

### Supported Package Managers:
* **APT**: Debian, Ubuntu, Mint, Pop!_OS
* **DNF**: Fedora, RHEL, CentOS
* **PACMAN**: Arch Linux, Manjaro
* **ZYPPER**: openSUSE

> **Note**: You will simply be asked for your `sudo` password in the terminal during the first launch to allow the script to prepare your environment.

---

## File Structure

~/Applications/<br>
├── freecad_launcher.sh          # Main script<br>
├── FreeCAD-stable.AppImage      # Symlink to latest stable<br>
├── FreeCAD-weekly.AppImage      # Symlink to latest weekly<br>
└── freecad_icon.png             # Application icon<br>

~/.local/share/applications/ <br>
└── freecad-launcher.desktop     # Desktop shortcut <br>

## License

MIT License
Copyright (c) 2026 deltahedra3d

See the LICENSE file for details.
