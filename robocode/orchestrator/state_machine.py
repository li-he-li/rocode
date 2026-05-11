"""Orchestrator state enum for agent loop lifecycle tracking."""

from enum import Enum


class OrchestratorState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    RECOVERING = "recovering"
    FAILED = "failed"
    SUCCESS = "success"
