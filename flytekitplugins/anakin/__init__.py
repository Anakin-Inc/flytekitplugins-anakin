"""
.. currentmodule:: flytekitplugins.anakin

Flyte tasks for `Anakin <https://anakin.io>`_ (https://api.anakin.io/v1) —
web scraping, mapping, crawling, AI-powered search and agentic research,
Wire pre-built site automation, website monitoring, AI visibility, browser
sessions, and AI browser automation. Built on the official ``anakin-sdk``
Python client where it covers the endpoint, and direct REST calls
(``httpx``) where it doesn't yet — see ``tasks.py``'s module docstring and
``README.md``'s task table for which is which.

.. autosummary::
   :template: custom.rst
   :toctree: generated/

   scrape_url
   search
   agentic_search
   map_site
   crawl_site
   wire_read_action
   wire_write_action
   wire_discover
   wire_catalog
   wire_identities
   wire_login
   wire_build
   session_list
   session_delete
   monitor_create
   monitor_list
   monitor_changes
   monitor_control
   ai_visibility_sources
   ai_visibility_search
   browser_task
   ANAKIN_SECRET_GROUP
   ANAKIN_SECRET_KEY
   DEFAULT_ANAKIN_BASE_URL
"""

from .tasks import (
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
    monitor_list,
    scrape_url,
    search,
    session_delete,
    session_list,
    wire_build,
    wire_catalog,
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
    "agentic_search",
    "ai_visibility_search",
    "ai_visibility_sources",
    "browser_task",
    "crawl_site",
    "map_site",
    "monitor_changes",
    "monitor_control",
    "monitor_create",
    "monitor_list",
    "scrape_url",
    "search",
    "session_delete",
    "session_list",
    "wire_build",
    "wire_catalog",
    "wire_discover",
    "wire_identities",
    "wire_login",
    "wire_read_action",
    "wire_write_action",
]
