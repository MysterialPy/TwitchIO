TwitchIO
================

Support
---------------------------
For support using TwitchIO, please join the official `support server
<http://discord.gg/JhW28zp>`_ on `Discord <https://discordapp.com/>`_.

Installation
---------------------------

**TwitchIO requires Python 3.6 or higher.**

It is usually recommended you install development packages in your own project's virtual environment.
Corey Schafer has some great tutorials on setting these up: `Linux/MacOS venv <https://www.youtube.com/watch?v=Kg1Yvry_Ydk>`_ 
or `Windows venv <https://www.youtube.com/watch?v=APOPm01BVrk>`_

.. code:: sh

    pip install twitchio

**Installing from latest git**

.. code:: sh

    pip install git+https://github.com/TwitchIO/TwitchIO.git

Getting Started
----------------------------
TwitchIO uses many endpoints which may require different tokens and IDs.

1. IRC endpoints which require an OAuth token.
    To get a token, log in to Twitch with the bot's account and visit:
    https://twitchapps.com/tmi/

2. HTTP endpoints which require a client ID.
    *To be documented.*

3. HTTP endpoints which require an OAuth token and certain scopes.
    *To be documented.*

All 3 endpoints may be used at the same time. Otherwise, you may choose to use any or some of the endpoints.

Currently, TwitchIO's development is at a phase which has emphasis on the IRC endpoint and creating a framework around it.
Once this is implemented, the other 2 endpoints will be developed further.

A quick and easy bot example:

.. code:: py

    from twitchio.ext import commands


    class Bot(commands.Bot):

        def __init__(self):
            super().__init__(irc_token='...', client_id='...', nick='...', prefix='!',
                             initial_channels=['...'])

        # Events don't need decorators when subclassed
        async def event_ready(self):
            print(f'Ready | {self.nick}')

        async def event_message(self, message):
            print(message.content)
            await self.handle_commands(message)

        # Commands use a decorator...
        @commands.command(name='test')
        async def my_command(self, ctx):
            await ctx.send(f'Hello {ctx.author.name}!')


    bot = Bot()
    bot.run()

Client
----------------------------

.. autoclass:: twitchio.client.Client
    :members:

Topics
----------------------------
Webhooks allow you to subscribe to different topics, which ones are described below.

.. autoclass:: twitchio.webhook.Topic
    :members:

.. autoclass:: twitchio.webhook.UserFollows
    :members:
    :show-inheritance:

.. autoclass:: twitchio.webhook.StreamChanged
    :members:
    :show-inheritance:

.. autoclass:: twitchio.webhook.UserChanged
    :members:
    :show-inheritance:

.. autoclass:: twitchio.webhook.GameAnalytics
    :members:
    :show-inheritance:

.. autoclass:: twitchio.webhook.ExtensionAnalytics
    :members:
    :show-inheritance:


Dataclasses
----------------------------
Dataclasses belonging to TwitchIO.

.. note::
    These should not be created by the user. Instead, you should use the ones
    passed to event listeners or returned from properties and methods of TwitchIO's objects.

.. autoclass:: twitchio.dataclasses.Message
    :members:
    :inherited-members:
    :show-inheritance:

.. autoclass:: twitchio.dataclasses.Channel
    :members:
    :inherited-members:
    :show-inheritance:

.. autoclass:: twitchio.dataclasses.User
    :members:
    :inherited-members:
    :show-inheritance:

.. autoclass:: twitchio.dataclasses.Context
    :members:
    :inherited-members:
    :show-inheritance:

.. autoclass:: twitchio.dataclasses.NoticeSubscription
    :members:
    :inherited-members:
    :show-inheritance:

.. autoclass:: twitchio.dataclasses.CustomReward
    :members:
    :inherited-members:
    :show-inheritance:

.. autoclass:: twitchio.dataclasses.CustomRewardRedemption
    :members:
    :inherited-members:
    :show-inheritance:

Errors
-----------------------

.. autoexception:: twitchio.errors.TwitchIOBException

.. autoexception:: twitchio.errors.AuthenticationError

.. autoexception:: twitchio.errors.WSConnectionFailure

.. autoexception:: twitchio.errors.ClientError

.. autoexception:: twitchio.errors.EchoMessageWarning

.. autoexception:: twitchio.errors.InvalidContent

.. autoexception:: twitchio.errors.HTTPException


Module Contents
---------------

.. automodule:: twitchio
    :members:
    :show-inheritance:
