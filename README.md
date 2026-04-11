# FreeCAD Smart Launcher

A Bash utility for Linux designed to manage, update, and launch both Stable and Weekly FreeCAD AppImages.

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

- **API Resilience** 
Fallback mechanisms to bypass GitHub API rate limits and allow offline launching.

---

## Installation

Run in terminal : curl -fsSL https://raw.githubusercontent.com/deltahedra3d/freecad-launcher/main/freecad_launcher.sh | bash

OR

### 1. Download the script
```bash
curl -fsSL https://raw.githubusercontent.com/deltahedra3d/freecad-launcher/main/freecad_launcher.sh -o freecad_launcher.sh

### 2. Make it executable

chmod +x freecad_launcher.sh

### 2. Run it

./freecad_launcher.sh

On first launch, the script will:

Create required directories
Download FreeCAD
Set up a desktop shortcut

## Dependencies

The script will check and prompt installation if missing.

Required tools:
curl
wget
jq
zenity


Install on Debian / Ubuntu:
sudo apt update && sudo apt install -y jq zenity curl wget

## File Structure

~/Applications/
├── freecad_launcher.sh
├── FreeCAD-stable.AppImage      -> symlink
├── FreeCAD-weekly.AppImage      -> symlink
└── freecad_icon.png

~/.local/share/applications/
└── freecad-launcher.desktop

## License

MIT License
Copyright (c) 2026 deltahedra3d

See the LICENSE file for details.
