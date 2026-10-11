#!/usr/bin/env bash
# Remove everything install.sh added. Leaves ~/.config/armory-crate (settings) in place.
set -uo pipefail

systemctl --user disable --now armory-crated.service 2>/dev/null
rm -f "$HOME/.config/systemd/user/armory-crated.service" \
      "$HOME/.local/bin/armory-crate" \
      "$HOME/.local/share/applications/org.armorycrate.ArmoryCrate.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/org.armorycrate.ArmoryCrate.svg"
systemctl --user daemon-reload

sudo rm -f /etc/udev/rules.d/60-armory-crate.rules /etc/modules-load.d/armory-crate-nct6775.conf
sudo udevadm control --reload
sudo udevadm trigger --action=change --subsystem-match=hidraw
echo "Removed. nct6775 stays loaded until reboot (sudo modprobe -r nct6775 to unload now)."
