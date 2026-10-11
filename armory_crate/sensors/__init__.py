"""Read-only hardware monitoring. One Snapshot per refresh tick."""

from dataclasses import dataclass

from . import board, cpu, gpu, hwmon, system


@dataclass
class Snapshot:
    cpu: cpu.CpuInfo
    gpu: gpu.GpuInfo | None
    board: board.BoardInfo
    system: system.SystemInfo


def sample(fan_labels=None, root=hwmon.SYSFS):
    chips = hwmon.scan(root)
    g = gpu.read(root)
    return Snapshot(cpu=cpu.read(chips, root), gpu=g,
                    board=board.read(chips, root, fan_labels=fan_labels),
                    system=system.read(chips, root))
