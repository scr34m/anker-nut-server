# Anker NUT Server

A Python-based NUT (Network UPS Tools) server that bridges Anker devices to Home Assistant via the standard NUT protocol. This allows you to monitor your Anker devices as UPS devices in Home Assistant.


## Quick Start

### 1. Clone and Setup

At least Pyton 3.12 is required because of [anker solix api](https://github.com/thomluther/anker-solix-api)
```bash
git clone https://github.com/scr34m/anker-nut-server.git
cd ecoflow-nut-server

git clone git@github.com:thomluther/anker-solix-api.git
```

### 2. Configure Your Devices
```bash
# For single device
cp config.example.json config.json
# Edit config.json with your device serial and credentials

# For multiple devices  
cp config_multi.example.json config_multi.json
# Edit config_multi.json with your devices
```

### 3. Install Dependencies
```bash
pip3 install -r requirements.txt
```

### 4. Start the Server
```bash
python3 simple_nut_server.py
```

## Home Assistant Integration

1. Install the **NUT** integration in Home Assistant
2. Configure it to connect to your Pi's IP: `YOUR_PI_IP:3493`
3. Add your Anker devices as UPS devices
4. Monitor battery status in HA dashboard

## 🔧 Configuration

```json
{
  "devices": [
    {
      "serial": "YOUR_DEVICE_SERIAL_1",
      "ups_name": "device_1_name"
    },
    {
      "serial": "YOUR_DEVICE_SERIAL_2", 
      "ups_name": "device_2_name"
    }
  ],
  "mqtt": {
    "username": "your_email@example.com",
    "password": "your_password",
    "country_code": "US"
  },
  "nut": {
    "host": "0.0.0.0",
    "port": 3493
  },
  "logging": {
    "level": "DEBUG",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  }
}
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
