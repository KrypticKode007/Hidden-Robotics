#include <Arduino.h>
#include <cstdint>
#include <cstring>

// Hardware Pin Definitions (ESP32-S3)
constexpr uint8_t PIN_ESTOP_RELAY = 21; // Active-LOW hardware E-Stop relay
constexpr uint8_t PIN_PWM_LEFT    = 4;
constexpr uint8_t PIN_PWM_RIGHT   = 5;
constexpr uint32_t SERIAL_BAUD    = 921600;
constexpr uint32_t WATCHDOG_MS    = 250;

// Protocol Opcodes
constexpr uint8_t OP_CMD_VEL = 0x01; // [0x01, int16_le linear_mm_s, int16_le angular_mrad_s]
constexpr uint8_t OP_ESTOP   = 0xFF; // [0xFF, uint8_t engage (1 = HALT, 0 = ARM)]

uint8_t rx_buf[128];
size_t rx_idx = 0;
bool estop_latched = true; // Boot in safe halted state
uint32_t last_cmd_ms = 0;

// Consistent Overhead Byte Stuffing (COBS) Decoder
size_t cobs_decode(const uint8_t* src, size_t len, uint8_t* dst) {
    size_t read_idx = 0, write_idx = 0;
    while (read_idx < len) {
        uint8_t code = src[read_idx];
        if (code == 0 || read_idx + code > len + 1) return 0;
        read_idx++;
        for (uint8_t i = 1; i < code; i++) {
            dst[write_idx++] = src[read_idx++];
        }
        if (code != 0xFF && read_idx < len) {
            dst[write_idx++] = 0x00;
        }
    }
    return write_idx;
}

void engage_hardware_estop(bool halt) {
    estop_latched = halt;
    // Active-LOW: LOW = Cut motor power / engage brakes, HIGH = Armed
    digitalWrite(PIN_ESTOP_RELAY, halt ? LOW : HIGH);
    if (halt) {
        analogWrite(PIN_PWM_LEFT, 0);
        analogWrite(PIN_PWM_RIGHT, 0);
    }
}

void apply_differential_drive(int16_t linear_mm_s, int16_t angular_mrad_s) {
    if (estop_latched) return;

    // Simple differential mixing (scale to 0-255 PWM magnitude)
    int32_t left  = (linear_mm_s - (angular_mrad_s / 4)) / 4;
    int32_t right = (linear_mm_s + (angular_mrad_s / 4)) / 4;

    analogWrite(PIN_PWM_LEFT,  constrain(abs(left), 0, 255));
    analogWrite(PIN_PWM_RIGHT, constrain(abs(right), 0, 255));
}

void dispatch_packet(const uint8_t* pkt, size_t len) {
    if (len < 1) return;
    last_cmd_ms = millis();

    if (pkt[0] == OP_ESTOP && len >= 2) {
        engage_hardware_estop(pkt[1] != 0);
    } else if (pkt[0] == OP_CMD_VEL && len >= 5) {
        int16_t linear  = static_cast<int16_t>(pkt[1] | (pkt[2] << 8));
        int16_t angular = static_cast<int16_t>(pkt[3] | (pkt[4] << 8));
        apply_differential_drive(linear, angular);
    }
}

void setup() {
    pinMode(PIN_ESTOP_RELAY, OUTPUT);
    pinMode(PIN_PWM_LEFT, OUTPUT);
    pinMode(PIN_PWM_RIGHT, OUTPUT);
    engage_hardware_estop(true); // Fail-safe at boot

    Serial.begin(SERIAL_BAUD);
}

void loop() {
    while (Serial.available() > 0) {
        uint8_t b = static_cast<uint8_t>(Serial.read());
        if (b == 0x00) { // COBS frame delimiter
            if (rx_idx > 0) {
                uint8_t decoded[128];
                size_t dec_len = cobs_decode(rx_buf, rx_idx, decoded);
                if (dec_len > 0) dispatch_packet(decoded, dec_len);
                rx_idx = 0;
            }
        } else if (rx_idx < sizeof(rx_buf)) {
            rx_buf[rx_idx++] = b;
        } else {
            rx_idx = 0; // Overflow reset
        }
    }

    // Hardware safety watchdog: auto-halt if companion node stops heartbeating
    if (!estop_latched && (millis() - last_cmd_ms > WATCHDOG_MS)) {
        engage_hardware_estop(true);
    }
}
