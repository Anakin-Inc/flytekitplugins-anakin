"""
.. currentmodule:: flytekitplugins.anakin

Flyte tasks for `Anakin <https://anakin.io>`_ (https://api.anakin.io/v1) —
web scraping, AI-powered search, and multi-stage agentic research, built on
the official ``anakin-sdk`` Python client.

.. autosummary::
   :template: custom.rst
   :toctree: generated/

   scrape_url
   search
   agentic_search
   ANAKIN_SECRET_GROUP
   ANAKIN_SECRET_KEY
   DEFAULT_ANAKIN_BASE_URL
"""

from .tasks import (
    ANAKIN_SECRET_GROUP,
    ANAKIN_SECRET_KEY,
    DEFAULT_ANAKIN_BASE_URL,
    agentic_search,
    scrape_url,
    search,
)

__all__ = [
    "ANAKIN_SECRET_GROUP",
    "ANAKIN_SECRET_KEY",
    "DEFAULT_ANAKIN_BASE_URL",
    "agentic_search",
    "scrape_url",
    "search",
]
