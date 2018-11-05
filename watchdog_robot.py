#!/usr/bin/env python
from pprint import pprint
import time
import json
import logging
from argparse import ArgumentParser
from itertools import chain
from datetime import datetime, timedelta
from traceback import format_exc
import re

from telegram import ParseMode
from telegram.ext import CommandHandler, MessageHandler, Filters, RegexHandler
from tgram import TgramRobot, run_polling

from project.database import connect_db


class InvalidCommand(Exception):
    pass


HELP = """*Watchdog Robot*

Bot can delete messages of these types:
{msg_types}

To start deleting messages of particular type use this command in chat: `/watchdog_block MSG_TYPE` where MSG\_TYPE is one of types listed above.

To stop deleting messages of particular type use: `/watchdog_allow MSG_TYPE` where MSG\_TYPE is one of types listed above.

By defalt, messages of all types are allowed.

To see which message types are allowed and which disabled use command `/watchdog_config`

By default when bot deletes message it write about it to the chat. If you want to disable this notifications use command `/watchdog_set notify_actions=no`

All these commands `/watchdog_allow`, `/watchdog_block`, `/watchdog_config` and `/watchdog_set` have to be sent to the chat which you want to configure. Do not send this command in private message to the bot, it will ignore such private messages.

*How to Install Bot to the Chat*

- Add bot as ADMIN to the chat group
- Allow bot to delete messages, any other admin permissions are not required

*Questions, Feedback*

Email: lorien @ lorien . name

*Open Source*

The source code is available at [github.com/lorien/watchdog_robot](https://github.com/lorien/watchdog_robot)

*My Other Projects*

[@daysandbox_bot](https://t.me/daysandbox_bot) - bot that fights with spam messages in chat groups
[@nosticker_bot](https://t.me/nosticker_bot) - bot to delete stickers posted to group
[@joinhider_bot](https://t.me/joinhider_bot) - removes messages about new user joined the group
[@coinsignal_robot](https://t.me/coinsignal_robot) - bot to be notified when price of specific coin reaches the level you have set, also you can use this bot just to see price of coins.
"""
db = connect_db()
ADMIN_IDS_CACHE = {}
SUPERUSER_IDS = set([
    46284539, # @madspectator
])
RE_ALLOW_COMMAND = re.compile('^/watchdog_allow (\w+)$')
RE_BLOCK_COMMAND = re.compile('^/watchdog_block (\w+)$')
RE_SET_COMMAND = re.compile('^/watchdog_set (\w+)=(\w+)$')
OPTION_CACHE = {}
DEFAULT_IS_ALLOWED = True
DEFAULT_SETTINGS = {
    'notify_actions': True,
}
VALID_SETTINGS = (
    'notify_actions',
)
MSG_TYPES = (
    'link', 'bot', 'user', 'sticker', 'gif', 'voice',
    'attachment', 'audio', 'photo', 'user_joined_msg',
    'user_left_msg', 'mention', 'video_message',
)


class InvalidCommand(Exception):
    pass


