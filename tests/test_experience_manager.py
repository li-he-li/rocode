"""Tests for ExperienceManager — physics analysis, annotation processing, call flow analysis."""

import json
from robocode.agent.experience_manager import ExperienceManager


class FakeDB:
    """In-memory DB for testing ExperienceManager."""

    def __init__(self):
        self.physics_data = []
        self.annotations = []
        self.tool_calls = []
        self.pending = []
        self._pending_id = 0

    def get_unprocessed_physics(self, session_id):
        return self.physics_data

    def get_unprocessed_annotations(self, session_id):
        return self.annotations

    def list_tool_calls(self, session_id, limit=100):
        return self.tool_calls

    def insert_annotation(self, **kwargs):
        pass

    def insert_experience_log(self, event_type, file_path="", details=None):
        pass

    def insert_experience_pending(self, session_id, data_type, data_id):
        self._pending_id += 1
        return self._pending_id

    def get_pending_experiences(self, session_id):
        return self.pending

    def update_pending_status(self, pending_id, status, error_msg=""):
        for p in self.pending:
            if p["id"] == pending_id:
                p["status"] = status
                if error_msg:
                    p["error_msg"] = error_msg

    def update_tool_call_physics_captured(self, tool_call_id):
        pass


class TestAnalyzePhysics:
    def make_manager(self):
        db = FakeDB()
        return ExperienceManager(db=db, session_id="s01")

    def test_insufficient_data_returns_none(self):
        mgr = self.make_manager()
        mgr._db.physics_data = [
            {
                "tool_name": "move_robot_xyz",
                "speed_ratio": 0.5,
                "joint_angles_before": json.dumps([10, 20, 30, 40, 50, 60]),
                "joint_angles_after": json.dumps([11, 21, 31, 41, 51, 61]),
                "duration_ms": 3000,
            },
            {
                "tool_name": "move_robot_xyz",
                "speed_ratio": 0.3,
                "joint_angles_before": json.dumps([10, 20, 30, 40, 50, 60]),
                "joint_angles_after": json.dumps([10.5, 20.5, 30.5, 40.5, 50.5, 60.5]),
                "duration_ms": 5000,
            },
        ]
        result = mgr.analyze_physics(min_data_points=3)
        assert result is None

    def test_discovers_speed_deviation_pattern(self):
        mgr = self.make_manager()
        mgr._db.physics_data = [
            {
                "tool_name": "move_robot_xyz",
                "speed_ratio": 0.8,
                "joint_angles_before": json.dumps([10, 20, 30, 40, 50, 60]),
                "joint_angles_after": json.dumps([14, 24, 34, 44, 54, 64]),
                "duration_ms": 1500,
            },
            {
                "tool_name": "move_robot_xyz",
                "speed_ratio": 0.8,
                "joint_angles_before": json.dumps([14, 24, 34, 44, 54, 64]),
                "joint_angles_after": json.dumps([18, 28, 38, 48, 58, 68]),
                "duration_ms": 1400,
            },
            {
                "tool_name": "move_robot_xyz",
                "speed_ratio": 0.3,
                "joint_angles_before": json.dumps([10, 20, 30, 40, 50, 60]),
                "joint_angles_after": json.dumps([10.3, 20.3, 30.3, 40.3, 50.3, 60.3]),
                "duration_ms": 5000,
            },
            {
                "tool_name": "move_robot_xyz",
                "speed_ratio": 0.3,
                "joint_angles_before": json.dumps([10, 20, 30, 40, 50, 60]),
                "joint_angles_after": json.dumps([10.4, 20.4, 30.4, 40.4, 50.4, 60.4]),
                "duration_ms": 4800,
            },
        ]
        results = mgr.analyze_physics(min_data_points=2)
        assert results is not None
        assert "move_robot_xyz" in results
        tool_data = results["move_robot_xyz"]
        assert "speed_groups" in tool_data
        # speed=0.8 group should exist
        has_high_speed = any("0.8" in str(g) for g in tool_data["speed_groups"])
        assert has_high_speed


