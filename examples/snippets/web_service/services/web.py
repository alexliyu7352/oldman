"""Illustrative Web service declaration; this is not a standalone project."""

from oldman.runtime.web import WebApplication


class ExampleWebService(WebApplication):
    SERVICE_NAME = "Example web service"
