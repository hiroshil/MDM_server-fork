import logging
import logging.config

class LoggerCustom(logging.getLoggerClass()):

    def error(self, *args, **kwargs):
        if 'exc_info' not in kwargs:
            kwargs['exc_info'] = self.isEnabledFor(logging.DEBUG)
        super().error(*args, **kwargs)

    def warning(self, *args, **kwargs):
        if 'exc_info' not in kwargs:
            kwargs['exc_info'] = self.isEnabledFor(logging.DEBUG)
        super().warning(*args, **kwargs)

logging.setLoggerClass(LoggerCustom)
log_config = {'version': 1, 'disable_existing_loggers': False, 'root': {'level': 'ERROR', 'handlers': ['file_handler'], 'propagate': False}, 'formatters': {'detail': {'format': '%(asctime)s | %(name)s | %(levelname)s | %(funcName)s: %(message)s'}, 'simple': {'format': '%(name)s - %(levelname)s: %(message)s'}}, 'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'simple', 'stream': 'ext://sys.stderr'}, 'file_handler': {'class': 'logging.handlers.RotatingFileHandler', 'formatter': 'detail', 'filename': 'app.log', 'maxBytes': 10485760, 'backupCount': 1, 'encoding': 'utf8'}, 'null_handler': {'class': 'logging.NullHandler'}}, 'loggers': {'App': {'handlers': ['console'], 'propagate': True}, 'StreamDownloader': {'propagate': True}, 'streamlink': {'propagate': True}, 'Tasks': {'propagate': True}, 'httpclient': {'propagate': True}, 'werkzeug': {'level': 'ERROR', 'handlers': ['null_handler'], 'propagate': False}}}

def setup(level):
    level = level.upper()
    log_config['root']['level'] = level
    logging.config.dictConfig(log_config)

