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

import enum


__all__ = ("PredictionEnum", "BroadcasterTypeEnum", "UserTypeEnum", "ModEventEnum")


class PredictionEnum(enum.Enum):

    blue_1 = "blue-1"
    pink_2 = "pink-2"


class BroadcasterTypeEnum(enum.Enum):

    partner = "partner"
    affiliate = "affiliate"
    none = ""


class UserTypeEnum(enum.Enum):

    staff = "staff"
    admin = "admin"
    global_mod = "global_mod"
    none = ""


class ModEventEnum(enum.Enum):

    moderator_remove = "moderation.moderator.remove"
    moderator_add = "moderation.moderator.add"
