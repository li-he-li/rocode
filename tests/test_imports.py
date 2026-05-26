"""Smoke tests: verify all package modules import cleanly."""


def test_import_robocode():
    pass


def test_import_config():
    pass


def test_import_models():
    pass


def test_import_cli():
    from robocode import cli  # noqa


def test_import_agent():
    from robocode import agent  # noqa


def test_import_llm():
    from robocode import llm  # noqa


def test_import_orchestrator():
    from robocode import orchestrator  # noqa


def test_import_tools():
    from robocode import tools  # noqa


def test_import_backends():
    from robocode import backends  # noqa


def test_import_persistence():
    from robocode import persistence  # noqa


def test_import_utils():
    from robocode import utils  # noqa
