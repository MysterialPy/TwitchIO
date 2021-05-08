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

import datetime
from typing import Optional, Union, Set, TYPE_CHECKING

from .abcs import Messageable
from .chatter import Chatter, PartialChatter
from .models import BitsLeaderboard

if TYPE_CHECKING:
    from .websocket import WSConnection
    from .user import User


__all__ = ("Channel",)


class Channel(Messageable):

    __slots__ = ("_name", "_ws")

    __messageable_channel__ = True

    def __init__(self, name: str, websocket: "WSConnection"):
        self._name = name
        self._ws = websocket

    def __eq__(self, other):
        return other.name == self._name

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return f"<Channel name: {self.name}>"

    def _fetch_channel(self):
        return self  # Abstract method

    def _fetch_websocket(self):
        return self._ws  # Abstract method

    def _bot_is_mod(self):
        cache = self._ws._cache[self.name]  # noqa
        for user in cache:
            if user.name == self._ws.nick:
                try:
                    mod = user.is_mod
                except AttributeError:
                    return False

                return mod

    @property
    def name(self) -> str:
        """The channel name."""
        return self._name

    @property
    def chatters(self) -> Optional[Set[Union[Chatter, PartialChatter]]]:
        """The channels current chatters."""
        try:
            chatters = self._ws._cache[self._name]  # noqa
        except KeyError:
            return None

        return chatters

    def get_chatter(self, name: str) -> Optional[Union[Chatter, PartialChatter]]:
        """Retrieve a chatter from the channels user cache.

        Parameters
        -----------
        name: str
            The chatter's name to try and retrieve.

        Returns
        --------
        Union[:class:`twitchio.chatter.Chatter`, :class:`twitchio.chatter.PartialChatter`]
            Could be a :class:`twitchio.user.PartialChatter` depending on how the user joined the channel.
            Returns None if no user was found.
        """
        name = name.lower()

        try:
            cache = self._ws._cache[self._name]  # noqa
            for chatter in cache:
                if chatter.name == name:
                    return chatter

            return None
        except KeyError:
            return None

    async def user(self, force=False) -> "User":
        """|coro|
        Fetches the User from the api.

        Parameters
        -----------
        force: :class:`bool`
            Whether to force a fetch from the api, or try and pull from the cache. Defaults to `False`

        Returns
        --------
        :class:`twitchio.User` the user associated with the channel
        """
        return (await self._ws._client.fetch_users(login=[self._name], force=force))[0]

    async def fetch_bits_leaderboard(
        self, token: str, period: str = "all", user_id: int = None, started_at: datetime.datetime = None
    ) -> BitsLeaderboard:
        """|coro|
        Fetches the bits leaderboard for the channel. This requires an OAuth token with the bits:read scope.

        Parameters
        -----------
        token: :class:`str`
            the OAuth token with the bits:read scope
        period: Optional[:class:`str`]
            one of `day`, `week`, `month`, `year`, or `all`, defaults to `all`
        started_at: Optional[:class:`datetime.datetime`]
            the timestamp to start the period at. This is ignored if the period is `all`
        user_id: Optional[:class:`int`]
            the id of the user to fetch for
        """
        data = await self._ws._client._http.get_bits_board(token, period, user_id, started_at)
        return BitsLeaderboard(self._ws._client._http, data)

    async def whisper(self, content: str):
        """|coro|
        Whispers the user behind the channel. This will not work if the channel is the same as the one you are sending the message from.

        .. warning:
            Whispers are very unreliable on twitch. If you do not receive a whisper, this is probably twitch's fault, not the library's.

        Parameters
        -----------
        content: :class:`str`
            The content to send to the user
        """
        await self.send(f"/w {self.name} {content}")
