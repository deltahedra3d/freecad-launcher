#!/bin/bash
# FreeCAD Smart Launcher (v6.4 - robust install fix)

INSTALL_DIR="$HOME/Applications"
SCRIPT_PATH="$INSTALL_DIR/freecad_launcher.sh"
ICON_PATH="$INSTALL_DIR/freecad_icon.svg"
REPO="FreeCAD/FreeCAD"
INSTALL_URL="https://raw.githubusercontent.com/deltahedra3d/freecad-launcher/main/freecad_launcher.sh"

# ====================== 1. DEPENDENCIES ======================
MISSING_DEPS=()
for cmd in jq zenity curl wget; do
    if ! command -v "$cmd" &> /dev/null; then
        MISSING_DEPS+=("$cmd")
    fi
done

if ! ldconfig -p | grep -q "libfuse.so.2"; then
    FUSE_NEEDED=true
else
    FUSE_NEEDED=false
fi

if [ ${#MISSING_DEPS[@]} -ne 0 ] || [ "$FUSE_NEEDED" = true ]; then
    if command -v apt &> /dev/null; then
        sudo apt update && sudo apt install -y "${MISSING_DEPS[@]}" libfuse2
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y "${MISSING_DEPS[@]}" fuse-libs
    elif command -v pacman &> /dev/null; then
        sudo pacman -Sy --noconfirm --needed "${MISSING_DEPS[@]}" fuse2
    elif command -v zypper &> /dev/null; then
        sudo zypper install -y "${MISSING_DEPS[@]}" fuse
    fi
fi

# ====================== 2. PREPARATION ======================
mkdir -p "$INSTALL_DIR"
mkdir -p "$HOME/.local/share/applications"

if [ ! -f "$ICON_PATH" ]; then
    wget -q "https://raw.githubusercontent.com/FreeCAD/FreeCAD/master/src/Gui/Icons/freecad.svg" -O "$ICON_PATH"
fi

# ====================== 3. DESKTOP ======================
cat <<EOF > "$HOME/.local/share/applications/freecad-launcher.desktop"
[Desktop Entry]
Name=FreeCAD Launcher
Exec=$SCRIPT_PATH
Icon=$ICON_PATH
Terminal=false
Type=Application
Categories=Graphics;Engineering;
StartupNotify=true
EOF

chmod +x "$HOME/.local/share/applications/freecad-launcher.desktop"

# ====================== 4. SELF INSTALL (ROBUST) ======================
echo "Installing launcher to $SCRIPT_PATH"

SCRIPT_SOURCE="$(readlink -f "$0" 2>/dev/null)"

if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ]; then
    cp "$SCRIPT_SOURCE" "$SCRIPT_PATH"
else
    echo "Detected pipe execution, downloading script..."
    curl -fsSL "$INSTALL_URL" -o "$SCRIPT_PATH"
fi

chmod +x "$SCRIPT_PATH"

# ====================== 5. FETCH INFO ======================
ONLINE=true
STABLE_JSON=$(curl -s --connect-timeout 5 "https://api.github.com/repos/$REPO/releases/latest") || ONLINE=false

if [ "$ONLINE" = true ] && [ -n "$STABLE_JSON" ]; then
    STABLE_TAG=$(echo "$STABLE_JSON" | jq -r '.tag_name // "Unknown"')

    WEEKLY_JSON=$(curl -s --connect-timeout 5 "https://api.github.com/repos/$REPO/releases" | \
        jq -r '[.[] | select(.tag_name | test("weekly"; "i"))] | first')

    WEEKLY_DATE=$(echo "$WEEKLY_JSON" | jq -r '.published_at | split("T")[0] // "Unknown"')
else
    STABLE_TAG="OFFLINE"
    WEEKLY_DATE="OFFLINE"
    ONLINE=false
fi

STATUS_NEW="🔴 UPDATE"
STATUS_OK="🟢 READY"

# ====================== 6. UPDATE FUNCTION ======================
update_version() {
    local type=$1
    cd "$INSTALL_DIR" || return 1

    [ "$ONLINE" = false ] && return 1

    if [ "$type" = "stable" ]; then
        JSON="$STABLE_JSON"
        TITLE="Stable"
    else
        JSON="$WEEKLY_JSON"
        TITLE="Weekly"
    fi

    URL=$(echo "$JSON" | jq -r '.assets[] | select(.name | contains("AppImage") and contains("x86_64") and (test("sha256|sig|zsync") | not)) | .browser_download_url' | head -n1)

    [ -z "$URL" ] && return 1

    FILENAME=$(basename "$URL")
    HIDDEN_NAME=".$FILENAME"
    LINK_NAME="FreeCAD-${type}.AppImage"

    if [ ! -f "$HIDDEN_NAME" ]; then
        wget "$URL" -O "$HIDDEN_NAME.tmp" 2>&1 | \
        stdbuf -oL tr '\r' '\n' | \
        sed -u 's/.* \([0-9]\+%\).*/\1\n# Downloading.../' | \
        zenity --progress --title="Updating $TITLE" --auto-close

        if [ -f "$HIDDEN_NAME.tmp" ]; then
            mv "$HIDDEN_NAME.tmp" "$HIDDEN_NAME"
            chmod +x "$HIDDEN_NAME"
        else
            rm -f "$HIDDEN_NAME.tmp"
            return 1
        fi
    fi

    ln -sf "$HIDDEN_NAME" "$LINK_NAME"

    # Cleanup adapté
    if [ "$type" = "stable" ]; then
        find . -name ".FreeCAD_*AppImage" ! -name "*weekly*" ! -name "$HIDDEN_NAME" -delete
    else
        find . -name ".FreeCAD_*weekly*AppImage" ! -name "$HIDDEN_NAME" -delete
    fi
}

# ====================== 7. STATUS ======================
[ -f "$INSTALL_DIR/FreeCAD-stable.AppImage" ] && STABLE_STATUS="$STATUS_OK" || STABLE_STATUS="$STATUS_NEW"
[ -f "$INSTALL_DIR/FreeCAD-weekly.AppImage" ] && WEEKLY_STATUS="$STATUS_OK" || WEEKLY_STATUS="$STATUS_NEW"

# ====================== 8. MENU ======================
CHOICE=$(zenity --list --radiolist \
    --title="FreeCAD Smart Launcher" \
    --text="Select version" \
    --width=600 --height=400 \
    --column=" " --column="Edition" --column="Version" --column="Status" \
    TRUE "Stable" "$STABLE_TAG" "$STABLE_STATUS" \
    FALSE "Weekly" "$WEEKLY_DATE" "$WEEKLY_STATUS" \
    FALSE "Update Both" "-" "🔄")

case "$CHOICE" in
    "Stable")
        update_version "stable"
        "$INSTALL_DIR/FreeCAD-stable.AppImage" &
        ;;
    "Weekly")
        update_version "weekly"
        "$INSTALL_DIR/FreeCAD-weekly.AppImage" &
        ;;
    "Update Both")
        update_version "stable"
        update_version "weekly"
        zenity --info --text="Done"
        ;;
esac
