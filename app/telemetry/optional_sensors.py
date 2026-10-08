"""
Optional hardware sensors: INA219 current/power monitoring and ambient I2C sensors.
"""

from __future__ import annotations

from typing import List, Optional
from app.core.config import TelemetryConfig
from app.core.logging_config import RateLimitedLogger, get_logger
from app.storage.models import TelemetrySample

raw_logger = get_logger("TELEMETRY.OPTIONAL")
logger = RateLimitedLogger(raw_logger, window_seconds=60.0)


class OptionalSensorsCollector:
    """Manages optional I2C physical sensors such as INA219 voltage/power monitors."""

    def __init__(self, config: TelemetryConfig):
        self._enabled = config.enable_ina219
        self._bus_num = config.ina219_i2c_bus
        self._address = config.ina219_i2c_address
        self._sensor_initialized = False

    def collect(self) -> List[TelemetrySample]:
        if not self._enabled:
            return []

        samples: List[TelemetrySample] = []

        try:
            from smbus2 import SMBus  # type: ignore

            with SMBus(self._bus_num) as bus:
                # Read INA219 bus voltage register (0x02)
                # Raw register is 16-bit big endian, bits 15-3 contain voltage in 4mV units
                data = bus.read_i2c_block_data(self._address, 0x02, 2)
                raw_v = (data[0] << 8) | data[1]
                v_millivolts = (raw_v >> 3) * 4
                bus_volts = round(v_millivolts / 1000.0, 3)

                samples.append(
                    TelemetrySample(
                        metric_name="ina219_bus_voltage",
                        value=bus_volts,
                        unit="volts",
                        source=f"i2c:{self._bus_num}@{hex(self._address)}",
                        availability_status="AVAILABLE",
                    )
                )

        except ImportError:
            samples.append(
                TelemetrySample(
                    metric_name="ina219_bus_voltage",
                    value=None,
                    unit="volts",
                    source=f"i2c:{self._bus_num}",
                    availability_status="UNSUPPORTED",
                    error_message="smbus2 library not installed",
                )
            )
        except Exception as e:
            samples.append(
                TelemetrySample(
                    metric_name="ina219_bus_voltage",
                    value=None,
                    unit="volts",
                    source=f"i2c:{self._bus_num}@{hex(self._address)}",
                    availability_status="UNAVAILABLE",
                    error_message=f"I2C read failed: {e}",
                )
            )

        return samples
