import builtins
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from armory_crate import sensors
from armory_crate.aura.hidraw import discover
from armory_crate.sensors import board, cpu, gpu, hwmon


def make_tree(root):
    def w(rel, text):
        p = Path(root, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    w("class/hwmon/hwmon1/name", "k10temp\n")
    w("class/hwmon/hwmon1/temp1_input", "47125\n")
    w("class/hwmon/hwmon1/temp1_label", "Tctl\n")
    w("class/hwmon/hwmon1/temp3_input", "45000\n")
    w("class/hwmon/hwmon1/temp3_label", "Tccd1\n")
    w("class/hwmon/hwmon3/name", "asusec\n")
    w("class/hwmon/hwmon3/temp1_input", "54000\n")
    w("class/hwmon/hwmon3/temp1_label", "VRM\n")
    w("class/hwmon/hwmon10/name", "nct6799\n")
    w("class/hwmon/hwmon10/fan1_input", "0\n")
    w("class/hwmon/hwmon10/fan2_input", "1234\n")
    w("class/hwmon/hwmon10/pwm2", "128\n")
    w("class/hwmon/hwmon10/in0_input", "1100\n")
    w("class/hwmon/hwmon10/in0_label", "Vcore\n")
    w("class/hwmon/hwmon10/pwm2_enable", "5\n")
    for n, khz in enumerate((5000000, 3000000)):
        w(f"devices/system/cpu/cpu{n}/cpufreq/scaling_cur_freq", f"{khz}\n")
    w("devices/system/cpu/cpu0/cpufreq/scaling_governor", "performance\n")
    w("devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", "5250992\n")
    w("devices/system/cpu/cpufreq/boost", "1\n")
    w("devices/system/cpu/amd_pstate/status", "active\n")
    w("devices/virtual/dmi/id/board_name", "ROG STRIX B650E-I GAMING WIFI\n")
    w("devices/virtual/dmi/id/board_vendor", "ASUSTeK COMPUTER INC.\n")
    dev = "devices/pci/0000:03:00.0"
    w(f"{dev}/vendor", "0x1002\n")
    w(f"{dev}/device", "0x7550\n")
    w(f"{dev}/gpu_busy_percent", "12\n")
    w(f"{dev}/pp_dpm_sclk", "0: 500Mhz\n1: 2400Mhz *\n")
    w(f"{dev}/hwmon/hwmon6/name", "amdgpu\n")
    w(f"{dev}/hwmon/hwmon6/temp1_input", "55000\n")
    w(f"{dev}/hwmon/hwmon6/temp1_label", "edge\n")
    w(f"{dev}/hwmon/hwmon6/fan1_input", "900\n")
    w(f"{dev}/hwmon/hwmon6/power1_average", "39000000\n")
    os.makedirs(Path(root, "class/drm/card1"))
    os.symlink(Path(root, dev), Path(root, "class/drm/card1/device"))
    w("proc_cpuinfo", "model name\t: AMD Ryzen 5 7500F 6-Core Processor\n")


class FakeSysfsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        make_tree(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_hwmon_scan_order_and_scaling(self):
        chips = hwmon.scan(self.root)
        self.assertEqual([c.name for c in chips], ["k10temp", "asusec", "nct6799"])
        self.assertEqual(chips[0].get("temp", "Tctl").value, 47.125)
        nct = chips[2]
        self.assertEqual(nct.get("in", "Vcore").value, 1.1)
        self.assertAlmostEqual(nct.get("pwm", index=2).value, 50.196, places=2)

    def test_cpu(self):
        info = cpu.read(hwmon.scan(self.root), self.root, Path(self.root, "proc_cpuinfo"), with_load=False)
        self.assertEqual(info.model, "AMD Ryzen 5 7500F 6-Core Processor")
        self.assertEqual(info.freqs_mhz, [5000.0, 3000.0])
        self.assertEqual((info.governor, info.boost, info.driver_status), ("performance", True, "active"))
        self.assertEqual((info.tctl, info.ccds), (47.125, {"Tccd1": 45.0}))

    def test_board_fans_with_labels(self):
        b = board.read(hwmon.scan(self.root), self.root, fan_labels={"nct6799/fan2": "CPU_FAN"})
        self.assertEqual(b.superio, "nct6799")
        self.assertEqual([(f.label, f.rpm) for f in b.fans], [("Fan 1", 0.0), ("CPU_FAN", 1234.0)])
        self.assertEqual(b.temps, {"VRM": 54.0})
        self.assertEqual(b.voltages, {"Vcore": 1.1})

    def test_gpu(self):
        g = gpu.read(self.root)
        self.assertEqual((g.busy, g.sclk_mhz, g.fan_rpm, g.power_w), (12, 2400.0, 900.0, 39.0))
        self.assertEqual(g.temps, {"edge": 55.0})


class ReadOnlyGuaranteeTests(unittest.TestCase):
    """Sensor and discovery code must never open anything for writing."""

    WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

    def test_no_writes_during_sampling_and_discovery(self):
        real_open, real_os_open = builtins.open, os.open
        violations = []

        def guarded_open(file, mode="r", *a, **kw):
            if any(c in mode for c in "wax+"):
                violations.append((str(file), mode))
            return real_open(file, mode, *a, **kw)

        def guarded_os_open(path, flags, *a, **kw):
            if flags & self.WRITE_FLAGS:
                violations.append((str(path), flags))
            return real_os_open(path, flags, *a, **kw)

        def no_write(*a, **kw):
            violations.append(("os.write", a[:1]))
            raise AssertionError("os.write called")

        with mock.patch("builtins.open", guarded_open), \
                mock.patch("os.open", guarded_os_open), mock.patch("os.write", no_write):
            sensors.sample()           # real /sys on this machine
            discover()
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
