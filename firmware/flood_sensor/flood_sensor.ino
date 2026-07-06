/*
 * ============================================================
 *  Secure IoT Water Level Monitoring System — Sensor Firmware
 * ============================================================
 *  Author    : Deng Daniel Ayuen Kur
 *  Roll No   : 240103002054
 *  Hardware  : NodeMCU ESP8266 + HC-SR04 Ultrasonic Sensor
 *  Project   : Masters in Cybersecurity — Final Year Project
 *  Demo Mode : Tuned for a small water container (~30 cm deep)
 * ============================================================
 *
 *  Wiring:
 *    HC-SR04 VCC  -> Vin / 5V pin  (NOT 3.3V — sensor needs 5V)
 *    HC-SR04 GND  -> GND
 *    HC-SR04 TRIG -> D1 (GPIO5)
 *
 *    HC-SR04 ECHO -> [1 kΩ] -> D2 (GPIO4)  ← VOLTAGE DIVIDER REQUIRED
 *                                  |
 *                               [2 kΩ]         Echo outputs 5V;
 *                                  |            divider brings it to ~3.3V
 *                                 GND           safe for ESP8266 GPIO.
 *
 *    Green  LED  -> D5 (GPIO14) via 330Ω resistor   (SAFE)
 *    Yellow LED  -> D6 (GPIO12) via 330Ω resistor   (WARNING)
 *    Red    LED  -> D7 (GPIO13) via 330Ω resistor   (DANGER)
 *    Buzzer      -> D8 (GPIO15)
 *
 *  IMPORTANT — Serial Monitor baud:
 *    This sketch uses Serial.begin(115200). Set the Arduino
 *    Serial Monitor to 115200 baud to read the output. (The
 *    "9600" printed on the board refers to its factory test
 *    firmware, not to your own sketches.)
 *
 *  Required Libraries (install via Arduino Library Manager):
 *    - ESP8266WiFi       (bundled with ESP8266 board package)
 *    - ESP8266HTTPClient (bundled)
 *    - ArduinoJson       v6.x  (by Benoit Blanchon)
 * ============================================================
 */

#include <ESP8266WiFi.h>
#include <WiFiClientSecureBearSSL.h>
#include <ESP8266HTTPClient.h>
#include <ArduinoJson.h>

// ─── Wi-Fi Configuration ────────────────────────────────────
const char* WIFI_SSID      = "Deng";       // <-- CHANGE
const char* WIFI_PASSWORD  = "dengayuen";   // <-- CHANGE

// ─── Server Configuration ───────────────────────────────────
// Render serves HTTPS only — use your deployed URL, no trailing slash.
const char* SERVER_HOST     = "https://flood-monitoring-system.onrender.com";  // <-- CHANGE to your Render URL
const char* API_ENDPOINT    = "/api/v1/reading";
const char* API_KEY         = "PASTE_SENSOR_API_KEY_FROM_RENDER_DASHBOARD"; // <-- CHANGE (Render dashboard -> service -> Environment)
const char* SENSOR_ID       = "Juba Bridge";
const char* SENSOR_LOCATION = "Juba Bridge Simulation — IoT Lab, South Sudan";

// ─── Pin Definitions ────────────────────────────────────────
#define TRIG_PIN    D1   // HC-SR04 trigger
#define ECHO_PIN    D2   // HC-SR04 echo  (via 1kΩ + 2kΩ voltage divider)
#define LED_SAFE    D5   // Green  LED
#define LED_WARNING D6   // Yellow LED
#define LED_DANGER  D7   // Red    LED
#define BUZZER_PIN  D8   // Piezo buzzer

