import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent / "anker-solix-api"))

from api.mqtt import AnkerSolixMqttSession
from api.errors import AnkerSolixError
from api.api import AnkerSolixApi
from aiohttp.client_exceptions import ClientError
from aiohttp import ClientSession
from typing import Any
import time
import logging
import asyncio

LOG = logging.getLogger(__name__)

class AnkerMqttMonitor:

    def __init__(self, username, password, country_code) -> None:
        self.user: str = username
        self.password: str = password
        self.country: str = country_code
        self.api: AnkerSolixApi | None = None
        self.devices: dict = {}
        self.topics: set = set()

    async def main(self, devices, msg_callback) -> None:  # noqa: C901
        mqtt_session: AnkerSolixMqttSession | None = None
        self.msg_callback = msg_callback

        try:
            async with ClientSession() as websession:

                await self._auth(websession)

                # Initialize the session
                if not (
                    (mqtt_session := await self.api.startMqttSession())
                    and mqtt_session.is_connected()
                ):
                    return False
                LOG.info(
                    f"Connected successfully to MQTT server {mqtt_session.host}:{mqtt_session.port}"
                )

                await self._select_and_subscribe_devices(devices, mqtt_session)

                await asyncio.sleep(2)

                poller_task = None
                try:
                    # Start the background poller with subscriptions and update trigger
                    poller_task = asyncio.create_task(
                        mqtt_session.message_poller(
                            topics=self.topics,
                            trigger_devices=list(self.devices.keys()),
                            msg_callback=self.print_values,
                            timeout=60,
                        )
                    )

                    last_request = 0
                    interval = 10
                    while True:
                        await asyncio.sleep(1)

                        # Published immediate status request
                        now = time.time()
                        if now - last_request >= interval:
                            for sn, device in self.devices.items():
                                mqtt_session.status_request(deviceDict=device)
                            last_request = now

                        if not (mqtt_session and mqtt_session.is_connected()):
                            LOG.error("❌ MQTT client disconnected...")
                            break
                except (asyncio.CancelledError, KeyboardInterrupt) as _:
                    # Cancel the started tasks
                    # Wait for the tasks to finish cancellation if not completed already
                    try:
                        if poller_task:
                            poller_task.cancel()
                            await poller_task
                    except asyncio.CancelledError:
                        LOG.info("MQTT client poller task cancelled.")
                return True

        except (
            asyncio.CancelledError,
            KeyboardInterrupt,
            ClientError,
            AnkerSolixError,
        ) as err:
            if isinstance(err, ClientError | AnkerSolixError):
                LOG.error("❌ %s: %s", type(err), err)
                LOG.info("Api Requests: %s", self.api.request_count)
                LOG.info(
                    self.api.request_count.get_details(last_hour=True))
            return False
        finally:
            if mqtt_session:
                LOG.info("Disconnecting from MQTT server...")
                if self.api.mqttsession:
                    self.api.mqttsession.cleanup()

    async def _auth(self, websession):
        LOG.info(
            "Trying Api authentication for user %s...", self.user)
        self.api = AnkerSolixApi(
            self.user,
            self.password,
            self.country,
            websession,
            LOG,
        )
        if await self.api.async_authenticate():
            LOG.info("Anker Cloud authentication: OK")
        else:
            LOG.info("Anker Cloud authentication: CACHED")

    async def _select_and_subscribe_devices(self, devices, mqtt_session):
        self.device_selected: dict = {}
        LOG.info("Getting sites and device list...")
        await self.api.update_sites()
        await self.api.get_bind_devices()

        self.topics = set()
        self.devices = {}

        for device_sn in devices:
            device = self.api.devices.get(device_sn)
            if (device is None):
                LOG.info(
                    f"❌Specified device {device_sn} not found for account {self.api.apisession.email}")
                continue

            device_sn = device.get("device_sn")
            device_pn = (
                device.get("device_pn")
                or device.get("product_code")
                or ""
            )
            LOG.info(
                f"Starting MQTT server connection for device {device_sn} (model {device_pn})..."
            )

            self.devices[device_sn] = device

            # subscribe root Topic of selected device
            if prefix := mqtt_session.get_topic_prefix(
                deviceDict=device
            ):
                self.topics.add(f"{prefix}#")

            # Command messages (app to device)
            if cmd_prefix := mqtt_session.get_topic_prefix(
                deviceDict=device, publish=True
            ):
                self.topics.add(f"{cmd_prefix}#")

    def print_values(
        self,
        session: AnkerSolixMqttSession,
        topic: str,
        message: Any,
        data: bytes | dict,
        model: str,
        *args,
        **kwargs,
    ) -> None:
        for sn, device in self.api.mqttsession.mqtt_data.items():
            fields = {}
            for key, value in device.items():
                if key != "topics":
                    fields[key] = value
            self.msg_callback(sn, fields)