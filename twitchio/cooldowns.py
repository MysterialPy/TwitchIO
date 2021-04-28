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

import asyncio
import time


class RateBucket:

    HTTPLIMIT = 800
    IRCLIMIT = 20
    MODLIMIT = 100

    HTTP = 60
    IRC = 30

    def __init__(self, *, method: str):
        self.method = method

        if method == 'irc':
            self.reset_time = self.IRC
            self.limit = self.IRCLIMIT
        elif method == 'mod':
            self.reset_time = self.IRC
            self.limit = self.MODLIMIT
        else:
            self.reset_time = self.HTTP
            self.limit = self.HTTPLIMIT

        self.tokens = 0
        self._reset = time.time() + self.reset_time

    @property
    def limited(self):
        return self.tokens == self.limit

    def reset(self):
        self.tokens = 0
        self._reset = time.time() + self.reset_time

    def update(self, *, reset=None, remaining=None):
        now = time.time()

        if self._reset <= now:
            self.reset()

        if reset:
            self._reset = int(reset)

        if remaining:
            self.tokens = self.limit - int(remaining)
        else:
            self.tokens += 1

    async def wait_reset(self):
        now = time.time()

        await asyncio.sleep(self._reset - now)
        self.reset()
