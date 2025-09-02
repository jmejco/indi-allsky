#!/usr/bin/env python3
"""
Standalone MQTT Sensor Publisher
Reads SHT30 sensor and publishes data to MQTT broker
"""

import sys
import time
import logging
import signal
import os
import math
import board
import busio
import adafruit_sht31d
import paho.mqtt.client as mqtt

# Configuration
MQTT_BROKER = "allsky.lab"   # Change to your MQTT broker address
MQTT_PORT = 1883
MQTT_USERNAME = "indi-allsky"    # Change to your MQTT username
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD')
MQTT_TOPIC_TEMP = "indi-allsky/pi/temp_c"
MQTT_TOPIC_HUMIDITY = "indi-allsky/pi/humidity"
UPDATE_INTERVAL = 15  # seconds

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('mqtt-sensor-publisher')

class MqttSensorPublisher:
    def __init__(self):
        # Validate MQTT password
        if not MQTT_PASSWORD:
            logger.error('MQTT_PASSWORD environment variable not set')
            logger.error('Set it with: export MQTT_PASSWORD="your_password"')
            sys.exit(1)
            
        self.sensor = None
        self.mqtt_client = None
        self.connected = False
        self.running = True

    def get_dew_point_c(self, t_air_c, rel_humidity):
        """Compute the dew point in degrees Celsius
        :param t_air_c: current ambient temperature in degrees Celsius
        :type t_air_c: float
        :param rel_humidity: relative humidity in %
        :type rel_humidity: float
        :return: the dew point in degrees Celsius
        :rtype: float
        """
        # Validate inputs to prevent math domain errors
        if rel_humidity <= 0 or rel_humidity > 100:
            logger.warning('Invalid humidity value: %.2f%%, using 1%%', rel_humidity)
            rel_humidity = 1.0
            
        A = 17.27
        B = 237.7
        alpha = ((A * t_air_c) / (B + t_air_c)) + math.log(rel_humidity / 100.0)
        return (B * alpha) / (A - alpha)

    def init_sensor(self):
        """Initialize SHT30 sensor"""
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            self.sensor = adafruit_sht31d.SHT31D(i2c, address=0x44)
            logger.info('SHT30 sensor initialized at address 0x44')
            return True
        except Exception as e:
            logger.error('Failed to initialize SHT30 sensor: %s', str(e))
            return False

    def setup_mqtt(self):
        """Initialize MQTT client"""
        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            self.mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
            logger.info('MQTT client configured for %s:%d', MQTT_BROKER, MQTT_PORT)
            return True
        except Exception as e:
            logger.error('Failed to setup MQTT client: %s', str(e))
            return False

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT connection callback"""
        if reason_code == 0:
            self.connected = True
            logger.info('Connected to MQTT broker')
        else:
            logger.error('Failed to connect to MQTT broker: %s', reason_code)

    def on_mqtt_disconnect(self, client, userdata, flags, reason_code, properties):
        """MQTT disconnection callback"""
        self.connected = False
        logger.warning('Disconnected from MQTT broker')

    def read_and_publish_sensor(self):
        """Read sensor data and publish to MQTT"""
        if not self.connected:
            logger.warning('Not connected to MQTT broker, skipping publish')
            return False

        try:
            # Read sensor with heater reset if needed
            temp = self.sensor.temperature
            humidity = self.sensor.relative_humidity
            
            # Check if humidity is stuck and apply heater reset
            if humidity == 0.0:
                logger.info('Humidity stuck at 0%, applying heater reset...')
                self.sensor.heater = True
                time.sleep(2)
                self.sensor.heater = False
                time.sleep(1)
                
                # Read again after heater reset
                temp = self.sensor.temperature
                humidity = self.sensor.relative_humidity
            
            # Calculate dew point using class method
            dew_point = self.get_dew_point_c(temp, humidity)
            
            # Publish to MQTT
            self.mqtt_client.publish(MQTT_TOPIC_TEMP, f"{temp:.2f}")
            self.mqtt_client.publish(MQTT_TOPIC_HUMIDITY, f"{humidity:.2f}")
            self.mqtt_client.publish("indi-allsky/pi/dewpoint_c", f"{dew_point:.2f}")
            
            logger.info('Published: Temp=%.2f°C, Humidity=%.2f%%, Dew Point=%.2f°C', temp, humidity, dew_point)
            return True
            
        except Exception as e:
            logger.error('Failed to read/publish sensor data: %s', str(e))
            return False

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info('Received signal %d, shutting down', signum)
        self.running = False

    def cleanup(self):
        """Clean up resources"""
        try:
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            logger.info('Cleanup completed')
        except Exception as e:
            logger.error('Error during cleanup: %s', str(e))

    def run(self):
        """Main loop"""
        logger.info('Starting MQTT sensor publisher')
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        if not self.init_sensor():
            sys.exit(1)
        
        if not self.setup_mqtt():
            self.cleanup()
            sys.exit(1)
        
        try:
            while self.running:
                self.read_and_publish_sensor()
                time.sleep(UPDATE_INTERVAL)
        except Exception as e:
            logger.error('Unexpected error: %s', str(e))
        finally:
            self.cleanup()

if __name__ == "__main__":
    publisher = MqttSensorPublisher()
    publisher.run()