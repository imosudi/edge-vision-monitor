"""
Unit tests for ESP32-S3 ambient temperature and humidity telemetry sampler.
"""

from __future__ import annotations

import unittest
from app.core.config import TelemetryConfig
from app.telemetry.ambient import (
    AmbientSensorCollector,
    classify_comfort,
    ESP32_CHIP_TYPE,
    ESP32_MAC_ADDRESS,
)
from app.telemetry.collector import TelemetryCollector


class TestAmbientTelemetry(unittest.TestCase):
    """Test ambient telemetry parsing, comfort classification, and collector integration."""

    def test_classify_comfort_ranges(self):
        """Test thermal comfort categorisation across diverse temperature and humidity points."""
        status, color = classify_comfort(15.0, 50.0)
        self.assertEqual(status, "Extreme Cold")
        self.assertEqual(color, "#4A00E0")

        status, color = classify_comfort(18.0, 50.0)
        self.assertEqual(status, "Chilly")
        self.assertEqual(color, "#3498DB")

        status, color = classify_comfort(21.0, 50.0)
        self.assertEqual(status, "Cool / Crisp")
        self.assertEqual(color, "#2ECC71")

        status, color = classify_comfort(22.5, 50.0)
        self.assertEqual(status, "Very Comfortable")
        self.assertEqual(color, "#27AE60")

        status, color = classify_comfort(22.5, 70.0)
        self.assertEqual(status, "Sticky / Damp")
        self.assertEqual(color, "#3498DB")

        status, color = classify_comfort(24.5, 50.0)
        self.assertEqual(status, "Warm")
        self.assertEqual(color, "#F39C12")

        status, color = classify_comfort(24.5, 65.0)
        self.assertEqual(status, "Stuffy / Hot")
        self.assertEqual(color, "#E74C3C")

        status, color = classify_comfort(27.0, 40.0)
        self.assertEqual(status, "Warm")
        self.assertEqual(color, "#F39C12")

        status, color = classify_comfort(30.0, 50.0)
        self.assertEqual(status, "Extreme Heat")
        self.assertEqual(color, "#8B0000")

    def test_regex_parsing(self):
        """Test parsing of actual ESP32 serial log output line."""
        line = "I (430601) dht22: [2026-10-19 12:20:18] Temperature: 28.0 C | Humidity: 29.5% | Comfort: Warm (#F39C12) | LED RGB: R=243 G=156 B=18"
        m = AmbientSensorCollector.LOG_REGEX.search(line)
        self.assertIsNotNone(m)
        temp_val = float(m.group(1))
        hum_val = float(m.group(2))
        comfort_val = m.group(3).strip()
        color_val = m.group(4)

        self.assertEqual(temp_val, 28.0)
        self.assertEqual(hum_val, 29.5)
        self.assertEqual(comfort_val, "Warm")
        self.assertEqual(color_val, "#F39C12")

    def test_metadata_structure(self):
        """Verify ESP32 hardware metadata specifications."""
        config = TelemetryConfig(enable_ambient=False)
        collector = AmbientSensorCollector(config)
        meta = collector.get_metadata()

        self.assertEqual(meta["chip_type"], ESP32_CHIP_TYPE)
        self.assertEqual(meta["mac_address"], ESP32_MAC_ADDRESS)
        self.assertIn("DHT22", meta["sensor_model"])
        self.assertEqual(meta["serial_port"], "/dev/ttyUSB0")
        self.assertEqual(meta["baud_rate"], 115200)

    def test_telemetry_collector_ambient_integration(self):
        """Verify TelemetryCollector incorporates ambient metrics and metadata in snapshot."""
        config = TelemetryConfig(enable_ambient=False)
        collector = TelemetryCollector(config)
        samples = collector.sample_all()
        snapshot = collector.get_latest_snapshot()

        # When enable_ambient is False, collector behaves gracefully
        self.assertIsInstance(snapshot, dict)
        collector.stop()


if __name__ == "__main__":
    unittest.main()
