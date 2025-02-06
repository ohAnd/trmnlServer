'''
This module provides the ConfigManager class for managing configuration settings
of the application. The configuration settings are stored in a 'config.yaml' file.

Classes:
    ConfigManager: Manages loading, updating, and saving configuration settings.

Usage example:
    config_manager = ConfigManager('/path/to/config/directory')
    config_manager.set_refresh_time(600)
'''
import os
import sys
import yaml


class ConfigManager:
    '''
    Manages the configuration settings for the application.

    This class handles loading, updating, and saving configuration settings from a 'config.yaml'
    file. If the configuration file does not exist, it creates one with default values and
    prompts the user to restart the server.
    '''
    def __init__(self, given_dir):
        self.current_dir = given_dir
        self.config_file = os.path.join(self.current_dir, 'config.yaml')
        self.default_config = {
            'image_path': 'images/screen.bmp',
            'image_modification': True,
            'refresh_time': 900,
            'battery_max_voltage': 4.1,
            'battery_min_voltage': 2.3
        }
        self.config = self.default_config.copy()
        self.load_config()

    def load_config(self):
        """
        Reads the configuration from 'config.yaml' file located in the current directory.
        If the file exists, it loads the configuration values.
        If the file does not exist, it creates a new 'config.yaml' file with default values and
        prompts the user to restart the server after configuring the settings.
        """
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config.update(yaml.safe_load(f))
        else:
            self.write_config()
            print("Config file not found. Created a new one with default values.")
            print("Please restart the server after configuring the settings in config.yaml")
            sys.exit(0)

    def write_config(self):
        """
        Writes the configuration to 'config.yaml' file located in the current directory.
        """
        with open(self.config_file, 'w', encoding='utf-8') as config_file_handle:
            yaml.safe_dump(self.config, config_file_handle)

    def set_refresh_time(self, refresh_time):
        """
        Updates the configuration file with the new refresh time.
        """
        self.config['refresh_time'] = refresh_time
        self.write_config()

    def set_image_path(self, image_path):
        """
        Updates the configuration file with the new image path.
        """
        self.config['image_path'] = image_path
        self.write_config()

    def set_image_modification(self, image_modification):
        """
        Updates the configuration file with the new image modification setting.
        """
        self.config['image_modification'] = image_modification
        self.write_config()

    def set_battery_max_voltage(self, battery_max_voltage):
        """
        Updates the configuration file with the new battery max voltage.
        """
        self.config['battery_max_voltage'] = battery_max_voltage
        self.write_config()

    def set_battery_min_voltage(self, battery_min_voltage):
        """
        Updates the configuration file with the new battery min voltage.
        """
        self.config['battery_min_voltage'] = battery_min_voltage
        self.write_config()
