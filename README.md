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

### 🚀 Option 1: Quick Install (Recommended)

Paste this command into your terminal to install and configure everything automatically:


`curl -fsSL [https://github.com/deltahedra3d/freecad-weekly-launcher/raw/refs/heads/main/freecad_launcher.sh](https://github.com/deltahedra3d/freecad-weekly-launcher/raw/refs/heads/main/freecad_launcher.sh)` 

### 1. Download the script

wget [https://github.com/deltahedra3d/freecad-weekly-launcher/raw/refs/heads/main/freecad_launcher.sh](https://github.com/deltahedra3d/freecad-weekly-launcher/raw/refs/heads/main/freecad_launcher.sh)

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
curl/wget Network communication and downloading
jq JSON processing for GitHub API data
zenity Graphical interface for menus and progress bars


Install on Debian / Ubuntu:
sudo apt update && sudo apt install -y jq zenity curl wget

## File Structure

~/Applications/
├── freecad_launcher.sh          # Main script
├── FreeCAD-stable.AppImage      # Symlink to latest stable
├── FreeCAD-weekly.AppImage      # Symlink to latest weekly
└── freecad_icon.png             # Application icon

~/.local/share/applications/
└── freecad-launcher.desktop     # Desktop shortcut

## License

MIT License
Copyright (c) 2026 deltahedra3d

See the LICENSE file for details.