class WatchdogRobot(TgramRobot):
    def remember_user(self, msg):
        update = {
            '_id': msg.from_user.id,
            'msg': msg.to_dict(),
            'join_date': datetime.utcnow(),
        }
        update_insert = {
            'first_join_date': datetime.utcnow(),
        }
        db.user.find_one_and_update(
            {'_id': update['_id']},
            {'$set': update, '$setOnInsert': update_insert},
            upsert=True,
        )

    def remember_chat(self, msg):
        update = {
            '_id': msg.chat.id,
            'msg': msg.to_dict(),
            'join_date': datetime.utcnow(),
        }
        update_insert = {
            'first_join_date': datetime.utcnow(),
        }
        db.chat.find_one_and_update(
            {'_id': update['_id']},
            {'$set': update, '$setOnInsert': update_insert},
            upsert=True,
        )

    def render_help(self):
        msg_types_data = '\n'.join(
            ' - %s' % x.replace('_', r'\_') for x in MSG_TYPES
        )
        return HELP.format(msg_types=msg_types_data)

    def get_chat_admin_ids(self, bot, chat_id):
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

    def build_user_name(self, user):
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

    def find_msg_types(self, msg):
        ret = set()
        for ent in chain(msg.entities, msg.caption_entities):
            if ent.type in ('url', 'text_link'):
                ret.add('link')
            elif ent.type  == 'email':
                ret.add('email')
            elif ent.type == 'mention':
                ret.add('mention')
        for user in msg.new_chat_members:
            if user.is_bot:
                ret.add('bot')
        if msg.sticker:
            ret.add('sticker')
        if msg.document and msg.document.mime_type == 'video/mp4':
            ret.add('gif')
        if msg.voice:
            ret.add('voice')
        if msg.document:
            ret.add('attachment')
        if msg.audio:
            ret.add('audio')
        if msg.photo:
            ret.add('photo')
        if msg.new_chat_members:
            ret.add('user_joined_msg')
        if msg.left_chat_member:
            ret.add('user_left_msg')
        if msg.video_note:
            ret.add('video_message')
        return ret

    def before_start_processing(self):
        self.bot_id = self.bot.get_me().id
        self.db = connect_db()

    def handle_start_help(self, bot, update):
        msg = update.effective_message
        if msg.chat.type == 'private':
            self.remember_user(msg)
            bot.send_message(
                chat_id=update.message.chat.id,
                text=self.render_help(),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )

    def safe_delete_msg(self, bot, msg):
        try:
            bot.delete_message(
                chat_id=msg.chat.id,
                message_id=msg.message_id
            )
        except Exception as ex:
            logging.error(ex)

    def handle_config(self, bot, update):
        msg = update.effective_message
        if msg.chat.type == 'private':
            self.remember_user(msg)
        if msg.from_user.id not in self.get_chat_admin_ids(bot, msg.chat.id):
            self.safe_delete_msg(bot, msg)
        elif msg.chat.type in ('group', 'supergroup'):
            out = ['*Chat config:*']
            for setting in VALID_SETTINGS:
                allowed = self.load_chat_setting(
                    msg.chat.id,
                    setting,
                    DEFAULT_SETTINGS[setting]
                )
                out.append(
                    ' - `%s`: %s' % (
                        setting, 'YES' if allowed else 'NO'
                    )
                )
            for msg_type in MSG_TYPES:
                allowed = self.load_chat_setting(
                    msg.chat.id,
                    'is_allowed_%s' % msg_type,
                    DEFAULT_IS_ALLOWED
                )
                out.append(
                    ' - `%s` allowed: %s' % (
                        msg_type, 'YES' if allowed else 'NO'
                    )
                )
            msg_text = '\n'.join(out)
            bot.send_message(
                chat_id=update.message.chat.id,
                text=msg_text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )

    def handle_stat(self, bot, update):
        msg = update.message
        if msg.chat.type == 'private':
            self.remember_user(msg)
        if msg.chat.type != 'private':
            pass
        elif msg.from_user.id not in SUPERUSER_IDS:
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
                    'type': 'delete',
                }
                events = list(db.log.find(query))
                chat_count = len(set((x['msg']['chat']['id'] for x in events)))
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

    def save_chat_setting(self, chat_id, option, value):
        OPTION_CACHE[(chat_id, option)] = value
        self.db.config.find_one_and_update(
            {'chat_id': chat_id, 'key': option},
            {'$set': {'value': value}},
            upsert=True,
        )

    def load_chat_setting(self, chat_id, option, default):
        try:
            value = OPTION_CACHE[(chat_id, option)]
        except KeyError:
            item = self.db.config.find_one(
                {'chat_id': chat_id, 'key': option}
            )
            if item:
                value = item['value']
            else:
                value = default
                OPTION_CACHE[(chat_id, option)] = value
        return value

    def handle_allow(self, bot, update):
        try:
            msg = update.effective_message
            if msg.chat.type == 'private':
                self.remember_user(msg)
            if msg.from_user.id not in self.get_chat_admin_ids(bot, msg.chat.id):
                self.safe_delete_msg(bot, msg)
            else:
                match = RE_ALLOW_COMMAND.match(msg.text)
                if not match:
                    raise InvalidCommand
                msg_type = match.group(1)
                if msg_type not in MSG_TYPES:
                    raise InvalidCommand
                self.save_chat_setting(
                    msg.chat.id, 'is_allowed_%s' % msg_type, True
                )
                bot.send_message(
                    msg.chat.id, '%ss are allowed now.' % msg_type.title(),
                    parse_mode=ParseMode.MARKDOWN
                )
        except InvalidCommand as ex:
            bot.send_message(msg.chat.id, 'Invalid command')

    def handle_set(self, bot, update):
        try:
            msg = update.effective_message
            if msg.chat.type == 'private':
                self.remember_user(msg)
            if msg.from_user.id not in self.get_chat_admin_ids(bot, msg.chat.id):
                self.safe_delete_msg(bot, msg)
            else:
                match = RE_SET_COMMAND.match(msg.text)
                if not match:
                    raise InvalidCommand
                setting_key = match.group(1)
                if setting_key not in VALID_SETTINGS:
                    raise InvalidCommand
                setting_value = match.group(2)
                if not setting_value in ('yes', 'no'):
                    raise InvalidCommand
                else:
                    setting_value = (setting_value == 'yes')
                self.save_chat_setting(
                    msg.chat.id, setting_key, setting_value
                )
                msg_text = 'Setting `%s` has been set to `%s`' % (
                    setting_key, setting_value
                )
                bot.send_message(
                    msg.chat.id, msg_text, parse_mode=ParseMode.MARKDOWN
                )
        except InvalidCommand as ex:
            bot.send_message(msg.chat.id, 'Invalid command')

    def handle_block(self, bot, update):
        try:
            msg = update.effective_message
            if msg.chat.type == 'private':
                self.remember_user(msg)
            if msg.from_user.id not in self.get_chat_admin_ids(bot, msg.chat.id):
                self.safe_delete_msg(bot, msg)
            else:
                match = RE_BLOCK_COMMAND.match(msg.text)
                if not match:
                    raise InvalidCommand
                msg_type = match.group(1)
                if msg_type not in MSG_TYPES:
                    raise InvalidCommand
                self.save_chat_setting(
                    msg.chat.id, 'is_allowed_%s' % msg_type, False
                )
                bot.send_message(
                    msg.chat.id, '%ss are blocked now' % msg_type.title()
                )
        except InvalidCommand as ex:
            bot.send_message(msg.chat.id, 'Invalid command')

    def moderate_message(self, bot, msg, msg_type):
        try:
            bot.delete_message(
                chat_id=msg.chat.id,
                message_id=msg.message_id
            )
        except Exception as ex:
            db.fail.save({
                'date': datetime.utcnow(),
                'error': str(ex),
                'traceback': format_exc(),
                'msg': msg.to_dict(),
            })
            raise
        else:
            db.log.save({
                'date': datetime.utcnow(),
                'text': msg.text,
                'type': 'delete',
                'reason': msg_type,
                'msg': msg.to_dict(),
            })
            if self.is_notification_enabled(msg.chat.id):
                msg_text = 'Message from %s deleted. Reason: %s' % (
                    self.build_user_name(msg.from_user), msg_type
                )
                bot.send_message(
                    chat_id=msg.chat.id, text=msg_text
                )

    def handle_any_message(self, bot, update):
        msg = update.effective_message
        if msg.chat.type == 'private':
            self.remember_user(msg)
            return
        # Do not block messages from admins
        if msg.from_user.id in self.get_chat_admin_ids(bot, msg.chat.id):
            return
        # Handle message from non-admin user
        types = self.find_msg_types(msg)
        if types:
            for msg_type in types:
                allowed = self.load_chat_setting(
                    msg.chat.id,
                    'is_allowed_%s' % msg_type,
                    DEFAULT_IS_ALLOWED
                )
                if not allowed:
                    self.moderate_message(bot, msg, msg_type)
                    break

    def is_notification_enabled(self, chat_id):
        return self.load_chat_setting(
            chat_id,
            'notify_actions',
            DEFAULT_SETTINGS['notify_actions'],
        )

    #def handle_new_chat_members(self, bot, update):
    #    msg = update.effective_message

    #    for user in msg.new_chat_members:
    #        # If bot is one of new_chat_members then that means
    #        # bot was added into new chat
    #        if user.id == self.bot_id:
    #            self.remember_chat(msg)

    #    # Do not block messages from admins
    #    if msg.from_user.id in self.get_chat_admin_ids(bot, msg.chat.id):
    #        return
    #    # Handle message from non-admin user
    #    user_allowed = self.load_chat_setting(
    #        msg.chat.id,
    #        'is_allowed_user',
    #        DEFAULT_IS_ALLOWED
    #    )
    #    bot_allowed = self.load_chat_setting(
    #        msg.chat.id,
    #        'is_allowed_bot',
    #        DEFAULT_IS_ALLOWED
    #    )
    #    if not bot_allowed or not user_allowed:
    #        for user in msg.new_chat_members:
    #            reason = None
    #            if not bot_allowed and user.is_bot:
    #                reason = 'bot'
    #            elif not user_allowed:
    #                reason = 'user'
    #            if reason:
    #                try:
    #                    bot.kick_chat_member(msg.chat.id, user.id)
    #                except Exception as ex:
    #                    db.fail.save({
    #                        'date': datetime.utcnow(),
    #                        'error': str(ex),
    #                        'traceback': format_exc(),
    #                        'msg': msg.to_dict(),
    #                    })
    #                    raise
    #                else:
    #                    db.log.save({
    #                        'date': datetime.utcnow(),
    #                        'text': msg.text,
    #                        'type': 'kick',
    #                        'reason': reason,
    #                        'msg': msg.to_dict(),
    #                    })
    #                    if self.is_notification_enabled(msg.chat.id):
    #                        msg_text = 'User %s removed. Reason: %s are not allowed' % (
    #                            self.build_user_name(user), reason
    #                        )
    #                        bot.send_message(
    #                            chat_id=msg.chat.id, text=msg_text
    #                        )

    def register_handlers(self, dispatcher):
        dispatcher.add_handler(CommandHandler(
            ['start', 'help'], self.handle_start_help)
        )
        dispatcher.add_handler(CommandHandler('stat', self.handle_stat))
        dispatcher.add_handler(RegexHandler(
            '^/watchdog_allow ', self.handle_allow
        ))
        dispatcher.add_handler(RegexHandler(
            '^/watchdog_block ', self.handle_block
        ))
        dispatcher.add_handler(CommandHandler(
            'watchdog_config', self.handle_config
        ))
        dispatcher.add_handler(CommandHandler(
            'watchdog_set', self.handle_set
        ))
        #dispatcher.add_handler(MessageHandler(
        #    Filters.status_update.new_chat_members, self.handle_new_chat_members
        #))
        dispatcher.add_handler(MessageHandler(
            (
                Filters.text | Filters.audio | Filters.document
                | Filters.photo | Filters.video | Filters.sticker
                | Filters.document | Filters.voice
                | Filters.video_note
                | Filters.status_update.left_chat_member
                | Filters.status_update.new_chat_members
            ),
            self.handle_any_message
        ))
        #dispatcher.add_handler(
        #    MessageHandler(Filters.all, self.handle_any_other)
        #)


if __name__ == '__main__':
    run_polling(WatchdogRobot)
