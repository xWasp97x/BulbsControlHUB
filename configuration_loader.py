import json


class ConfigurationLoader:
	def __init__(self, configuration_file):
		self.configuration_file = configuration_file

	def load_configuration(self, *keys):
		with open(self.configuration_file, "rb") as file:
			config = json.load(file)

		results = dict()

		for key in keys:
			if key in config.keys():
				results[key] = config[key]
			else:
				raise KeyError("{} is not in {}!".format(key, self.configuration_file))
		return results
