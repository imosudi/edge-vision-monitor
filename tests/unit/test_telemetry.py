"""
Unit tests for telemetry decoding, bitfield extraction, and metric normalisation.
"""

from app.storage.models import TelemetrySample
from app.telemetry.raspberry_pi import RaspberryPiTelemetry, ThrottlingDecoder


def test_throttling_decoder_nominal():
    decoded = ThrottlingDecoder.decode(0x0)
    assert decoded["undervoltage_now"] is False
    assert decoded["throttled_now"] is False
    assert decoded["arm_freq_capped_now"] is False
    assert decoded["is_throttled_or_undervolted"] is False


def test_throttling_decoder_undervoltage_now():
    # Bit 0 = Undervoltage now
    decoded = ThrottlingDecoder.decode(0x1)
    assert decoded["undervoltage_now"] is True
    assert decoded["is_throttled_or_undervolted"] is True


def test_throttling_decoder_past_and_present_flags():
    # Bit 0 (undervolt now) + Bit 18 (throttling occurred in past = 0x40000)
    raw = 0x40001
    decoded = ThrottlingDecoder.decode(raw)
    assert decoded["undervoltage_now"] is True
    assert decoded["throttled_occurred"] is True
    assert decoded["is_throttled_or_undervolted"] is True


def test_telemetry_sample_defaults_and_null_support():
    sample = TelemetrySample(
        metric_name="hailo_temperature",
        value=None,
        unit="celsius",
        source="hailort",
        availability_status="UNSUPPORTED",
        error_message="Sensor unavailable on this host",
    )
    assert sample.value is None
    assert sample.availability_status == "UNSUPPORTED"
    assert sample.error_message is not None