class TestProcessAnnotations:
    def make_manager(self):
        db = FakeDB()
        return ExperienceManager(db=db, session_id="s01")

    def test_failure_cases_extracted(self):
        mgr = self.make_manager()
        mgr._db.annotations = [
            {
                "tool_call_id": 1,
                "tool_name": "move_robot_xyz",
                "category": "motion",
                "choices": json.dumps(
                    {"motion_quality": "严重振动", "position_accuracy": "明显偏差"}
                ),
                "is_failure": 1,
                "free_text": "整个桌子都在抖",
            },
            {
                "tool_call_id": 2,
                "tool_name": "move_robot_xyz",
                "category": "motion",
                "choices": json.dumps(
                    {"motion_quality": "严重振动", "position_accuracy": "轻微偏差"}
                ),
                "is_failure": 1,
                "free_text": "",
            },
        ]
        result = mgr.process_annotations()
        assert result is not None
        assert "motion" in result
        assert len(result["motion"]["failures"]) == 2

    def test_success_cases_extracted(self):
        mgr = self.make_manager()
        mgr._db.annotations = [
            {
                "tool_call_id": 3,
                "tool_name": "control_suction",
                "category": "gripper",
                "choices": json.dumps({"grasp_result": "成功", "gripper_force": "合适"}),
                "is_failure": 0,
                "free_text": "",
            },
        ]
        result = mgr.process_annotations()
        assert "gripper" in result
        assert result["gripper"]["failures"] == []
        assert result["gripper"]["total"] == 1


class TestAnalyzeCallFlow:
    def make_manager(self):
        db = FakeDB()
        return ExperienceManager(db=db, session_id="s01")

    def test_discovers_tool_sequence_pattern(self):
        mgr = self.make_manager()
        mgr._db.tool_calls = [
            {
                "id": 1,
                "tool_name": "check_calibration_status",
                "task_instruction": "抓取海绵块",
                "turn_number": 0,
                "prev_call_id": None,
                "result": json.dumps({"success": True}),
            },
            {
                "id": 2,
                "tool_name": "move_robot_xyz",
                "task_instruction": "抓取海绵块",
                "turn_number": 1,
                "prev_call_id": 1,
                "result": json.dumps({"success": True}),
            },
            {
                "id": 3,
                "tool_name": "6d_grasp",
                "task_instruction": "抓取海绵块",
                "turn_number": 2,
                "prev_call_id": 2,
                "result": json.dumps({"success": True}),
            },
        ]
        result = mgr.analyze_call_flow()
        assert result is not None
        assert "sequences" in result
        sequences = [tuple(s["tools"]) for s in result["sequences"]]
        assert ("check_calibration_status", "move_robot_xyz", "6d_grasp") in sequences

    def test_retry_pattern_detection(self):
        mgr = self.make_manager()
        mgr._db.tool_calls = [
            {
                "id": 1,
                "tool_name": "move_robot_xyz",
                "task_instruction": "移动到目标",
                "turn_number": 0,
                "prev_call_id": None,
                "result": json.dumps({"success": False}),
            },
            {
                "id": 2,
                "tool_name": "move_robot_xyz",
                "task_instruction": "移动到目标",
                "turn_number": 1,
                "prev_call_id": 1,
                "result": json.dumps({"success": True}),
            },
        ]
        result = mgr.analyze_call_flow()
        assert "retries" in result
        assert len(result["retries"]) > 0


