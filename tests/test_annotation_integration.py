"""Integration test: annotation panel + confidence feedback pipeline.

Tests the annotation flow end-to-end:
  register pending → mock tty input → collect annotation → DB write
  → failure detection → confidence feedback update
"""

from unittest.mock import patch

import pytest

from robocode.services.analytics.db import AuditDB
from robocode.agent.annotation import AnnotationCollector
from robocode.agent.experience_manager import ExperienceManager
from robocode.agent.experience_filesystem import write_experience
from robocode.cli.annotation_panel import AnnotationPanel


def _make_db_with_pending(tmp_path):
    db = AuditDB(str(tmp_path / "test.db"))
    db.initialize()
    sid = db.create_session()
    cid = db.record_tool_call(sid, "move_robot_xyz", "L2", {"x": 300}, {"success": True})
    return db, sid, cid


def _setup_exp_dir(tmp_path):
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / "_archive").mkdir(parents=True, exist_ok=True)
    (exp_dir / "_history").mkdir(parents=True, exist_ok=True)
    return exp_dir


class TestAnnotationPanelEndToEnd:
    @pytest.mark.asyncio
    async def test_successful_annotation_flow(self, tmp_path):
        db, sid, cid = _make_db_with_pending(tmp_path)
        collector = AnnotationCollector(db=db, session_id=sid)
        collector.register_tool_call(cid, "move_robot_xyz", {"x": 300})

        panel = AnnotationPanel(collector)

        with patch.object(panel, "_read_input_line", return_value="动作平稳，位置准确"):
            results, fb = await panel.run()

        assert len(results) == 1
        assert fb == "动作平稳，位置准确"
        r = results[0]
        assert r.tool_name == "move_robot_xyz"
        assert r.category == "motion"
        assert not r.is_failure
        assert r.free_text == "动作平稳，位置准确"
        assert r.choices == {}

        annotations = db.get_unprocessed_annotations(sid)
        assert len(annotations) == 1
        assert annotations[0]["is_failure"] == 0
        db.close()

    @pytest.mark.asyncio
    async def test_failure_annotation_detected(self, tmp_path):
        db, sid, cid = _make_db_with_pending(tmp_path)
        collector = AnnotationCollector(db=db, session_id=sid)
        collector.register_tool_call(cid, "move_robot_xyz", {"x": 300})

        panel = AnnotationPanel(collector)

        with patch.object(panel, "_read_input_line", return_value="振动严重，位置偏了"):
            results, fb = await panel.run()

        assert len(results) == 1
        assert fb == "振动严重，位置偏了"
        r = results[0]
        assert r.is_failure is True
        assert r.free_text == "振动严重，位置偏了"
        assert r.choices == {}

        failures = AnnotationPanel.get_failure_summary(results)
        assert len(failures) == 1
        assert failures[0]["tool_name"] == "move_robot_xyz"
        db.close()

    @pytest.mark.asyncio
    async def test_skip_annotation(self, tmp_path):
        db, sid, cid = _make_db_with_pending(tmp_path)
        collector = AnnotationCollector(db=db, session_id=sid)
        collector.register_tool_call(cid, "move_robot_xyz", {"x": 300})

        panel = AnnotationPanel(collector)

        with patch.object(panel, "_read_input_line", return_value=""):
            results, fb = await panel.run()

        assert len(results) == 0
        assert fb == ""
        assert collector.count_unannotated() == 0
        db.close()

    @pytest.mark.asyncio
    async def test_no_pending_collects_chat_feedback(self, tmp_path):
        db, sid, cid = _make_db_with_pending(tmp_path)
        collector = AnnotationCollector(db=db, session_id=sid)

        panel = AnnotationPanel(collector)
        with patch.object(panel, "_read_input_line", return_value="纯聊天，讨论了一些问题"):
            results, fb = await panel.run()
        assert results == []
        assert fb == "纯聊天，讨论了一些问题"
        db.close()


class TestConfidenceFeedback:
    def test_failure_lowers_confidence(self, tmp_path):
        db, sid, cid = _make_db_with_pending(tmp_path)
        exp_dir = _setup_exp_dir(tmp_path)

        fm = {"confidence": 0.7, "data_points": 10, "tags": ["test"], "category": "motion"}
        body = "# Motion Experience\n\n## 建议\n- [RULE] 控制速度"
        write_experience("motion", "motion-experience.md", fm, body, base_dir=exp_dir)

        mgr = ExperienceManager(db=db, session_id=sid)
        mgr.update_experience(
            "motion",
            "motion-experience.md",
            frontmatter_updates={"confidence": 0.65},
            base_dir=exp_dir,
        )

        content = (exp_dir / "motion" / "motion-experience.md").read_text()
        assert "confidence: 0.65" in content
        db.close()

    def test_success_raises_confidence(self, tmp_path):
        db, sid, cid = _make_db_with_pending(tmp_path)
        exp_dir = _setup_exp_dir(tmp_path)

        fm = {"confidence": 0.5, "data_points": 10, "tags": ["test"], "category": "motion"}
        body = "# Motion\n\n## 建议\n- test"
        write_experience("motion", "motion-test.md", fm, body, base_dir=exp_dir)

        mgr = ExperienceManager(db=db, session_id=sid)
        mgr.update_experience(
            "motion", "motion-test.md", frontmatter_updates={"confidence": 0.53}, base_dir=exp_dir
        )

        content = (exp_dir / "motion" / "motion-test.md").read_text()
        assert "confidence: 0.53" in content
        db.close()
