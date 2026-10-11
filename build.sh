#!/bin/sh
# Builds the Debian/Ubuntu package into build/linux/:
#   build/linux/pkg/                              the installed layout (usr/, lib/, etc/)
#   build/linux/armory-crate_<version>_all.deb    Debian/Ubuntu package
#   build/linux/armory-crate-<version>-linux.tar.gz   the same tree, for other distributions
#                                                      (sudo tar -xzf ... -C /)
#
# Pure Python, so there's nothing to compile: this just lays files out where the .deb (or the
# tarball, for non-Debian distributions) expects them and lets dpkg-deb do the rest - the same
# plain dpkg-deb --build approach as ttlcd's own build.sh, no debhelper/dpkg-buildpackage needed.
#
# armory_crate/ is installed to /usr/lib/python3/dist-packages, the standard location Debian/
# Ubuntu's own python3-* packages use, so `python3 -m armory_crate` just works afterwards with no
# PYTHONPATH - unlike packaging/install.sh's run-from-checkout launcher, which does need one.
set -e
cd "$(dirname "$0")"

VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' armory_crate/__init__.py)
OUT=build/linux
PKG=$PWD/$OUT/pkg
SRC=packaging/deb

rm -rf "$OUT"
mkdir -p "$PKG/usr/lib/python3/dist-packages" "$PKG/usr/bin" "$PKG/usr/lib/systemd/user" \
         "$PKG/lib/udev/rules.d" "$PKG/etc/modules-load.d" "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/scalable/apps" "$PKG/DEBIAN"

echo "[1/3] armory_crate (version $VER)"
cp -a armory_crate "$PKG/usr/lib/python3/dist-packages/"
find "$PKG/usr/lib/python3/dist-packages/armory_crate" -name '__pycache__' -exec rm -rf {} +

install -m 755 "$SRC/launcher" "$PKG/usr/bin/armory-crate"
install -m 644 "$SRC/armory-crated.service" "$PKG/usr/lib/systemd/user/armory-crated.service"
install -m 644 "$SRC/org.armorycrate.ArmoryCrate.desktop" "$PKG/usr/share/applications/org.armorycrate.ArmoryCrate.desktop"
install -m 644 packaging/60-armory-crate.rules "$PKG/lib/udev/rules.d/60-armory-crate.rules"
install -m 644 packaging/nct6775.conf "$PKG/etc/modules-load.d/armory-crate-nct6775.conf"
install -m 644 packaging/org.armorycrate.ArmoryCrate.svg \
    "$PKG/usr/share/icons/hicolor/scalable/apps/org.armorycrate.ArmoryCrate.svg"
sed "s/@VERSION@/$VER/" "$SRC/control" > "$PKG/DEBIAN/control"
install -m 755 "$SRC/postinst" "$PKG/DEBIAN/postinst"
install -m 755 "$SRC/prerm" "$PKG/DEBIAN/prerm"

echo "[2/3] armory-crate_${VER}_all.deb"
dpkg-deb --root-owner-group --build "$PKG" "$OUT/armory-crate_${VER}_all.deb" >/dev/null

echo "[3/3] armory-crate-${VER}-linux.tar.gz"
tar -czf "$OUT/armory-crate-${VER}-linux.tar.gz" --owner=0 --group=0 -C "$PKG" usr lib etc
echo "build OK: $OUT"