class TestCreateExperience:
    def make_manager(self):
        db = FakeDB()
        return ExperienceManager(db=db, session_id="s01")

    def test_create_physics_experience(self):
        mgr = self.make_manager()
        frontmatter, body = mgr.create_experience(
            category="physics",
            domain="velocity",
            title="速度与角度偏差",
            data={"speed_groups": {"0.8": {"avg_delta": 4.0, "count": 2}}},
            confidence=0.65,
            data_points=4,
        )
        assert frontmatter["type"] == "physics"
        assert frontmatter["confidence"] == 0.65
        assert frontmatter["data_points"] == 4
        assert "速度与角度偏差" in body
        assert "数据支撑" in body

    def test_create_operational_experience(self):
        mgr = self.make_manager()
        frontmatter, body = mgr.create_experience(
            category="motion",
            domain="high-speed-vibration",
            title="高速运动振动风险",
            data=None,
            confidence=0.72,
            data_points=5,
            annotations={
                "motion": {
                    "failures": [{"motion_quality": "严重振动"}],
                    "total": 3,
                    "successes": [],
                }
            },
        )
        assert frontmatter["type"] == "operational"
        assert "案例" in body


class TestMergeAndPrune:
    def make_manager(self):
        db = FakeDB()
        return ExperienceManager(db=db, session_id="s01")

    def test_should_prune_low_confidence(self):
        mgr = self.make_manager()
        assert mgr.should_prune(confidence=0.25, data_points=2) is True

    def test_should_not_prune_high_confidence(self):
        mgr = self.make_manager()
        assert mgr.should_prune(confidence=0.6, data_points=10) is False

    def test_should_not_prune_many_data_points(self):
        mgr = self.make_manager()
        # Even low confidence, many data points means keep it
        assert mgr.should_prune(confidence=0.25, data_points=20) is False


