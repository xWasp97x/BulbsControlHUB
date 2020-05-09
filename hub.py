import logging
import os
import socket
import sys
import time
from yeelight import Bulb
from configuration_loader import ConfigurationLoader
from pyroute2 import IPRoute
from loguru import logger
from tqdm import tqdm, trange
from paho.mqtt.client import Client
import threading
import configparser


class HUB:
	def __init__(self, config_file='./hub_config.ini'):
		logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - [%(levelname)s]: %(message)s', handlers=[logging.FileHandler("log.txt"),
																												logging.StreamHandler()])
		log_format = '<green>{time: YYYY-MM-DD HH:mm:ss.SSS}</green> <level>{level}: {message}</level>'
		logger.remove()
		logger.add(sys.stdout, format=log_format, colorize=True)
		config_loader = ConfigurationLoader(config_file)
		logger.add(os.path.join(config_loader['logging']['logs_path'], 'log_{time: YYYY-MM-DD}.log'), format=log_format, colorize=True, compression='zip', rotation='00:00')
		config = configparser.ConfigParser()
		self.mqtt_broker = config['mqtt']['mqtt_broker']
		self.mqtt_topic = config['mqtt']['mqtt_topic']
		mqtt_id = config['mqtt']['mqtt_id']
		self.mqtt_client = Client(client_id=mqtt_id)
		self.mqtt_client.enable_logger(logger)
		self.mqtt_client.on_message = self.toggle_bulbs
		self.mqtt_client.on_connect = self.mqtt_subscribe
		self.mqtt_client.on_disconnect = self.mqtt_connect
		self.mqtt_connect()
		self.bulbs = None
		self.loop_thread = threading.Thread(target=self.loop)
		self.loop_thread.start()

	def mqtt_connect(self):
		logger.debug(f'Connecting to MQTT broker {self.mqtt_broker}...')
		try:
			response = self.mqtt_client.connect(host=self.mqtt_broker, port=1883)
		except Exception as e:
			logger.error(f"Can't connect to MQTT broker; {e}")
			response = 1
		if response != 0:
			logger.error(f'Not connected to MQTT broker {self.mqtt_broker}')

	def mqtt_subscribe(self, *args):
		self.mqtt_client.subscribe(topic=self.mqtt_topic, qos=1)
		logger.info(f'Subscribed to {self.mqtt_topic}')

	def get_subnet(self):
		ip_scanner = IPRoute()
		info = [{'iface': x['index'],
				 'addr': x.get_attr('IFA_ADDRESS'),
				 'mask': x['prefixlen']} for x in ip_scanner.get_addr()]
		ip_scanner.close()

		subnet = None
		for interface in info:
			if '192.168' in interface['addr']:
				subnet = f'192.168.{interface["addr"].split(".")[2]}'
				return subnet

	def get_bulbs_ips(self):
		logger.info('Scanning network for bulbs...')

		subnet = self.get_subnet()
		if subnet is None:
			logger.error('No router connection! Aborting...')
			return None

		#subnet = '192.168.178'
		logger.debug(f'Subnet: {subnet}')

		bulbs = list()  # [{'hostname': '<>', 'ip': '<>'}]

		progressbar = trange(256, desc='', leave=True)
		for subnet_ip in progressbar:
			try:
				ip = f'{subnet}.{subnet_ip}'
				progressbar.set_description(f'Scanning {ip}')
				hostname = socket.gethostbyaddr(ip)[0]
				if 'yeelink' in hostname:
					bulbs.append({'hostname': hostname, 'ip': ip})
					logger.info(f'Found new bulb: {hostname} at {ip}')
			except socket.herror as se:
				if 'Unknown host' not in str(se):
					logger.error(str(se))

		result = [f"hostname: {bulb['hostname']}, ip: {bulb['ip']}" for bulb in bulbs]
		if len(bulbs) > 0:
			logger.info(f'Network scan ended, result:\n' + '\n'.join(result))
		else:
			logger.warning(f'Network scan ended, no bulbs found')

		return bulbs

	def toggle_bulb(self, bulb):
		bulb_obj = Bulb(bulb['ip'])
		response = bulb_obj.toggle()
		if response == 'ok':
			logger.info(f'Toggled {bulb["hostname"]} at {bulb["ip"]}')
		else:
			logger.error(f'Toggle error for {bulb["hostname"]} at {bulb["ip"]}')

	def toggle_bulbs(self, bulbs, *args):
		if type(bulbs) is not list:
			available_bulbs = self.bulbs
		else:
			available_bulbs = bulbs
		logger.info('Toggling bulbs...')
		for bulb in available_bulbs:
			self.toggle_bulb(bulb)
		logger.info('All bulbs toggled.')

	def loop(self):
		try:
			self.bulbs = self.get_bulbs_ips()
			time.sleep(5)
		except Exception as e:
			logger.critical(f"Unhandled exception: {e}")
			time.sleep(1)


hub = HUB()
hub.mqtt_client.loop_forever()







