#!/usr/bin/env python
from pprint import pprint
import time
import json
import logging
from argparse import ArgumentParser
from itertools import chain
from datetime import datetime, timedelta
from traceback import format_exc

from telegram import ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

from project.database import connect_db

HELP = """*Derminator Bot*

This bot removes any link posted to the group.

*Commands*

/help - display this help message

*How to Use*

- Add bot as ADMIN to the chat group
- Allow bot to delete messages, any other admin permissions are not required

*Questions, Feedback*

Support group: [@tgrambots](https://t.me/tgrambots)

*Open Source*

The source code is available at [github.com/lorien/derminator_bot](https://github.com/lorien/derminator_bot)

*My Other Project*

[@daysandbox_bot](https://t.me/daysandbox_bot) - bot that fights with spam messages in chat groups
[@nosticker_bot](https://t.me/nosticker_bot) - bot to delete stickers posted to group
[@joinhider_bot](https://t.me/joinhider_bot) - removes messages about new user joined the group
[@coinsignal_robot](https://t.me/coinsignal_robot) - bot to be notified when price of specific coin reaches the level you have set, also you can use this bot just to see price of coins.

*Donation*
Ethereum: 0x00D0c93B180452a7c7B70F463aD9D24d9C6d4d61
Litecoin: LKJ86NwUkoboZyFHQwKPx8X984g3m3MPjC
Dash: XtGpsphiR2n9Shx9JFAwnuwGmWzSEvmrtU
UFO coin: CAdfaUR3tqfumoN7vQMVZ98CakyywgwK1L
"""
db = connect_db()
ADMIN_IDS_CACHE = {}


class InvalidCommand(Exception):
    pass


def reason_to_delete(msg):
    reason = None
    for ent in chain(msg.entities, msg.caption_entities):
        if ent.type in ('url', 'text_link'):
            reason = 'external link'
        elif ent.type in ('email',):
            reason = 'email'
    return reason


def build_user_name(user):
    if user.first_name and user.last_name:
        return '%s %s' % (
            user.first_name,
            user.last_name,
        )
    elif user.first_name:
        return user.first_name
    elif user.username:
        return user.first_name
    else:
        return '#%d' % user.id


def get_admin_ids(bot, chat_id):
    try:
        ids, update_time = ADMIN_IDS_CACHE[chat_id]
    except KeyError:
        ids, update_time = None, 0
    else:
        logging.debug('Using cached admin ids for chat [%d]' % chat_id)
    if time.time() - update_time > 3600:
        admins = bot.get_chat_administrators(chat_id)
        ids = [x.user.id for x in admins]
        ADMIN_IDS_CACHE[chat_id] = (ids, time.time())
    return ids


class Controller(object):
    def __init__(self, bot, mode='production'):
        assert mode in ('production', 'test')
        self.bot = bot
        self.bot_id = self.bot.get_me().id
        self.mode = mode
        self.db = connect_db()

    def handle_start_help(self, bot, update):
        #if msg.chat.type == 'private':
        bot.send_message(
            chat_id=update.message.chat.id,
            text=HELP,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )

    def handle_any_message(self, bot, update):
        msg = update.effective_message
        # Do not restrict messages from admins
        admin_ids = get_admin_ids(bot, msg.chat.id)
        if msg.from_user.id in admin_ids:
            return
        # Handle message from non-admin user
        del_reason = reason_to_delete(msg)
        if del_reason:
            try:
                bot.delete_message(
                    chat_id=update.message.chat.id,
                    message_id=update.message.message_id
                )
            except Exception as ex:
                db.fail.save({
                    'date': datetime.utcnow(),
                    'error': str(ex),
                    'traceback': format_exc(),
                    'chat_id': update.message.chat.id,
                    'chat_username': update.message.chat.username,
                })
                raise
            else:
                db.event.save({
                    'date': datetime.utcnow(),
                    'text': update.message.text,
                    'type': 'delete_msg',
                    'chat_id': update.message.chat.id,
                    'chat_username': update.message.chat.id,
                    'user_id': update.message.from_user.id,
                    'user_username': update.message.from_user.username,
                })
                msg = 'Message from %s deleted. Reason: %s' % (
                    build_user_name(update.message.from_user),
                    del_reason
                )
                bot.send_message(
                    chat_id=update.message.chat.id,
                    text=msg
                )


    def handle_stat(self, bot, update):
        msg = update.message
        if msg.chat.type != 'private':
            pass
        else:
            today = datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            start = today
            day_chats = []
            day_messages = []
            for x in range(7):
                end = start + timedelta(days=1)
                query = {
                    'date': {'$gte': start, '$lt': end},
                    'type': 'delete_msg',
                }
                events = list(db.event.find(query))
                chat_count = len(set((x['chat_id'] for x in events)))
                msg_count = len(events)
                day_chats.insert(0, chat_count)
                day_messages.insert(0, msg_count)
                start -= timedelta(days=1)
            output = '\n'.join((
                'Chats: %s' % ' | '.join(map(str, day_chats)),
                'Deleted messages: %s' % ' | '.join(map(str, day_chats)),
            ))
            bot.send_message(
                chat_id=msg.chat.id,
                text=output
            )

def register_handlers(dispatcher, ctl):
    dispatcher.add_handler(CommandHandler(
        ['start', 'help'], ctl.handle_start_help)
    )
    dispatcher.add_handler(CommandHandler('stat', ctl.handle_stat))
    dispatcher.add_handler(MessageHandler(
        (
            Filters.text | Filters.audio | Filters.document
            | Filters.photo | Filters.video
        ),
        ctl.handle_any_message
    ))


def get_token(mode):
    assert mode in ('test', 'production')
    with open('var/config.json') as inp:
        config = json.load(inp)
    if mode == 'test':
        return config['test_api_token']
    else:
        return config['api_token']


def init_updater_with_mode(mode):
    return Updater(token=get_token(mode), workers=16)


def init_bot_with_mode(mode):
    return Bot(token=get_token(mode))


def main():
    parser = ArgumentParser()
    parser.add_argument('--mode', default='production')
    opts = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG)
    updater = init_updater_with_mode(opts.mode)
    dispatcher = updater.dispatcher
    ctl = Controller(updater.bot, opts.mode)
    register_handlers(dispatcher, ctl)
    updater.bot.delete_webhook()
    updater.start_polling()




if __name__ == '__main__':
    main()
