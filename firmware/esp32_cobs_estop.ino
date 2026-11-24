#include <Arduino.h>
#include <cstdint>
#include <cstring>

// ============================================================================
// Kai-007 x Hidden-Robotics | ESP32-S3 Actuator, E-Stop & Telemetry Firmware
// Protocol: COBS-encoded binary frames @ 921600 bps (0x00 frame delimiter)
// ============================================================================

// Hardware Pin Definitions (ESP32-S3)
constexpr uint8_t  PIN_ESTOP_RELAY   = 21; // Active-LOW hardware E-Stop relay
constexpr uint8_t  PIN_PWM_LEFT      = 4;  // Left motor PWM speed
constexpr uint8_t  PIN_PWM_RIGHT     = 5;  // Right motor PWM speed
constexpr uint8_t  PIN_DIR_LEFT      = 6;  // Left motor direction (HIGH = fwd, LOW = rev)
constexpr uint8_t  PIN_DIR_RIGHT     = 7;  // Right motor direction (HIGH = fwd, LOW = rev)
constexpr uint8_t  PIN_STATUS_LED    = 2;  // Onboard status indicator
constexpr uint8_t  PIN_BATT_ADC      = 1;  // ADC1_CH0 battery voltage divider input

// Voltage Divider Calibration (e.g., 100k / 20k divider -> scale = 6.0)
constexpr float    BATT_DIVIDER_MULT = 6.0f;

// Serial, Watchdog & Telemetry Timing
constexpr uint32_t SERIAL_BAUD       = 921600;
constexpr uint32_t WATCHDOG_MS       = 250;
constexpr uint32_t TELEMETRY_MS      = 100; // 10 Hz telemetry stream
constexpr size_t   RX_BUF_SIZE       = 64;

// Binary Protocol Opcodes
constexpr uint8_t  OP_CMD_VEL        = 0x01; // Host -> MCU: [0x01, int16 linear_mm_s, int16 angular_mrad_s]
constexpr uint8_t  OP_HEARTBEAT      = 0x02; // Host -> MCU: [0x02]
constexpr uint8_t  OP_TELEMETRY      = 0x10; // MCU -> Host: [0x10, uint16 batt_mv, uint8 estop, uint8 pwm_l, uint8 pwm_r]
constexpr uint8_t  OP_ESTOP          = 0xFF; // Host -> MCU: [0xFF, uint8 halt (1 = HALT, 0 = ARM)]

// Runtime State
uint8_t  rx_buf[RX_BUF_SIZE];
size_t   rx_idx        = 0;
bool     estop_latched = true; // Always boot in safe halted state
uint8_t  cur_pwm_left  = 0;
uint8_t  cur_pwm_right = 0;
uint32_t last_cmd_ms   = 0;
uint32_t last_telem_ms = 0;

// Safe unaligned little-endian byte readers
static inline uint8_t read_u8(const uint8_t* buf, size_t offset) {
    return *(buf + offset);
}

static inline int16_t read_i16_le(const uint8_t* buf, size_t offset) {
    uint16_t lo = static_cast<uint16_t>(*(buf + offset));
    uint16_t hi = static_cast<uint16_t>(*(buf + offset + 1));
    return static_cast<int16_t>(lo | (hi << 8));
}

// Consistent Overhead Byte Stuffing (COBS) Encoder (MCU -> Host)
size_t cobs_encode(const uint8_t* src, size_t len, uint8_t* dst) {
    size_t read_idx  = 0;
    size_t write_idx = 1;
    size_t code_idx  = 0;
    uint8_t code     = 1;

    while (read_idx < len) {
        uint8_t b = *(src + read_idx++);
        if (b == 0x00) {
            *(dst + code_idx) = code;
            code_idx = write_idx++;
            code = 1;
        } else {
            *(dst + write_idx++) = b;
            code++;
            if (code == 0xFF) {
                *(dst + code_idx) = code;
                code_idx = write_idx++;
                code = 1;
            }
        }
    }
    *(dst + code_idx) = code;
    *(dst + write_idx++) = 0x00; // Frame delimiter
    return write_idx;
}

