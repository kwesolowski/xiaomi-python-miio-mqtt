#!/usr/bin/python3

import miio
import miio.exceptions
import miio.airhumidifier

import paho.mqtt.client as mqtt_client
import sys
import yaml
import argparse
import os
import json
import copy

_parser = argparse.ArgumentParser("Bridge python-miio xiaomi device to mqtt")
_parser.add_argument('--config', default=os.path.join(os.getcwd(), 'config.yml'))
_args = _parser.parse_args()

_config = yaml.safe_load(open(_args.config, 'rb').read())

if _config['simplify']:
    def simplify_dict(obj, prop: str):
        if prop in obj:
            del obj[prop]
else:
    def simplify_dict(obj, prop: str):
        pass

class StdoutBackend:
    def output(self, topic: str, value: dict):
        print(f"{topic}: {json.dumps(value)}")

backend_list = []
for b in _config['backends']:
    if b=='stdout':
        print("Adding stdout backend")
        backend_list.append(StdoutBackend())

class InterfacedDevice:
    def __init__(self, miio_device, config):
        self._miio_device = miio_device
        self._config = config
    
    def report(self):
        try:
            status = self._miio_device.status()
            data = self.humidifier_report(status)
            return data
        except miio.exceptions.DeviceException as e:
            print(e, file=sys.stderr)
            return None
        

    def humidifier_report(self, status):
        data = copy.deepcopy(status.data)
        data['temperature'] = status.temperature
        simplify_dict(data, 'hw_version')
        simplify_dict(data, 'temp_dec')  
        simplify_dict(data, 'use_time')  
        simplify_dict(data, 'buzzer')   
        simplify_dict(data, 'child_lock') 
        simplify_dict(data, 'led_b')
        simplify_dict(data, 'power')
        simplify_dict(data, 'mode')
        simplify_dict(data, 'limit_hum')
        simplify_dict(data, 'speed')
        simplify_dict(data, 'dry')
        return data

    def topic(self):
        return os.path.join(_config['topicprefix'], self._config['topic'])

interfaced_devices = []

for cfg in _config['humidifiers']:
    print(f"Configuring humidifer: {cfg['topic']} from {cfg['ip']}")
    d = miio.airhumidifier.AirHumidifierCA1(cfg['ip'], cfg['token'], lazy_discover=True)
    interfaced_devices.append(InterfacedDevice(d, cfg))


while True:
    for d in interfaced_devices:
            report = d.report()
            if report != None:
                for b in backend_list:
                    b.output(d.topic(), report)