// ─── Alert Thresholds (distance from sensor face in cm) ─────
//  DEMO MODE: tuned for a ~30 cm deep bucket/basin.
//  Mount the sensor ~5 cm above the container rim, pointing down.
//  Total sensor-face to container-bottom distance ≈ 35 cm.
//
//  Fill level vs distance from sensor:
//    Empty  : ~35 cm  →  SAFE
//    ~half  : ~20 cm  →  SAFE / borderline
//    ~2/3   : ~13 cm  →  WARNING
//    ~80%+  :  <7 cm  →  DANGER
//
//  Smaller distance = higher water = more dangerous.
//
//  Two thresholds fully define the three bands:
//    dist >  SAFE_DIST            → SAFE
//    DANGER_DIST <= dist <= SAFE_DIST → WARNING
//    dist <  DANGER_DIST          → DANGER
#define SAFE_DIST     20    // > 20 cm → SAFE    (water below half)
#define DANGER_DIST    7    // < 7 cm  → DANGER  (~80%+ full)

// ─── Sensor Installation Height ─────────────────────────────
//  Measure your actual setup:
//    container depth (cm) + gap from sensor to rim (cm) = this value
//  Example: 28 cm bucket + 7 cm above rim = 35 cm
#define SENSOR_HEIGHT_CM  35.0f

// ─── Timing ─────────────────────────────────────────────────
#define READING_INTERVAL_MS    3000UL   // reading every 3 s (demo-friendly)
#define WIFI_TIMEOUT_MS       30000UL   // 30 s Wi-Fi connect timeout
// Render's free tier spins the service down after ~15 min idle and can take
// 30-50 s to wake on the next request — allow generous timeout + retries.
#define HTTP_TIMEOUT_MS       15000     // 15 s HTTP request timeout
#define MAX_RETRIES               4

// ─── Globals ────────────────────────────────────────────────
float          g_lastDistance    = -1.0f;
int            g_alertLevel      = 0;
unsigned long  g_lastReadingTime = 0;
unsigned long  g_lastReconnTime  = 0;
BearSSL::WiFiClientSecure g_wifiClient;

// ============================================================
//  SETUP
// ============================================================
void setup() {
    Serial.begin(115200);
    Serial.println(F("\n===================================="));
    Serial.println(F("  IoT Flood Monitoring System v1.0"));
    Serial.println(F("  Deng Daniel Ayuen Kur  240103002054"));
    Serial.println(F("  Hardware: ESP8266 + HC-SR04  [DEMO]"));
    Serial.println(F("====================================\n"));

    pinMode(TRIG_PIN,    OUTPUT);
    pinMode(ECHO_PIN,    INPUT);
    pinMode(LED_SAFE,    OUTPUT);
    pinMode(LED_WARNING, OUTPUT);
    pinMode(LED_DANGER,  OUTPUT);
    pinMode(BUZZER_PIN,  OUTPUT);

    // Boot-safe: force all outputs low immediately.
    // GPIO15 (D8) in particular must be LOW at startup.
    setAllLEDs(LOW);
    digitalWrite(BUZZER_PIN, LOW);

    runSelfTest();
    connectWiFi();

    // ESP8266 lacks the flash/RAM to maintain a full CA trust store, so we
    // skip certificate validation for the outbound HTTPS connection to
    // Render. This trusts the network path, not the cert chain — acceptable
    // for a sensor with no confidential data, but not a general-purpose
    // pattern. Pin Render's Let's Encrypt root CA instead if that matters
    // for your threat model.
    g_wifiClient.setInsecure();
}

// ============================================================
//  LOOP
// ============================================================
void loop() {
    unsigned long now = millis();

    // Reconnect Wi-Fi if lost
    if (WiFi.status() != WL_CONNECTED) {
        if (now - g_lastReconnTime >= WIFI_TIMEOUT_MS) {
            Serial.println(F("[WiFi] Connection lost — reconnecting..."));
            connectWiFi();
            g_lastReconnTime = now;
        }
    }

    // Periodic measurement
    if (now - g_lastReadingTime >= READING_INTERVAL_MS) {
        g_lastReadingTime = now;
        takeMeasurement();
    }
}

