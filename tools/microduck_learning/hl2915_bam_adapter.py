#!/usr/bin/env python3
"""Shared runtime registration for the custom HL-2915 BAM actuator."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


METADATA_KEY = "hl2915_adapter"


@dataclass(frozen=True)
class AdapterConfig:
    error_gain: float
    max_velocity_rpm: float = 110.0
    default_vin: float = 12.0
    default_kp: float = 16.0
    max_pwm: float = 0.97
    max_current_a: float = 1.5

    def validate(self) -> None:
        values = asdict(self)
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values.values()):
            raise ValueError("adapter metadata must contain finite numbers")
        if self.error_gain <= 0:
            raise ValueError("error_gain must be greater than zero")
        if not 1.0 <= self.max_velocity_rpm <= 200.0:
            raise ValueError("max_velocity_rpm must be in 1..200")
        if not 0.0 < self.default_vin <= 14.0:
            raise ValueError("default_vin must be in (0, 14]")
        if not 0.0 < self.default_kp <= 255.0:
            raise ValueError("default_kp must be in (0, 255]")
        if not 0.0 < self.max_pwm <= 1.0:
            raise ValueError("max_pwm must be in (0, 1]")
        if not 0.0 < self.max_current_a <= 1.5:
            raise ValueError("max_current_a must be in (0, 1.5]")

    @classmethod
    def from_mapping(cls, value: Any) -> "AdapterConfig":
        if not isinstance(value, dict):
            raise ValueError(f"missing {METADATA_KEY} object")
        try:
            config = cls(**value)
        except TypeError as exc:
            raise ValueError(f"invalid {METADATA_KEY}: {exc}") from exc
        config.validate()
        return config

    def to_mapping(self) -> dict[str, float]:
        self.validate()
        return asdict(self)


def register(config: AdapterConfig):
    config.validate()
    try:
        from bam.actuator import VoltageControlledActuator
        from bam.feetech.actuator import STS3215Actuator
        from bam.parameter import Parameter
        from bam.testbench import Pendulum
        import bam.actuators as registry
    except ImportError as exc:
        raise SystemExit(
            "BAM is missing; run this command inside the microduck_rl/BAM uv environment"
        ) from exc

    class HL2915Actuator(STS3215Actuator):
        def __init__(self, testbench_class):
            super().__init__(testbench_class)
            self.vin = config.default_vin
            self.kp = config.default_kp
            self.error_gain = config.error_gain
            self.max_pwm = config.max_pwm
            self.max_current = config.max_current_a
            self.default_max_velocity = config.max_velocity_rpm * 2.0 * math.pi / 60.0
            self.q_target_smooth = 0.0

        def initialize(self):
            super().initialize()
            self.model.kt = Parameter(0.912, 0.05, 2.5)
            self.model.R = Parameter(2.0, 0.1, 10.0)
            self.model.armature = Parameter(0.0001, 0.00001, 0.04)
            self.model.q_offset = Parameter(0.0, -0.2, 0.2)
            self.model.error_gain_ratio = Parameter(1.0, 0.1, 10.0)
            self.model.max_velocity = Parameter(
                self.default_max_velocity,
                0.1 * self.default_max_velocity,
                10.0 * self.default_max_velocity,
            )

        def compute_control(self, q_target, q, dq, dt):
            self.q_target_smooth = self.backend.clamp(
                q_target,
                self.q_target_smooth - self.model.max_velocity.value * dt,
                self.q_target_smooth + self.model.max_velocity.value * dt,
            )
            effective_target = q + (
                self.q_target_smooth - q
            ) * self.model.error_gain_ratio.value
            return VoltageControlledActuator.compute_control(
                self, effective_target, q, dq, dt
            )

    registry.actuators["hl2915"] = lambda: HL2915Actuator(Pendulum)
    return registry


def register_from_model(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("BAM model JSON root must be an object")
    if payload.get("actuator") != "hl2915":
        raise ValueError(f"expected actuator='hl2915', got {payload.get('actuator')!r}")
    config = AdapterConfig.from_mapping(payload.get(METADATA_KEY))
    return payload, register(config)
