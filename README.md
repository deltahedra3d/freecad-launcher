<img width="1095" height="349" alt="FreeCAD_launcher" src="https://github.com/user-attachments/assets/0b81ee80-622b-4d9f-9b83-d445af8ca72b" />


# FreeCAD Smart Launcher

A Bash utility for Linux designed to manage, update, and launch both Stable and Weekly FreeCAD AppImages.
<img width="723" height="460" alt="INTERFACE" src="https://github.com/user-attachments/assets/d2b4fd7c-86c1-4e87-a9d7-02d8165c7706" />
<img width="723" height="auto" alt="INTERFACE_CACHYOS" src="https://github.com/user-attachments/assets/0a358f2e-9294-4742-9c49-e04f998c5b5e" />

<img width="800" height="450" alt="video_1" src="https://github.com/user-attachments/assets/2ac6ba4b-943c-4fe8-906a-bf87a6e67d40" />






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

- **Compatible with all major Linux distributions** (Ubuntu, Debian, Fedora, Arch, openSUSE, etc.).

---


## Installation

### Option 1 : Quick Install (Recommended)

Paste this command into your terminal to install and configure everything automatically:


```bash
curl -fsSL https://raw.githubusercontent.com/deltahedra3d/freecad-launcher/main/freecad_launcher.sh | bash
```
### Option 2 : Manual

#### 1. Download the script
Use `curl` or `wget` to download the raw file:

```bash
wget https://raw.githubusercontent.com/deltahedra3d/freecad-launcher/main/freecad_launcher.sh
```

#### 2. Make it executable
```bash
chmod +x freecad_launcher.sh
```

#### 3. Run it
```bash
./freecad_launcher.sh
```

### On first launch, the script will :

* Create required directories
* Download FreeCAD (Stable or Weekly depending of your choice)
* Set up a desktop shortcut (FreeCAD Launcher)

---

## Uninstall
Go to `~/Applications` and delete the FreeCAD files

---

## Dependencies

### No manual installation required

The script is designed to be **Universal**. On the first run, it automatically detects your distribution's package manager and prompts to install any missing tools (`jq`, `zenity`, `curl`, `wget`).

### Supported Package Managers:
* **APT**: Debian, Ubuntu, Mint, Pop!_OS
* **DNF**: Fedora, RHEL, CentOS
* **PACMAN**: Arch Linux, CachyOS, Manjaro
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