// ============================================================
//  SELF TEST — blink all LEDs and beep twice on boot
// ============================================================
void runSelfTest() {
    Serial.println(F("[SYSTEM] Running self-test..."));
    for (int pin : {(int)LED_SAFE, (int)LED_WARNING, (int)LED_DANGER}) {
        digitalWrite(pin, HIGH);
        delay(350);
        digitalWrite(pin, LOW);
    }
    // Two short beeps — active buzzer: HIGH = on, LOW = off
    digitalWrite(BUZZER_PIN, HIGH); delay(150);
    digitalWrite(BUZZER_PIN, LOW);  delay(100);
    digitalWrite(BUZZER_PIN, HIGH); delay(150);
    digitalWrite(BUZZER_PIN, LOW);
    Serial.println(F("[SYSTEM] Self-test passed"));
}

// ============================================================
//  WI-FI CONNECTION (with network scan diagnostics)
//  The scan prints every visible 2.4 GHz network so you can
//  confirm the SSID is actually reachable. If your network
//  never appears in the list, it is broadcasting on 5 GHz
//  (ESP8266 cannot see 5 GHz) or is out of range / asleep.
//
//  Timeout status codes (WiFi.status()):
//    0 = idle          1 = SSID not found (wrong name / 5 GHz)
//    4 = connect fail  6 = wrong password
// ============================================================
void connectWiFi() {
    Serial.println(F("[WiFi] Scanning for networks..."));
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    delay(100);

    int n = WiFi.scanNetworks();
    if (n == 0) {
        Serial.println(F("[WiFi] No networks found at all!"));
    } else {
        for (int i = 0; i < n; i++) {
            Serial.printf("  found: '%s'  ch%d  %d dBm  %s\n",
                          WiFi.SSID(i).c_str(),
                          WiFi.channel(i),
                          WiFi.RSSI(i),
                          (WiFi.encryptionType(i) == ENC_TYPE_NONE) ? "open" : "secured");
        }
    }

    Serial.printf("[WiFi] Connecting to '%s'...\n", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long t0 = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - t0 > WIFI_TIMEOUT_MS) {
            Serial.printf("\n[WiFi] Timed out — operating offline. Status code: %d\n",
                          WiFi.status());
            return;
        }
        delay(500);
        Serial.print(F("."));
    }
    Serial.printf("\n[WiFi] Connected!  IP: %s  RSSI: %d dBm\n",
                  WiFi.localIP().toString().c_str(),
                  WiFi.RSSI());
}

// ============================================================
//  MEASURE DISTANCE — average of 3 valid pulses
//  HC-SR04: 10 µs trigger / echo protocol.  Range: 2–400 cm.
//  NOT waterproof — keep electronics dry.
// ============================================================
float measureDistance() {
    float total      = 0.0f;
    int   validCount = 0;

    for (int i = 0; i < 3; i++) {
        // Clean 10 µs trigger pulse
        digitalWrite(TRIG_PIN, LOW);
        delayMicroseconds(4);
        digitalWrite(TRIG_PIN, HIGH);
        delayMicroseconds(10);
        digitalWrite(TRIG_PIN, LOW);

        // Wait for echo (30 ms timeout ≈ 5 m)
        long dur = pulseIn(ECHO_PIN, HIGH, 30000UL);
        if (dur == 0) continue;

        float d = (dur * 0.0343f) / 2.0f;   // cm
        if (d >= 2.0f && d <= 300.0f) {      // HC-SR04 practical max ~300 cm
            total += d;
            validCount++;
        }
        delay(80);   // inter-pulse gap to avoid echo overlap
    }

    if (validCount == 0) {
        Serial.println(F("[SENSOR] No valid echo — check wiring & voltage divider"));
        return -1.0f;
    }
    return total / (float)validCount;
}

// ============================================================
//  DETERMINE ALERT LEVEL
//    dist <  DANGER_DIST          → 3 DANGER
//    dist <  SAFE_DIST            → 2 WARNING
//    else                        → 1 SAFE
// ============================================================
int determineAlertLevel(float dist) {
    if (dist < DANGER_DIST)  return 3;   // DANGER
    if (dist < SAFE_DIST)    return 2;   // WARNING
    return 1;                            // SAFE
}

