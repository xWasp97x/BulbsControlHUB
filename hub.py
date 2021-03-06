import os
import socket
import sys
import time
from yeelight import Bulb
from pyroute2 import IPRoute
from loguru import logger
from paho.mqtt.client import Client
import threading
import configparser


class HUB:
	def __init__(self, config_file='./hub_config.ini'):
		log_format = '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> <level>{level}: {message}</level>'
		logger.remove()
		logger.add(sys.stdout, format=log_format, colorize=True)
		config = configparser.ConfigParser()
		if not os.path.isfile(config_file):
			logger.critical(f"Cannot find '{config_file}', aborting...")
			exit(1)
		config.read(config_file)
		logger.add(os.path.join(config['logging']['logs_path'], 'log_{time:YYYY-MM-DD}.log'), format=log_format, colorize=True, compression='zip', rotation='00:00')
		logger.info('Booting up...')
		self.mqtt_broker = config['mqtt']['mqtt_broker']
		self.mqtt_topic = config['mqtt']['mqtt_topic']
		self.scan_rate = int(config['scanning']['rate'])
		self.max_threads = int(config['scanning']['threads'])
		logger.info(f"[Scan configuration]:\nScan rate: {self.scan_rate}s\nScan threads: {self.max_threads}")
		mqtt_id = config['mqtt']['mqtt_id']
		logger.info(f"[MQTT configuration]\nBroker: {self.mqtt_broker}\nTopic: {self.mqtt_topic}\nID: {mqtt_id}")
		self.mqtt_client = Client(client_id=mqtt_id)
		self.mqtt_client.enable_logger(logger)
		self.mqtt_client.on_message = self.toggle_bulbs
		self.mqtt_client.on_connect = self.mqtt_subscribe
		self.mqtt_client.on_disconnect = self.mqtt_connect
		self.mqtt_client.loop_start()
		self.mqtt_connect()
		self.bulbs = []  # [{'hostname': '<>', 'ip': '<>'}]
		self.threads_buffer = []
		self.startup()
		self.loop()

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

	def scanner(self, ips_list):
		for ip in ips_list:
			try:
				hostname = socket.gethostbyaddr(ip)[0]
				if 'yeelink' in hostname:
					self.threads_buffer.append({'hostname': hostname, 'ip': ip})
					logger.info(f'Found new bulb: {hostname} at {ip}')
			except socket.herror as se:
				if 'Unknown host' not in str(se):
					logger.error(str(se))

	def spawn_scanners(self, ips: list):
		max_threads = self.max_threads
		ips_for_thread = int(len(ips)/max_threads)
		limits = [i*ips_for_thread for i in range(max_threads)]
		ranges = [ips[limit: limit+ips_for_thread+1] for limit in limits]
		threads = []
		for r in ranges:
			t = threading.Thread(target=self.scanner, args=(r,))
			t.start()
			threads.append(t)

		t: threading.Thread
		for t in threads:
			t.join()

	def get_bulbs_ips(self):
		logger.info('Scanning network for bulbs...')

		subnet = self.get_subnet()
		if subnet is None:
			logger.error('No router connection! Aborting...')
			return None

		#subnet = '192.168.178'
		logger.debug(f'Subnet: {subnet}')

		ips = [f"{subnet}.{i}" for i in range(0, 256)]

		self.threads_buffer = []

		self.spawn_scanners(ips)

		bulbs = self.threads_buffer

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

	def check_mqtt_connection(self):
		logger.debug("Checking mqtt broker connection...")
		if not self.mqtt_client.is_connected():
			logger.warning("Broker connection error, trying reconnection...")
			self.mqtt_client.reconnect()
		if not self.mqtt_client.is_connected():
			logger.error("Reconnection error")

	def loop(self):
		SCAN_RATE = self.scan_rate
		while True:
			try:
				self.bulbs = self.get_bulbs_ips()
				time.sleep(SCAN_RATE)
			except KeyboardInterrupt as ki:
				logger.critical("HUB killed, stopping mqtt loop...")
				try:
					self.mqtt_client.loop_stop()
				except:
					self.mqtt_client.loop_stop(force=True)
			except Exception as e:
				logger.critical(f"Unhandled exception: {e}")
				time.sleep(1)

	def turn_off_bulbs(self):
		logger.info("Turning off bulbs...")
		for bulb in self.bulbs:
			bulb_obj = Bulb(bulb['ip'])
			response = bulb_obj.turn_off()
			if response == 'ok':
				logger.info(f'{bulb["hostname"]} turned off at {bulb["ip"]}')
			else:
				logger.error(f'Turn off error for {bulb["hostname"]} at {bulb["ip"]}')

	def startup(self):
		logger.info("Setting up...")
		self.bulbs = self.get_bulbs_ips()
		self.turn_off_bulbs()



if len(sys.argv) > 1:
	hub = HUB(sys.argv[1])
else:
	hub = HUB()
