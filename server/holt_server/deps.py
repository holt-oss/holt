"""Request dependencies shared by the routers: the internal key and the caller."""

from __future__ import annotations

import hmac
import ipaddress
from typing import TYPE_CHECKING

from fastapi import Depends, Header, Request

from holt_server.errors import ApiError

if TYPE_CHECKING:
    from holt_server.services import Services


def services(request: Request) -> Services:
    return request.app.state.services


async def internal(
    request: Request,
    x_holt_internal_key: str | None = Header(default=None),
) -> None:
    expected = services(request).settings.internal_key
    if not expected or not x_holt_internal_key or not hmac.compare_digest(
        x_holt_internal_key.encode(), expected.encode()
    ):
        raise ApiError("unauthorized", "This API is only for the Holt website.")


# `X-Holt-Client` values the server knows. Anything else is ignored.
MCP = "mcp"


class Caller:
    def __init__(self, user_id: str | None, ip: str | None, client: str | None = None) -> None:
        self.user_id = user_id
        self.ip = ip
        # "mcp": an anonymous request from the web's MCP connector. Its limits
        # are one bucket for every chat, not per IP (see `rate_key`).
        self.client = client if client == MCP and not user_id else None

    @property
    def mcp(self) -> bool:
        return self.client == MCP

    @property
    def rate_key(self) -> str:
        if self.user_id:
            return f"user:{self.user_id}"
        return "mcp" if self.mcp else f"ip:{self.ip}"

    @property
    def mcp_address_key(self) -> str:
        """Who counts as one caller inside the MCP bucket: the address, or one
        IPv6 /64 (a single network can pick from all of it). Requests with no
        address share one count, so leaving it out buys nothing."""
        ip = self.ip or "unknown"
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return f"mcp-ip:{ip}"
        if addr.version == 6:
            if addr.ipv4_mapped is None:
                return f"mcp-ip:{ipaddress.ip_network((addr, 64), strict=False)}"
            addr = addr.ipv4_mapped
        return f"mcp-ip:{addr}"

    def limit(self, svc: Services) -> int:
        s = svc.settings
        if self.user_id:
            return s.user_rate_per_hour
        return s.mcp_work_per_hour if self.mcp else s.anon_rate_per_hour

    def read_limit(self, svc: Services) -> int:
        s = svc.settings
        if self.user_id:
            return s.user_read_rate_per_hour
        return s.mcp_read_per_hour if self.mcp else s.anon_read_rate_per_hour


async def caller(
    request: Request,
    _: None = Depends(internal),
    x_holt_user: str | None = Header(default=None),
    x_holt_client_ip: str | None = Header(default=None),
    x_holt_client: str | None = Header(default=None),
) -> Caller:
    user_id = (x_holt_user or "").strip()[:200] or None
    # No fallback to the socket address: that is the BFF's, and every anonymous
    # visitor would share one bucket.
    ip = (x_holt_client_ip or "").strip()[:64] or None
    return Caller(user_id, ip, (x_holt_client or "").strip().lower() or None)


def signed_in(who: Caller) -> str:
    if not who.user_id:
        raise ApiError("unauthorized", "Please sign in first.")
    return who.user_id
