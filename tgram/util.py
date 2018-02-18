from argparse import ArgumentParser
import json

from telegram import ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, RegexHandler


class TgramRobot(object):

    def __init__(self, config_file='var/config.json'):
        self.config = self.load_config(config_file)
        self.opts = {
            'mode': None,
        }

    # PUBLIC API

    def parse_cli_opts(self):
        parser = ArgumentParser()
        parser.add_argument('--mode', default='production')
        opts = parser.parse_args()
        self.opts = {
            'mode': opts.mode,
        }
        self._check_opts_integrity()

    def load_config(self, config_path):
        with open(config_path) as inp:
            return json.load(inp)

    def get_token(self):
        return self.config['api_token_%s' % self.opts['mode']]

    def run_polling(self):
        self.updater = self._init_updater(self.get_token())
        self.dispatcher = self.updater.dispatcher
        self.register_handlers()
        self.before_start_processing()
        self.updater.bot.delete_webhook()
        self.updater.start_polling()

    def before_start_processing():
        pass

    # PRIVATE METHODS

    def _check_opts_integrity(self):
        assert self.opts['mode'] in ('production', 'test')

    def _init_updater(self, token):
        return Updater(token=token, workers=16)

    def _init_bot(self, token):
        return Bot(token=token)
