# -*- coding: utf-8 -*-
"""
VietModManager API Package
Cung cấp cầu nối PyWebView IPC và các HTTP REST Endpoints.
"""

from api.ipc_bridge import ModManagerAPI, api_instance, log_startup
from api.routes import server_app, configure_routes, create_http_server

__all__ = [
    "ModManagerAPI",
    "api_instance",
    "log_startup",
    "server_app",
    "configure_routes",
    "create_http_server",
]
