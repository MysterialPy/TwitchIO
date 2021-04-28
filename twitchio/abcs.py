# -*- coding: utf-8 -*-

"""
The MIT License (MIT)

Copyright (c) 2017-2021 TwitchIO

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""

import abc
import time

from .cooldowns import RateBucket
from .errors import *


class IRCLimiterMapping:

    def __init__(self):
        self.buckets = {}

    def get_bucket(self, channel: str, method: str) -> RateBucket:
        try:
            bucket = self.buckets[channel]
        except KeyError:
            bucket = RateBucket(method=method)
            self.buckets[channel] = bucket

        if bucket.method != method:
            bucket.method = method
            if method == 'mod':
                bucket.limit = bucket.MODLIMIT
            else:
                bucket.limit = bucket.IRCLIMIT

            self.buckets[channel] = bucket

        return bucket


limiter = IRCLimiterMapping()


class Messageable(metaclass=abc.ABCMeta):

    __slots__ = ()

    __invalid__ = ('ban', 'unban', 'timeout', 'untimeout', 'w', 'colour', 'color', 'mod',
                   'unmod', 'clear', 'subscribers', 'subscriberoff', 'slow', 'slowoff',
                   'r9k', 'r9koff', 'emoteonly', 'emoteonlyoff', 'host', 'unhost')

    @abc.abstractmethod
    def _get_channel(self):
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def _get_socket(self):
        raise NotImplementedError

    @abc.abstractmethod
    def _get_method(self):
        raise NotImplementedError

    def check_bucket(self, channel):
        ws = self._get_socket

        try:
            bot = ws._channel_cache[channel]['bot']
        except KeyError:
            bucket = limiter.get_bucket(channel=channel, method='irc')
        else:
            if bot.is_mod:
                bucket = limiter.get_bucket(channel=channel, method='mod')
            else:
                bucket = limiter.get_bucket(channel=channel, method='irc')

        now = time.time()
        bucket.update()

        if bucket.limited:
            raise TwitchIOBException(f'IRC Message rate limit reached for channel <{channel}>.'
                                     f' Please try again in {bucket._reset - now:.2f}s')

    @staticmethod
    def check_content(channel, content: str):
        if not channel:
            raise TwitchIOBException('Invalid channel for Messageable. Must be channel or user.')

        if len(content) > 500:
            raise InvalidContent('Length of message can not be > 500.')

    async def send(self, content: str):
        """|coro|

        Send a message to the destination associated with the dataclass.

        Destination will either be a channel or user.
        Chat commands are not allowed to be invoked with this method.

        Parameters
        ------------
        content: str
            The content you wish to send as a message. The content must be a string.

        Raises
        --------
        TwitchIOBException
            Invalid destination.
        InvalidContent
            Invalid content.
        """
        content = str(content)

        channel, user = self._get_channel()
        method = self._get_method()

        self.check_content(channel, content)

        if content.startswith(('.', '/')):
            if content.lstrip('./').startswith(self.__invalid__):
                raise InvalidContent('UnAuthorised chat command for send. Use built in method(s).')

        ws = self._get_socket
        self.check_bucket(channel)

        if method == 'User':
            content = f'.w {user} {content}'

        await ws.send_privmsg(channel, content=content)

    async def clear(self):
        """|coro|

        Method which sends .clear to Twitch and clears the chat.
        """

        ws = self._get_socket
        channel, _ = self._get_channel()

        self.check_bucket(channel)

        await ws.send_privmsg(channel, content=f'.clear')

    async def slow(self):
        """|coro|

        Method which sends a .slow to Twitch and sets the channel to slowmode.
        """

        ws = self._get_socket
        channel, _ = self._get_channel()

        self.check_bucket(channel)

        await ws.send_privmsg(channel, content=f'.slow')

    async def unslow(self):
        """|coro|

        Method which sends a .slowoff to Twitch and sets the channel to slowmode off.
        """

        ws = self._get_socket
        channel, _ = self._get_channel()

        self.check_bucket(channel)

        await ws.send_privmsg(channel, content=f'.slowoff')

    async def slow_off(self):
        """|coro|

        Alias to unslow.
        """
        await self.unslow()

    async def timeout(self, user: str, duration: int=600, reason: str=''):
        """|coro|

        Method which sends a .timeout command to Twitch.

        Parameters
        ------------
        user: str
            The user you wish to timeout.
        duration: int
            The duration in seconds to timeout the user.
        reason: Optional[str]
            The reason you timed out the user.
        """

        ws = self._get_socket
        channel, _ = self._get_channel()

        self.check_bucket(channel)

        await ws.send_privmsg(channel, content=f'.timeout {user} {duration} {reason}')

    async def untimeout(self, user: str):
        """|coro|

        Method which sends a .untimeout command to Twitch.

        Parameters
        ------------
        user: str
            The user you wish to untimeout.
        """

        ws = self._get_socket
        channel, _ = self._get_channel()

        self.check_bucket(channel)

        await ws.send_privmsg(channel, content=f'.untimeout {user}')

    async def ban(self, user: str, reason: str=''):
        """|coro|

        Method which sends a .ban command to Twitch.

        Parameters
        ------------
        user: str
            The user you would like to ban.
        reason: Optional[str]
            The reason you banned this user.
        """

        ws = self._get_socket
        channel, _ = self._get_channel()

        self.check_bucket(channel)

        await ws.send_privmsg(channel, content=f'.ban {user} {reason}')

    async def unban(self, user: str):
        """|coro|

        Method which sends a .unban command to Twitch.

        Parameters
        ------------
        user: str
            The user you wish to unban.
        """

        ws = self._get_socket
        channel, _ = self._get_channel()

        self.check_bucket(channel)

        await ws.send_privmsg(channel, content=f'.unban {user}')

    async def send_me(self, content: str):
        """|coro|

        Method which sends .me along with your content.

        Parameters
        ------------
        content: str
            The message you wish to send.

        Raises
        --------
        InvalidContent
            The content exceeded 500 characters.
        """

        ws = self._get_socket
        channel, _ = self._get_channel()

        self.check_bucket(channel)
        self.check_content(channel, content)

        await ws.send_privmsg(channel, content=f'.me {content}')

    async def colour(self, colour: str):
        """Send a colour change request to Twitch.

        Parameters
        ------------
        colour: str
            A predefined colour listed below. Turbo Users may use a valid hex code. e.g #233233

            Blue
            BlueViolet
            CadetBlue
            Chocolate
            Coral
            DodgerBlue
            FireBrick
            GoldenRod
            Green
            HotPink
            OrangeRed
            Red
            SeaGreen
            SpringGreen
            YellowGreen
        """
        ws = self._get_socket
        channel, _ = self._get_channel()

        self.check_bucket(channel)
        await ws.send_privmsg(channel, content=f'.color {colour}')

    async def color(self, colour: str):
        """An alias to colour."""
        await self.colour(colour)

