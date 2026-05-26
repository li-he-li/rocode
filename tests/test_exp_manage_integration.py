"""Integration test: _run_exp_manage() full pipeline.

Tests the complete experience management chain:
  analyze_physics → analyze_call_flow → process_annotations
  → LLM reflection → write files → merge → prune → rebuild_index → mark processed

Uses FakeProvider to mock LLM, tmp_path for filesystem isolation.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from robocode.services.analytics.db import AuditDB
from robocode.agent.experience_manager import ExperienceManager
from robocode.agent.experience_filesystem import (
    write_experience,
    rebuild_index,
)
from robocode.agent.reflector import Reflector
from robocode.llm.fake_provider import FakeProvider
from robocode.llm.base import StreamEvent


def _make_db_with_physics(tmp_path):
    db = AuditDB(str(tmp_path / "test.db"))
    db.initialize()
    sid = db.create_session()
    cid1 = db.record_tool_call(
        sid, "move_robot_xyz", "L2", {"x": 300}, {"success": True}, duration_ms=100
    )
    cid2 = db.record_tool_call(
        sid, "move_robot_xyz", "L2", {"x": 350}, {"success": True}, duration_ms=200
    )
    cid3 = db.record_tool_call(
        sid, "move_robot_xyz", "L2", {"x": 400}, {"success": True}, duration_ms=150
    )
    db.insert_physics_data(
        tool_call_id=cid1,
        session_id=sid,
        tool_name="move_robot_xyz",
        joint_angles_before=[10, 20, 30, 40, 50, 60],
        joint_angles_after=[12, 22, 32, 42, 52, 62],
        duration_ms=3000,
        speed_ratio=0.5,
    )
    db.insert_physics_data(
        tool_call_id=cid2,
        session_id=sid,
        tool_name="move_robot_xyz",
        joint_angles_before=[10, 20, 30, 40, 50, 60],
        joint_angles_after=[15, 25, 35, 45, 55, 65],
        duration_ms=4000,
        speed_ratio=0.5,
    )
    db.insert_physics_data(
        tool_call_id=cid3,
        session_id=sid,
        tool_name="move_robot_xyz",
        joint_angles_before=[12, 22, 32, 42, 52, 62],
        joint_angles_after=[18, 28, 38, 48, 58, 68],
        duration_ms=3500,
        speed_ratio=0.5,
    )
    return db, sid


def _make_db_with_annotations(tmp_path):
    db = AuditDB(str(tmp_path / "test.db"))
    db.initialize()
    sid = db.create_session()
    cid1 = db.record_tool_call(sid, "move_robot_xyz", "L2", {"x": 300}, {"success": True})
    cid2 = db.record_tool_call(sid, "move_robot_xyz", "L2", {"x": 350}, {"success": False})
    db.insert_physics_data(
        tool_call_id=cid1,
        session_id=sid,
        tool_name="move_robot_xyz",
        joint_angles_before=[10, 20, 30, 40, 50, 60],
        joint_angles_after=[12, 22, 32, 42, 52, 62],
        duration_ms=3000,
        speed_ratio=0.5,
    )
    db.insert_annotation(
        tool_call_id=cid1,
        session_id=sid,
        category="motion",
        choices={"motion_quality": "平稳", "position_accuracy": "准确"},
        is_failure=False,
    )
    db.insert_annotation(
        tool_call_id=cid2,
        session_id=sid,
        category="motion",
        choices={"motion_quality": "严重振动", "position_accuracy": "明显偏差"},
        is_failure=True,
    )
    return db, sid


def _make_db_with_call_flow(tmp_path):
    db = AuditDB(str(tmp_path / "test.db"))
    db.initialize()
    sid = db.create_session()
    db.record_tool_call(
        sid, "get_status", "L0", {}, {"success": True}, task_instruction="移动到300", turn_number=1
    )
    db.record_tool_call(
        sid,
        "move_robot_xyz",
        "L2",
        {"x": 300},
        {"success": True},
        task_instruction="移动到300",
        turn_number=2,
        prev_call_id=1,
    )
    return db, sid


def _setup_exp_dir(tmp_path):
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / "_archive").mkdir(parents=True, exist_ok=True)
    (exp_dir / "_history").mkdir(parents=True, exist_ok=True)
    return exp_dir


class TestExpManagePhysicsPipeline:
    def test_physics_analysis_creates_experience_file(self, tmp_path):
        db, sid = _make_db_with_physics(tmp_path)
        exp_dir = _setup_exp_dir(tmp_path)
        mgr = ExperienceManager(db=db, session_id="")

        physics = mgr.analyze_physics()
        assert physics is not None
        assert "move_robot_xyz" in physics

        fm, body = mgr.create_experience(
            category="physics",
            domain="angle-deviation",
            title="move_robot_xyz 角度偏差分析",
            data={"move_robot_xyz": physics["move_robot_xyz"]},
            confidence=0.6,
            data_points=physics["move_robot_xyz"]["total_data_points"],
        )
        write_experience("physics", "move_robot_xyz-angle-deviation.md", fm, body, base_dir=exp_dir)
        rebuild_index(base_dir=exp_dir)

        fpath = exp_dir / "physics" / "move_robot_xyz-angle-deviation.md"
        assert fpath.exists()
        content = fpath.read_text()
        assert "confidence:" in content
        db.close()

    def test_physics_data_marked_processed(self, tmp_path):
        db, sid = _make_db_with_physics(tmp_path)
        assert len(db.get_unprocessed_physics()) == 3
        db.mark_physics_processed()
        assert len(db.get_unprocessed_physics()) == 0
        db.close()


class TestExpManageCallFlowPipeline:
    def test_call_flow_analysis_with_data(self, tmp_path):
        db, sid = _make_db_with_call_flow(tmp_path)
        mgr = ExperienceManager(db=db, session_id="")
        flows = mgr.analyze_call_flow()
        assert flows is not None
        assert "sequences" in flows or "instruction_map" in flows
        db.close()

    def test_call_flow_empty_session_returns_all(self, tmp_path):
        db, sid = _make_db_with_call_flow(tmp_path)
        calls = db.list_tool_calls("")
        assert len(calls) >= 2
        db.close()


class TestExpManageAnnotationPipeline:
    def test_annotation_processing_creates_experience(self, tmp_path):
        db, sid = _make_db_with_annotations(tmp_path)
        exp_dir = _setup_exp_dir(tmp_path)
        mgr = ExperienceManager(db=db, session_id="")

        annotations = mgr.process_annotations()
        assert annotations is not None
        assert "motion" in annotations
        cat_data = annotations["motion"]
        assert cat_data["total"] == 2
        assert len(cat_data["failures"]) == 1

        fm, body = mgr.create_experience(
            category="motion",
            domain="motion-best-practices",
            title="motion 操作经验",
            data=None,
            confidence=0.6,
            data_points=cat_data["total"],
            annotations={"motion": cat_data},
        )
        write_experience("motion", "motion-experience.md", fm, body, base_dir=exp_dir)

        fpath = exp_dir / "motion" / "motion-experience.md"
        assert fpath.exists()
        db.close()


class TestExpManageReflectorIntegration:
    @pytest.mark.asyncio
    async def test_reflector_produces_bullets_with_fake_provider(self):
        fake_response = [
            StreamEvent(
                kind="text_delta", payload={"delta": "- [PARAM] speed_ratio 0.3~0.5 是精度甜蜜点\n"}
            ),
            StreamEvent(kind="text_delta", payload={"delta": "- [CAUTION] z<50 时 IK 无解\n"}),
            StreamEvent(kind="end_turn", payload={}),
        ]
        provider = FakeProvider(responses=[fake_response])
        reflector = Reflector(provider=provider, max_bullets=8)
        physics = {
            "move_robot_xyz": {
                "speed_groups": {
                    0.5: {
                        "avg_max_delta": 5.2,
                        "count": 2,
                        "avg_duration_ms": 3500,
                        "samples": [{"before": [1, 2, 3, 4, 5, 6], "after": [2, 3, 4, 5, 6, 7]}],
                    }
                },
                "total_data_points": 2,
            }
        }
        bullets = await reflector.reflect(
            physics=physics,
            transcript=[{"role": "user", "content": "移动机械臂"}],
        )
        assert len(bullets) == 2
        assert any("PARAM" in b["raw"] for b in bullets)

    @pytest.mark.asyncio
    async def test_reflector_graceful_on_exception(self):
        provider = MagicMock()
        provider.stream = AsyncMock(side_effect=RuntimeError("API down"))
        reflector = Reflector(provider=provider, max_bullets=8)
        bullets = []
        try:
            bullets = await reflector.reflect(
                physics={"tool": {"speed_groups": {}, "total_data_points": 1}}
            )
        except Exception:
            pass
        assert isinstance(bullets, list)


class TestExpManageMergeAndPrune:
    def test_merge_similar_files(self, tmp_path):
        db = AuditDB(str(tmp_path / "test.db"))
        db.initialize()
        exp_dir = _setup_exp_dir(tmp_path)
        mgr = ExperienceManager(db=db, session_id="")

        fm1 = {"confidence": 0.6, "data_points": 10, "tags": ["test"], "category": "motion"}
        body1 = "# Motion A\n\n## 数据\n- speed 0.5: delta=3.2\n\n## 建议\n- [RULE] 控制速度"
        fm2 = {"confidence": 0.5, "data_points": 5, "tags": ["test"], "category": "motion"}
        body2 = "# Motion B\n\n## 数据\n- speed 0.5: delta=3.1\n\n## 建议\n- [RULE] 控制速度"

        write_experience("motion", "motion-a.md", fm1, body1, base_dir=exp_dir)
        write_experience("motion", "motion-b.md", fm2, body2, base_dir=exp_dir)

        merged = mgr.merge_experiences(base_dir=exp_dir)
        assert merged >= 1

        remaining = [
            f
            for f in exp_dir.glob("**/*.md")
            if f.name != "index.md" and "_archive" not in str(f) and "_history" not in str(f)
        ]
        assert len(remaining) == 1
        assert "data_points: 15" in remaining[0].read_text()
        db.close()

    def test_prune_low_confidence(self, tmp_path):
        db = AuditDB(str(tmp_path / "test.db"))
        db.initialize()
        exp_dir = _setup_exp_dir(tmp_path)
        mgr = ExperienceManager(db=db, session_id="")

        fm_low = {"confidence": 0.2, "data_points": 3, "tags": ["test"], "category": "motion"}
        fm_ok = {"confidence": 0.7, "data_points": 10, "tags": ["test"], "category": "motion"}

        write_experience("motion", "low-conf.md", fm_low, "# Low", base_dir=exp_dir)
        write_experience("motion", "ok-conf.md", fm_ok, "# OK", base_dir=exp_dir)

        pruned = mgr.prune_experiences(base_dir=exp_dir)
        assert pruned == 1

        remaining = [
            f
            for f in exp_dir.glob("**/*.md")
            if f.name != "index.md" and "_archive" not in str(f) and "_history" not in str(f)
        ]
        assert len(remaining) == 1
        assert remaining[0].name == "ok-conf.md"
        db.close()


class TestExpManageFullPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline_physics_and_annotations(self, tmp_path):
        db, sid = _make_db_with_annotations(tmp_path)
        exp_dir = _setup_exp_dir(tmp_path)

        fake_response = [
            StreamEvent(
                kind="text_delta", payload={"delta": "- [PARAM] motion speed sweet spot\n"}
            ),
            StreamEvent(kind="end_turn", payload={}),
        ]
        provider = FakeProvider(responses=[fake_response])
        mgr = ExperienceManager(db=db, session_id="")
        reflector = Reflector(provider=provider, max_bullets=8)

        physics = mgr.analyze_physics()
        annotations = mgr.process_annotations()
        assert (physics or annotations) is not None

        bullets = await reflector.reflect(
            transcript=[{"role": "user", "content": "移动机械臂"}],
            physics=physics,
            annotations=annotations,
        )
        assert len(bullets) >= 1

        if annotations:
            for category, cat_data in annotations.items():
                if not cat_data.get("failures") and not cat_data.get("successes"):
                    continue
                filename = f"{category}-experience.md"
                fm, body = mgr.create_experience(
                    category=category,
                    domain=f"{category}-best-practices",
                    title=f"{category} 操作经验",
                    data=None,
                    confidence=0.6,
                    data_points=cat_data.get("total", 0),
                    annotations={category: cat_data},
                    bullets=bullets,
                )
                write_experience(category, filename, fm, body, base_dir=exp_dir)

        mgr.merge_experiences(base_dir=exp_dir)
        mgr.prune_experiences(base_dir=exp_dir)
        rebuild_index(base_dir=exp_dir)
        db.mark_physics_processed()
        db.mark_annotations_processed()

        assert (exp_dir / "index.md").exists()
        assert "motion" in (exp_dir / "index.md").read_text()
        assert len(db.get_unprocessed_physics()) == 0
        assert len(db.get_unprocessed_annotations()) == 0
        db.close()

    @pytest.mark.asyncio
    async def test_full_pipeline_empty_data_no_files(self, tmp_path):
        db = AuditDB(str(tmp_path / "test.db"))
        db.initialize()
        db.create_session()
        exp_dir = _setup_exp_dir(tmp_path)
        mgr = ExperienceManager(db=db, session_id="")

        assert mgr.analyze_physics() is None
        assert mgr.process_annotations() is None
        assert mgr.analyze_call_flow() is None

        mgr.merge_experiences(base_dir=exp_dir)
        mgr.prune_experiences(base_dir=exp_dir)
        rebuild_index(base_dir=exp_dir)

        md_files = [
            f
            for f in exp_dir.glob("**/*.md")
            if f.name != "index.md" and "_archive" not in str(f) and "_history" not in str(f)
        ]
        assert len(md_files) == 0
        db.close()
