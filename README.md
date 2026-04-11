# FreeCAD Smart Launcher

A Bash utility for Linux designed to manage, update, and launch both Stable and Weekly FreeCAD AppImages.

## Features
* **Dual-Version Management**: Switch easily between Stable (production) and Weekly (development) builds.
* **Automatic Updates**: Detects and downloads the latest releases directly from the GitHub repository.
* **Smart Storage**: Manages files within `~/Applications`, creates symbolic links for consistency, and performs automatic cleanup of obsolete versions.
* **Desktop Integration**: Automatically generates a desktop entry in `~/.local/share/applications` for integration with system application menus.
* **API Resilience**: Includes fallback mechanisms to bypass GitHub API rate limits and launch local versions when offline.

---

## Installation

1. **Download the script**: Copy the script code into a file named `freecad_launcher.sh`.
2. **Set execution permissions**:
   ```bash
   chmod +x freecad_launcher.sh
Execute the script:

Bash
./freecad_launcher.sh
The script will automatically handle the initial setup and directory creation during the first run. It will also create a desktop shortcut for easier access.

Dependencies
The script verifies and prompts for the installation of the following tools:

curl & wget: For network communication and downloads.

jq: For processing JSON data from the GitHub API.

zenity: For the graphical user interface and progress tracking.

On Debian/Ubuntu based systems, these can be installed via:

Bash
sudo apt update && sudo apt install jq zenity curl wget
GitHub Rate Limiting
GitHub limits unauthenticated API requests to 60 per hour.

Issue: If you encounter a "Could not find download URL" error, your IP address may be temporarily rate-limited by GitHub.

Solution: Recent versions of this script use a hybrid discovery method that attempts to scrape the public release page when the API is unavailable. If a block persists, the script will prioritize launching the existing local version.

File Structure
~/Applications/freecad_launcher.sh: The main execution script.

~/Applications/FreeCAD-stable.AppImage: Symlink to the current stable build.

~/Applications/FreeCAD-weekly.AppImage: Symlink to the current weekly build.

~/Applications/freecad_icon.png: Icon used for the desktop entry.

~/.local/share/applications/freecad-launcher.desktop: System desktop entry for the application menu.

Troubleshooting
If the Weekly build fails to download:

Ensure your internet connection is active.

Wait approximately 60 minutes for the GitHub API limit to reset if the fallback method also fails.

Verify that you are using version 4.7 or higher of the launcher script to ensure compatibility with the latest GitHub layout changes.

License
Copyright (c) 2026 deltahedra3d.
This project is licensed under the MIT License - see the LICENSE file for details or visit opensource.org/licenses/MIT.
