# -*- coding: utf-8 -*-

"""
The MIT License (MIT)

Copyright (c) 2017-2019 TwitchIO

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
import importlib
import inspect
import itertools
import sys
import threading
import traceback
import uuid
from typing import Union, List, Tuple

from .core import Command, AutoCog
from .errors import *
from .stringparser import StringParser
from twitchio.client import Client
from twitchio.dataclasses import Context
from twitchio.errors import ClientError
from twitchio.webhook import TwitchWebhookServer
from twitchio.websocket import WebsocketConnection


class Bot(Client):
    """Twitch IRC Bot.

    Parameters
    ------------
    irc_token: str
        The OAuth token to use for IRC.
    client_id: str:
        Your application ID, used for HTTP endpoints.
    prefix: str
        The bots prefix.
    nick: str
        The bots nick in lowercase.
    loop: [Optional]
        The asyncio event loop to use.
    initial_channels: list
        The initial channels for the bot to join on startup.
    webhook_server: bool [Optional]
        A bool indicating whether the built-in webhook server should be used.
    local_host: str [Optional]
        The local host the webhook server should run on.
    external_host: str [Optional]
        The external address the webhook_server should listen on.
    port: int [Optional]
        The port the webhook_server should be started on.
    callback: str [Optional]
        The pages as a string where the webhook_server should listen for events.

    Notes
    -------
    .. note::

        To enable the webhook server, the webhook_server parameter must be True.
        A local_host, external_host and port must also be provided.


        An optional parameter `callback` may be passed. This should be the page Twitch sends data to.
        A long random string, such as hex, is advised e.g `2t389hth892t3h898hweiogtieo`
    """

    def __init__(self, irc_token: str, api_token: str = None, *, client_id: str = None, prefix: Union[list, tuple, str],
                 nick: str, loop: asyncio.BaseEventLoop = None, initial_channels: Union[list, tuple] = None,
                 webhook_server: bool = False, local_host: str = None, external_host: str = None, callback: str = None,
                 port: int = None, **attrs):

        self.loop = loop or asyncio.get_event_loop()
        super().__init__(loop=self.loop, client_id=client_id, **attrs)
        self.nick = nick
        self.initial_channels = initial_channels

        self._ws = WebsocketConnection(bot=self, loop=self.loop, http=self.http, irc_token=irc_token,
                                       nick=nick, initial_channels=initial_channels, **attrs)

        self._webhook_server = None
        if webhook_server:
            self._webhook_server = TwitchWebhookServer(bot=self,
                                                       local=local_host,
                                                       external=external_host,
                                                       callback=callback,
                                                       port=port)
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=self._webhook_server.run_server, args=(loop,), daemon=True)
            thread.start()

        self.loop.create_task(self._prefix_setter(prefix))

        self.extra_listeners = {}
        self.commands = {}
        self.modules = {}
        self.cogs = {}
        self._aliases = {}
        self._checks = []
        self.prefixes = None

        self._init_methods()

    def _init_methods(self):
        commands = inspect.getmembers(self)

        for _, obj in commands:
            if not isinstance(obj, Command):
                continue

            obj.instance = self

            try:
                self.add_command(obj)
            except CommandError:
                traceback.print_exc()
                continue

    def add_command(self, command):
        if not isinstance(command, Command):
            raise TypeError('Commands passed may be a subclass of Command.')
        elif command.name in self.commands:
            raise CommandError(f'Failed to load command <{command.name}>, a command with that name already exists')
        elif not inspect.iscoroutinefunction(command._callback):
            raise CommandError(f'Failed to load command <{command.name}>. Commands must be coroutines.')

        self.commands[command.name] = command

        if not command.aliases:
            return

        for alias in command.aliases:
            if alias in self.commands:
                del self.commands[command.name]
                raise CommandError(
                    f'Failed to load command <{command.name}>, a command with that name/alias already exists.')

            self._aliases[alias] = command.name

    def remove_command(self, command):
        if command.aliases:
            for a in command.aliases:
                self._aliases.pop(a)

        try:
            del self.commands[command.name]
        except KeyError:
            # Not sure why this would happen, but people be people.
            pass

    def load_module(self, name: str):
        """Method which loads a module and its cogs.

        Parameters
        ------------
        name: str
            The name of the module to load in dot.path format.
        """
        if name in self.modules:
            return

        valid = False

        module = importlib.import_module(name)
        for _, member in inspect.getmembers(module):
            if inspect.isclass(member) and issubclass(member, AutoCog):
                member(self)._prepare(self)
                valid = True

        if hasattr(module, 'prepare'):
            module.prepare(self)
        elif not valid:
            del module
            del sys.modules[name]
            raise ImportError(f'Module <{name}> is missing a prepare method')

        if name not in self.modules:
            self.modules[name] = module

    def unload_module(self, name: str):
        """Method which unloads a module and its cogs/commands/events.

        Parameters
        ------------
        name: str
            The name of the module to load in dot.path format.
        """
        module = self.modules.pop(name, None)
        if not module:
            return

        for cogname, _ in inspect.getmembers(module):
            if cogname in self.cogs:
                self.remove_cog(cogname)

        try:
            module.breakdown(self)
        finally:
            del module
            del sys.modules[name]

    def add_cog(self, cog):
        """Method which loads a cog and adds its commands and events.

        Parameters
        ------------
        cog:
            An instance of the cog you wish to load.
        """
        members = inspect.getmembers(cog)

        for name, member in members:
            if isinstance(member, Command):
                member.instance = cog
                self.add_command(member)
            elif name.startswith('event_'):
                self.add_listener(member, name)

        self.cogs[type(cog).__name__] = cog

    def remove_cog(self, cogname: str):
        """Method which removes a cog and adds its commands and events.

        Parameters
        ------------
        cogname:
            The name of the cog you wish to remove.
        """
        cog = self.cogs.pop(cogname, None)
        if not cog:
            return

        for name, member in inspect.getmembers(cog):
            if isinstance(member, Command):
                self.remove_command(member)
            elif name.startswith('event_'):
                del self.extra_listeners[name]
            elif name in self.extra_listeners:
                del self.extra_listeners[member.__name__]

        try:
            unload = getattr(cog, f'_{cog.__name__}__unload')
        except AttributeError:
            pass
        else:
            unload(self)

        del cog

    def add_check(self, func):
        """Adds a global check to the bot.

        Parameters
        ------------
        func : callable
            The function or coroutine to add as a global check to the bot.
        """

        self._checks.append(func)

    def remove_check(self, func):
        """Remove a global check from the bot.

        Parameters
        ------------
        func : callable
            The function to remove as a global check from the bot.
        """

        self._checks.remove(func)

    def run(self):
        """A blocking call that initializes the IRC Bot event loop.

        This should be the last function to be called.

        .. warning::
            You do not need to use this function unless you are accessing the IRC Endpoints.
        .. warning::
            You do not use this function if you are using :meth:`.start`
        """
        loop = self.loop or asyncio.get_event_loop()

        loop.run_until_complete(self._ws._connect())

        try:
            loop.run_until_complete(self._ws._listen())
        except KeyboardInterrupt:
            pass
        finally:
            self._ws.teardown()

    async def start(self):
        """|coro|

        An asynchronous call which starts the IRC Bot event loop.

        This should only be used when integrating Twitch Bots with Discord Bots.
        :meth:`.run` should be used instead.

        .. warning::
            Do not use this function if you are using :meth:`.run`
        """
        await self._ws._connect()

        try:
            await self._ws._listen()
        except KeyboardInterrupt:
            pass
        finally:
            self._ws.teardown()

    async def _prefix_setter(self, item):
        if inspect.iscoroutinefunction(item):
            item = await item()
        elif callable(item):
            item = item()

        if isinstance(item, (list, tuple)):
            self.prefixes = item
        elif isinstance(item, str):
            self.prefixes = [item]
        else:
            raise ClientError(
                'Invalid prefix provided. A list, tuple, str or callable returning either should be used.')

    async def _get_prefixes(self, message):
        prefix = ret = self.prefixes
        if callable(prefix):
            ret = prefix(self, message.content)
            if inspect.isawaitable(ret):
                ret = await ret

        if isinstance(ret, (list, tuple)):
            ret = [p for p in ret if p]

        if isinstance(ret, str):
            ret = [ret]

        if not ret:
            raise ClientError('Invalid prefix provided.')

        return ret

    async def get_prefix(self, message):
        prefixes = await self._get_prefixes(message)

        prefix = None
        content = message.content

        for pre in prefixes:
            if content.startswith(pre):
                prefix = pre
                break

        return prefix

    def get_channel(self, name: str):
        """Retrieves a :class:`.Channel` from cache.

        Parameters
        ------------
        name: str
            The channel name to retrieve from cache.
        """
        cache = self._ws._channel_cache.get(name.lower())
        if cache:
            return cache['channel']

        return None

    async def join_channels(self, channels: Union[List[str], Tuple[str]]):
        """|coro|

        Join the specified channels.

        Parameters
        ------------
        channels: Union[List[str], Tuple[str]]
            The channels in either a list or tuple form to join.
        """
        await self._ws.join_channels(*channels)

    async def part_channels(self, channels: Union[List[str], Tuple[str]]):
        """|coro|

        Part the specified channels.

        Parameters
        ------------
        channels: Union[List[str], Tuple[str]]
            The channels in either a list or tuple form to part.
        """
        await self._ws.part_channels(*channels)

    async def get_context(self, message, cls=None):
        """|coro|

        A function which creates context with the given message.
        A custom context class can be passed.

        Parameters
        ------------
        message: :class:`.Message`
            The message to create context from.
        cls: Optional[Type]
            The optional custom class to create Context.

        Returns
        ---------
        :class:`.Context`
            The context created.
        """
        prefix = await self.get_prefix(message)

        if not cls:
            cls = Context

        ctx = cls(message=message, channel=message.channel, user=message.author, prefix=prefix)
        return ctx

    async def _dispatch(self, event: str, *args, **kwargs):
        await self._ws._dispatch(event, *args, **kwargs)

    async def _handle_checks(self, ctx, no_global_checks=False):
        command = ctx.command

        if no_global_checks:
            checks = [predicate for predicate in command._checks]
        else:
            checks = [predicate for predicate in itertools.chain(self._checks, command._checks)]

        if not checks:
            return True

        for predicate in checks:
            if inspect.iscoroutinefunction(predicate):
                result = await predicate(ctx)
            else:
                result = predicate(ctx)
            if not result:
                return predicate

            return result

    async def handle_commands(self, message, ctx=None):
        if ctx is None:
            try:
                ctx = await self.get_context(message)
            except Exception as e:
                return await self.event_error(e, message.raw_data)

        if not ctx.prefix:
            return

        content = message.content
        content = content[len(ctx.prefix)::].lstrip(' ')
        parsed = StringParser().process_string(content)

        message.clean_content = ' '.join(parsed.values())

        try:
            command = parsed.pop(0)
        except KeyError:
            return

        try:
            command = self._aliases[command]
        except KeyError:
            pass

        try:
            if command in self.commands:
                command = self.commands[command]
            elif command:
                raise CommandNotFound(f'<{command}> was not found.')
            else:
                return
        except Exception as e:
            ctx.command = None
            return await self.event_command_error(ctx, e)

        ctx.command = command
        instance = ctx.command.instance

        try:
            result = await self._handle_checks(ctx, command.no_global_checks)
        except Exception as e:
            return await self.event_command_error(ctx, e)
        else:
            if callable(result):
                return await self.event_command_error(ctx, CheckFailure(f'The command <{command.name}> failed to invoke'
                                                                        f' due to checks:: {result.__name__}'))
            elif not result:
                raise CheckFailure(f'The command <{command.name}> failed to invoke due to checks.')

        try:
            ctx.args, ctx.kwargs = await command.parse_args(instance, parsed)

            await self.global_before_hook(ctx)

            if ctx.command._before_invoke:
                await ctx.command._before_invoke(instance, ctx)

            if instance:
                await ctx.command._callback(instance, ctx, *ctx.args, **ctx.kwargs)
            else:
                await ctx.command._callback(ctx, *ctx.args, **ctx.kwargs)
        except Exception as e:
            if ctx.command.on_error:
                await ctx.command.on_error(instance, ctx, e)

            await self.event_command_error(ctx, e)

        try:
            # Invoke our after command hooks...
            if command._after_invoke:
                await ctx.command._after_invoke(ctx)
            await self.global_after_hook(ctx)
        except Exception as e:
            await self.event_command_error(ctx, e)

    async def global_before_hook(self, ctx):
        """|coro|

        Method which is called before any command is about to be invoked.

        This method is useful for setting up things before command invocation. E.g Database connections or
        retrieving tokens for use in the command.

        Parameters
        ------------
        ctx:
            The context used for command invocation.

        Examples
        ----------
        .. code:: py

            async def global_before_hook(self, ctx):
                # Make a database query for example to retrieve a specific token.
                token = db_query()

                ctx.token = token

            async def my_command(self, ctx):
                data = await self.create_clip(ctx.token, ...)

        Note
        ------
            The global_before_hook is called before any other command specific hooks.
        """
        pass

    async def global_after_hook(self, ctx):
        """|coro|

        Method which is called after any command is invoked regardless if it failed or not.

        This method is useful for cleaning up things after command invocation. E.g Database connections.

        Parameters
        ------------
        ctx:
            The context used for command invocation.

        Note
        ------
            The global_after_hook is called after the command successfully invokes.
        """
        pass

    async def event_webhook(self, data):
        """|coro|

        Event which is fired when a message from a Webhook subscription is received.

        Parameters
        ------------
        data: dict
            The webhook data as JSON.

        Warning
        ---------
            This event is only applicable when using the built in webhook server.
        """
        pass

    async def event_raw_pubsub(self, data):
        """|coro|

        Event which fires when a PubSub subscription event is received.

        Parameters
        ------------
        data:
            The raw data received from the PubSub event.

        Notes
        -------
        .. note::

            No parsing is done on the JSON and thus the data will be raw.
            A new event which parses the JSON will be released at a later date.
        """
        pass

    async def event_pubsub(self, data):
        raise NotImplementedError

    async def pubsub_subscribe(self, token: str, *topics):
        """|coro|

        Method which sends a LISTEN event over PubSub. This subscribes you to the topics provided.

        Parameters
        ------------
        token: str [Required]
            The oAuth token to use to subscribe.
        \*topics: Union[str] [Required]
            The topics to subscribe to.

        Raises
        --------
        WSConnectionFailure
            The PubSub websocket failed to connect.
        ClientError
            You reached the maximum amount of PubSub connections/Subscriptions.

        Returns
        ---------
        nonce: str
            The nonce associated with this subscription. Useful for validating responses.
        """
        nonce = uuid.uuid4().hex

        connection = await self._ws._pubsub_pool.delegate(*topics)
        await connection.subscribe(token, nonce, *topics)

        return nonce

    async def event_command_error(self, ctx, error):
        """|coro|

        Event called when an error occurs during command invocation.

        Parameters
        ------------
        ctx: :class:`.Context`
            The command context.
        error: :class:`.Exception`
            The exception raised while trying to invoke the command.
        """
        print('Ignoring exception in command: {0}:'.format(error), file=sys.stderr)
        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)

    async def event_mode(self, channel, user, status):
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

    async def event_userstate(self, user):
        """|coro|

        Event called when a USERSTATE is received from Twitch.

        Parameters
        ------------
        user: :class:`.User`
            User object containing relevant information to the USERSTATE.
        """
        pass

    async def event_raw_usernotice(self, channel, tags: dict):
        """|coro|

        Event called when a USERNOTICE is received from Twitch.
        Since USERNOTICE's can be fairly complex and vary, the following sub-events are available:

            :meth:`event_usernotice_subscription` :
            Called when a USERNOTICE Subscription or Re-subscription event is received.


        .. seealso::

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
        metadata: :class:`twitchio.dataclasses.NoticeSubscription`
            The object containing various metadata about the subscription event.
            For ease of use, this contains a :class:`.User` and :class:`.Channel`.
        """
        pass

    async def event_part(self, user):
        """|coro|

        Event called when a PART is received from Twitch.

        Parameters
        ------------
        user: :class:`.User`
            User object containing relevant information to the PART.
        """
        pass

    async def event_join(self, user):
        """|coro|

        Event called when a JOIN is received from Twitch.

        Parameters
        ------------
        user: :class:`.User`
            User object containing relevant information to the JOIN.
        """
        pass

    async def event_message(self, message):
        """|coro|

        Event called when a PRIVMSG is received from Twitch.

        Parameters
        ------------
        message: :class:`.Message`
            Message object containing relevant information.
        """
        await self.handle_commands(message)

    async def event_error(self, error: Exception, data=None):
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

            @bot.event
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

            @bot.event
            async def event_ready():
                print(f'Logged into Twitch | {bot.nick}')
        """
        pass

    async def event_raw_data(self, data):
        """|coro|

        Event called with the raw data received by Twitch.

        Parameters
        ------------
        data: str
            The raw data received from Twitch.

        Example
        ---------
        .. code:: py

            @bot.event
            async def event_raw_data(data):
                print(data)
        """
        pass

    def command(self, *, name: str = None, aliases: Union[list, tuple] = None, cls=Command):
        """Decorator which registers a command on the bot.

        Commands must be a coroutine.

        Parameters
        ------------
        name: str [Optional]
            The name of the command. By default if this is not supplied, the function name will be used.
        aliases: Union[list, tuple] [Optional]
            The command aliases. This must be a list or tuple.
        cls: class [Optional]
            The custom command class to override the default class. This must be similar to :class:`.Command`.
        no_global_checks : Optional[bool]
            Whether or not the command should abide by global checks. Defaults to False, which checks global checks.

        Raises
        --------
        TypeError
            Cls is not a class.
        """

        if not inspect.isclass(cls):
            raise TypeError(f'cls must be of type <class> not <{type(cls)}>')

        def decorator(func):
            cmd_name = name or func.__name__

            command = cls(name=cmd_name, func=func, aliases=aliases, instance=None)
            self.add_command(command)

            return command

        return decorator

    def event(self, func):
        """Decorator which adds an event listener to the bot.

        Example
        ---------
        .. code:: py

            @bot.event
            async def event_raw_data(data):
                print(data)

            @bot.event
            async def event_message(message):
                print(message.content)
                await bot.handle_commands(message)
        """
        if not inspect.iscoroutinefunction(func):
            raise TypeError('Events must be coroutines.')

        setattr(self, func.__name__, func)
        return func

    def check(self, func):
        """A decorator that adds a global check to the bot.

        This decorator allows regular functions or coroutines to be added to the bot.
        Global checks are ran before any other command specific checks.

        As with all other checks, the check(predicate), must contain a sole parametere of Context.

        Parameters
        ------------
        func : callable
            A regular function or coroutine to add as a global check.

        Examples
        ----------
        .. code::

            @bot.check
            async def my_global_check(self, ctx):
                return ctx.author.is_mod
        """
        self._checks.append(func)
        return func

    def add_listener(self, func, name: str = None):
        """Method which adds a coroutine as an extra listener.

        This can be used to add extra event listeners to the bot.

        Parameters
        ------------
        func: coro [Required]
            The coroutine to assign as a listener.
        name: str [Required]
            The event to register. E.g "event_message".
        """
        if not inspect.iscoroutinefunction(func):
            raise TypeError('Events must be coroutines.')

        name = name or func.__name__

        if name not in self.extra_listeners:
            self.extra_listeners[name] = [func]
        else:
            self.extra_listeners[name].append(func)

    def listen(self, event: str = None):
        """Decorator which adds a coroutine as a listener to an event.

        This can be used in place of :meth:`.event` or when more than one of the same event is required.

        Parameters
        ------------
        event: str [Optional]
            The event to listen to in the form of a string. E.g "event_message".

        Example
        ----------
        .. code:: py

            @bot.event()
            async def event_message(message):
            print(message.content)

            @bot.listen("event_message")
            async def extra_message(message):
            print(message.content)
        """

        def wrapper(func):
            self.add_listener(func, event)

            return func

        return wrapper

    async def modify_webhook_subscription(self, *, callback=None, mode, topic, lease_seconds=0, secret=None):
        """|coro|

        Creates a webhook subscription.

        Parameters
        ----------
        callback: Optional[str]
            The URL which will be called to verify the subscripton and on callback.
            If there's a webhook server running on the bot the callback will be automatically added.
        mode: :class:`.WebhookMode`
            Mode which describes whether the subscription should be created or not.
        topic: :class:`.Topic`
            Details about the subscription.
        lease_seconds: Optional[int]
            How many seconds the subscription should last. Defaults to 0, maximum is 846000.
        secret: Optional[str]
            A secret string which Twitch will use to add the `X-Hub-Signature` header to webhook requests.
            You can use this to verify the POST request came from Twitch using `sha256(secret, body)`.

        Raises
        --------
        Exception
            No callback url was specified and there is no webhook server running to retrieve a callback url from.

        HTTPException
            Bad request while modifying the subscription.
        """

        if callback is None:
            if self._webhook_server is None:
                raise Exception('No callback passed and no webhook server running to retrieve a callback url from.')

            callback = f'{self._webhook_server.external}:{self._webhook_server.port}/{self._webhook_server.callback}'

        await super().modify_webhook_subscription(
            callback=callback, mode=mode, topic=topic, lease_seconds=lease_seconds, secret=secret
        )
