#!/usr/bin/python3

import miio
import miio.exceptions
import miio.airhumidifier
import paho.mqtt.client
import urllib.parse
import sys
import yaml
import argparse
import os
import json
import copy
import typing
import datetime

_parser = argparse.ArgumentParser("Bridge python-miio xiaomi device to mqtt")
_parser.add_argument("--config", default=os.path.join(os.getcwd(), "config.yml"))
_args = _parser.parse_args()

_config = yaml.safe_load(open(_args.config, "rb").read())


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


if _config["simplify"]:

    def simplify_dict(obj, prop: str):
        if prop in obj:
            del obj[prop]


else:

    def simplify_dict(obj, prop: str):
        pass


class StdoutBackend:
    def output(self, topic: str, value: dict):
        print(f"{topic}: {json.dumps(value)}")


class PahoMqttBackend:
    def __init__(self, client: paho.mqtt.client.Client):
        self._client = client

    def output(self, topic: str, value: dict):
        self._client.publish(topic, json.dumps(value), retain=True)

    def subcribe_to_control(self, topic: str, command_handler):
        self._client.message_callback_add(topic, command_handler)
        self._client.subscribe(topic)


_all_backends = []
_mqtt_backends = []  # typing.List[PahoMqttBackend]


def prepare_backends(
    all_backends, mqtt_backends: typing.List[PahoMqttBackend], backends_config
):
    for b in backends_config:
        if b == "stdout":
            print("Adding stdout backend")
            stdout_backend = StdoutBackend()
            all_backends.append(stdout_backend)
        else:
            mqtt_url = urllib.parse.urlparse(b)
            c = paho.mqtt.client.Client()
            c.username_pw_set(mqtt_url.username, mqtt_url.password)
            c.connect(mqtt_url.hostname)

            mqtt_backend = PahoMqttBackend(c)

            all_backends.append(mqtt_backend)
            mqtt_backends.append(mqtt_backend)


prepare_backends(_all_backends, _mqtt_backends, _config["backends"])


class InterfacedDevice:
    def __init__(self, miio_device, config):
        self._miio_device = miio_device
        self._config = config
        self._last_succesful_report = datetime.datetime.now(datetime.timezone.utc)
        self._last_succesful_control = datetime.datetime.now(datetime.timezone.utc)

    def get_report(self):
        raise NotImplementedError

    def topic(self):
        return os.path.join(_config["topic_prefix"], self._config["topic"])

    def status_topic(self):
        return os.path.join(self.topic(), "status")

    def control_topic(self):
        return os.path.join(self.topic(), "control")

    def error_topic(self):
        return os.path.join(self.topic(), "error")

    def handle_control(self, client, userdata, message: paho.mqtt.client.MQTTMessage):
        raise NotImplementedError


