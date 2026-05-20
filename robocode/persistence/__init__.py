"""Compatibility re-export — persistence.db migrated to services/analytics/db.py."""

from robocode.services.analytics.db import AuditDB

__all__ = ["AuditDB"]
