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

import importlib
import inspect
import sys
import traceback
from typing import Callable, Optional, Union, Coroutine

from twitchio.client import Client
from .core import *
from .errors import *
from .meta import Cog
from .stringparser import StringParser
from .utils import _CaseInsensitiveDict


class Bot(Client):
    def __init__(
        self,
        token: str,
        *,
        prefix: Union[str, list, tuple, set, Callable, Coroutine],
        client_secret: str = None,
        initial_channels: Union[list, tuple, Callable] = None,
        heartbeat: Optional[float] = 30.0,
        **kwargs,
    ):
        super().__init__(
            token=token, client_secret=client_secret, initial_channels=initial_channels, heartbeat=heartbeat
        )

        self._prefix = prefix

        if kwargs.get("case_insensitive", False):
            self._commands = _CaseInsensitiveDict()
            self._command_aliases = _CaseInsensitiveDict()
        else:
            self._commands = {}
            self._command_aliases = {}

        self._modules = {}
        self._cogs = {}
        self._checks = []

        self.__init__commands__()

    def __init__commands__(self):
        commands = inspect.getmembers(self)

        for _, obj in commands:
            if not isinstance(obj, Command):
                continue

            obj._instance = self

            try:
                self.add_command(obj)
            except TwitchCommandError:
                traceback.print_exc()
                continue

    async def __get_prefixes__(self, message):
        ret = self._prefix

        if callable(self._prefix):
            if inspect.iscoroutinefunction(self._prefix):
                ret = await self._prefix(self, message)
            else:
                ret = self._prefix(self, message)

        if not isinstance(ret, (list, tuple, set, str)):
            raise TypeError(f"Prefix must be of either class <list, tuple, set, str> not <{type(ret)}>")

        return ret

    async def get_prefix(self, message):
        # TODO Docs
        prefixes = await self.__get_prefixes__(message)

        if not isinstance(prefixes, str):
            for prefix in prefixes:
                if message.content.startswith(prefix):
                    return prefix
        elif message.content.startswith(prefixes):
            return prefixes
        else:
            return None

    def add_command(self, command: Command):
        """Method which registers a command for use by the bot.

        Parameters
        ------------
        command: :class:`.Command`
            The command to register.
        """
        if not isinstance(command, Command):
            raise TypeError("Commands passed must be a subclass of Command.")
        elif command.name in self.commands:
            raise TwitchCommandError(
                f"Failed to load command <{command.name}>, a command with that name already exists."
            )
        elif not inspect.iscoroutinefunction(command._callback):
            raise TwitchCommandError(f"Failed to load command <{command.name}>. Commands must be coroutines.")

        self.commands[command.name] = command

        if not command.aliases:
            return

        for alias in command.aliases:
            if alias in self.commands:
                del self.commands[command.name]
                raise TwitchCommandError(
                    f"Failed to load command <{command.name}>, a command with that name/alias already exists."
                )

            self._command_aliases[alias] = command.name

    def get_command(self, name: str) -> Optional[Command]:
        """Method which retrieves a registered command.

        Parameters
        ------------
        name: :class:`str`
            The name or alias of the command to retrieve.

        Returns
        ---------
        Optional[:class:`.Command`]
        """
        name = self._command_aliases.get(name, name)

        return self._commands.get(name, None)

    def remove_command(self, name: str):
        """
        Method which removes a registered command

        Parameters
        -----------
        name: :class:`str`
            the name or alias of the command to delete.

        Returns
        --------
        None

        Raises
        -------
        :class:`.CommandNotFound` The command was not found
        """
        name = self._command_aliases.pop(name, name)

        for alias in list(self._command_aliases.keys()):
            if self._command_aliases[alias] == name:
                del self._command_aliases[alias]

        try:
            del self._commands[name]
        except KeyError:
            raise CommandNotFound(f"The command '{name}` was not found")

    def get_cog(self, name: str) -> Optional[Cog]:
        """Retrieve a Cog from the bots loaded Cogs.

        Could be None if the Cog was not found.

        Returns
        ---------
        Optional[:class:`.Cog`]
        """
        cog = self.cogs.get(name, None)

        return cog

    async def get_context(self, message, *, cls=None):
        """Get a Context object from a message.

        Parameters
        ----------
        message: :class:`.Message`
            The message object to get context for.
        cls
            The class to return. Defaults to Context. Its constructor must take message, prefix, valid, and bot
            as arguments.

        Returns
        ---------
        An instance of cls.

        Raises
        ---------
        :class:`.CommandNotFound` No valid command was passed
        """
        if not cls:
            cls = Context

        prefix = await self.get_prefix(message)
        if not prefix:
            return cls(message=message, prefix=prefix, valid=False, bot=self)

        content = message.content[len(prefix) : :].lstrip()  # Strip prefix and remainder whitespace
        view = StringParser()
        parsed = view.process_string(content)  # Return the string as a dict view

        try:
            command_ = parsed.pop(0)
        except KeyError:
            raise CommandNotFound(f"No valid command was passed.")

        try:
            command_ = self._command_aliases[command_]
        except KeyError:
            pass

        if command_ in self.commands:
            command_ = self.commands[command_]
        else:
            context = cls(message=message, bot=self, prefix=prefix, command=None, valid=False, view=view)
            error = CommandNotFound(f'No command "{command_}" was found.')

            self.run_event("command_error", context, error)
            return context

        context = cls(message=message, bot=self, prefix=prefix, command=command_, valid=True, view=view)

        return context

    async def handle_commands(self, message):
        context = await self.get_context(message)
        await self.invoke(context)

    async def invoke(self, context):
        # TODO Docs
        if not context.prefix or not context.is_valid:
            return

        self.run_event("command_invoke", context)
        await context.command(context)

    def load_module(self, name: str):
        """Method which loads a module and it's cogs.

        Parameters
        ------------
        name: str
            The name of the module to load in dot.path format.
        """
        if name in self._modules:
            raise ValueError(f"Module <{name}> is already loaded")

        module = importlib.import_module(name)

        if hasattr(module, "prepare"):
            module.prepare(self)
        else:
            del module
            del sys.modules[name]
            raise ImportError(f"Module <{name}> is missing a prepare method")

        self._modules[name] = module

    def unload_module(self, name: str):
        if name not in self._modules:
            raise ValueError(f"Module <{name}> is not loaded")

        module = self._modules.pop(name)

        if hasattr(module, "breakdown"):
            try:
                module.breakdown(self)
            except:
                pass

        to_delete = [cog_name for cog_name, cog in self._cogs.items() if cog.__module__ == module]
        for name in to_delete:
            self.remove_cog(name)

        to_delete = [name for name, cmd in self._commands if cmd._callback.__module__ == module]
        for name in to_delete:
            self.remove_command(name)

        for m in list(sys.modules.keys()):
            if m == module.__name__ or m.startswith(module.__name__ + "."):
                del sys.modules[m]

    def reload_module(self, name: str):
        if name not in self._modules:
            raise ValueError(f"Module <{name}> is not loaded")

        module = self._modules.pop(name)

        modules = {
            name: m
            for name, m in sys.modules.items()
            if name == module.__name__ or name.startswith(module.__name__ + ".")
        }

        try:
            self.unload_module(name)
            self.load_module(name)
        except Exception as e:
            sys.modules.update(modules)
            module.prepare(self)
            raise

    def add_cog(self, cog):
        if not isinstance(cog, Cog):
            raise InvalidCog('Cogs must derive from "commands.Cog".')

        if cog.name in self._cogs:
            raise InvalidCog(f'Cog "{cog.name}" has already been loaded.')

        cog._load_methods(self)
        self._cogs[cog.name] = cog

    def remove_cog(self, cog_name: str):
        if cog_name not in self._cogs:
            raise InvalidCog(f"Cog '{cog_name}' not found")

        cog = self._cogs.pop(cog_name)

        cog._unload_methods(self)

    async def global_before_invoke(self, ctx):
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

            async def global_before_invoke(self, ctx):
                # Make a database query for example to retrieve a specific token.
                token = db_query()

                ctx.token = token

            async def my_command(self, ctx):
                data = await self.create_clip(ctx.token, ...)

        Note
        ------
            The global_before_invoke is called before any other command specific hooks.
        """
        pass

    async def global_after_invoke(self, ctx):
        """|coro|

        Method which is called after any command is invoked regardless if it failed or not.

        This method is useful for cleaning up things after command invocation. E.g Database connections.

        Parameters
        ------------
        ctx:
            The context used for command invocation.

        Note
        ------
            The global_after_invoke is called only after the command successfully invokes.
        """
        pass

    @property
    def commands(self):
        return self._commands

    @property
    def cogs(self):
        return self._cogs

    async def event_command_error(self, context, error):
        """|coro|

        Event called when an error occurs during command invocation.

        Parameters
        ------------
        context: :class:`.Context`
            The command context.
        error: :class:`.Exception`
            The exception raised while trying to invoke the command.
        """
        print(f"Ignoring exception in command: {error}:", file=sys.stderr)
        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)

    async def event_message(self, message):
        """|coro|

        Event called when a PRIVMSG is received from Twitch.

        Parameters
        ------------
        message: :class:`.Message`
            Message object containing relevant information.
        """
        await self.handle_commands(message)

    def command(
        self, *, name: str = None, aliases: Union[list, tuple] = None, cls=Command, no_global_checks=False
    ) -> Callable[[Callable], Command]:
        """Decorator which registers a command with the bot.

        Commands must be a coroutine.

        Parameters
        ------------
        name: str [Optional]
            The name of the command. By default if this is not supplied, the function name will be used.
        aliases: Optional[Union[list, tuple]]
            The command aliases. This must be a list or tuple.
        cls: class [Optional]
            The custom command class to override the default class. This must be similar to :class:`.Command`.
        no_global_checks : Optional[bool]
            Whether or not the command should abide by global checks. Defaults to False, which checks global checks.

        Raises
        --------
        TypeError
            cls is not type class.
        """

        if not inspect.isclass(cls):
            raise TypeError(f"cls must be of type <class> not <{type(cls)}>")

        def decorator(func: Callable):
            cmd_name = name or func.__name__

            cmd = cls(name=cmd_name, func=func, aliases=aliases, instance=None, no_global_checks=no_global_checks)
            self.add_command(cmd)

            return cmd

        return decorator

    def group(
        self, *, name: str = None, aliases: Union[list, tuple] = None, cls=Group, no_global_checks=False
    ) -> Callable[[Callable], Group]:
        if not inspect.isclass(cls):
            raise TypeError(f"cls must be of type <class> not <{type(cls)}>")

        def decorator(func: Callable):
            cmd_name = name or func.__name__

            cmd = cls(name=cmd_name, func=func, aliases=aliases, instance=None, no_global_checks=no_global_checks)
            self.add_command(cmd)

            return cmd

        return decorator

    def check(self, func: Callable[[Context], bool]) -> Callable:
        if func in self._checks:
            raise ValueError("The function is already registered as a bot check")

        self._checks.append(func)
        return func

