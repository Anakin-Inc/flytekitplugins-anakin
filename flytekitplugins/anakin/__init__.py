"""
.. currentmodule:: flytekitplugins.anakin

Flyte tasks for `Anakin <https://anakin.io>`_, a web data API: scrape and
crawl sites to markdown, AI web search and research, Wire site actions,
website monitors, AI visibility and AI browser tasks. Built on the official
``anakin-sdk`` client.

.. autosummary::
   :template: custom.rst
   :toctree: generated/

   scrape_url
   map_site
   crawl_site
   search
   agentic_search
   wire_discover
   wire_catalogs
   wire_catalog
   wire_read_action
   wire_write_action
   wire_identities
   wire_login
   wire_build
   wire_build_status
   monitor_create
   monitor_list
   monitor_get
   monitor_changes
   monitor_control
   ai_visibility_sources
   ai_visibility_search
   session_list
   session_delete
   browser_task
"""

from flytekitplugins.anakin._version import __version__
from flytekitplugins.anakin.tasks import (
    ANAKIN_SECRET_GROUP,
    ANAKIN_SECRET_KEY,
    DEFAULT_ANAKIN_BASE_URL,
    agentic_search,
    ai_visibility_search,
    ai_visibility_sources,
    browser_task,
    crawl_site,
    map_site,
    monitor_changes,
    monitor_control,
    monitor_create,
    monitor_get,
    monitor_list,
    scrape_url,
    search,
    session_delete,
    session_list,
    wire_build,
    wire_build_status,
    wire_catalog,
    wire_catalogs,
    wire_discover,
    wire_identities,
    wire_login,
    wire_read_action,
    wire_write_action,
)

__all__ = [
    "ANAKIN_SECRET_GROUP",
    "ANAKIN_SECRET_KEY",
    "DEFAULT_ANAKIN_BASE_URL",
    "__version__",
    "agentic_search",
    "ai_visibility_search",
    "ai_visibility_sources",
    "browser_task",
    "crawl_site",
    "map_site",
    "monitor_changes",
    "monitor_control",
    "monitor_create",
    "monitor_get",
    "monitor_list",
    "scrape_url",
    "search",
    "session_delete",
    "session_list",
    "wire_build",
    "wire_build_status",
    "wire_catalog",
    "wire_catalogs",
    "wire_discover",
    "wire_identities",
    "wire_login",
    "wire_read_action",
    "wire_write_action",
]
