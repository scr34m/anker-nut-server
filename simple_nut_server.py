#!/usr/bin/env python3
"""
Simplified NUT server that directly parses Anker MQTT data.
"""

import asyncio
import logging
import os
import time
from typing import Dict, Any, List, Optional
import socket
import threading
import mqtt_monitor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
LOG = logging.getLogger(__name__)


class SimpleAnkerNUTServer:
    def __init__(self, devices: List[Dict[str, str]], anker: Dict[str, Any], nut_config: Dict[str, Any]):
        self.devices = devices
        self.anker = anker
        self.nut_server = None
        self.ups_data = {}
        self.running = False

        # NUT server configuration
        self.nut_host = nut_config["host"]
        self.nut_port = nut_config["port"]

    def start_mqtt_monitor(self):
        serials = [device["serial"] for device in self.devices]

        monitor = mqtt_monitor.AnkerMqttMonitor(
            self.anker["username"], self.anker["password"], self.anker["country_code"])
        asyncio.create_task(monitor.main(
            serials, msg_callback=self.update_ups_data))

    def start_nut_server(self):
        """Start the NUT server."""
        LOG.info("🚀 Starting NUT server...")

        # Create server socket
        self.nut_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.nut_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.nut_server.bind((self.nut_host, self.nut_port))
            self.nut_server.listen(5)
            LOG.info(
                f"✅ NUT server listening on {self.nut_host}:{self.nut_port}")

            self.running = True

            # Start server in background thread
            server_thread = threading.Thread(
                target=self._run_nut_server, daemon=True)
            server_thread.start()

        except Exception as e:
            LOG.error(f"❌ Failed to start NUT server: {e}")
            raise

    # see https://github.com/foxthefox/ioBroker.ecoflow-mqtt/blob/main/doc/devices/river3plus.md
    # https://networkupstools.org/docs/developer-guide.chunked/_variables.html
    def update_ups_data(self, serial: str, data: Dict[str, Any]):
        """Update UPS data from parsed message."""

        LOG.info(data)
        
        serial_to_ups = {d["serial"]: d["ups_name"] for d in self.devices}
        ups_name = serial_to_ups.get(serial)

        # Initialize UPS data if not exists
        if ups_name not in self.ups_data:
            self.ups_data[ups_name] = {}

        self.ups_data[ups_name]["ups.realpower"] = data.get("output_power_total", 0) # ac_output_power
        self.ups_data[ups_name]["input.realpower"] = data.get("grid_to_battery_power", 0)

        self.ups_data[ups_name]["battery.charge"] = data.get("main_battery_soc", 0)

        self.ups_data[ups_name]["battery.temperature"] = data.get("temperature", 0)

        # so so calculation
        self.ups_data[ups_name]["battery.runtime"] = int(data.get("remaining_time_hours", 0) * 3600)

        self.ups_data[ups_name]["battery.status"] = "CHRG" # ONBATT TODO

        # Set timestamp
        self.ups_data[ups_name]["ups.timestamp"] = int(time.time())

        self.ups_data[ups_name]["ups.status"] = "OL" # OB  TODO

    def _run_nut_server(self):
        """Run the NUT server loop."""
        while self.running:
            try:
                client_socket, address = self.nut_server.accept()
                LOG.info(f"📡 NUT client connected from {address}")

                # Handle client in separate thread
                client_thread = threading.Thread(
                    target=self._handle_nut_client,
                    args=(client_socket,),
                    daemon=True
                )
                client_thread.start()

            except Exception as e:
                if self.running:
                    LOG.error(f"❌ NUT server error: {e}")

    def _handle_nut_client(self, client_socket):
        """Handle NUT client requests."""
        try:
            while self.running:
                # Read command from client
                data = client_socket.recv(1024)
                if not data:
                    break

                command = data.decode().strip()
                LOG.debug(f"📨 NUT command: {command}")

                # Process NUT commands
                response = self._process_nut_command(command)

                # Send response
                if response:
                    client_socket.send(response.encode())
                    LOG.debug(f"📤 NUT response: {response}")

        except Exception as e:
            LOG.error(f"❌ NUT client error: {e}")
        finally:
            client_socket.close()

    # https://networkupstools.org/docs/developer-guide.chunked/net-protocol.html
    def _process_nut_command(self, command: str) -> Optional[str]:
        """Process NUT protocol commands."""
        if command == "LIST UPS":
            # List all UPS devices
            ups_list = []
            for device in self.devices:
                ups_name = device["ups_name"]
                ups_list.append(f"UPS {ups_name} \"Anker C1000\"")
            return f"BEGIN LIST UPS\n" + "\n".join(ups_list) + "\nEND LIST UPS\n"

        elif command.startswith("LIST VAR "):
            # Extract UPS name from command
            ups_name = command.split("LIST VAR ")[1]
            if ups_name in self.ups_data:
                return self._get_ups_variables(ups_name)
            else:
                return f"ERR UNKNOWN-UPS\n"

        elif command.startswith("GET VAR "):
            # Extract UPS name and variable from command
            parts = command.split(" ")
            if len(parts) >= 4:
                ups_name = parts[2]
                var_name = parts[3]
                if ups_name in self.ups_data:
                    value = self.ups_data[ups_name].get(var_name, 0)
                    if isinstance(value, float):
                        return f"VAR {ups_name} {var_name} {value:.1f}\n"
                    else:
                        return f"VAR {ups_name} {var_name} {value}\n"
                else:
                    return f"ERR UNKNOWN-UPS\n"

        elif command.startswith("GET TYPE "):
            parts = command.split(" ")
            if len(parts) >= 4:
                ups_name = parts[2]
                var_name = parts[3]
                return f"TYPE {ups_name} {var_name} \"NUMBER\"\n"

        elif command.startswith("GET DESC "):
            parts = command.split(" ")
            if len(parts) >= 4:
                ups_name = parts[2]
                var_name = parts[3]
                return f"DESC {ups_name} {var_name} \"Not implemented\"\n"

        elif command.startswith("LIST CMD"):
            parts = command.split(" ")
            if len(parts) == 3:
                ups_name = parts[2]
                return f"BEGIN LIST CMD {ups_name}\n" + f"END LIST CMD {ups_name}\n"

        elif command.startswith("GET UPSDESC"):
            parts = command.split(" ")
            if len(parts) == 3:
                ups_name = parts[2]
                return f"UPSDESC {ups_name} \"Not implemented\"\n"

        elif command == "USERNAME admin":
            return "OK\n"

        elif command == "PASSWORD admin":
            return "OK\n"

        elif command == "LOGIN":
            return "OK\n"

        elif command == "LOGOUT":
            return "OK\n"

        else:
            LOG.debug(f"Unknown NUT command: {command}")
            return None

    def _get_ups_variables(self, ups_name: str) -> str:
        """Get all UPS variables in NUT format."""
        if ups_name not in self.ups_data:
            return f"ERR UNKNOWN-UPS\n"

        data = self.ups_data[ups_name]
        variables = [
            f"VAR {ups_name} battery.charge \"{data.get('battery.charge', 0)}\"",
            f"VAR {ups_name} battery.temperature \"{data.get('battery.temperature', 0)}\"",
            f"VAR {ups_name} battery.runtime \"{data.get('battery.runtime', 0)}\"",
            f"VAR {ups_name} battery.status \"{data.get('battery.status', 'UNKNOWN')}\"",
            f"VAR {ups_name} ups.realpower \"{data.get('ups.realpower', 0)}\"",
            f"VAR {ups_name} ups.status \"{data.get('ups.status', 'UNKNOWN')}\"",
            f"VAR {ups_name} ups.timestamp \"{data.get('ups.timestamp', 0)}\"",
            f"VAR {ups_name} input.realpower \"{data.get('input.realpower', 0)}\"",
        ]

        return f"BEGIN LIST VAR {ups_name}\n" + "\n".join(variables) + f"\nEND LIST VAR {ups_name}\n"

    async def start(self):
        """Start the Anker NUT server."""
        LOG.info("🚀 Starting Simple Anker NUT Server")

        try:
            # Setup MQTT monitor
            self.start_mqtt_monitor()

            # Start NUT server
            self.start_nut_server()

            LOG.info("✅ Simple Anker NUT Server started successfully!")
            LOG.info(f"📡 NUT server: {self.nut_host}:{self.nut_port}")
            LOG.info(
                f"🔋 UPS devices: {[device['ups_name'] for device in self.devices]}")
            LOG.info("🎯 Ready for Home Assistant NUT integration!")

            # Keep running
            while self.running:
                await asyncio.sleep(1)

        except Exception as e:
            LOG.error(f"❌ Failed to start server: {e}")
            raise

    def stop(self):
        """Stop the server."""
        LOG.info("🛑 Stopping Simple Anker NUT Server...")
        self.running = False

        if self.nut_server:
            self.nut_server.close()

        LOG.info("✅ Simple Anker NUT Server stopped")


async def main():
    """Main function."""
    # Load configuration from file
    import json
    config_path = os.path.join(os.path.dirname(__file__), "config_multi.json")

    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)
        devices = config["devices"]
        anker = config["anker"]
        nut_config = config["nut"]
    else:
        LOG.error(f"❌ Missing configuration file: config_multi.json")
        exit(1)

    # Create and start server
    server = SimpleAnkerNUTServer(devices, anker, nut_config)

    try:
        await server.start()
    except KeyboardInterrupt:
        LOG.info("🛑 Received interrupt signal")
    finally:
        server.stop()

if __name__ == "__main__":
    asyncio.run(main())
