# xiaomi-python-miio-mqtt
Python Miio to MQTT bridge

## Launching with systemd

 cp xiaomi-python-miio-mqtt/xiaomi_python_miio_mqtt.service.template /etc/systemd/system/xiaomi_python_miio_mqtt.service

sudo systemctl daemon-reload

sudo systemctl start xiaomi_python_miio_mqtt.service
sudo systemctl status xiaomi_python_miio_mqtt.service

sudo systemctl enable xiaomi_python_miio_mqtt.service
