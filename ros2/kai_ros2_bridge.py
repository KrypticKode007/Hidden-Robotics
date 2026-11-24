#!/usr/bin/env python3
import struct
import serial
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import Bool


def cobs_encode(data: bytes) -> bytes:
    """Encodes a byte payload using Consistent Overhead Byte Stuffing + 0x00 delimiter."""
    out = bytearray()
    code_idx = 0
    out.append(0)
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


class KaiRos2Bridge(Node):
    def __init__(self):
        super().__init__("kai_ros2_bridge")
        self.declare_parameter("serial_port", "/dev/ttyACM0")
        self.declare_parameter("baud_rate", 921600)

        port = self.get_parameter("serial_port").get_parameter_value().string_value
        baud = self.get_parameter("baud_rate").get_parameter_value().integer_value

        self.ser = serial.Serial(port, baudrate=baud, timeout=0.05)
        self.estop_active = True  # Start halted until StrongBox proximity arms the system

        self.sub_vel = self.create_subscription(Twist, "/kai/cmd_vel", self.on_cmd_vel, 10)
        self.sub_estop = self.create_subscription(Bool, "/kai/estop", self.on_estop, 10)
        self.get_logger().info(f"Connected to ESP32-S3 actuator controller on {port} @ {baud} bps")

    def on_estop(self, msg: Bool):
        self.estop_active = msg.data
        payload = struct.pack("<BB", 0xFF, 1 if self.estop_active else 0)
        self.ser.write(cobs_encode(payload))
        state = "ENGAGED (HALT)" if self.estop_active else "RELEASED (ARMED)"
        self.get_logger().warn(f"Hardware GPIO 21 E-Stop {state}")

    def on_cmd_vel(self, msg: Twist):
        if self.estop_active:
            return
        linear_mm_s = int(max(-32767, min(32767, msg.linear.x * 1000.0)))
        angular_mrad_s = int(max(-32767, min(32767, msg.angular.z * 1000.0)))
        payload = struct.pack("<Bhh", 0x01, linear_mm_s, angular_mrad_s)
        self.ser.write(cobs_encode(payload))


def main(args=None):
    rclpy.init(args=args)
    node = KaiRos2Bridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # Fail-safe E-Stop on node shutdown
        node.ser.write(cobs_encode(struct.pack("<BB", 0xFF, 1)))
        node.ser.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
      