// Consistent Overhead Byte Stuffing (COBS) Decoder (Host -> MCU)
size_t cobs_decode(const uint8_t* src, size_t len, uint8_t* dst, size_t max_dst) {
    size_t read_idx  = 0;
    size_t write_idx = 0;

    while (read_idx < len) {
        uint8_t code = *(src + read_idx);
        if (code == 0 || read_idx + code > len + 1) {
            return 0;
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
    digitalWrite(PIN_ESTOP_RELAY, halt ? LOW : HIGH);
    digitalWrite(PIN_STATUS_LED, halt ? LOW : HIGH);

    if (halt) {
        cur_pwm_left  = 0;
        cur_pwm_right = 0;
        analogWrite(PIN_PWM_LEFT, 0);
        analogWrite(PIN_PWM_RIGHT, 0);
    }
}

// Differential Drive Mixer
void apply_differential_drive(int16_t linear_mm_s, int16_t angular_mrad_s) {
    if (estop_latched) {
        cur_pwm_left  = 0;
        cur_pwm_right = 0;
        analogWrite(PIN_PWM_LEFT, 0);
        analogWrite(PIN_PWM_RIGHT, 0);
        return;
    }

    int32_t left_cmd  = (static_cast<int32_t>(linear_mm_s) - (static_cast<int32_t>(angular_mrad_s) / 4)) / 4;
    int32_t right_cmd = (static_cast<int32_t>(linear_mm_s) + (static_cast<int32_t>(angular_mrad_s) / 4)) / 4;

    digitalWrite(PIN_DIR_LEFT,  left_cmd >= 0 ? HIGH : LOW);
    digitalWrite(PIN_DIR_RIGHT, right_cmd >= 0 ? HIGH : LOW);

    cur_pwm_left  = static_cast<uint8_t>(constrain(abs(left_cmd), 0, 255));
    cur_pwm_right = static_cast<uint8_t>(constrain(abs(right_cmd), 0, 255));

    analogWrite(PIN_PWM_LEFT, cur_pwm_left);
    analogWrite(PIN_PWM_RIGHT, cur_pwm_right);
}

// Transmit 10 Hz Battery & Actuator Telemetry Frame
void send_telemetry_frame() {
    uint32_t pin_mv  = analogReadMilliVolts(PIN_BATT_ADC);
    uint16_t batt_mv = static_cast<uint16_t>(pin_mv * BATT_DIVIDER_MULT);

    uint8_t raw[6];
    *(raw + 0) = OP_TELEMETRY;
    *(raw + 1) = static_cast<uint8_t>(batt_mv & 0xFF);
    *(raw + 2) = static_cast<uint8_t>((batt_mv >> 8) & 0xFF);
    *(raw + 3) = estop_latched ? 1 : 0;
    *(raw + 4) = cur_pwm_left;
    *(raw + 5) = cur_pwm_right;

    uint8_t encoded[12];
    size_t enc_len = cobs_encode(raw, sizeof(raw), encoded);
    Serial.write(encoded, enc_len);
}

// Command Dispatcher
void dispatch_packet(const uint8_t* pkt, size_t len) {
    if (len < 1) return;
    last_cmd_ms = millis();

    uint8_t opcode = read_u8(pkt, 0);

    if (opcode == OP_ESTOP && len >= 2) {
        engage_hardware_estop(read_u8(pkt, 1) != 0);
    } else if (opcode == OP_CMD_VEL && len >= 5) {
        int16_t linear_mm_s    = read_i16_le(pkt, 1);
        int16_t angular_mrad_s = read_i16_le(pkt, 3);
        apply_differential_drive(linear_mm_s, angular_mrad_s);
    } else if (opcode == OP_HEARTBEAT) {
        // Watchdog timer refreshed
    }
}

void setup() {
    pinMode(PIN_ESTOP_RELAY, OUTPUT);
    pinMode(PIN_PWM_LEFT, OUTPUT);
    pinMode(PIN_PWM_RIGHT, OUTPUT);
    pinMode(PIN_DIR_LEFT, OUTPUT);
    pinMode(PIN_DIR_RIGHT, OUTPUT);
    pinMode(PIN_STATUS_LED, OUTPUT);
    pinMode(PIN_BATT_ADC, INPUT);

    engage_hardware_estop(true);

    Serial.begin(SERIAL_BAUD);
    last_cmd_ms   = millis();
    last_telem_ms = millis();
}

void loop() {
    while (Serial.available() > 0) {
        uint8_t incoming = static_cast<uint8_t>(Serial.read());

        if (incoming == 0x00) {
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
            rx_idx = 0;
        }
    }

    uint32_t now = millis();

    // Hardware Safety Watchdog
    if (!estop_latched && (now - last_cmd_ms > WATCHDOG_MS)) {
        engage_hardware_estop(true);
    }

    // 10 Hz Telemetry Stream
    if (now - last_telem_ms >= TELEMETRY_MS) {
        last_telem_ms = now;
        send_telemetry_frame();
    }
}
