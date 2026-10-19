"""
ESP32-S3 Ambient Temperature and Humidity Telemetry Sampler.
Reads live serial log stream from ESP32 on /dev/ttyUSB0 connected to DHT22 sensor on GPIO 21.
Supports both PySerial and zero-dependency standard library termios serial communication.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import TelemetryConfig
from app.core.logging_config import get_logger
from app.storage.models import TelemetrySample

logger = get_logger("TELEMETRY.AMBIENT")

ESP32_CHIP_TYPE = "ESP32-S3 (QFN56) (revision v0.2)"
ESP32_FEATURES = "Wi-Fi, BT 5 (LE), Dual Core + LP Core, 240MHz, Embedded PSRAM 8MB (AP_3v3)"
ESP32_CRYSTAL_FREQUENCY = "40MHz"
ESP32_MAC_ADDRESS = "94:a9:90:1c:78:14"
ESP32_SENSOR_MODEL = "DHT22 (AM2302) on GPIO 21"


def classify_comfort(temperature_c: float, humidity_percent: float) -> Tuple[str, str]:
    """
    Classify thermal comfort and return classification label with corresponding hex colour.
    Matches the onboard LED comfort logic in temp_humidity/temp_sensor_main.c.
    """
    if temperature_c < 16.0:
        return "Extreme Cold", "#4A00E0"
    elif temperature_c < 19.0:
        return "Chilly", "#3498DB"
    elif temperature_c < 21.5:
        return "Cool / Crisp", "#2ECC71"
    elif temperature_c <= 23.5:
        if humidity_percent > 65.0:
            return "Sticky / Damp", "#3498DB"
        return "Very Comfortable", "#27AE60"
    elif temperature_c <= 25.0:
        if humidity_percent > 60.0:
            return "Stuffy / Hot", "#E74C3C"
        return "Warm", "#F39C12"
    elif temperature_c <= 28.0:
        if humidity_percent <= 45.0:
            return "Warm", "#F39C12"
        elif humidity_percent <= 60.0:
            return "Stuffy / Hot", "#E74C3C"
        return "Sticky / Damp", "#3498DB"
    else:
        return "Extreme Heat", "#8B0000"


class AmbientSensorCollector:
    """
    Manages continuous background reading and parsing of ambient metrics
    emitted by ESP32-S3 over UART serial interface (/dev/ttyUSB0).
    """

    LOG_REGEX = re.compile(
        r"Temperature:\s*([-\d.]+)\s*C.*?[,|]\s*Humidity:\s*([-\d.]+)%(?:.*?[,|]\s*Comfort:\s*([^(\n]+?)\s*\((#[0-9a-fA-F]{6})\))?",
        re.IGNORECASE,
    )

    def __init__(self, config: TelemetryConfig):
        self._enabled = getattr(config, "enable_ambient", getattr(config, "enable_ambient_sensor", True))
        self._port = getattr(config, "ambient_serial_port", "/dev/ttyUSB0")
        self._baud = getattr(config, "ambient_baud_rate", 115200)

        self._lock = threading.Lock()
        self._latest_temp: Optional[float] = None
        self._latest_humidity: Optional[float] = None
        self._latest_comfort: Optional[str] = None
        self._latest_color: Optional[str] = None
        self._latest_timestamp_str: Optional[str] = None
        self._last_read_monotonic: float = 0.0
        self._device_present: bool = False
        self._is_running: bool = False
        self._thread: Optional[threading.Thread] = None

        if self._enabled:
            self.start()

    def start(self) -> None:
        """Start the background serial listener thread."""
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(
            target=self._serial_reader_loop,
            name="AmbientSensorReader",
            daemon=True,
        )
        self._thread.start()
        logger.info("Ambient sensor collector started on serial port '%s' at %d baud", self._port, self._baud)

    def stop(self) -> None:
        """Stop background listener thread cleanly."""
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        logger.info("Ambient sensor collector stopped")

    def is_present(self) -> bool:
        """Return True if ESP32 device node exists and has communicated recently."""
        if not self._device_present:
            return False
        return (time.monotonic() - self._last_read_monotonic) <= 20.0

    def get_metadata(self) -> Dict[str, Any]:
        """Return ESP32 hardware specifications, comfort classification, and status."""
        with self._lock:
            temp = self._latest_temp
            humidity = self._latest_humidity
            comfort = self._latest_comfort
            color = self._latest_color

        if temp is not None and humidity is not None and not comfort:
            comfort, color = classify_comfort(temp, humidity)

        return {
            "chip_type": ESP32_CHIP_TYPE,
            "features": ESP32_FEATURES,
            "crystal_frequency": ESP32_CRYSTAL_FREQUENCY,
            "mac_address": ESP32_MAC_ADDRESS,
            "sensor_model": ESP32_SENSOR_MODEL,
            "serial_port": self._port,
            "baud_rate": self._baud,
            "is_connected": self.is_present(),
            "temperature_c": temp,
            "humidity_percent": humidity,
            "comfort_status": comfort or "Unknown",
            "comfort_color": color or "#888888",
        }

    def collect(self) -> List[TelemetrySample]:
        """
        Produce structured telemetry samples for ambient temperature and humidity.
        Guarantees verifiable metrics without fabricating measurements.
        """
        if not self._enabled:
            return []

        now_mono = time.monotonic()
        with self._lock:
            temp = self._latest_temp
            humidity = self._latest_humidity
            last_mono = self._last_read_monotonic

        is_fresh = (now_mono - last_mono) <= 20.0 and temp is not None and humidity is not None

        samples: List[TelemetrySample] = []
        source_id = f"esp32:{self._port}"

        if is_fresh:
            samples.append(
                TelemetrySample(
                    metric_name="ambient_temperature_c",
                    value=round(temp, 1),
                    unit="celsius",
                    source=source_id,
                    availability_status="AVAILABLE",
                )
            )
            samples.append(
                TelemetrySample(
                    metric_name="ambient_humidity_percent",
                    value=round(humidity, 1),
                    unit="percent",
                    source=source_id,
                    availability_status="AVAILABLE",
                )
            )
            samples.append(
                TelemetrySample(
                    metric_name="ambient_sensor_present",
                    value=1.0,
                    unit="boolean",
                    source=source_id,
                    availability_status="AVAILABLE",
                )
            )
        else:
            device_exists = os.path.exists(self._port)
            status_desc = "UNAVAILABLE" if device_exists else "UNSUPPORTED"
            err_msg = (
                f"ESP32 on '{self._port}' communication timeout"
                if device_exists
                else f"ESP32 serial device node '{self._port}' not present"
            )

            samples.append(
                TelemetrySample(
                    metric_name="ambient_temperature_c",
                    value=None,
                    unit="celsius",
                    source=source_id,
                    availability_status=status_desc,
                    error_message=err_msg,
                )
            )
            samples.append(
                TelemetrySample(
                    metric_name="ambient_humidity_percent",
                    value=None,
                    unit="percent",
                    source=source_id,
                    availability_status=status_desc,
                    error_message=err_msg,
                )
            )
            samples.append(
                TelemetrySample(
                    metric_name="ambient_sensor_present",
                    value=0.0,
                    unit="boolean",
                    source=source_id,
                    availability_status="AVAILABLE",
                    error_message=err_msg if not device_exists else None,
                )
            )

        return samples

    def _serial_reader_loop(self) -> None:
        """Continuous serial listener with automatic reconnection and fallback."""
        while self._is_running:
            if not os.path.exists(self._port):
                self._device_present = False
                time.sleep(2.0)
                continue

            stream_obj = None
            fd = -1
            use_pyserial = False

            # 1. Try PySerial first if installed
            try:
                import serial  # type: ignore

                stream_obj = serial.Serial(self._port, self._baud, timeout=1.0)
                use_pyserial = True
                self._device_present = True
                logger.info("Connected to ESP32 on '%s' via PySerial", self._port)
            except ImportError:
                # 2. Zero-dependency standard library termios fallback
                try:
                    import termios

                    fd = os.open(self._port, os.O_RDONLY | os.O_NOCTTY)
                    attrs = termios.tcgetattr(fd)
                    attrs[4] = termios.B115200
                    attrs[5] = termios.B115200
                    attrs[0] = termios.IGNPAR
                    attrs[1] = 0
                    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
                    attrs[3] = termios.ICANON
                    termios.tcsetattr(fd, termios.TCSANOW, attrs)
                    stream_obj = os.fdopen(fd, "r", encoding="utf-8", errors="replace")
                    use_pyserial = False
                    self._device_present = True
                    logger.info("Connected to ESP32 on '%s' via standard library termios", self._port)
                except Exception as termios_err:
                    logger.warning("Failed opening '%s' via termios: %s", self._port, termios_err)
                    self._device_present = False
                    time.sleep(3.0)
                    continue
            except Exception as ser_err:
                logger.warning("Failed opening serial port '%s': %s", self._port, ser_err)
                self._device_present = False
                time.sleep(3.0)
                continue

            # Stream reading loop
            try:
                while self._is_running:
                    if use_pyserial:
                        line_bytes = stream_obj.readline()
                        if not line_bytes:
                            continue
                        line = line_bytes.decode("utf-8", errors="replace").strip()
                    else:
                        line = stream_obj.readline().strip()
                        if not line:
                            time.sleep(0.05)
                            continue

                    self._parse_log_line(line)
            except Exception as stream_err:
                logger.warning("Serial read error on '%s': %s", self._port, stream_err)
            finally:
                self._device_present = False
                if stream_obj:
                    try:
                        stream_obj.close()
                    except Exception:
                        pass
                elif fd >= 0:
                    try:
                        os.close(fd)
                    except Exception:
                        pass
                time.sleep(2.0)

    def _parse_log_line(self, line: str) -> bool:
        """Parse DHT22 log output from ESP32 serial stream."""
        if "dht22" not in line and "Temperature:" not in line:
            return False

        match = self.LOG_REGEX.search(line)
        if not match:
            return False

        try:
            temp_val = float(match.group(1))
            hum_val = float(match.group(2))
            comfort_val = match.group(3).strip() if match.group(3) else None
            color_val = match.group(4).strip() if match.group(4) else None

            if not comfort_val or not color_val:
                comfort_val, color_val = classify_comfort(temp_val, hum_val)

            with self._lock:
                self._latest_temp = temp_val
                self._latest_humidity = hum_val
                self._latest_comfort = comfort_val
                self._latest_color = color_val
                self._last_read_monotonic = time.monotonic()
                self._device_present = True

            return True
        except (ValueError, IndexError) as err:
            logger.debug("Failed parsing DHT22 line '%s': %s", line, err)
            return False
