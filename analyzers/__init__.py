#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyzers module voor Baarn Politiek MCP Server.
Bevat document analyse en zoek functionaliteit.
"""

from .search_analyzer import SearchAnalyzer, get_search_analyzer

__all__ = [
    'SearchAnalyzer',
    'get_search_analyzer',
]