class TestUpdateMergePrune:
    """Tests for update_experience, merge_experiences, prune_experiences —
    using real temporary directories with actual experience files."""

    import tempfile as _tempfile_mod
    import shutil as _shutil_mod

    @staticmethod
    def _make_temp_root():
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="exp_test_"))
        for cat in [
            "physics",
            "motion",
            "gripper",
            "grasp",
            "code",
            "general",
            "_archive",
            "_history",
        ]:
            (tmp / cat).mkdir(parents=True, exist_ok=True)
        return tmp

    @staticmethod
    def make_manager():
        db = FakeDB()
        return ExperienceManager(db=db, session_id="s01")

    # ── update_experience ──────────────────────────────────────────────

    def test_update_experience_updates_frontmatter(self):
        """update_experience should merge new frontmatter and keep body intact."""
        import shutil
        from robocode.agent.experience_filesystem import write_experience

        mgr = self.make_manager()
        d = self._make_temp_root()
        try:
            fm = {
                "type": "physics",
                "confidence": 0.5,
                "data_points": 10,
                "tags": ["physics"],
                "sources": "s1",
                "created": "2026-05-01",
                "updated": "2026-05-01",
            }
            write_experience("physics", "test.md", fm, "# Test Body", base_dir=d)

            ok = mgr.update_experience(
                "physics",
                "test.md",
                frontmatter_updates={"confidence": 0.75},
                base_dir=d,
            )
            assert ok is True

            updated_fm = mgr._read_frontmatter(d / "physics" / "test.md")
            assert updated_fm["confidence"] == 0.75
            assert updated_fm["data_points"] == 10
            body = mgr._read_body(d / "physics" / "test.md")
            assert "# Test Body" in body
            backups = list((d / "_history").glob("test.md.*.md"))
            assert len(backups) == 1
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_update_experience_missing_file_returns_false(self):
        """update_experience returns False for non-existent file."""
        import shutil

        mgr = self.make_manager()
        d = self._make_temp_root()
        try:
            ok = mgr.update_experience(
                "physics",
                "nonexistent.md",
                frontmatter_updates={"confidence": 0.8},
                base_dir=d,
            )
            assert ok is False
        finally:
            shutil.rmtree(d, ignore_errors=True)

    # ── merge_experiences ──────────────────────────────────────────────

    def test_merge_similar_files(self):
        """Two >80% similar files should be merged into one."""
        import shutil
        from robocode.agent.experience_filesystem import write_experience

        mgr = self.make_manager()
        d = self._make_temp_root()
        try:
            fm1 = {
                "type": "physics",
                "confidence": 0.6,
                "data_points": 8,
                "tags": ["physics", "velocity"],
                "sources": "s1",
                "created": "2026-05-01",
                "updated": "2026-05-01",
            }
            body1 = "## 概览\n\n速度与偏差关系。\n\n## 数据支撑\n\n| speed | delta |\n|-------|-------|\n| 0.5 | 0.1 |\n"

            fm2 = {
                "type": "physics",
                "confidence": 0.7,
                "data_points": 5,
                "tags": ["physics", "velocity"],
                "sources": "s2",
                "created": "2026-05-02",
                "updated": "2026-05-02",
            }
            body2 = "## 概览\n\n速度与偏差关系。\n\n## 数据支撑\n\n| speed | delta |\n|-------|-------|\n| 0.8 | 4.0 |\n"

            write_experience("physics", "velocity-1.md", fm1, body1, base_dir=d)
            write_experience("physics", "velocity-2.md", fm2, body2, base_dir=d)

            merged_count = mgr.merge_experiences(base_dir=d)
            assert merged_count == 1

            archive_files = list((d / "_archive").rglob("*.md"))
            assert len(archive_files) == 1

            target = d / "physics" / "velocity-1.md"
            assert target.exists()
            target_body = mgr._read_body(target)
            assert "合并自: velocity-2.md" in target_body
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_merge_skips_dissimilar_files(self):
        """Files with <80% similarity should not be merged."""
        import shutil
        from robocode.agent.experience_filesystem import write_experience

        mgr = self.make_manager()
        d = self._make_temp_root()
        try:
            fm1 = {
                "type": "physics",
                "confidence": 0.6,
                "data_points": 8,
                "tags": ["physics"],
                "sources": "s1",
                "created": "2026-05-01",
                "updated": "2026-05-01",
            }
            body1 = "## 角度偏差分析\n\n这是关于关节角度的数据。\n"

            fm2 = {
                "type": "operational",
                "confidence": 0.7,
                "data_points": 5,
                "tags": ["grasp"],
                "refs": "",
                "success": True,
                "sources": "s2",
                "created": "2026-05-02",
                "updated": "2026-05-02",
            }
            body2 = "## 抓取操作经验\n\n完全不同的内容关于抓取成功率。\n"

            write_experience("physics", "angle.md", fm1, body1, base_dir=d)
            write_experience("physics", "grasp-exp.md", fm2, body2, base_dir=d)

            merged_count = mgr.merge_experiences(base_dir=d)
            assert merged_count == 0
            assert (d / "physics" / "angle.md").exists()
            assert (d / "physics" / "grasp-exp.md").exists()
        finally:
            shutil.rmtree(d, ignore_errors=True)

    # ── prune_experiences ─────────────────────────────────────────────

    def test_prune_archives_low_confidence_files(self):
        """Low-confidence low-data-points files should be archived."""
        import shutil
        from robocode.agent.experience_filesystem import write_experience

        mgr = self.make_manager()
        d = self._make_temp_root()
        try:
            fm_low = {
                "type": "physics",
                "confidence": 0.2,
                "data_points": 2,
                "tags": ["physics"],
                "sources": "s1",
                "created": "2026-05-01",
                "updated": "2026-05-01",
            }
            write_experience("physics", "low-conf.md", fm_low, "# Low conf", base_dir=d)

            fm_high = {
                "type": "physics",
                "confidence": 0.8,
                "data_points": 15,
                "tags": ["physics"],
                "sources": "s1",
                "created": "2026-05-01",
                "updated": "2026-05-01",
            }
            write_experience("physics", "high-conf.md", fm_high, "# High conf", base_dir=d)

            pruned = mgr.prune_experiences(base_dir=d)
            assert pruned == 1

            archive_files = list((d / "_archive").rglob("*.md"))
            assert len(archive_files) == 1
            assert archive_files[0].name == "low-conf.md"

            assert (d / "physics" / "high-conf.md").exists()
            assert not (d / "physics" / "low-conf.md").exists()
        finally:
            shutil.rmtree(d, ignore_errors=True)
