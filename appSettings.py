import os
import sys
import json
from argparse import ArgumentTypeError, RawTextHelpFormatter
from jsonargparse import ArgumentParser, ActionConfigFile
LogLevelName = ('notset', 'info', 'error', 'warning', 'debug')
DEFAULT_DOWNLOAD_DIR = os.path.join(os.getcwd(), 'DL')

class AppSettings:
    default_path_config = 'app.json'

    def __init__(self):
        self.file_config = self.default_path_config

    def load(self, conf_json_str=None):
        parser = self.setupParser()
        if conf_json_str is None:
            conf = parser.parse_args()
        else:
            parser.error_handler = None
            conf = parser.parse_string(conf_json_str)
        if conf.config is None:
            self.file_config = self.default_path_config
        else:
            self.file_config = conf.config
        parser.save(conf, self.file_config, 'json_indented', overwrite=True)
        conf = vars(conf)
        conf.pop('__default_config__', None)
        self.__dict__.update(conf)

    def dump(self):
        with open(self.file_config, 'r') as f:
            data = json.load(f)
        data['log_level_name'] = LogLevelName
        return data

    def validateWorkers(self, arg):
        ' Type function for argparse - a float within some predefined bounds '
        MIN = 1
        try:
            workers = int(arg)
        except ValueError:
            raise ArgumentTypeError('Number of active downloads argument must be a number')
        if workers < MIN:
            raise ArgumentTypeError('Number of active downloads argument must be >= %d' % MIN)
        return workers

    def validateConnections(self, arg):
        ' Type function for - a float within some predefined bounds '
        MIN = 1
        try:
            threads = int(arg)
        except ValueError:
            raise ArgumentTypeError('Number of connections must be a number')
        if threads < MIN:
            raise ArgumentTypeError('Number of connections must be >= %d' % MIN)
        return threads

    def validateLogLevel(self, arg):
        if arg.lower() not in LogLevelName:
            raise ArgumentTypeError('Level must is: %s' % ', '.join(LogLevelName))
        return arg

    def setupParser(self):
        description = """A small tool download videos and documents by NguyenKhong.
Web: https://nhtcntt.blogspot.com"""
        parser = ArgumentParser(default_config_files=[self.default_path_config], parser_mode='jsonnet', description=description, formatter_class=RawTextHelpFormatter)
        parser.add_argument('-ad', '--active-downloads', default=1, type=self.validateWorkers, help='Maximum number of active downloads run parallel. Default: 1')
        parser.add_argument('-cc', '--connections', default=5, type=self.validateConnections, help='Maximum number of connections per download. Default: 5')
        parser.add_argument('-d', '--download-dir', default=DEFAULT_DOWNLOAD_DIR, help='Directory store files')
        parser.add_argument('-l', '--log-level', default='error', type=self.validateLogLevel, help='Log level. Default: error, There are log level: %s' % ', '.join(LogLevelName))
        parser.add_argument('-c', '--config', action=ActionConfigFile)
        return parser

    def checkArgs(self):
        argv = sys.argv
        if len(argv) >= 2 and (argv[1] == '--help' or argv[1] == '-h'):
            parser = self.setupParser()
            parser.print_help()
            sys.exit(0)

app_settings = AppSettings()
if __name__ == '__main__':
    app_settings.loads(test_json_conf)
    print(app_settings.connections)
