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

import inspect
from typing import Union, Optional, Callable, Awaitable

import itertools
import copy
from typing import Any, Union, Optional, Callable, Awaitable, Tuple, TYPE_CHECKING

from twitchio.abcs import Messageable
from .cooldowns import *
from .errors import *
from . import builtin_converter

if TYPE_CHECKING:
    from twitchio import Message, Chatter, PartialChatter
    from . import Cog, Bot
    from .stringparser import StringParser


__all__ = ("Command", "command", "Group", "Context", "cooldown")


def _boolconverter(param: str):
    param = param.lower()
    if param in ("yes", "y", "1", "true", "on"):
        return True
    elif param in ("no", "n", "0", "false", "off"):
        return False

    raise BadArgument(f"Expected a boolean value, got {param}")


class Command:
    def __init__(self, name: str, func: Callable, **attrs):
        if not inspect.iscoroutinefunction(func):
            raise TypeError("Command callback must be a coroutine.")

        self._callback = func
        self._checks = []
        self._cooldowns = []
        self._name = name

        self._instance = None
        self.cog = None
        self.parent: Optional[Group] = attrs.get("parent")

        try:
            self._checks.extend(func.__checks__)
        except AttributeError:
            pass

        try:
            self._cooldowns.extend(func.__cooldowns__)
        except AttributeError:
            pass

        self.aliases = attrs.get("aliases", None)
        sig = inspect.signature(func)
        self.params = sig.parameters.copy()

        self.event_error = None
        self._before_invoke = None
        self._after_invoke = None
        self.no_global_checks = attrs.get("no_global_checks", False)

        for key, value in self.params.items():
            if isinstance(value.annotation, str):
                self.params[key] = value.replace(annotation=eval(value.annotation, func.__globals__))

    @property
    def name(self):
        return self._name

    @property
    def full_name(self):
        if not self.parent:
            return self._name

        return f"{self.parent.full_name} {self._name}"

    def _resolve_converter(self, converter: Union[Callable, Awaitable, type]) -> Callable:
        if isinstance(converter, type) and converter.__module__.startswith("twitchio"):
            if converter in builtin_converter._mapping:
                return builtin_converter._mapping[converter]

        return converter

    async def _convert_types(self, context: "Context", param: inspect.Parameter, parsed: str) -> Any:
        converter = param.annotation
        if converter is param.empty:
            if param.default in (param.empty, None):
                converter = str
            else:
                converter = type(param.default)

        true_converter = self._resolve_converter(converter)

        try:
            if true_converter in (int, str):
                argument = true_converter(parsed)
            elif true_converter is bool:
                argument = _boolconverter(parsed)
            else:
                argument = true_converter(context, parsed)
            if inspect.iscoroutine(argument):
                argument = await argument
        except BadArgument:
            raise

        except Exception as e:
            raise ArgumentParsingFailed(
                f"Invalid argument parsed at `{param.name}` in command `{self.name}`."
                f" Expected type {converter} got {type(parsed)}.",
                e,
            ) from e

        return argument

    async def parse_args(self, context: "Context", instance: "Cog", parsed: dict, index=0) -> Tuple[list, dict]:
        if isinstance(self, Group):
            parsed = parsed.copy()
        iterator = iter(self.params.items())
        args = []
        kwargs = {}

        try:
            next(iterator)
            if instance:
                next(iterator)
        except StopIteration:
            raise TwitchCommandError(f"self or ctx is a required argument which is missing.")

        for _, param in iterator:
            index += 1
            if param.kind == param.POSITIONAL_OR_KEYWORD:
                try:
                    argument = parsed.pop(index)
                except (KeyError, IndexError):
                    if param.default is param.empty:
                        raise MissingRequiredArgument(param)
                    args.append(param.default)
                else:
                    argument = await self._convert_types(context, param, argument)
                    args.append(argument)

            elif param.kind == param.KEYWORD_ONLY:
                rest = " ".join(parsed.values())
                if rest.startswith(" "):
                    rest = rest.lstrip(" ")

                if rest:
                    rest = await self._convert_types(context, param, rest)
                elif param.default is param.empty:
                    raise MissingRequiredArgument(param)
                else:
                    rest = param.default

                kwargs[param.name] = rest
                parsed.clear()
                break
            elif param.VAR_POSITIONAL:
                args.extend(parsed.values())
                break

        if parsed:
            pass  # TODO Raise Too Many Arguments.

        return args, kwargs

    async def invoke(self, context: "Context", *, index=0):
        # TODO Docs
        args, kwargs = await self.parse_args(context, self._instance, context.view.words, index=index)
        context.args, context.kwargs = args, kwargs

        async def try_run(func, *, to_command=False):
            try:
                await func
            except Exception as _e:
                if not to_command:
                    context.bot.run_event("error", _e)
                else:
                    context.bot.run_event("command_error", context, _e)

        check_result = await self.handle_checks(context)

        if check_result is not True:
            context.bot.run_event("command_error", context, check_result)
            return

        limited = self._run_cooldowns(context)

        if limited:
            context.bot.run_event("command_error", context, limited[0])
            return

        instance = self._instance
        if instance:
            args = [instance, context]
        else:
            args = [context]

        await try_run(context.bot.global_before_invoke(context))

        if self._before_invoke:
            await try_run(self._before_invoke(*args), to_command=True)

        try:
            await self._callback(*args, *context.args, **context.kwargs)
        except Exception as e:
            if self.event_error:
                await try_run(self.event_error(*args, e))

            context.bot.run_event("command_error", context, e)
        else:
            context.bot.run_event("command_complete", context)

        # Invoke our after command hooks
        if self._after_invoke:
            await try_run(self._after_invoke(*args), to_command=True)

        await try_run(context.bot.global_after_invoke(context))

    def _run_cooldowns(self, context):
        try:
            buckets = self._cooldowns[0].get_buckets(context)
        except IndexError:
            return None

        expired = []

        try:
            for bucket in buckets:
                bucket.update_bucket(context)
        except CommandOnCooldown as e:
            expired.append(e)

        return expired

    async def handle_checks(self, context):
        # TODO Docs

        if not self.no_global_checks:
            checks = [predicate for predicate in itertools.chain(context.bot._checks, self._checks)]
        else:
            checks = self._checks

        try:
            for predicate in checks:
                result = predicate(context)

                if inspect.isawaitable(result):
                    result = await result

                if not result:
                    raise CheckFailure(f"The check {predicate} for command {self.name} failed.")

            if self.cog:
                if not await self.cog.cog_check(context):
                    raise CheckFailure(f"The cog check for command <{self.name}> failed.")

            return True
        except Exception as e:
            return e

    async def __call__(self, context: "Context", *, index=0):
        await self.invoke(context, index=index)


