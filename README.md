# Secure IoT Water Level Monitoring and Early Warning System
### Flood Management in Low-Resource Nations — South Sudan Case Study

**Author:** Deng Daniel Ayuen Kur  
**Roll No:** 240103002054  
**Programme:** Masters in Cybersecurity — Final Year Project

---

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Security Design](#security-design)
4. [Hardware Requirements](#hardware-requirements)
5. [Software Requirements](#software-requirements)
6. [Installation & Setup](#installation--setup)
7. [Deploying to GitHub + Render](#deploying-to-github--render)
8. [Sensor Firmware Deployment](#sensor-firmware-deployment)
9. [API Reference](#api-reference)
10. [Alert Thresholds](#alert-thresholds)
11. [Project Structure](#project-structure)

---

## System Overview

This system continuously monitors water levels at river stations, reservoirs, and drainage points using low-cost IoT hardware. When water levels rise above configurable thresholds, it automatically:

- Triggers visual and audible local alerts on the sensor node (LEDs + buzzer)
- Sends SMS alerts to emergency contacts via Twilio
- Sends email alerts to authorities via SMTP
- Updates the live web dashboard in real-time
- Stores all readings and events in a database for audit and analysis

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       SYSTEM ARCHITECTURE                        │
├─────────────┬──────────────┬──────────────┬──────────────────────┤
│  Layer 1    │   Layer 2    │   Layer 3    │      Layer 4         │
│  Sensing    │  Edge Node   │  Transport   │   Cloud / Server     │
│             │              │              │                      │
│ HC-SR04   │  ESP8266     │  Wi-Fi       │  Flask + SQLite      │
│ Ultrasonic  │  NodeMCU     │  HTTP POST   │  REST API            │
│ Sensor      │  (firmware)  │  + MQTT      │  WebSocket           │
└─────────────┴──────────────┴──────────────┴──────────────────────┘
                                                      │
                              ┌───────────────────────┤
                              │                       │
                    ┌─────────▼──────┐    ┌───────────▼──────────┐
                    │  Layer 5       │    │  Layer 6              │
                    │  Dashboard     │    │  Alert & Warning      │
                    │                │    │                       │
                    │  Web UI        │    │  SMS (Twilio)         │
                    │  Real-time     │    │  Email (SMTP)         │
                    │  Charts        │    │  Dashboard popup      │
                    │  Sensor status │    │  Siren / LEDs         │
                    └────────────────┘    └───────────────────────┘
```

### Water Level Calculation

The HC-SR04 sensor is mounted above the water surface, pointing down. It measures the **distance** from sensor face to the water surface:

```
Water Level (cm) = Sensor Height − Measured Distance
```

**Demo example:** Sensor mounted 35 cm above the container bottom (28 cm bucket + 7 cm gap above rim).  
If measured distance = 15 cm → Water Level = 35 − 15 = **20 cm** (WARNING zone)

---

## Security Design

This system implements multiple security layers as required for critical infrastructure:

| Mechanism | Implementation |
|-----------|---------------|
| **Transport security** | HTTPS/TLS support (configure with nginx reverse proxy) |
| **Sensor authentication** | Pre-shared API key (`X-API-Key` header) |
| **User authentication** | JWT access tokens (8 h) + refresh tokens |
| **Authorisation** | Role-based access control: `admin` → `operator` → `viewer` |
| **Rate limiting** | Flask-Limiter on all API endpoints |
| **Input validation** | Type and range checking on all incoming data |
| **SQL injection** | SQLAlchemy ORM parameterised queries only |
| **XSS prevention** | Server-side HTML escaping + JS `esc()` utility |
| **Audit logging** | All logins, sensor registrations, alert actions logged to DB |
| **Password hashing** | bcrypt via Werkzeug `generate_password_hash` |
| **CORS** | Configurable via `CORS_ORIGINS` env variable |

---

## Hardware Requirements

### Per sensor node

| Component | Model | Approx. Cost (USD) |
|-----------|-------|-------------------|
| Microcontroller | NodeMCU ESP8266 | $2–4 |
| Ultrasonic sensor | HC-SR04 | $1–3 |
| Green LED | 5mm | $0.05 |
| Yellow LED | 5mm | $0.05 |
| Red LED | 5mm | $0.05 |
| Piezo buzzer | Active 5V | $0.30 |
| Resistors (330Ω) | × 3 (LEDs) | $0.10 |
| Resistors (1 kΩ + 2 kΩ) | × 1 set (Echo voltage divider) | $0.05 |
| Power supply | 5V USB / solar | $2–10 |
| Weatherproof enclosure | IP65 box | $3–8 |
| **Total per node** | | **~$11–28** |

### Wiring Diagram

```
HC-SR04            NodeMCU ESP8266
───────            ───────────────
VCC  ───────────► Vin / 5V  (NOT 3.3V — HC-SR04 needs 5V supply)
GND  ───────────► GND
TRIG ───────────► D1 (GPIO5)
ECHO ──[1 kΩ]──► D2 (GPIO4)    ← VOLTAGE DIVIDER on Echo!
          |                       HC-SR04 Echo = 5V; ESP8266 GPIO = 3.3V max
       [2 kΩ]
          |
         GND

LEDs (via 330Ω resistors):
Green  ──────────► D5 (GPIO14)   SAFE
Yellow ──────────► D6 (GPIO12)   WARNING
Red    ──────────► D7 (GPIO13)   DANGER

Buzzer ──────────► D8 (GPIO15)
```

---

## Software Requirements

### Server
- Python 3.9+
- See `server/requirements.txt` for all packages

### Firmware
- Arduino IDE 2.x
- ESP8266 board package (`https://arduino.esp8266.com/stable/package_esp8266com_index.json`)
- Libraries:
  - `ArduinoJson` v6 (install via Library Manager)
  - `ESP8266WiFi` (bundled with ESP8266 board package)
  - `ESP8266HTTPClient` (bundled)

---

## Installation & Setup

### 1. Clone / download the project

```bash
cd /opt
git clone https://github.com/yourusername/flood-monitoring-system.git
cd flood-monitoring-system
```

### 2. Run the setup script

**Linux / macOS:**
```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

**Windows:**
```
scripts\setup.bat
```

The script will:
- Create a Python virtual environment
- Install all dependencies
- Copy `.env.example` → `.env`
- Print generated secret keys for you to paste into `.env`

### 3. Configure environment variables

Edit `server/.env`:

```dotenv
SECRET_KEY=<generated-key>
JWT_SECRET_KEY=<generated-key>
SENSOR_API_KEY=<generated-key>       # copy this to flood_sensor.ino

# Optional SMS alerts
TWILIO_ACCOUNT_SID=ACxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxx
TWILIO_FROM_NUMBER=+1XXXXXXXXXX
ALERT_PHONE_NUMBERS=+211912345678

# Optional email alerts
SMTP_USERNAME=youremail@gmail.com
SMTP_PASSWORD=your_app_password
ALERT_EMAILS=authority@juba.gov.ss
```

### 4. Start the server

```bash
cd server
source venv/bin/activate   # Windows: venv\Scripts\activate
python app.py
```

Server starts at `http://0.0.0.0:5000`

Open the dashboard at `http://YOUR_SERVER_IP:5000/`

**Default credentials:**  
Username: `admin`  
Password: `Admin@FloodWatch2025!`  
**Change the password immediately after first login.**

### 5. Production deployment (recommended)

Use `gunicorn` + `nginx` for production:

```bash
pip install gunicorn
gunicorn --worker-class gthread --workers 1 --threads 8 -b 0.0.0.0:5000 "app:create_app('production')"
```

Flask-SocketIO is configured with `async_mode="threading"` (see `app.py`), so
gunicorn's `gthread` worker is used instead of `eventlet`/`gevent` — no extra
async library or monkey-patching needed. Socket.IO falls back to HTTP
long-polling for real-time updates, which is sufficient for this system's
update frequency.

Configure nginx as a reverse proxy with SSL/TLS certificates (Let's Encrypt).

---

## Deploying to GitHub + Render

The project repo root is `flood-monitoring-system/`. It ships with a `render.yaml`
Blueprint so Render can build and run the Flask/Socket.IO server directly from
GitHub, with no manual dashboard configuration.

### 1. Push the code to GitHub

```bash
cd flood-monitoring-system
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/<your-username>/<your-repo>.git
git branch -M main
git push -u origin main
```

`.env`, the `venv/` folder, the SQLite database, and logs are excluded via
`.gitignore` — only source code is pushed.

### 2. Deploy on Render

1. Go to [render.com](https://dashboard.render.com) and sign in with GitHub.
2. Click **New +** → **Blueprint**, then select this repository.
3. Render reads `render.yaml` and provisions a **Web Service** with:
   - `rootDir: server`
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn --worker-class gthread --workers 1 --threads 8 -b 0.0.0.0:$PORT "app:create_app('production')"`
   - Auto-generated `SECRET_KEY`, `JWT_SECRET_KEY`, `SENSOR_API_KEY`
4. Click **Apply** — Render builds and deploys automatically. Every future
   `git push` to `main` triggers a new deploy.
5. Once live, your dashboard is at `https://<your-service-name>.onrender.com/`.
   Log in with the seeded admin account and **change the password immediately**.
6. Copy the deployed `SENSOR_API_KEY` (Render dashboard → service → Environment)
   into `flood_sensor.ino` so real sensors can authenticate against the
   hosted server instead of `localhost`.

### Important limitation: SQLite on Render's free tier

Render's free web services use an **ephemeral filesystem** — the SQLite
database resets on every deploy and periodically on restart/idle spin-down.
This is fine for demoing the system, but not for long-term data retention.
To persist data:

- Add a free **Render PostgreSQL** instance and set the `DATABASE_URL`
  environment variable to its connection string (no code changes needed —
  `config.py` already reads `DATABASE_URL` from the environment), **or**
- Upgrade to a paid Render plan and attach a persistent Disk mounted at
  the `server/` working directory.

### Alternatives to Render

Any host that can run a long-lived Python process works the same way
(`gunicorn --worker-class gthread --workers 1 --threads 8 ...`): Railway,
Fly.io, or a VPS with nginx as described above. **GitHub Pages will not
work** — it only serves static files and cannot run the Flask/SQLite/Socket.IO
backend.

---

## Sensor Firmware Deployment

### 1. Open in Arduino IDE

Open `firmware/flood_sensor/flood_sensor.ino`

### 2. Edit configuration constants

```cpp
const char* WIFI_SSID      = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD  = "YOUR_WIFI_PASSWORD";

// Local server on your LAN:
const char* SERVER_HOST    = "http://YOUR_SERVER_IP:5000";
// Deployed on Render (HTTPS only — see "Deploying to GitHub + Render" above):
// const char* SERVER_HOST = "https://YOUR-SERVICE.onrender.com";

const char* API_KEY        = "PASTE_SENSOR_API_KEY_FROM_.ENV";
const char* SENSOR_ID      = "SENSOR_001";      // unique per device
const char* SENSOR_LOCATION = "Station Name";
```

If pointing at Render (or any HTTPS endpoint), the sketch already uses
`BearSSL::WiFiClientSecure` with `setInsecure()` — the ESP8266 doesn't
validate the server's TLS certificate (not enough flash/RAM for a full CA
store). That's an accepted trade-off for a sensor with no confidential data;
pin Render's root CA instead if your threat model requires it. `HTTP_TIMEOUT_MS`
is also set generously (15 s, 4 retries) to tolerate Render's free-tier
cold start after idle spin-down.

Also set the physical installation height:
```cpp
#define SENSOR_HEIGHT_CM 300.0f   // actual height in cm above river bed
```

### 3. Adjust alert thresholds

```cpp
#define SAFE_DIST     200   // > 200 cm from sensor = SAFE
#define WARNING_DIST  100   // 100–200 cm = WARNING
#define DANGER_DIST    50   // < 50 cm = DANGER
```

### 4. Flash the firmware

Select: Tools → Board → ESP8266 Boards → **NodeMCU 1.0 (ESP-12E Module)**  
Select the correct COM port.  
Click Upload.

---

## API Reference

All dashboard API endpoints require `Authorization: Bearer <jwt_token>`.  
All sensor endpoints require `X-API-Key: <sensor_api_key>`.

### Sensor Data Submission (ESP8266 → Server)

```
POST /api/v1/reading
X-API-Key: <sensor_api_key>

{
  "sensor_id":   "SENSOR_001",
  "location":    "Nile River Station A",
  "distance":    145.5,
  "water_level": 154.5,
  "alert_level": 2,
  "rssi":        -65
}
```

### Authentication

```
POST /api/v1/auth/login
{"username": "admin", "password": "..."}
→ {"access_token": "...", "user": {...}}
```

### Dashboard Data

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/stats` | GET | System statistics |
| `/api/v1/readings` | GET | Historical readings (params: `sensor_id`, `hours`, `limit`) |
| `/api/v1/readings/latest` | GET | Latest reading per sensor |
| `/api/v1/sensors` | GET | List all sensors |
| `/api/v1/alerts` | GET | List alerts (param: `resolved=true/false`) |
| `/api/v1/alerts/<id>/acknowledge` | POST | Acknowledge an alert |
| `/api/v1/audit` | GET | Audit log (admin only) |

---

## Alert Thresholds

| Level | Condition | Action |
|-------|-----------|--------|
| **SAFE** (1) | Distance > 200 cm | Green LED on |
| **WARNING** (2) | Distance 100–200 cm | Yellow LED + slow beep + SMS + Email |
| **DANGER** (3) | Distance < 50 cm | Red LED + rapid beeps + SMS + Email |

Thresholds are configurable via `.env`:
```dotenv
SAFE_THRESHOLD=200
WARNING_THRESHOLD=100
DANGER_THRESHOLD=50
```

---

## Project Structure

```
flood-monitoring-system/
├── firmware/
│   └── flood_sensor/
│       └── flood_sensor.ino     # ESP8266 Arduino firmware
│
├── server/
│   ├── app.py                   # Flask app factory + all routes
│   ├── config.py                # Configuration classes
│   ├── models.py                # SQLAlchemy ORM models
│   ├── auth.py                  # JWT + API-key authentication
│   ├── alert_service.py         # SMS + Email alert dispatcher
│   ├── requirements.txt         # Python dependencies
│   ├── .env.example             # Environment variable template
│   │
│   ├── templates/
│   │   ├── base.html            # Base HTML template
│   │   ├── login.html           # Login page
│   │   └── dashboard.html       # Main monitoring dashboard
│   │
│   └── static/
│       ├── css/style.css        # Custom CSS
│       └── js/dashboard.js      # Dashboard JavaScript (Socket.IO + Chart.js)
│
└── scripts/
    ├── setup.sh                 # Linux/macOS setup
    └── setup.bat                # Windows setup
```

---

*FloodWatch IoT — Protecting communities through early warning technology*  
*South Sudan Flood Management Initiative — 2025*
