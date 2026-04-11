#!/bin/bash

# FreeCAD Weekly Smart Launcher & Updater
# Copyright (c) 2026 DELTAHEDRA
# Licensed under the MIT License

# --- CONFIGURATION ---
INSTALL_DIR="$HOME/Applications"
SCRIPT_PATH="$INSTALL_DIR/update_freecad.sh"
DESKTOP_FILE="$HOME/.local/share/applications/freecad-weekly.desktop"
ICON_PATH="$INSTALL_DIR/freecad_icon.png"
FINAL_NAME="FreeCAD.AppImage"
REPO="FreeCAD/FreeCAD"
CURRENT_SCRIPT=$(readlink -f "$0")
REQUIRED_SPACE=1024 # 1GB

# 1. DEPENDENCY CHECK & UNIVERSAL AUTO-INSTALL
if ! command -v jq &> /dev/null; then
    clear
    echo "=========================================="
    echo "       FREECAD INSTALLER SETUP"
    echo "=========================================="
    echo ""
    echo "This script requires 'jq' to fetch the latest version from GitHub."
    read -p "Would you like to install it now? [Y/n]: " confirm
    
    if [[ -z "$confirm" || $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
        echo "Detecting package manager..."
        if command -v apt &> /dev/null; then sudo apt update && sudo apt install -y jq
        elif command -v dnf &> /dev/null; then sudo dnf install -y jq
        elif command -v pacman &> /dev/null; then sudo pacman -S --noconfirm jq
        elif command -v zypper &> /dev/null; then sudo zypper install -y jq
        else
            echo "[!] Could not detect package manager. Please install 'jq' manually."
            exit 1
        fi
    else
        echo "Installation cancelled. Exiting..."
        exit 1
    fi
fi

# 2. FOLDERS & ICON PREPARATION
mkdir -p "$INSTALL_DIR"
mkdir -p "$HOME/.local/share/applications"

# Download the icon if it doesn't exist
if [ ! -f "$ICON_PATH" ]; then
    wget -q "https://www.freecad.org/images/favicon.ico" -O "$ICON_PATH"
fi

# 3. SELF-INSTALLATION
if [ "$CURRENT_SCRIPT" != "$SCRIPT_PATH" ]; then
    echo "[+] Installing script to $INSTALL_DIR..."
    cp "$0" "$SCRIPT_PATH"
    chmod +x "$SCRIPT_PATH"
fi

# 4. CREATE DESKTOP SHORTCUT
cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Name=FreeCAD Weekly
Comment=Auto-updating FreeCAD Weekly build
Exec=$SCRIPT_PATH
Icon=$ICON_PATH
Terminal=true
Type=Application
Categories=Graphics;Engineering;
StartupNotify=true
EOF
chmod +x "$DESKTOP_FILE"

# 5. UPDATE LOGIC
clear
echo "=========================================="
echo "       FREECAD SMART LAUNCHER"
echo "=========================================="
echo "Searching for the latest Weekly Build..."

cd "$INSTALL_DIR"

URL=$(curl -s "https://api.github.com/repos/$REPO/releases" | jq -r '
  [ .[].assets[] | select(
    (.name | test("weekly"; "i")) and 
    (.name | test("x86_64")) and 
    (.name | endswith(".AppImage")) and 
    (.name | test("zsync|sha256|sig") | not)
  ) ] | sort_by(.name) | last | .browser_download_url')

if [ -z "$URL" ] || [ "$URL" == "null" ]; then
    echo "[!] Could not reach GitHub. Launching current version..."
    notify-send "FreeCAD" "Update check failed, launching offline..."
else
    # The real file is HIDDEN (starts with a dot)
    REAL_FILENAME=".$((basename "$URL"))"

    if [ ! -f "$REAL_FILENAME" ]; then
        echo "[*] NEW VERSION FOUND"
        notify-send "FreeCAD" "New version found! Downloading update..."
        
        FREE_SPACE=$(df -m "$INSTALL_DIR" | tail -1 | awk '{print $4}')
        if [ "$FREE_SPACE" -lt "$REQUIRED_SPACE" ]; then
            echo "[!] Not enough disk space for update."
            notify-send "FreeCAD Error" "Not enough disk space for update."
        else
            echo "[+] Downloading..."
            wget -q --show-progress "$URL" -O "$REAL_FILENAME"
            chmod +x "$REAL_FILENAME"

            echo "[*] Cleaning up old versions..."
            find . -maxdepth 1 -name ".FreeCAD*.AppImage" ! -name "$REAL_FILENAME" -delete
            
            # Create/Update the SYMLINK (Visible file)
            ln -sf "$REAL_FILENAME" "$FINAL_NAME"
            echo "[+] Update complete!"
            notify-send "FreeCAD" "Update successful!"
        fi
    else
        echo "[+] Everything is up to date."
    fi
fi

echo ""
echo ">>> Launching FreeCAD..."
echo "=========================================="

# Launch the SYMLINK
if [ -f "$FINAL_NAME" ]; then
    "./$FINAL_NAME" &
    sleep 1
else
    echo "[!] FreeCAD executable not found!"
    read -p "Press enter to exit..."
fi
exit