class Group(Command):
    def __init__(self, *args, invoke_with_subcommand=False, **kwargs):
        super(Group, self).__init__(*args, **kwargs)
        self._sub_commands = {}
        self._invoke_with_subcommand = invoke_with_subcommand

    async def __call__(self, context: "Context", *, index=0):
        if not context.view.words:
            return await self.invoke(context, index=index)

        arg = list(context.view.words.items())[0]
        if arg[1] in self._sub_commands:
            _ctx = copy.copy(context)
            _ctx.view = _ctx.view.copy()
            _ctx.view.words.pop(arg[0])
            await self._sub_commands[arg[1]](_ctx, index=arg[0])

            if self._invoke_with_subcommand:
                await self.invoke(context, index=index)

        else:
            await self.invoke(context, index=index)

    def command(
        self, *, name: str = None, aliases: Union[list, tuple] = None, cls=Command, no_global_checks=False
    ) -> Callable[[Callable], Command]:
        if cls and not inspect.isclass(cls):
            raise TypeError(f"cls must be of type <class> not <{type(cls)}>")

        def decorator(func: Callable):
            fname = name or func.__name__
            cmd = cls(name=fname, func=func, aliases=aliases, no_global_checks=no_global_checks, parent=self)
            self._sub_commands[cmd.name] = cmd
            if cmd.aliases:
                for a in cmd.aliases:
                    self._sub_commands[a] = cmd

            return cmd

        return decorator

    def group(
        self,
        *,
        name: str = None,
        aliases: Union[list, tuple] = None,
        cls=None,
        no_global_checks=False,
        invoke_with_subcommand=False,
    ) -> Callable[[Callable], "Group"]:
        cls = cls or Group
        if cls and not inspect.isclass(cls):
            raise TypeError(f"cls must be of type <class> not <{type(cls)}>")

        def decorator(func: Callable):
            fname = name or func.__name__
            cmd = cls(
                name=fname,
                func=func,
                aliases=aliases,
                no_global_checks=no_global_checks,
                parent=self,
                invoke_with_subcommand=invoke_with_subcommand,
            )
            self._sub_commands[cmd.name] = cmd
            if cmd.aliases:
                for a in cmd.aliases:
                    self._sub_commands[a] = cmd

            return cmd

        return decorator