class InterfacedHumidifier(InterfacedDevice):
    def __init__(self, *args, **kwargs):
        super(InterfacedHumidifier, self).__init__(*args, **kwargs)
        self._last_status = None

    def get_report(self):
        try:
            status: miio.airhumidifier.AirHumidifierStatus = self._miio_device.status()

            self._last_status = status

            data = self.get_humidifier_report(status)
            data["location"] = self._config["location"]
            if "sublocation" in self._config:
                data["sublocation"] = self._config["sublocation"]
            self._last_succesful_report = datetime.datetime.now(datetime.timezone.utc)
            return data
        except (miio.exceptions.DeviceException, OSError) as e:
            eprint(e)
            return None

    def get_humidifier_report(self, status):
        data = copy.deepcopy(status.data)
        data["temperature"] = status.temperature
        simplify_dict(data, "hw_version")
        simplify_dict(data, "temp_dec")
        simplify_dict(data, "use_time")
        simplify_dict(data, "buzzer")
        simplify_dict(data, "child_lock")
        simplify_dict(data, "led_b")
        simplify_dict(data, "limit_hum")
        simplify_dict(data, "speed")
        simplify_dict(data, "dry")
        return data

    def apply_control(self, mdev: miio.airhumidifier.AirHumidifierCA1, control: dict):
        target_speed = control.get("speed", 0.0)
        print(f"{self.control_topic()}: setting speed = {target_speed} from {control}")
        try:
            self.set_active_control(target_speed, mdev)
            self.set_passive_control(mdev)
            self._last_succesful_control = datetime.datetime.now(datetime.timezone.utc)
        except Exception as e:
            eprint(f"{self.control_topic()}: failed to apply control: ", e)

    def is_tank_empty(self):
        if self._last_status is not None:
            return self._last_status.depth < _config["minimal_water_depth"]
        else:
            return False

    def set_active_control(self, target_speed, mdev):
        if target_speed < 0.05:
            if self._last_status.is_on:
                mdev.off()
        else:
            if self.is_tank_empty():
                if self._last_status.is_on:
                    mdev.off()
            else:
                if not self._last_status.is_on:
                    mdev.on()
                if target_speed < 0.33:
                    if (
                        not self._last_status.mode
                        == miio.airhumidifier.OperationMode.Silent
                    ):
                        mdev.set_mode(miio.airhumidifier.OperationMode.Silent)
                elif target_speed < 0.66:
                    if (
                        not self._last_status.mode
                        == miio.airhumidifier.OperationMode.Medium
                    ):
                        mdev.set_mode(miio.airhumidifier.OperationMode.Medium)
                elif target_speed < 1.01:
                    if (
                        not self._last_status.mode
                        == miio.airhumidifier.OperationMode.High
                    ):
                        mdev.set_mode(miio.airhumidifier.OperationMode.High)
                else:
                    pass

    def set_passive_control(self, mdev):
        if self._last_status.child_lock != True:
            mdev.set_child_lock(True)

        if (
            self._last_status.led_brightness is not None
            and self._last_status.led_brightness != miio.airhumidifier.LedBrightness.Dim
        ):
            mdev.set_led_brightness(miio.airhumidifier.LedBrightness.Dim)

        if self._last_status.target_humidity != 80:
            mdev.set_target_humidity(80)

        if self._last_status.buzzer != False:
            mdev.set_buzzer(False)

        if self._last_status.dry != False:
            mdev.set_dry(False)

    def handle_control(self, client, userdata, message: paho.mqtt.client.MQTTMessage):
        if self._last_status is None:
            return

        try:
            self.apply_control(self._miio_device, json.loads(message.payload))
        except miio.exceptions.DeviceError as e:
            eprint(e)


_interfaced_devices = []


def prepare_devices(device_list, humidifiers_config):
    for cfg in humidifiers_config:
        print(f"Configuring humidifer: {cfg['topic']} from {cfg['ip']}")
        d = miio.airhumidifier.AirHumidifierCA1(
            cfg["ip"], cfg["token"], lazy_discover=True
        )
        id = InterfacedHumidifier(d, cfg)
        device_list.append(id)
        for mqtt in _mqtt_backends:
            mqtt.subcribe_to_control(id.control_topic(), id.handle_control)


prepare_devices(_interfaced_devices, _config["humidifiers"])


def send_output(topic: str, data):
    for b in _all_backends:
        b.output(topic, data)

    for b in _mqtt_backends:
        b._client.loop()


for d in _interfaced_devices:
    send_output(d.error_topic(), "Deamon startup")


communication_time_delta = datetime.timedelta(
    minutes=_config["communication_error_timout_minutes"]
)

while True:
    now = datetime.datetime.now(datetime.timezone.utc)
    for d in _interfaced_devices:
        if (
            now - d._last_succesful_report > communication_time_delta
            or now - d._last_succesful_control > communication_time_delta
        ):
            send_output(
                d.error_topic(),
                f"Failed to communicate for {communication_time_delta.days}",
            )
        if d is InterfacedHumidifier and d.is_tank_empty():
            send_output(d.error_topic(), "Water Tank is empty")

    for d in _interfaced_devices:
        report = d.get_report()
        if report != None:
            send_output(d.status_topic(), report)

    for b in _mqtt_backends:
        b._client.loop(1)
