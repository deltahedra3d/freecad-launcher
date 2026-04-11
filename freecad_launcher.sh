#!/bin/bash

# FreeCAD Smart Launcher (v3.5 - Final Branding)
# Copyright (c) 2026 deltahedra3d

INSTALL_DIR="$HOME/Applications"
SCRIPT_PATH="$INSTALL_DIR/freecad_launcher.sh"
ICON_PATH="$INSTALL_DIR/freecad_icon.png"
REPO="FreeCAD/FreeCAD"

# 1. DEPENDENCIES
for cmd in jq zenity curl wget; do
    if ! command -v $cmd &> /dev/null; then
        sudo apt update && sudo apt install -y $cmd
    fi
done

# 2. PREPARATION
mkdir -p "$INSTALL_DIR"
mkdir -p "$HOME/.local/share/applications"
[ ! -f "$ICON_PATH" ] && wget -q "https://www.freecad.org/images/favicon.ico" -O "$ICON_PATH"

# 3. FORCE DESKTOP LAUNCHER (Renamed to FreeCAD Launcher)
cat <<EOF > "$HOME/.local/share/applications/freecad-launcher.desktop"
[Desktop Entry]
Name=FreeCAD Launcher
Comment=Launch Stable or Weekly versions
Exec=$SCRIPT_PATH
Icon=$ICON_PATH
Terminal=false
Type=Application
Categories=Graphics;Engineering;
StartupNotify=true
EOF
chmod +x "$HOME/.local/share/applications/freecad-launcher.desktop"

# Auto-install/rename logic
if [ "$(readlink -f "$0")" != "$(readlink -f "$SCRIPT_PATH")" ]; then
    echo "[+] Installing script as $SCRIPT_PATH..."
    cp "$0" "$SCRIPT_PATH" && chmod +x "$SCRIPT_PATH"
fi

# 4. GET INFO FOR MENU
STABLE_INFO=$(curl -s "https://api.github.com/repos/$REPO/releases/latest" | jq -r '.tag_name // "Unknown"')

WEEKLY_JSON=$(curl -s "https://api.github.com/repos/$REPO/releases" | jq -r '[.[] | select(.tag_name | contains("weekly"))] | first')
WEEKLY_DATE=$(echo "$WEEKLY_JSON" | jq -r '.published_at | split("T")[0] // "Unknown"')

# 5. UPDATE FUNCTION
update_version() {
    local type=$1
    local final_name="FreeCAD-$type.AppImage"
    cd "$INSTALL_DIR" || exit

    if [ "$type" == "stable" ]; then
        URL=$(curl -s "https://api.github.com/repos/$REPO/releases/latest" | jq -r '.assets[] | select(.name | contains("AppImage")) | select(.name | contains("x86_64")) | select(.name | test("sha256|sig|zsync") | not) | .browser_download_url' | head -n 1)
    else
        URL=$(echo "$WEEKLY_JSON" | jq -r '.assets[] | select(.name | contains("AppImage") and contains("x86_64") and (test("sha256|sig|zsync") | not)) | .browser_download_url' | head -n 1)
    fi

    if [ -n "$URL" ] && [ "$URL" != "null" ]; then
        FILENAME=$(basename "$URL")
        REAL_FILENAME=".$FILENAME"

        if [ ! -f "$REAL_FILENAME" ]; then
            wget "$URL" -O "$REAL_FILENAME" 2>&1 | \
            stdbuf -oL sed -ur 's/^.* ([0-9]+)% .*$/\1/' | \
            zenity --progress --window-icon="$ICON_PATH" --title="FreeCAD $type" --text="Downloading $FILENAME..." --auto-close --percentage=0
            
            chmod +x "$REAL_FILENAME"
            find . -maxdepth 1 -name ".FreeCAD*" | grep -i "$type" | grep -v "$FILENAME" | xargs rm -f 2>/dev/null
        fi
        ln -sf "$REAL_FILENAME" "$final_name"
    else
        zenity --error --window-icon="$ICON_PATH" --text="Could not find download URL for $type."
    fi
}

# 6. MENU (Updated Titles)
CHOICE=$(zenity --list --radiolist \
    --window-icon="$ICON_PATH" \
    --title="FreeCAD Launcher" \
    --text="Select version to launch:" \
    --width=500 --height=350 \
    --column="Select" --column="Version" --column="Info" \
    TRUE "Stable" "Release: $STABLE_INFO" \
    FALSE "Weekly" "Built: $WEEKLY_DATE" \
    FALSE "Update" "Update both versions")

case "$CHOICE" in
    "Stable")
        update_version "stable"
        ./FreeCAD-stable.AppImage &
        ;;
    "Weekly")
        update_version "weekly"
        ./FreeCAD-weekly.AppImage &
        ;;
    "Update")
        (update_version "stable" && update_version "weekly") | zenity --progress --pulsate --window-icon="$ICON_PATH" --auto-close --title="Update" --text="Refreshing both versions..."
        zenity --info --window-icon="$ICON_PATH" --text="Update complete!" --timeout=2
        ;;
    *)
        exit
        ;;
esac
