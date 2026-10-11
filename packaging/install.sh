#!/usr/bin/env bash
# Not Armory Crate installer for Ubuntu 26.04 (GNOME / Wayland).
#
#   ./packaging/install.sh                   system + user setup (asks for sudo once)
#   ./packaging/install.sh --enable-service  also enable + start armory-crated
#
# The Aura service is NOT started by default: run `armory-crate probe` first and
# check the output before letting anything write colours to the hardware.
set -euo pipefail

PREFIX="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="$PREFIX/packaging"
ENABLE_SERVICE=0
[[ "${1:-}" == "--enable-service" ]] && ENABLE_SERVICE=1

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }

say "Installing dependencies (GTK4, libadwaita, Python bindings)"
sudo apt-get install -y python3-gi python3-psutil gir1.2-gtk-4.0 gir1.2-adw-1

for mod in gi psutil; do
  python3 -c "import $mod" 2>/dev/null || { echo "still missing python3 module: $mod after apt install"; exit 1; }
done
python3 -c "import gi; gi.require_version('Adw','1')" 2>/dev/null \
  || { echo "still missing libadwaita after apt install"; exit 1; }

# --- system part --------------------------------------------------------
say "Installing udev rule (hidraw access for verified RGB interfaces only)"
sudo install -m 0644 "$PKG/60-armory-crate.rules" /etc/udev/rules.d/60-armory-crate.rules
sudo udevadm control --reload
sudo udevadm trigger --action=change --subsystem-match=hidraw
sudo udevadm settle
# Verify the uaccess ACL actually landed (checks permissions only; opens nothing).
PYTHONPATH="$PREFIX" python3 - <<'EOF'
import os
from armory_crate.aura import registry
from armory_crate.aura.hidraw import discover
for info in discover():
    if registry.match(info):
        ok = os.access(info.node, os.R_OK | os.W_OK)
        print(f"    {info.node} {info.vid_pid} if={info.interface}: {'access OK' if ok else 'NO ACCESS'}")
EOF

say "Loading nct6775 (fan sensors) now and on every boot"
sudo install -m 0644 "$PKG/nct6775.conf" /etc/modules-load.d/armory-crate-nct6775.conf
sudo modprobe nct6775
if grep -qs '^nct' /sys/class/hwmon/hwmon*/name; then
  echo "    fan sensors: $(grep -h '^nct' /sys/class/hwmon/hwmon*/name | head -1)"
else
  echo "    WARNING: nct6775 loaded but no Super-I/O hwmon appeared (see 'sudo dmesg | grep nct')"
fi

# --- user part ----------------------------------------------------------
say "Installing launcher, desktop entry, icon and user service"
BIN="$HOME/.local/bin"
mkdir -p "$BIN" "$HOME/.local/share/applications" \
         "$HOME/.local/share/icons/hicolor/scalable/apps" "$HOME/.config/systemd/user"

cat > "$BIN/armory-crate" <<EOF
#!/bin/sh
PYTHONPATH="$PREFIX\${PYTHONPATH:+:\$PYTHONPATH}" exec /usr/bin/python3 -m armory_crate "\$@"
EOF
chmod 0755 "$BIN/armory-crate"

sed "s|@PREFIX@|$PREFIX|g" "$PKG/org.armorycrate.ArmoryCrate.desktop" \
  > "$HOME/.local/share/applications/org.armorycrate.ArmoryCrate.desktop"
install -m 0644 "$PKG/org.armorycrate.ArmoryCrate.svg" \
  "$HOME/.local/share/icons/hicolor/scalable/apps/org.armorycrate.ArmoryCrate.svg"
sed "s|@PREFIX@|$PREFIX|g" "$PKG/armory-crated.service" > "$HOME/.config/systemd/user/armory-crated.service"
systemctl --user daemon-reload
update-desktop-database -q "$HOME/.local/share/applications" 2>/dev/null || true

if (( ENABLE_SERVICE )); then
  say "Enabling Aura service"
  systemctl --user enable --now armory-crated.service
else
  say "Aura service installed but NOT started."
  echo "    Next: armory-crate probe            (read-only device check)"
  echo "    Then: systemctl --user enable --now armory-crated"
fi

case ":$PATH:" in *":$BIN:"*) ;; *) echo "NOTE: add $BIN to your PATH";; esac
say "Done"
