"""Tests for PhysicsCollector — before/after joint angle capture."""

from robocode.agent.physics_collector import PhysicsCollector


class FakeSdkBackend:
    """Minimal fake backend for testing PhysicsCollector without full SdkBackend."""

    def __init__(self, fake_client):
        self._client = fake_client

    def get_motor_angles(self):
        return self._client.get_motor_angles()

    @property
    def is_fake(self):
        from robocode.backends.sdk_backend import FakeEpisodeAPP

        return isinstance(self._client, FakeEpisodeAPP)


class FakeAuditDB:
    """In-memory recorder for testing PhysicsCollector."""

    def __init__(self):
        self.physics_records = []

    def insert_physics_data(self, **kwargs):
        self.physics_records.append(kwargs)

    def get_unprocessed_physics(self, session_id):
        return self.physics_records


class TestPhysicsCollectorCaptureBefore:
    def make_collector(self):
        from robocode.backends.sdk_backend import FakeEpisodeAPP

        db = FakeAuditDB()
        backend = FakeSdkBackend(FakeEpisodeAPP())
        collector = PhysicsCollector(backend=backend, db=db, session_id="sess-01")
        return collector, db

    def test_capture_before_returns_angle_snapshot(self):
        collector, _ = self.make_collector()
        snapshot = collector.capture_before("move_robot_xyz")
        assert snapshot is not None
        assert "joint_angles" in snapshot
        assert len(snapshot["joint_angles"]) == 6
        assert snapshot["tool_name"] == "move_robot_xyz"
        assert "end_pose" not in snapshot

    def test_capture_before_fake_returns_fixed_values(self):
        collector, _ = self.make_collector()
        snapshot = collector.capture_before("move_robot_xyz")
        assert snapshot["joint_angles"] == [180.0, 90.0, 83.0, 30.0, 110.0, 30.0]

    def test_capture_before_sdk_failure_returns_empty_snapshot(self):
        """When SDK fails, snapshot should still be returned with error marker."""
        from robocode.backends.sdk_backend import FakeEpisodeAPP

        class BrokenFake(FakeEpisodeAPP):
            def get_motor_angles(self):
                raise ConnectionError("CAN bus blocked")

        db = FakeAuditDB()
        backend = FakeSdkBackend(BrokenFake())
        collector = PhysicsCollector(backend=backend, db=db, session_id="sess-01")
        snapshot = collector.capture_before("move_robot_xyz")
        assert snapshot is not None
        assert snapshot.get("joint_angles") is None
        assert snapshot.get("capture_error") is not None


class TestPhysicsCollectorCaptureAfter:
    def make_collector(self):
        from robocode.backends.sdk_backend import FakeEpisodeAPP

        db = FakeAuditDB()
        backend = FakeSdkBackend(FakeEpisodeAPP())
        collector = PhysicsCollector(backend=backend, db=db, session_id="sess-01")
        return collector, db

    def test_capture_after_writes_to_db(self):
        collector, db = self.make_collector()
        before = collector.capture_before("move_robot_xyz")
        after = collector.capture_after(
            "move_robot_xyz", before, tool_call_id=42, duration_ms=3200, speed_ratio=0.5
        )
        assert after is not None
        assert len(db.physics_records) == 1
        rec = db.physics_records[0]
        assert rec["tool_call_id"] == 42
        assert rec["tool_name"] == "move_robot_xyz"
        assert rec["joint_angles_before"] == before["joint_angles"]
        assert rec["duration_ms"] == 3200
        assert rec["speed_ratio"] == 0.5

    def test_capture_after_without_call_id_skips_db_write(self):
        collector, db = self.make_collector()
        before = collector.capture_before("move_robot_xyz")
        collector.capture_after("move_robot_xyz", before)
        assert len(db.physics_records) == 0


class TestPhysicsCollectorSummary:
    def make_collector(self):
        from robocode.backends.sdk_backend import FakeEpisodeAPP

        db = FakeAuditDB()
        backend = FakeSdkBackend(FakeEpisodeAPP())
        collector = PhysicsCollector(backend=backend, db=db, session_id="sess-01")
        return collector

    def test_get_physics_summary_computes_delta(self):
        collector = self.make_collector()
        before = {
            "joint_angles": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
            "tool_name": "move_robot_xyz",
        }
        after = {
            "joint_angles": [12.0, 22.0, 32.0, 42.0, 52.0, 62.0],
            "tool_name": "move_robot_xyz",
            "duration_ms": 3200,
        }
        summary = collector.get_physics_summary(before, after)
        assert summary is not None
        assert summary["joint_delta"] == [2.0, 2.0, 2.0, 2.0, 2.0, 2.0]
        assert summary["duration_ms"] == 3200

    def test_get_physics_summary_with_missing_before(self):
        collector = self.make_collector()
        before = {"joint_angles": None, "tool_name": "move_robot_xyz", "capture_error": "fail"}
        after = {
            "joint_angles": [12.0, 22.0, 32.0, 42.0, 52.0, 62.0],
            "tool_name": "move_robot_xyz",
        }
        summary = collector.get_physics_summary(before, after)
        assert summary is None
