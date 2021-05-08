from typing import TYPE_CHECKING, Tuple, Dict, Type
from ...http import Route

from . import models

if TYPE_CHECKING:
    from .server import EventSubClient
    from .models import EventData

__all__ = "EventSubHTTP",

class EventSubHTTP:
    URL = "https://api.twitch.tv/helix/eventsub/"

    def __init__(self, client: "EventSubClient"):
        self._client = client
        self._http = client.client._http

    async def create_subscription(self, event_type: Tuple[str, int, Type["EventData"]], condition: Dict[str, str]):
        payload = {
            "type": event_type[0],
            "version": str(event_type[1]),
            "condition": condition,
            "transport": {
                "method": "webhook",
                "callback": self._client.route,
                "secret": self._client.secret
            }
        }
        route = Route("POST", self.URL + "subscriptions", body=payload)
        return await self._http.request(route)

    async def delete_subscription(self, sub_id: str):
        return await self._http.request(Route("DELETE", self.URL+"subscriptions", query=[("id", sub_id)]))

    async def get_subscriptions(self, status: str=None):
        qs = []
        if status:
            qs.append(("status", status))

        return [models.Subscription(d) for d in await self._http.request(Route("GET", self.URL+"subscriptions", query=qs))]

    async def get_status(self, status: str=None):
        qs = []
        if status:
            qs.append(("status", status))

        v = await self._http.request(Route("GET", self.URL + "subscriptions", query=qs), full_body=True)
        del v['data']
        del v['pagination']
        return v
