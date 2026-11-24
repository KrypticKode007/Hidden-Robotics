#!/usr/bin/env python3
import json
import struct
import threading
import serial
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from sensor_msgs.msg import BatteryState
from std_msgs.msg import Bool, String

# Protocol Opcodes
OP_CMD_VEL   = 0x01  # Host -> MCU: [0x01, int16 linear_mm_s, int16 angular_mrad_s]
OP_HEARTBEAT = 0x02  # Host -> MCU: [0x02]
OP_TELEMETRY = 0x10  # MCU -> Host: [0x10, uint16 batt_mv, uint8 estop_latched, uint8 pwm_l, uint8 pwm_r]
OP_ESTOP     = 0xFF  # Host -> MCU: [0xFF, uint8 halt]


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
            return b""
        idx += 1
        for _ in range(1, code):
            out.append(frame[idx])
            idx += 1
        if code != 0xFF and idx < len(frame):
            out.append(0x00)
    return bytes(out)


class KaiRos2Bridge(Node):
    def __init__(self):
        super().__init__("kai_ros2_bridge")
        self.declare_parameter("serial_port", "/dev/ttyACM0")
        self.declare_parameter("baud_rate", 921600)

        port = self.get_parameter("serial_port").get_parameter_value().string_value
        baud = self.get_parameter("baud_rate").get_parameter_value().integer_value

        self.ser = serial.Serial(port, baudrate=baud, timeout=0.05)
        self.estop_active = True
        self._running = True

        # Subscribers (Commands from Kai-007 / Nav2)
        self.sub_vel = self.create_subscription(Twist, "/kai/cmd_vel", self.on_cmd_vel, 10)
        self.sub_estop = self.create_subscription(Bool, "/kai/estop", self.on_estop, 10)

        # Publishers (Live Hardware Health back to Kai-007 & Android Dashboard)
        self.pub_telemetry = self.create_publisher(String, "/kai/telemetry", 10)
        self.pub_battery = self.create_publisher(BatteryState, "/kai/battery", 10)

        # 10 Hz Heartbeat timer to keep ESP32-S3 250ms watchdog alive when armed
        self.heartbeat_timer = self.create_timer(0.10, self._send_heartbeat)

        # Background thread for incoming MCU telemetry frames
        self._rx_thread = threading.Thread(target=self._serial_rx_loop, daemon=True)
        self._rx_thread.start()

        self.get_logger().info(f"Connected to ESP32-S3 on {port} @ {baud} bps (Telemetry Active)")

    def _send_heartbeat(self):
        if not self.estop_active and self.ser.is_open:
            self.ser.write(cobs_encode(struct.pack("<B", OP_HEARTBEAT)))

    def on_estop(self, msg: Bool):
        self.estop_active = msg.data
        self.ser.write(cobs_encode(struct.pack("<BB", OP_ESTOP, 1 if self.estop_active else 0)))
        state = "ENGAGED (HALT)" if self.estop_active else "RELEASED (ARMED)"
        self.get_logger().warn(f"Hardware GPIO 21 E-Stop {state}")

    def on_cmd_vel(self, msg: Twist):
        if self.estop_active:
            return
        linear_mm_s = int(max(-32767, min(32767, msg.linear.x * 1000.0)))
        angular_mrad_s = int(max(-32767, min(32767, msg.angular.z * 1000.0)))
        self.ser.write(cobs_encode(struct.pack("<Bhh", OP_CMD_VEL, linear_mm_s, angular_mrad_s)))

    def _serial_rx_loop(self):
        rx_buf = bytearray()
        while self._running and self.ser.is_open:
            try:
                chunk = self.ser.read(64)
                for byte in chunk:
                    if byte == 0x00:
                        if rx_buf:
                            pkt = cobs_decode(bytes(rx_buf))
                            rx_buf.clear()
                            self._handle_mcu_packet(pkt)
                    else:
                        rx_buf.append(byte)
            except Exception:
                pass

    def _handle_mcu_packet(self, pkt: bytes):
        if len(pkt) >= 6 and pkt[0] == OP_TELEMETRY:
            batt_mv, estop_flag, pwm_l, pwm_r = struct.unpack("<HBBB", pkt[1:6])
            voltage_v = batt_mv / 1000.0

            # Publish standard ROS 2 BatteryState
            batt_msg = BatteryState()
            batt_msg.header.stamp = self.get_clock().now().to_msg()
            batt_msg.voltage = float(voltage_v)
            batt_msg.present = True
            self.pub_battery.publish(batt_msg)

            # Publish JSON telemetry for Kai-007 & Android BLE Dashboard
            telem_json = json.dumps({
                "type": "robotics_telemetry",
                "battery_v": round(voltage_v, 2),
                "estop_latched": bool(estop_flag),
                "pwm_left": pwm_l,
                "pwm_right": pwm_r,
            })
            self.pub_telemetry.publish(String(data=telem_json))

    def destroy_node(self):
        self._running = False
        if self.ser.is_open:
            self.ser.write(cobs_encode(struct.pack("<BB", OP_ESTOP, 1)))
            self.ser.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = KaiRos2Bridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
            