class Context(Messageable):

    __messageable_channel__ = True

    def __init__(self, message: "Message", bot: "Bot", **attrs):
        self.message = message
        self.channel = message.channel
        self.author: Union["Chatter", "PartialChatter"] = message.author

        self.prefix: Optional[str] = attrs.get("prefix")

        self.command: Optional[Command] = attrs.get("command")
        if self.command:
            self.cog: Optional["Cog"] = self.command.cog

        self.args: Optional[list] = attrs.get("args")
        self.kwargs: Optional[dict] = attrs.get("kwargs")

        self.view: Optional["StringParser"] = attrs.get("view")
        self.is_valid: bool = attrs.get("valid")

        self.bot: "Bot" = bot
        self._ws = self.channel._ws

    def _fetch_channel(self):
        return self.channel  # Abstract method

    def _fetch_websocket(self):
        return self._ws  # Abstract method

    def _bot_is_mod(self):
        cache = self._ws._cache[self.channel._name]
        for user in cache:
            if user.name == self._ws.nick:
                try:
                    mod = user.is_mod
                except AttributeError:
                    return False

                return mod

    @property
    def chatters(self) -> Optional[set]:
        """The channels current chatters."""
        try:
            users = self._ws._cache[self.channel._name]
        except KeyError:
            return None

        return users

    @property
    def users(self) -> Optional[set]:  # Alias to chatters
        """Alias to chatters."""
        return self.chatters

    def get_user(self, name: str):
        """Retrieve a user from the channels user cache.

        Parameters
        -----------
        name: str
            The user's name to try and retrieve.

        Returns
        --------
        Union[:class:`twitchio.user.User`, :class:`twitchio.user.PartialUser`]
            Could be a :class:`twitchio.user.PartialUser` depending on how the user joined the channel.
            Returns None if no user was found.
        """
        name = name.lower()

        cache = self._ws._cache[self.channel._name]
        for user in cache:
            if user.name == name:
                return user

        return None


def command(
    *, name: str = None, aliases: Union[list, tuple] = None, cls=Command, no_global_checks=False
) -> Callable[[Callable], Command]:
    if cls and not inspect.isclass(cls):
        raise TypeError(f"cls must be of type <class> not <{type(cls)}>")

    def decorator(func: Callable):
        fname = name or func.__name__
        cmd = cls(name=fname, func=func, aliases=aliases, no_global_checks=no_global_checks)

        return cmd

    return decorator


def group(
    *,
    name: str = None,
    aliases: Union[list, tuple] = None,
    cls=Group,
    no_global_checks=False,
    invoke_with_subcommand=False,
) -> Callable[[Callable], Group]:
    if cls and not inspect.isclass(cls):
        raise TypeError(f"cls must be of type <class> not <{type(cls)}>")

    def decorator(func: Callable):
        fname = name or func.__name__
        cmd = cls(
            name=fname,
            func=func,
            aliases=aliases,
            no_global_checks=no_global_checks,
            invoke_with_subcommand=invoke_with_subcommand,
        )

        return cmd

    return decorator


def cooldown(rate, per, bucket=Bucket.default):
    def decorator(func):
        if isinstance(func, Command):
            func._cooldowns.append(Cooldown(rate, per, bucket))
        else:
            func.__cooldowns__ = [Cooldown(rate, per, bucket)]
        return func

    return decorator