// ============================================================
//  WATER LEVEL FROM DISTANCE
// ============================================================
float distanceToWaterLevel(float dist) {
    float level = SENSOR_HEIGHT_CM - dist;
    return (level < 0.0f) ? 0.0f : level;
}

// ============================================================
//  UPDATE LEDs + BUZZER
// ============================================================
void updateIndicators(int level) {
    setAllLEDs(LOW);
    digitalWrite(BUZZER_PIN, LOW);   // ensure buzzer off (active buzzer)

    if (level == 1) {
        digitalWrite(LED_SAFE, HIGH);

    } else if (level == 2) {
        digitalWrite(LED_WARNING, HIGH);
        // Single warning beep — active buzzer: HIGH = on
        digitalWrite(BUZZER_PIN, HIGH); delay(300);
        digitalWrite(BUZZER_PIN, LOW);

    } else if (level == 3) {
        digitalWrite(LED_DANGER, HIGH);
        // Three rapid danger beeps
        for (int i = 0; i < 3; i++) {
            digitalWrite(BUZZER_PIN, HIGH); delay(180);
            digitalWrite(BUZZER_PIN, LOW);  delay(170);
        }
    }
}

void setAllLEDs(int state) {
    digitalWrite(LED_SAFE,    state);
    digitalWrite(LED_WARNING, state);
    digitalWrite(LED_DANGER,  state);
}

// ============================================================
//  TAKE MEASUREMENT + SEND TO SERVER
// ============================================================
void takeMeasurement() {
    float dist = measureDistance();
    if (dist < 0.0f) return;

    float waterLevel = distanceToWaterLevel(dist);
    int   alertLevel = determineAlertLevel(dist);

    const char* labels[] = {"", "SAFE", "WARNING", "DANGER"};
    Serial.println(F("─── Water Level Reading ────────────────"));
    Serial.printf("  Distance    : %.2f cm\n",  dist);
    Serial.printf("  Water Level : %.2f cm\n",  waterLevel);
    Serial.printf("  Alert Level : %s (%d)\n",  labels[alertLevel], alertLevel);
    Serial.printf("  WiFi RSSI   : %d dBm\n",   WiFi.RSSI());
    Serial.println(F("────────────────────────────────────────"));

    updateIndicators(alertLevel);
    g_lastDistance = dist;
    g_alertLevel   = alertLevel;

    if (WiFi.status() == WL_CONNECTED) {
        sendReading(dist, waterLevel, alertLevel);
    } else {
        Serial.println(F("[HTTP] Offline — reading not sent"));
    }
}

// ============================================================
//  SEND READING TO SERVER (with retry + API-key auth)
// ============================================================
void sendReading(float distance, float waterLevel, int alertLevel) {
    String url = String(SERVER_HOST) + String(API_ENDPOINT);

    StaticJsonDocument<256> doc;
    doc["sensor_id"]   = SENSOR_ID;
    doc["location"]    = SENSOR_LOCATION;
    doc["distance"]    = round(distance   * 100.0f) / 100.0f;
    doc["water_level"] = round(waterLevel * 100.0f) / 100.0f;
    doc["alert_level"] = alertLevel;
    doc["rssi"]        = WiFi.RSSI();
    String payload;
    serializeJson(doc, payload);

    for (int attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        HTTPClient http;
        http.begin(g_wifiClient, url);
        http.addHeader(F("Content-Type"), F("application/json"));
        http.addHeader(F("X-API-Key"),    API_KEY);
        http.addHeader(F("X-Sensor-ID"),  SENSOR_ID);
        http.setTimeout(HTTP_TIMEOUT_MS);

        int code = http.POST(payload);
        http.end();

        if (code == 200 || code == 201) {
            Serial.printf("[HTTP] OK (attempt %d) → HTTP %d\n", attempt, code);
            return;
        }
        Serial.printf("[HTTP] Failed (attempt %d/%d) → HTTP %d\n",
                      attempt, MAX_RETRIES, code);
        if (attempt < MAX_RETRIES) delay(3000);
    }
    Serial.println(F("[HTTP] All retries exhausted."));
}
