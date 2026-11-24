import struct
import time
import pytest


# --- COBS Encoder & Decoder (Mirrors ESP32-S3 & ROS 2 Node) ---
def cobs_encode(data: bytes) -> bytes:
    out = bytearray([0])
    code_idx = 0
    code = 1
    for byte in data:
        if byte == 0:
            out[code_idx] = code
            code_idx = len(out)
            out.append(0)
            code = 1
        else:
            out.append(byte)
            code += 1
            if code == 0xFF:
                out[code_idx] = code
                code_idx = len(out)
                out.append(0)
                code = 1
    out[code_idx] = code
    out.append(0x00)
    return bytes(out)


def cobs_decode(frame: bytes) -> bytes:
    if frame.endswith(b"\x00"):
        frame = frame[:-1]
    out = bytearray()
    idx = 0
    while idx < len(frame):
        code = frame[idx]
        if code == 0 or idx + code > len(frame) + 1:
            raise ValueError("Malformed COBS frame")
        idx += 1
        for _ in range(1, code):
            out.append(frame[idx])
            idx += 1
        if code != 0xFF and idx < len(frame):
            out.append(0x00)
    return bytes(out)


# --- Virtual ESP32-S3 Hardware-in-the-Loop (HIL) State Machine ---
class VirtualEsp32Actuator:
    def __init__(self, watchdog_ms: int = 250):
        self.watchdog_ms = watchdog_ms
        self.estop_latched = True   # Boot in fail-safe HALT
        self.gpio21_level = 0       # 0 = LOW (Relay open / safe), 1 = HIGH (Armed)
        self.pwm_left = 0
        self.pwm_right = 0
        self.last_cmd_ms = time.monotonic() * 1000.0

    def receive_wire_frame(self, encoded_frame: bytes):
        pkt = cobs_decode(encoded_frame)
        if not pkt:
            return
        self.last_cmd_ms = time.monotonic() * 1000.0
        opcode = pkt[0]

        if opcode == 0xFF and len(pkt) >= 2:
            halt = pkt[1] != 0
            self.estop_latched = halt
            self.gpio21_level = 0 if halt else 1
            if halt:
                self.pwm_left = 0
                self.pwm_right = 0

        elif opcode == 0x01 and len(pkt) >= 5:
            if self.estop_latched:
                self.pwm_left = 0
                self.pwm_right = 0
                return
            linear_mm_s, angular_mrad_s = struct.unpack("<hh", pkt[1:5])
            left_cmd = (linear_mm_s - (angular_mrad_s // 4)) // 4
            right_cmd = (linear_mm_s + (angular_mrad_s // 4)) // 4
            self.pwm_left = min(255, abs(left_cmd))
            self.pwm_right = min(255, abs(right_cmd))

    def tick_watchdog(self, now_ms: float | None = None):
        now = now_ms if now_ms is not None else time.monotonic() * 1000.0
        if not self.estop_latched and (now - self.last_cmd_ms > self.watchdog_ms):
            self.estop_latched = True
            self.gpio21_level = 0
            self.pwm_left = 0
            self.pwm_right = 0


# --- Automated Safety & Framing Tests ---
def test_cobs_roundtrip_with_embedded_zeros():
    raw = struct.pack("<Bhh", 0x01, 0, -500)  # Contains multiple 0x00 bytes
    encoded = cobs_encode(raw)
    assert 0x00 not in encoded[:-1]
    assert encoded.endswith(b"\x00")
    assert cobs_decode(encoded) == raw


def test_estop_blocks_motion_until_armed():
    mcu = VirtualEsp32Actuator()
    assert mcu.estop_latched is True
    assert mcu.gpio21_level == 0

    # Send velocity while halted -> motors must stay at 0 PWM
    vel_frame = cobs_encode(struct.pack("<Bhh", 0x01, 800, 0))
    mcu.receive_wire_frame(vel_frame)
    assert mcu.pwm_left == 0 and mcu.pwm_right == 0

    # Arm via StrongBox-authorized E-Stop release (0xFF, 0)
    arm_frame = cobs_encode(struct.pack("<BB", 0xFF, 0))
    mcu.receive_wire_frame(arm_frame)
    assert mcu.estop_latched is False
    assert mcu.gpio21_level == 1

    # Now velocity command drives motors
    mcu.receive_wire_frame(vel_frame)
    assert mcu.pwm_left == 200 and mcu.pwm_right == 200


def test_watchdog_auto_halts_on_link_drop():
    mcu = VirtualEsp32Actuator(watchdog_ms=250)
    mcu.receive_wire_frame(cobs_encode(struct.pack("<BB", 0xFF, 0)))
    mcu.receive_wire_frame(cobs_encode(struct.pack("<Bhh", 0x01, 600, 0)))
    assert mcu.pwm_left == 150

    # Simulate 300ms silence -> watchdog must cut GPIO 21 & zero PWM
    mcu.tick_watchdog(mcu.last_cmd_ms + 300.0)
    assert mcu.estop_latched is True
    assert mcu.gpio21_level == 0
    assert mcu.pwm_left == 0 and mcu.pwm_right == 0
                       
