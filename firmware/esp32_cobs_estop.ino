#include <Arduino.h>
#include <cstdint>
#include <cstring>

// ============================================================================
// Kai-007 x Hidden-Robotics | ESP32-S3 Actuator & Hardware E-Stop Firmware
// Protocol: COBS-encoded binary frames @ 921600 bps (0x00 frame delimiter)
// ============================================================================

// Hardware Pin Definitions (ESP32-S3)
constexpr uint8_t  PIN_ESTOP_RELAY = 21; // Active-LOW hardware E-Stop relay
constexpr uint8_t  PIN_PWM_LEFT    = 4;  // Left motor PWM speed
constexpr uint8_t  PIN_PWM_RIGHT   = 5;  // Right motor PWM speed
constexpr uint8_t  PIN_DIR_LEFT    = 6;  // Left motor direction (HIGH = fwd, LOW = rev)
constexpr uint8_t  PIN_DIR_RIGHT   = 7;  // Right motor direction (HIGH = fwd, LOW = rev)
constexpr uint8_t  PIN_STATUS_LED  = 2;  // Onboard status indicator

// Serial & Watchdog Configuration
constexpr uint32_t SERIAL_BAUD     = 921600;
constexpr uint32_t WATCHDOG_MS     = 250;
constexpr size_t   RX_BUF_SIZE     = 64;

// Binary Protocol Opcodes (inside COBS-decoded payload)
constexpr uint8_t  OP_CMD_VEL      = 0x01; // [0x01, int16_le linear_mm_s, int16_le angular_mrad_s]
constexpr uint8_t  OP_HEARTBEAT    = 0x02; // [0x02] Keep-alive ping from ROS 2 / Mac
constexpr uint8_t  OP_ESTOP        = 0xFF; // [0xFF, uint8_t halt (1 = HALT, 0 = ARM)]

// Runtime State
uint8_t  rx_buf[RX_BUF_SIZE];
size_t   rx_idx        = 0;
bool     estop_latched = true; // Always boot in safe halted state
uint32_t last_cmd_ms   = 0;

// Safe unaligned little-endian byte readers
static inline uint8_t read_u8(const uint8_t* buf, size_t offset) {
    return *(buf + offset);
}

static inline int16_t read_i16_le(const uint8_t* buf, size_t offset) {
    uint16_t lo = static_cast<uint16_t>(*(buf + offset));
    uint16_t hi = static_cast<uint16_t>(*(buf + offset + 1));
    return static_cast<int16_t>(lo | (hi << 8));
}

// Consistent Overhead Byte Stuffing (COBS) Decoder
size_t cobs_decode(const uint8_t* src, size_t len, uint8_t* dst, size_t max_dst) {
    size_t read_idx = 0;
    size_t write_idx = 0;

    while (read_idx < len) {
        uint8_t code = *(src + read_idx);
        if (code == 0 || read_idx + code > len + 1) {
            return 0; // Malformed COBS frame
        }
        read_idx++;

        for (uint8_t i = 1; i < code; i++) {
            if (write_idx >= max_dst) return 0;
            *(dst + write_idx++) = *(src + read_idx++);
        }

        if (code != 0xFF && read_idx < len) {
            if (write_idx >= max_dst) return 0;
            *(dst + write_idx++) = 0x00;
        }
    }
    return write_idx;
}

// Active-LOW Hardware E-Stop Relay & Motor Cutoff
void engage_hardware_estop(bool halt) {
    estop_latched = halt;
    // LOW = Relay open / motor power cut; HIGH = Relay closed / system armed
    digitalWrite(PIN_ESTOP_RELAY, halt ? LOW : HIGH);
    digitalWrite(PIN_STATUS_LED, halt ? LOW : HIGH);

    if (halt) {
        analogWrite(PIN_PWM_LEFT, 0);
        analogWrite(PIN_PWM_RIGHT, 0);
    }
}

// Differential Drive Mixer (mm/s linear, mrad/s angular -> PWM + Direction)
void apply_differential_drive(int16_t linear_mm_s, int16_t angular_mrad_s) {
    if (estop_latched) {
        analogWrite(PIN_PWM_LEFT, 0);
        analogWrite(PIN_PWM_RIGHT, 0);
        return;
    }

    int32_t left_cmd  = (static_cast<int32_t>(linear_mm_s) - (static_cast<int32_t>(angular_mrad_s) / 4)) / 4;
    int32_t right_cmd = (static_cast<int32_t>(linear_mm_s) + (static_cast<int32_t>(angular_mrad_s) / 4)) / 4;

    digitalWrite(PIN_DIR_LEFT,  left_cmd >= 0 ? HIGH : LOW);
    digitalWrite(PIN_DIR_RIGHT, right_cmd >= 0 ? HIGH : LOW);

    uint8_t pwm_l = static_cast<uint8_t>(constrain(abs(left_cmd), 0, 255));
    uint8_t pwm_r = static_cast<uint8_t>(constrain(abs(right_cmd), 0, 255));

    analogWrite(PIN_PWM_LEFT, pwm_l);
    analogWrite(PIN_PWM_RIGHT, pwm_r);
}

// Command Dispatcher
void dispatch_packet(const uint8_t* pkt, size_t len) {
    if (len < 1) return;
    last_cmd_ms = millis();

    uint8_t opcode = read_u8(pkt, 0);

    if (opcode == OP_ESTOP && len >= 2) {
        bool halt = (read_u8(pkt, 1) != 0);
        engage_hardware_estop(halt);
    } else if (opcode == OP_CMD_VEL && len >= 5) {
        int16_t linear_mm_s    = read_i16_le(pkt, 1);
        int16_t angular_mrad_s = read_i16_le(pkt, 3);
        apply_differential_drive(linear_mm_s, angular_mrad_s);
    } else if (opcode == OP_HEARTBEAT) {
        // Watchdog timer refreshed by last_cmd_ms above
    }
}

void setup() {
    pinMode(PIN_ESTOP_RELAY, OUTPUT);
    pinMode(PIN_PWM_LEFT, OUTPUT);
    pinMode(PIN_PWM_RIGHT, OUTPUT);
    pinMode(PIN_DIR_LEFT, OUTPUT);
    pinMode(PIN_DIR_RIGHT, OUTPUT);
    pinMode(PIN_STATUS_LED, OUTPUT);

    // Boot in fail-safe halted mode until Android StrongBox proximity arms the bus
    engage_hardware_estop(true);

    Serial.begin(SERIAL_BAUD);
    last_cmd_ms = millis();
}

void loop() {
    while (Serial.available() > 0) {
        uint8_t incoming = static_cast<uint8_t>(Serial.read());

        if (incoming == 0x00) {
            // End-of-frame delimiter reached
            if (rx_idx > 0) {
                uint8_t decoded[RX_BUF_SIZE];
                size_t dec_len = cobs_decode(rx_buf, rx_idx, decoded, RX_BUF_SIZE);
                if (dec_len > 0) {
                    dispatch_packet(decoded, dec_len);
                }
                rx_idx = 0;
            }
        } else if (rx_idx < RX_BUF_SIZE) {
            rx_buf[rx_idx++] = incoming;
        } else {
            // Buffer overflow protection: drop corrupted frame
            rx_idx = 0;
        }
    }

    // Hardware Safety Watchdog: auto-engage E-Stop if companion computer goes silent
    if (!estop_latched && (millis() - last_cmd_ms > WATCHDOG_MS)) {
        engage_hardware_estop(true);
    }
}
