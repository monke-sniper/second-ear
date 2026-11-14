"""Fixtures shared by the plumbing tests and the behaviour specs.

The doubles and PCM helpers live in tests/helpers.py so test modules can import
them directly; this file only exposes the TestClient fixture.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.app import create_app


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client
