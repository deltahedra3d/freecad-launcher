#!/bin/bash

# FreeCAD Smart Launcher (v5.4 - Fix Cleanup & Offline Mode)
# Copyright (c) 2026 deltahedra3d

INSTALL_DIR="$HOME/Applications"
SCRIPT_PATH="$INSTALL_DIR/freecad_launcher.sh"
ICON_PATH="$INSTALL_DIR/freecad_icon.svg"
REPO="FreeCAD/FreeCAD"

# 1. DEPENDENCIES CHECK
MISSING_DEPS=()
for cmd in jq zenity curl wget; do
    if ! command -v $cmd &> /dev/null; then MISSING_DEPS+=($cmd); fi
done

if ! ldconfig -p | grep -q "libfuse.so.2"; then FUSE_NEEDED=true; else FUSE_NEEDED=false; fi

if [ ${#MISSING_DEPS[@]} -ne 0 ] || [ "$FUSE_NEEDED" = true ]; then
    if command -v apt &> /dev/null; then sudo apt update && sudo apt install -y "${MISSING_DEPS[@]}" libfuse2
    elif command -v dnf &> /dev/null; then sudo dnf install -y "${MISSING_DEPS[@]}" fuse-libs
    elif command -v pacman &> /dev/null; then sudo pacman -Sy --noconfirm --needed "${MISSING_DEPS[@]}" fuse2
    elif command -v zypper &> /dev/null; then sudo zypper install -y "${MISSING_DEPS[@]}" fuse
    fi
fi

# 2. PREPARATION
mkdir -p "$INSTALL_DIR"
mkdir -p "$HOME/.local/share/applications"
[ -f "$INSTALL_DIR/freecad_icon.png" ] && rm "$INSTALL_DIR/freecad_icon.png"
if [ ! -f "$ICON_PATH" ]; then
    wget -q "https://raw.githubusercontent.com/FreeCAD/FreeCAD/master/src/Gui/Icons/freecad.svg" -O "$ICON_PATH"
fi

# 3. DESKTOP LAUNCHER
cat <<EOF > "$HOME/.local/share/applications/freecad-launcher.desktop"
[Desktop Entry]
Name=FreeCAD Launcher
Exec=$SCRIPT_PATH
Icon=$ICON_PATH
Terminal=false
Type=Application
Categories=Graphics;Engineering;
StartupNotify=true
StartupWMClass=zenity
EOF
chmod +x "$HOME/.local/share/applications/freecad-launcher.desktop"

# 4. SMART AUTO-INSTALL
if [ -f "$0" ] && [[ "$0" != *"bash"* ]] && [[ "$0" != *"sh"* ]]; then
    [ "$(readlink -f "$0")" != "$(readlink -f "$SCRIPT_PATH")" ] && cp "$0" "$SCRIPT_PATH" && chmod +x "$SCRIPT_PATH"
fi

# 5. GET INFO 
ONLINE=true
STABLE_JSON=$(curl -s --connect-timeout 3 "https://api.github.com/repos/$REPO/releases/latest") || ONLINE=false

if [ "$ONLINE" = true ] && [ -n "$STABLE_JSON" ]; then
    STABLE_TAG=$(echo "$STABLE_JSON" | jq -r '.tag_name // "Unknown"')
    WEEKLY_JSON=$(curl -s "https://api.github.com/repos/$REPO/releases" | jq -r '[.[] | select(.tag_name | contains("weekly"))] | first')
    WEEKLY_TAG=$(echo "$WEEKLY_JSON" | jq -r '.tag_name // "Unknown"')
    WEEKLY_DATE=$(echo "$WEEKLY_JSON" | jq -r '.published_at | split("T")[0] // "Unknown"')
else
    STABLE_TAG="OFFLINE"
    WEEKLY_DATE="OFFLINE"
    ONLINE=false
fi

# Traductions
if [[ $LANG == fr* ]]; then
    STATUS_NEW="🔴 MAJ DISPONIBLE"; STATUS_OK="🟢 À JOUR"; MENU_TEXT="Choisissez la version à lancer :"
    COL_EDITION="Édition"; COL_VERSION="Version / Date"; COL_STATUS="Statut"
else
    STATUS_NEW="🔴 UPDATE AVAILABLE"; STATUS_OK="🟢 UP TO DATE"; MENU_TEXT="Select version to launch:"
    COL_EDITION="Edition"; COL_VERSION="Version / Date"; COL_STATUS="Status"
fi

# Check Status
CHECK_STABLE=$(find "$INSTALL_DIR" -maxdepth 1 -name ".*$STABLE_TAG*.AppImage" | wc -l)
if [ "$ONLINE" = false ]; then STABLE_STATUS="⚡ LOCAL"; else
    [ "$CHECK_STABLE" -gt 0 ] && STABLE_STATUS="$STATUS_OK" || STABLE_STATUS="$STATUS_NEW"
fi

WEEKLY_FILENAME=$(echo "$WEEKLY_JSON" | jq -r '.assets[] | select(.name | contains("AppImage") and contains("x86_64") and (test("sha256|sig|zsync") | not)) | .name' | head -n 1)
if [ "$ONLINE" = false ]; then WEEKLY_STATUS="⚡ LOCAL"; else
    [ -f "$INSTALL_DIR/.$WEEKLY_FILENAME" ] && WEEKLY_STATUS="$STATUS_OK" || WEEKLY_STATUS="$STATUS_NEW"
fi

# 6. UPDATE FUNCTION
update_version() {
    local type=$1
    local final_name="FreeCAD-$type.AppImage"
    cd "$INSTALL_DIR" || exit

    [ "$ONLINE" = false ] && return

    if [ "$type" == "stable" ]; then
        URL=$(echo "$STABLE_JSON" | jq -r '.assets[] | select(.name | contains("AppImage") and contains("x86_64") and (test("sha256|sig|zsync") | not)) | .browser_download_url' | head -n 1)
    else
        URL=$(echo "$WEEKLY_JSON" | jq -r '.assets[] | select(.name | contains("AppImage") and contains("x86_64") and (test("sha256|sig|zsync") | not)) | .browser_download_url' | head -n 1)
    fi

    if [ -n "$URL" ] && [ "$URL" != "null" ]; then
        FILENAME=$(basename "$URL")
        REAL_FILENAME=".$FILENAME"
        if [ ! -f "$REAL_FILENAME" ]; then
            wget "$URL" -O "$REAL_FILENAME" 2>&1 | stdbuf -oL sed -ur 's/^.* ([0-9]+)% .*$/\1/' | zenity --progress --window-icon="$ICON_PATH" --title="FreeCAD Launcher" --text="Downloading $FILENAME..." --auto-close --percentage=0
            chmod +x "$REAL_FILENAME"
            
          
            if [ "$type" == "weekly" ]; then
                find . -maxdepth 1 -name ".FreeCAD*weekly*" ! -name "$REAL_FILENAME" -delete
            else
                find . -maxdepth 1 -name ".FreeCAD*" ! -name "*weekly*" ! -name "$REAL_FILENAME" -delete
            fi
            # -------------------
        fi
        ln -sf "$REAL_FILENAME" "$final_name"
    fi
}

# 7. MENU
CHOICE=$(zenity --list --radiolist --window-icon="$ICON_PATH" --title="FreeCAD Launcher" --text="<b>$MENU_TEXT</b>" --width=700 --height=400 \
    --column=" " --column="$COL_EDITION" --column="$COL_VERSION" --column="$COL_STATUS" \
    TRUE "Stable" "$STABLE_TAG" "$STABLE_STATUS" \
    FALSE "Weekly" "$WEEKLY_DATE" "$WEEKLY_STATUS" \
    FALSE "Update" "➔" "Refresh")

case "$CHOICE" in
    "Stable") update_version "stable"; ./FreeCAD-stable.AppImage & ;;
    "Weekly") update_version "weekly"; ./FreeCAD-weekly.AppImage & ;;
    "Update") (update_version "stable" && update_version "weekly") | zenity --progress --pulsate --auto-close --text="Updating..." ;;
    *) exit ;;
esac
