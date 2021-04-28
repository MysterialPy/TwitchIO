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

import asyncio
import inspect
import warnings
import logging
import traceback
import sys
from typing import Union, Callable, List, Optional, Tuple, Any

from . import models
from .websocket import WSConnection
from .http import TwitchHTTP
from .channel import Channel
from .message import Message
from .user import User, PartialUser, SearchUser
from .cache import user_cache, id_cache

__all__ = ("Client",)

logger = logging.getLogger("twitchio.client")


class Client:
    """TwitchIO Client object that is used to interact with the Twitch API and connect to Twitch IRC over websocket.

    Parameters
    ------------
    token: :class:`str`
        An OAuth Access Token to login with on IRC and interact with the API.
    client_secret: Optional[:class:`str`]
        An optional application Client Secret used to generate Access Tokens automatically.
    initial_channels: Optional[Union[:class:`list`, :class:`tuple`, Callable]]
        An optional list, tuple or callable which contains channel names to connect to on startup.
        If this is a callable, it must return a list or tuple.
    loop: Optional[:class:`asyncio.AbstractEventLoop`]
        The event loop the client will use to run.
    heartbeat: Optional[float]
        An optional float in seconds to send a PING message to the server. Defaults to 30.0.

    Attributes
    ------------
    loop: :class:`asyncio.AbstractEventLoop`
        The event loop the Client uses.
    """

    def __init__(
        self,
        token: str,
        *,
        client_secret: str = None,
        initial_channels: Union[list, tuple, Callable] = None,
        loop: asyncio.AbstractEventLoop = None,
        heartbeat: Optional[float] = 30.0,
    ):

        self.loop: asyncio.AbstractEventLoop = loop or asyncio.get_event_loop()
        self._heartbeat = heartbeat

        token = token.replace("oauth:", "")

        self._http = TwitchHTTP(self, api_token=token, client_secret=client_secret)
        self._connection = WSConnection(
            client=self, token=token, loop=self.loop, initial_channels=initial_channels, heartbeat=heartbeat
        )

        self._events = {}
        self._waiting: List[Tuple[str, Callable[[...], bool], asyncio.Future]] = []

    @classmethod
    def from_client_credentials(
        cls, client_id: str, client_secret: str, *, loop: asyncio.AbstractEventLoop = None
    ) -> "Client":
        """
        creates a client application token from your client credentials.

        .. warning:

            this is not suitable for logging in to IRC.

        .. note:

            This classmethod skips :meth:`~.__init__`

        Parameters
        ------------
        client_id: :class`str`

        client_secret: :class:`str`
            An application Client Secret used to generate Access Tokens automatically.
        loop: Optional[:class:`asyncio.AbstractEventLoop`]
            The event loop the client will use to run.

        Returns
        --------
        A new :class:`Client` instance
        """
        self = cls.__new__(cls)
        self.loop = loop or asyncio.get_event_loop()
        self._http = TwitchHTTP(self, client_id=client_id, client_secret=client_secret)
        self._connection = WSConnection(
            client=self, loop=self.loop, initial_channels=None, heartbeat=self._heartbeat
        )  # The only reason we're even creating this is to avoid attribute errors
        self._events = {}
        self._waiting = []
        return self

    def run(self):
        try:
            self.loop.create_task(self._connection._connect())
            self.loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.loop.create_task(self.close())

    async def close(self):
        # TODO session close
        await self._connection._close()

    def run_event(self, event_name, *args):
        name = f"event_{event_name}"
        logger.debug(f"dispatching event {event_name}")

        async def wrapped(func):
            try:
                await func(*args)
            except Exception as e:
                if name == "event_error":
                    # don't enter a dispatch loop!
                    raise

                self.run_event("error", e)

        inner_cb = getattr(self, name, None)
        if inner_cb is not None:
            if inspect.iscoroutinefunction(inner_cb):
                self.loop.create_task(wrapped(inner_cb))
            else:
                warnings.warn(f"event '{name}' callback is not a coroutine", category=RuntimeWarning)

        if name in self._events:
            for event in self._events[name]:
                self.loop.create_task(wrapped(event))

        for e, check, future in self._waiting:
            if e == event_name:
                if check(*args):
                    future.set_result(args)

    def add_event(self, callback: Callable, name: str = None) -> None:
        if not inspect.iscoroutine(callback) and not inspect.iscoroutinefunction(callback):
            raise ValueError("callback must be a coroutine")

        event_name = name or callback.__name__
        callback._event = event_name  # used to remove the event

        if event_name in self._events:
            self._events[event_name].append(callback)

        else:
            self._events[event_name] = [callback]

    def remove_event(self, callback: Callable) -> bool:
        if not hasattr(callback, "_event"):
            raise ValueError("callback is not a registered event")

        if callback in self._events[callback._event]:
            self._events[callback._event].remove(callback)
            return True

        return False

    def event(self, name: str = None) -> Callable:
        def decorator(func: Callable) -> Callable:
            self.add_event(func, name)
            return func

        return decorator

    async def wait_for(
        self, event: str, predicate: Callable[[], bool] = lambda *a: True, *, timeout=60.0
    ) -> Tuple[Any]:
        """|coro|

        Waits for an event to be dispatched, then returns the events data

        Parameters
        -----------
        event: :class:`str`
            The event to wait for. Do not include the `event_` prefix
        predicate: Callable[[...], bool]
            A check that is fired when the desired event is dispatched. if the check returns false,
            the waiting will continue until the timeout.
        timeout: :class:`int`
            How long to wait before timing out and raising an error.

        Returns
        --------
            The arguments passed to the event.
        """
        fut = self.loop.create_future()
        tup = (event, predicate, fut)
        self._waiting.append(tup)
        values = await asyncio.wait_for(fut, timeout, loop=self.loop)
        return values

    @id_cache()
    def get_channel(self, name: str) -> Optional[Channel]:
        """Retrieve a channel from the cache.

        Parameters
        -----------
        name: str
            The channel name to retrieve from cache. Returns None if no channel was found.

        Returns
        --------
            :class:`.Channel`
        """
        name = name.lower()

        if name in self._connection._cache:
            # Basically the cache doesn't store channels naturally, instead it stores a channel key
            # With the associated users as a set.
            # We create a Channel here and return it only if the cache has that channel key.

            channel = Channel(name=name, websocket=self._connection)
            return channel

    async def join_channels(self, channels: Union[List[str], Tuple[str]]):
        """|coro|

        Join the specified channels.

        Parameters
        ------------
        channels: Union[List[str], Tuple[str]]
            The channels in either a list or tuple form to join.
        """
        await self._connection.join_channels(*channels)

    async def part_channels(self, channels: Union[List[str], Tuple[str]]):
        """|coro|
        Part the specified channels.

        Parameters
        ------------
        channels: Union[List[str], Tuple[str]]
            The channels in either a list or tuple form to part.
        """
        await self._connection.part_channels(*channels)

    @property
    def connected_channels(self) -> List[Channel]:
        """A list of currently connected :class:`.Channel`"""
        return [self.get_channel(x) for x in self._connection._cache.keys()]

    @property
    def events(self):
        """A mapping of events name to coroutine."""
        return self._events

    @property
    def nick(self):
        """The IRC bots nick."""
        return self._http.nick or self._connection.nick

    def create_user(self, user_id: int, user_name: str) -> PartialUser:
        """
        A helper method to create a :class:`twitchio.PartialUser` from a user id and user name.

        Parameters
        -----------
        user_id: :class:`int`
            The id of the user
        user_name: :class:`str`
            The name of the user

        Returns
        --------
            :class:`twitchio.PartialUser`
        """
        return PartialUser(self._http, user_id, user_name)

    @user_cache()
    async def fetch_users(
        self, names: List[str] = None, ids: List[int] = None, token: str = None, force=False
    ) -> List[User]:
        """|coro|
        Fetches users from the helix API

        Parameters
        -----------
        names: Optional[List[:class:`str`]]
            usernames of people to fetch
        ids: Optional[List[:class:`str`]]
            ids of people to fetch
        token: Optional[:class:`str`]
            An optional OAuth token to use instead of the bot OAuth token
        force: :class:`bool`
            whether to force a fetch from the api, or check the cache first. Defaults to False

        Returns
        --------
        List[:class:`twitchio.User`]
        """
        # the forced argument doesnt actually get used here, it gets used by the cache wrapper.
        # But we'll include it in the args here so that sphinx catches it
        assert names or ids
        data = await self._http.get_users(ids, names, token=token)
        return [User(self._http, x) for x in data]

    async def fetch_clips(self, ids: List[str]):
        """|coro|

        Fetches clips by clip id.
        To fetch clips by user id, use :meth:`twitchio.PartialUser.fetch_clips`

        Parameters
        -----------
        ids: List[:class:`str`]
            A list of clip ids

        Returns
        --------
            List[:class:`twitchio.Clip`]
        """
        data = await self._http.get_clips(ids=ids)
        return [models.Clip(self._http, d) for d in data]

    async def fetch_videos(
        self,
        ids: List[int] = None,
        game_id: int = None,
        user_id: int = None,
        period=None,
        sort=None,
        type=None,
        language=None,
    ):
        """|coro|
        Fetches videos by id, game id, or user id

        Parameters
        -----------
        ids: Optional[List[:class:`int`]]
            A list of video ids
        game_id: Optional[:class:`int`]
            A game to fetch videos from
        user_id: Optional[:class:`int`]
            A user to fetch videos from. See :meth:`twitchio.PartialUser.fetch_videos`
        period: Optional[:class:`str`]
            The period for which to fetch videos. Valid values are `all`, `day`, `week`, `month`. Defaults to `all`.
            Cannot be used when video id(s) are passed
        sort: :class:`str`
            Sort orders of the videos. Valid values are `time`, `trending`, `views`, Defaults to `time`.
            Cannot be used when video id(s) are passed
        type: Optional[:class:`str`]
            Type of the videos to fetch. Valid values are `upload`, `archive`, `highlight`. Defaults to `all`.
            Cannot be used when video id(s) are passed
        language: Optional[:class:`str`]
            Language of the videos to fetch. Must be an `ISO-639-1 <https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes>`_ two letter code.
            Cannot be used when video id(s) are passed

        Returns
        --------
            List[:class:`twitchio.Video`]
        """
        from .models import Video

        data = await self._http.get_videos(
            ids, user_id=user_id, game_id=game_id, period=period, sort=sort, type=type, language=language
        )
        return [Video(self._http, x) for x in data]

    async def fetch_cheermotes(self, user_id: int = None):
        """|coro|

        Fetches cheermotes from the twitch API

        Parameters
        -----------
        user_id: Optional[:class:`int`]
            The channel id to fetch from.

        Returns
        --------
            List[:class:`twitchio.CheerEmote`]
        """
        data = await self._http.get_cheermotes(str(user_id) if user_id else None)
        return [models.CheerEmote(self._http, x) for x in data]

    async def fetch_top_games(self) -> List[models.Game]:
        """|coro|
        Fetches the top games from the api

        Returns
        --------
            List[:class:`twitchio.Game`]
        """
        data = await self._http.get_top_games()
        return [models.Game(d) for d in data]

    async def fetch_games(self, ids: List[int] = None, names: List[str] = None) -> List[models.Game]:
        """|coro|
        Fetches games by id or name.
        At least one id or name must be provided

        Parameters
        -----------
        ids: Optional[List[:class:`int`]]
            An optional list of game ids
        names: Optional[List[:class:`str`]]
            An optional list of game names

        Returns
        --------
            List[:class:`twitchio.Game`]
        """
        data = await self._http.get_games(ids, names)
        return [models.Game(d) for d in data]

    async def fetch_tags(self, ids: List[str] = None):
        """|coro|
        Fetches stream tags.

        Parameters
        -----------
        ids: Optional[List[:class:`str`]]
            The ids of the tags to fetch

        Returns
        --------
            List[:class:`twitchio.Tag`]
        """
        data = await self._http.get_stream_tags(ids)
        return [models.Tag(x) for x in data]

    async def search_categories(self, query: str):
        """|coro|
        Searches twitches categories

        Parameters
        -----------
        query: :class:`str`
            The query to search for

        Returns
        --------
            List[:class:`twitchio.Game`]
        """
        data = await self._http.get_search_categories(query)
        return [models.Game(x) for x in data]

    async def search_channels(self, query: str, *, live_only=False):
        """|coro|
        Searches channels for the given query

        Parameters
        -----------
        query: :class:`str`
            The query to search for
        live_only: :class:`bool`
            Only search live channels. Defaults to False

        Returns
        --------
            List[:class:`twitchio.SearchUser`]
        """
        data = await self._http.get_search_channels(query, live=live_only)
        return [SearchUser(self._http, x) for x in data]

    async def delete_videos(self, token: str, ids: List[int]) -> List[int]:
        """|coro|
        Delete videos from the api. Returns the video ids that were successfully deleted.

        Parameters
        -----------
        token: :class:`str`
            An oauth token with the channel:manage:videos scope
        ids: List[:class:`int`]
            A list of video ids from the channel of the oauth token to delete

        Returns
        --------
            List[:class:`int`]
        """
        resp = []
        for chunk in [ids[x : x + 3] for x in range(0, len(ids), 3)]:
            resp.append(await self._http.delete_videos(token, chunk))

        return resp

    async def get_webhook_subscriptions(self):
        """|coro|
        Fetches your current webhook subscriptions. Requires your bot to be logged in with an app access token.

        Returns
        --------
            List[:class:`twitchio.WebhookSubscription`]
        """
        data = await self._http.get_webhook_subs()
        return [models.WebhookSubscription(x) for x in data]

    async def event_token_expired(self):
        """|coro|

        A special event called when the oauth token expires. This is a hook into the http system, it will call this
        when a call to the api fails due to a token expiry. This function should return either a new token, or `None`.
        Returning `None` will cause the client to attempt an automatic token generation.

        .. note::
            This event is a callback hook. It is not a dispatched event. Any errors raised will be passed to the
            :ref:`~event_error` event.
        """
        return None

    async def event_mode(self, channel: Channel, user: User, status: str):
        """|coro|

        Event called when a MODE is received from Twitch.

        Parameters
        ------------
        channel: :class:`.Channel`
            Channel object relevant to the MODE event.
        user: :class:`.User`
            User object containing relevant information to the MODE.
        status: str
            The JTV status received by Twitch. Could be either o+ or o-.
            Indicates a moderation promotion/demotion to the :class:`.User`
        """
        pass

    async def event_userstate(self, user: User):
        """|coro|

        Event called when a USERSTATE is received from Twitch.

        Parameters
        ------------
        user: :class:`.User`
            User object containing relevant information to the USERSTATE.
        """
        pass

    async def event_raw_usernotice(self, channel: Channel, tags: dict):
        """|coro|

        Event called when a USERNOTICE is received from Twitch.
        Since USERNOTICE's can be fairly complex and vary, the following sub-events are available:

            :meth:`event_usernotice_subscription` :
            Called when a USERNOTICE Subscription or Re-subscription event is received.

        .. tip::

            For more information on how to handle USERNOTICE's visit:
            https://dev.twitch.tv/docs/irc/tags/#usernotice-twitch-tags


        Parameters
        ------------
        channel: :class:`.Channel`
            Channel object relevant to the USERNOTICE event.
        tags : dict
            A dictionary with the relevant information associated with the USERNOTICE.
            This could vary depending on the event.
        """
        pass

    async def event_usernotice_subscription(self, metadata):
        """|coro|

        Event called when a USERNOTICE subscription or re-subscription event is received from Twitch.

        Parameters
        ------------
        metadata: :class:`NoticeSubscription`
            The object containing various metadata about the subscription event.
            For ease of use, this contains a :class:`User` and :class:`Channel`.

        """
        pass

    async def event_part(self, user: User):
        """|coro|

        Event called when a PART is received from Twitch.

        Parameters
        ------------
        user: :class:`.User`
            User object containing relevant information to the PART.
        """
        pass

    async def event_join(self, channel: Channel, user: User):
        """|coro|

        Event called when a JOIN is received from Twitch.

        Parameters
        ------------
        channel: :class:`.Channel`
            The channel associated with the JOIN.
        user: :class:`.User`
            User object containing relevant information to the JOIN.
        """
        pass

    async def event_message(self, message: Message):
        """|coro|

        Event called when a PRIVMSG is received from Twitch.

        Parameters
        ------------
        message: :class:`.Message`
            Message object containing relevant information.
        """
        pass

    async def event_error(self, error: Exception, data: str = None):
        """|coro|

        Event called when an error occurs while processing data.

        Parameters
        ------------
        error: Exception
            The exception raised.
        data: str
            The raw data received from Twitch. Depending on how this is called, this could be None.

        Example
        ---------
        .. code:: py

            @bot.event()
            async def event_error(error, data):
                traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)
        """
        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)

    async def event_ready(self):
        """|coro|

        Event called when the Bot has logged in and is ready.

        Example
        ---------
        .. code:: py

            @bot.event()
            async def event_ready():
                print(f'Logged into Twitch | {bot.nick}')
        """
        pass

    async def event_raw_data(self, data: str):
        """|coro|

        Event called with the raw data received by Twitch.

        Parameters
        ------------
        data: str
            The raw data received from Twitch.

        Example
        ---------
        .. code:: py

            @bot.event()
            async def event_raw_data(data):
                print(data)
        """
        pass
