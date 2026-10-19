"""
Unified Telemetry Collector coordinating hardware, thermal, system,
process, and Hailo accelerator telemetry sampling.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import TelemetryConfig
from app.core.logging_config import get_logger
from app.storage.models import TelemetrySample
from app.telemetry.ambient import AmbientSensorCollector
from app.telemetry.hailo import collect_hailo_telemetry
from app.telemetry.hwmon import collect_hwmon_metrics
from app.telemetry.optional_sensors import OptionalSensorsCollector
from app.telemetry.process_metrics import ProcessMetricsSampler
from app.telemetry.raspberry_pi import RaspberryPiTelemetry
from app.telemetry.thermal import collect_thermal_metrics

logger = get_logger("TELEMETRY.COLLECTOR")


class TelemetryCollector:
    """Orchestrates all individual hardware telemetry samplers."""

    def __init__(self, config: TelemetryConfig):
        self._config = config
        self._rpi_sampler = RaspberryPiTelemetry()
        self._proc_sampler = ProcessMetricsSampler()
        self._opt_sampler = OptionalSensorsCollector(config)
        self._ambient_sampler = AmbientSensorCollector(config)
        self._latest_cache: Dict[str, Dict[str, Any]] = {}
        self._last_sample_monotonic = 0.0

    def sample_all(self) -> List[TelemetrySample]:
        """Execute one complete sampling pass across all enabled telemetry sources."""
        samples: List[TelemetrySample] = []
        now_utc = datetime.now(timezone.utc).isoformat()
        mono = time.monotonic()
        self._last_sample_monotonic = mono

        # 1. Linux hwmon
        if self._config.enable_hwmon:
            try:
                for s in collect_hwmon_metrics():
                    s.timestamp_utc = now_utc
                    s.monotonic_ts = mono
                    samples.append(s)
            except Exception as e:
                logger.warning("Error collecting hwmon metrics: %s", e)

        # 2. Linux Thermal Zones
        if self._config.enable_thermal:
            try:
                for s in collect_thermal_metrics():
                    s.timestamp_utc = now_utc
                    s.monotonic_ts = mono
                    samples.append(s)
            except Exception as e:
                logger.warning("Error collecting thermal metrics: %s", e)

        # 3. Raspberry Pi host sysfs & vcgencmd
        if self._config.enable_raspberry_pi:
            try:
                for s in self._rpi_sampler.collect():
                    s.timestamp_utc = now_utc
                    s.monotonic_ts = mono
                    samples.append(s)
            except Exception as e:
                logger.warning("Error collecting RPi metrics: %s", e)

        # 4. Hailo NPU accelerator
        if self._config.enable_hailo:
            try:
                for s in collect_hailo_telemetry():
                    s.timestamp_utc = now_utc
                    s.monotonic_ts = mono
                    samples.append(s)
            except Exception as e:
                logger.warning("Error collecting Hailo telemetry: %s", e)

        # 5. Process & Container resources
        if self._config.enable_process:
            try:
                for s in self._proc_sampler.collect():
                    s.timestamp_utc = now_utc
                    s.monotonic_ts = mono
                    samples.append(s)
            except Exception as e:
                logger.warning("Error collecting process metrics: %s", e)

        # 6. Optional I2C / INA219 sensors
        if self._config.enable_ina219:
            try:
                for s in self._opt_sampler.collect():
                    s.timestamp_utc = now_utc
                    s.monotonic_ts = mono
                    samples.append(s)
            except Exception as e:
                logger.warning("Error collecting optional sensors: %s", e)

        # 7. Ambient Temperature & Humidity (ESP32-S3 over /dev/ttyUSB0)
        enable_ambient = getattr(self._config, "enable_ambient", getattr(self._config, "enable_ambient_sensor", True))
        if enable_ambient:
            try:
                for s in self._ambient_sampler.collect():
                    s.timestamp_utc = now_utc
                    s.monotonic_ts = mono
                    samples.append(s)
            except Exception as e:
                logger.warning("Error collecting ambient sensor telemetry: %s", e)

        # Update in-memory snapshot cache
        for s in samples:
            self._latest_cache[s.metric_name] = {
                "name": s.metric_name,
                "value": s.value,
                "unit": s.unit,
                "source": s.source,
                "status": s.availability_status,
                "error": s.error_message,
                "timestamp_utc": s.timestamp_utc,
                "freshness_seconds": round(time.monotonic() - mono, 2),
            }

        # Enrich cache with ESP32 ambient metadata and comfort classification
        if enable_ambient:
            try:
                meta = self._ambient_sampler.get_metadata()
                self._latest_cache["ambient_metadata"] = {
                    "name": "ambient_metadata",
                    "value": 1.0 if meta.get("is_connected") else 0.0,
                    "unit": "metadata",
                    "source": f"esp32:{meta.get('serial_port')}",
                    "status": "AVAILABLE" if meta.get("is_connected") else "UNAVAILABLE",
                    "error": None,
                    "timestamp_utc": now_utc,
                    "freshness_seconds": round(time.monotonic() - mono, 2),
                    "chip_type": meta.get("chip_type"),
                    "features": meta.get("features"),
                    "crystal_frequency": meta.get("crystal_frequency"),
                    "mac_address": meta.get("mac_address"),
                    "sensor_model": meta.get("sensor_model"),
                    "serial_port": meta.get("serial_port"),
                    "baud_rate": meta.get("baud_rate"),
                    "comfort_status": meta.get("comfort_status"),
                    "comfort_color": meta.get("comfort_color"),
                }
                if "ambient_temperature_c" in self._latest_cache:
                    self._latest_cache["ambient_temperature_c"]["comfort_status"] = meta.get("comfort_status")
                    self._latest_cache["ambient_temperature_c"]["comfort_color"] = meta.get("comfort_color")
            except Exception as e:
                logger.debug("Error updating ambient metadata cache: %s", e)

        return samples

    def stop(self) -> None:
        """Cleanly terminate background collector workers and reader threads."""
        if hasattr(self, "_ambient_sampler") and self._ambient_sampler:
            try:
                self._ambient_sampler.stop()
            except Exception as e:
                logger.debug("Error stopping ambient sampler: %s", e)

    def get_ambient_metadata(self) -> Dict[str, Any]:
        """Return ESP32 ambient sensor hardware metadata and comfort classification."""
        if hasattr(self, "_ambient_sampler") and self._ambient_sampler:
            return self._ambient_sampler.get_metadata()
        return {}

    def get_latest_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """Return the most recent snapshot of all collected metrics with freshness."""
        now = time.monotonic()
        res: Dict[str, Dict[str, Any]] = {}
        for k, v in self._latest_cache.items():
            entry = dict(v)
            entry["freshness_seconds"] = round(now - self._last_sample_monotonic, 2)
            res[k] = entry
        return res

    def get_metric_catalog(self) -> List[Dict[str, Any]]:
        """Catalogue of discovered and known telemetry metrics, their units and provenance."""
        catalog = []
        for name, entry in self._latest_cache.items():
            catalog.append(
                {
                    "metric_name": name,
                    "unit": entry["unit"],
                    "source": entry["source"],
                    "current_status": entry["status"],
                }
            )
        return sorted(catalog, key=lambda x: x["metric_name"])
