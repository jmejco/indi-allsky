#!/usr/bin/env python3
"""
Standalone MQTT Dew Heater Controller
Receives MQTT commands and controls GPIO18 PWM for dew heater
"""

import sys
import time
import logging
import signal
import os
import subprocess
import paho.mqtt.client as mqtt

# Configuration
MQTT_BROKER = "allsky.lab"  # Change to your MQTT broker address
MQTT_PORT = 1883
MQTT_USERNAME = "indi-allsky"   # Change to your MQTT username
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD')
MQTT_TOPIC_COMMAND = "indi-allsky/sensor_user_1"  # Dew heater duty cycle

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('mqtt-dewheater-controller')

class MqttDewHeaterController:
    def __init__(self):
        # Validate MQTT password
        if not MQTT_PASSWORD:
            logger.error('MQTT_PASSWORD environment variable not set')
            logger.error('Set it with: export MQTT_PASSWORD="your_password"')
            sys.exit(1)
            
        self.mqtt_client = None
        self.connected = False
        self.running = True
        self.current_duty_cycle = 0

    def run_command(self, cmd):
        """Run shell command"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        except Exception as e:
            return False, "", str(e)

    def init_pwm(self):
        """Initialize GPIO18 PWM"""
        try:
            # Export PWM channel 0 (GPIO18) if not already exported
            success, out, err = self.run_command("echo 0 | sudo tee /sys/class/pwm/pwmchip0/export")
            if not success and "File exists" not in err and "Device or resource busy" not in err:
                logger.error('Failed to export PWM: %s', err)
                return False
            
            # Set PWM parameters
            self.run_command("echo 1000000 | sudo tee /sys/class/pwm/pwmchip0/pwm0/period")
            self.run_command("echo 0 | sudo tee /sys/class/pwm/pwmchip0/pwm0/duty_cycle")
            self.run_command("echo 1 | sudo tee /sys/class/pwm/pwmchip0/pwm0/enable")
            
            logger.info('GPIO18 PWM initialized')
            return True
        except Exception as e:
            logger.error('Failed to initialize PWM: %s', str(e))
            return False

    def setup_mqtt(self):
        """Initialize MQTT client"""
        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            self.mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
            self.mqtt_client.on_message = self.on_message
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
            client.subscribe(MQTT_TOPIC_COMMAND)
            logger.info('Connected to MQTT broker and subscribed to %s', MQTT_TOPIC_COMMAND)
        else:
            logger.error('Failed to connect to MQTT broker: %s', reason_code)

    def on_mqtt_disconnect(self, client, userdata, flags, reason_code, properties):
        """MQTT disconnection callback"""
        self.connected = False
        logger.warning('Disconnected from MQTT broker')

    def on_message(self, client, userdata, msg):
        """MQTT message callback"""
        try:
            duty_cycle = float(msg.payload.decode())
            self.set_dew_heater(duty_cycle)
        except Exception as e:
            logger.error('Failed to process MQTT message: %s', str(e))

    def set_dew_heater(self, duty_cycle):
        """Set dew heater PWM duty cycle (0-100%)"""
        try:
            # Clamp duty cycle to valid range
            duty_cycle = max(0, min(100, duty_cycle))
            
            # Convert percentage to nanoseconds
            duty_ns = int(1000000 * duty_cycle / 100)
            
            # Set PWM duty cycle
            success, out, err = self.run_command(f"echo {duty_ns} | sudo tee /sys/class/pwm/pwmchip0/pwm0/duty_cycle")
            
            if success:
                self.current_duty_cycle = duty_cycle
                logger.info('Dew heater set to %.1f%% duty cycle', duty_cycle)
            else:
                logger.error('Failed to set PWM duty cycle: %s', err)
                
        except Exception as e:
            logger.error('Failed to set dew heater: %s', str(e))

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info('Received signal %d, shutting down', signum)
        self.running = False

    def cleanup(self):
        """Clean up resources"""
        try:
            # Set PWM to 0% before shutdown
            self.run_command("echo 0 | sudo tee /sys/class/pwm/pwmchip0/pwm0/duty_cycle")
            
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            logger.info('Cleanup completed')
        except Exception as e:
            logger.error('Error during cleanup: %s', str(e))

    def run(self):
        """Main loop"""
        logger.info('Starting MQTT dew heater controller')
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        if not self.init_pwm():
            sys.exit(1)
        
        if not self.setup_mqtt():
            self.cleanup()
            sys.exit(1)
        
        try:
            while self.running:
                time.sleep(1)
        except Exception as e:
            logger.error('Unexpected error: %s', str(e))
        finally:
            self.cleanup()

if __name__ == "__main__":
    controller = MqttDewHeaterController()
    controller.run()