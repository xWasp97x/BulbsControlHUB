import logging
import socket
import time
from yeelight import Bulb
from configuration_loader import ConfigurationLoader
from pyroute2 import IPRoute
from logging_wrapper import ColorLogsWrapper
from tqdm import tqdm, trange
from paho.mqtt.client import Client
import threading


class HUB:
	def __init__(self, config_file='./config/hub_config'):
		logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - [%(levelname)s]: %(message)s', handlers=[logging.FileHandler("log.txt"),
																												logging.StreamHandler()])
		self.logger = ColorLogsWrapper(logging.getLogger(__name__))
		config_loader = ConfigurationLoader(config_file)
		configs = config_loader.load_configuration('mqtt_broker', 'mqtt_topic', 'mqtt_id')
		self.mqtt_broker = configs['mqtt_broker']
		self.mqtt_topic = configs['mqtt_topic']
		mqtt_id = configs['mqtt_id']
		self.mqtt_client = Client(client_id=mqtt_id)
		self.mqtt_client.enable_logger(self.logger)
		self.mqtt_client.on_message = self.toggle_bulbs
		self.mqtt_client.on_connect = self.mqtt_subscribe
		self.mqtt_client.on_disconnect = self.mqtt_connect
		self.mqtt_connect()
		self.bulbs = None
		self.loop_thread = threading.Thread(target=self.loop)
		self.loop_thread.start()

	def mqtt_connect(self):
		self.logger.debug(f'Connecting to MQTT broker {self.mqtt_broker}...')
		try:
			response = self.mqtt_client.connect(host=self.mqtt_broker, port=1883)
		except Exception as e:
			self.logger.error(f"Can't connect to MQTT broker; {e}")
			response = 1
		if response != 0:
			self.logger.error(f'Not connected to MQTT broker {self.mqtt_broker}')

	def mqtt_subscribe(self, *args):
		self.mqtt_client.subscribe(topic=self.mqtt_topic, qos=1)
		self.logger.info(f'Subscribed to {self.mqtt_topic}')

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
		self.logger.info('Scanning network for bulbs...')

		subnet = self.get_subnet()
		if subnet is None:
			self.logger.error('No router connection! Aborting...')
			return None

		#subnet = '192.168.178'
		self.logger.debug(f'Subnet: {subnet}')

		bulbs = list()  # [{'hostname': '<>', 'ip': '<>'}]

		progressbar = trange(256, desc='', leave=True)
		for subnet_ip in progressbar:
			try:
				ip = f'{subnet}.{subnet_ip}'
				progressbar.set_description(f'Scanning {ip}')
				hostname = socket.gethostbyaddr(ip)[0]
				if 'yeelink' in hostname:
					bulbs.append({'hostname': hostname, 'ip': ip})
					self.logger.info(f'Found new bulb: {hostname} at {ip}')
			except socket.herror as se:
				if 'Unknown host' not in str(se):
					self.logger.error(str(se))

		result = [f"hostname: {bulb['hostname']}, ip: {bulb['ip']}" for bulb in bulbs]
		if len(bulbs) > 0:
			self.logger.info(f'Network scan ended, result:\n' + '\n'.join(result))
		else:
			self.logger.warning(f'Network scan ended, no bulbs found')

		return bulbs

	def toggle_bulb(self, bulb):
		bulb_obj = Bulb(bulb['ip'])
		response = bulb_obj.toggle()
		if response == 'ok':
			self.logger.info(f'Toggled {bulb["hostname"]} at {bulb["ip"]}')
		else:
			self.logger.error(f'Toggle error for {bulb["hostname"]} at {bulb["ip"]}')

	def toggle_bulbs(self, bulbs, *args):
		if type(bulbs) is not list:
			available_bulbs = self.bulbs
		else:
			available_bulbs = bulbs
		self.logger.info('Toggling bulbs...')
		for bulb in available_bulbs:
			self.toggle_bulb(bulb)
		self.logger.info('All bulbs toggled.')

	def loop(self):
		try:
			self.bulbs = self.get_bulbs_ips()
			time.sleep(5)
		except Exception as e:
			self.logger.critical(f"Unhandled exception: {e}")
			time.sleep(1)

hub = HUB()
hub.mqtt_client.loop_forever()







