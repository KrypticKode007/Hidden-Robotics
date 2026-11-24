# Hidden-Robotics 🤖🛰️
**Embodied Physical-AI Runtime & Hardware Safety Stack for Kai-007**

**Hidden-Robotics** turns your local **Kai-007** AI brain into a real-world robotics controller—combining Apple Silicon intelligence, Android 15+ hardware proximity security, off-grid radio telemetry, ROS 2 middleware, and sub-millisecond ESP32-S3 motor safety.

No cloud dependency. No laggy web dashboards. Built for autonomous rovers, lab automation, industrial inspection, and custom physical AI builds.

---

## Why Hidden-Robotics Stands Apart

| Capability | Standard Robotics Stacks | **Hidden-Robotics** |
| :--- | :--- | :--- |
| **Safety Interlock** | Software-only stop buttons | **Android StrongBox ECDSA Dead-Man Switch** + active-low `GPIO 21` relay cutoff |
| **Field Connectivity** | Breaks when Wi-Fi drops | **2.4 GHz BLE Micro-Tunnel + 915 MHz LoRa + Offline `.ZIM` Docs** |
| **Motor Framing** | Unframed ASCII strings | **921600 bps COBS Binary Protocol** with `250 ms` hardware watchdog |
| **Mobile Telemetry** | Separate dedicated radios | **Android 15+ Sensor Gateway** (IMU, GPS, Camera & Walkie-Talkie L2CAP audio) |
| **AI Brain** | Expensive cloud API calls | **100% Local Apple MLX** + Hybrid Vector/Temporal Knowledge Vault |

---

## System Architecture

```text
┌───────────────────────────┐       2.4 GHz BLE / L2CAP       ┌───────────────────────────┐
│     Android 15+ Phone     │ ◄─────────────────────────────► │     macOS Apple Silicon   │
│ • StrongBox ECDSA Key     │   • Signed Proximity Heartbeat  │ • Kai-007 MLX Brain       │
│ • IMU / GPS / Camera      │   • 5G Cellular Web Tunnel      │ • Omni Robotics MCP       │
│ • Hold-to-Talk L2CAP Mic  │   • 10 Hz RSSI Watchdog         │ • Hybrid Knowledge Vault  │
└───────────────────────────┘                                 └─────────────┬─────────────┘
                                                                            │ ROS 2 / Docker
                                                                            ▼
┌───────────────────────────┐    921600 bps COBS UART/USB     ┌───────────────────────────┐
│   ESP32-S3 Actuator MCU   │ ◄─────────────────────────────► │   Companion SBC / Host    │
│ • GPIO 21 Active-LOW EStop│   • OP_CMD_VEL (0x01)           │ • Raspberry Pi 5 / Jetson │
│ • 250 ms Hardware Watchdog│   • OP_ESTOP (0xFF)             │ • ros2/kai_ros2_bridge.py │
│ • Differential PWM Mixer  │   • OP_HEARTBEAT (0x02)         │ • /kai/cmd_vel & /estop   │
└───────────────────────────┘                                 └───────────────────────────┘
```

---

## Repository Map

```text
Hidden-Robotics/
├── wire_kryptic_main.py              # Master orchestrator linking Kai-007 & robotics
├── omni_robotics_mcp.py              # Biometric & StrongBox-gated MCP robotics tools
├── kryptic_robotics_bridge.py        # Low-level actuator & telemetry router
├── android_sensor_gateway.py         # Android 15+ IMU, GPS & camera stream ingestor
├── kai_offline_internet.py           # Cascading BLE 5G, .ZIM, LoRa & Outbox router
├── KaiBleWebTunnel.kt                # Android 15+ cellular micro-tunnel companion
├── consolidate_omni_vault.py         # Spatial waypoint & hardware memory sync
├── config/
│   └── hidden_robotics.yaml          # Pinouts, velocity caps, BLE UUIDs & watchdogs
├── firmware/
│   ├── esp32_cobs_estop.ino          # ESP32-S3 COBS parser & GPIO 21 E-Stop firmware
│   └── platformio.ini                # One-command PlatformIO build configuration
├── ros2/
│   └── kai_ros2_bridge.py            # ROS 2 Humble/Jazzy /kai/cmd_vel & /kai/estop node
├── tests/
│   └── test_robotics_cobs_estop.py   # Virtual ESP32-S3 HIL safety & watchdog tests
├── .devcontainer/                    # Reproducible ROS 2 Jazzy Docker environment
├── KAI_HIDDEN_ROBOTICS_WHITEPAPER.pdf# Full technical & commercial architecture whitepaper
└── test_omni_e2e.sh                  # Automated E2E verification script
```

---

## Quick Start

### 1. Run the Safety & Framing Verification Suite (No Hardware Needed)
```bash
git clone https://github.com
cd Hidden-Robotics

pip install pytest pyserial pyyaml
chmod +x test_omni_e2e.sh
./test_omni_e2e.sh
```

### 2. Flash the ESP32-S3 Actuator Controller
```bash
pip install platformio
pio run -d firmware --target upload
```

### 3. Launch the ROS 2 Bridge (via Docker or Native ROS 2 Jazzy)
```bash
docker compose -f .devcontainer/docker-compose.yml up --build
```

---

## Commercial Licensing & Custom Robotics Deployments
* **Open-Source Core:** Licensed under **Apache-2.0** for personal research, education, and open hardware builds.
* **Commercial Fleet & Custom Integration:** Need custom kinematics, multi-rover LoRa mesh relays, or white-labeled enterprise deployments? Reach out to **KrypticKode007** for commercial support and licensing.
