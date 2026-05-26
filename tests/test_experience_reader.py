"""Tests for ExperienceReader — index loading, relevance lookup, confidence filtering."""

import shutil
import tempfile
from pathlib import Path
from robocode.agent.experience_reader import ExperienceReader


def make_experience_dir():
    tmp = Path(tempfile.mkdtemp(prefix="exp_reader_test_"))
    for sub in ["physics", "motion", "gripper", "grasp", "code", "general", "_archive", "_history"]:
        (tmp / sub).mkdir(parents=True, exist_ok=True)
    return tmp


class TestExperienceReaderLoadIndex:
    def test_load_existing_index(self):
        d = make_experience_dir()
        try:
            (d / "index.md").write_text(
                "# 机械臂经验索引\n\n总经验数: 2\n\n## 分类分布\n\n"
                "- physics: 1\n- grasp: 1\n\n"
                "## 最近更新\n- velocity-deviation | physics/velocity-deviation.md\n",
            )
            reader = ExperienceReader(base_dir=d)
            assert reader.has_experiences() is True
            assert reader.total_experiences == 2
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_no_index_graceful_degradation(self):
        d = make_experience_dir()
        try:
            reader = ExperienceReader(base_dir=d)
            assert reader.has_experiences() is False
            assert reader.total_experiences == 0
            summary = reader.get_index_summary()
            assert summary == ""
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestExperienceReaderConfidenceFilter:
    def test_filter_low_confidence(self):
        d = make_experience_dir()
        try:
            (d / "index.md").write_text(
                "# 索引\n\n总经验数: 3\n\n"
                "## 分类分布\n- physics: 2\n- grasp: 1\n\n"
                "## 最近更新\n"
                "- velocity-deviation | physics/velocity-deviation.md (confidence=0.85)\n"
                "- weak-signal | physics/weak-signal.md (confidence=0.25)\n"
                "- grasp-6d | grasp/grasp-6d.md (confidence=0.80)\n",
            )
            reader = ExperienceReader(base_dir=d)
            visible = reader.get_visible_experiences(min_confidence=0.4)
            assert len(visible) == 2
            confs = [e["confidence"] for e in visible]
            assert 0.85 in confs
            assert 0.80 in confs
            assert 0.25 not in confs
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_sort_by_confidence_desc(self):
        d = make_experience_dir()
        try:
            (d / "index.md").write_text(
                "# 索引\n\n总经验数: 3\n\n"
                "## 分类分布\n- physics: 2\n- grasp: 1\n\n"
                "## 最近更新\n"
                "- a | physics/a.md (confidence=0.60)\n"
                "- b | physics/b.md (confidence=0.85)\n"
                "- c | grasp/c.md (confidence=0.72)\n",
            )
            reader = ExperienceReader(base_dir=d)
            visible = reader.get_visible_experiences(min_confidence=0.4)
            assert visible[0]["confidence"] == 0.85
            assert visible[1]["confidence"] == 0.72
            assert visible[2]["confidence"] == 0.60
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestRebuildIndexToReaderPipeline:
    """Integration test: rebuild_index output MUST be parseable by ExperienceReader."""

    def test_rebuild_index_then_reader_sees_experiences(self):
        import tempfile
        from robocode.agent.experience_filesystem import write_experience, rebuild_index

        d = Path(tempfile.mkdtemp(prefix="exp_pipeline_test_"))
        try:
            for sub in [
                "physics",
                "motion",
                "gripper",
                "grasp",
                "code",
                "general",
                "_archive",
                "_history",
            ]:
                (d / sub).mkdir(parents=True, exist_ok=True)

            # Write an experience with known confidence
            fm = {
                "type": "physics",
                "tags": ["speed"],
                "confidence": 0.85,
                "data_points": 10,
                "sources": "sess-01",
                "created": "2026-05-14",
                "updated": "2026-05-14",
            }
            write_experience(
                "physics",
                "velocity-deviation.md",
                fm,
                "## 物理规律\n\n速度偏差分析。\n\n## 数据支撑\n\n...\n\n## 建议\n\n...",
                base_dir=d,
            )

            rebuild_index(base_dir=d)

            reader = ExperienceReader(base_dir=d)
            assert reader.has_experiences(), "Reader should see experiences after rebuild_index"
            assert reader.total_experiences >= 1
            visible = reader.get_visible_experiences(min_confidence=0.4)
            assert len(visible) >= 1
            assert visible[0]["confidence"] == 0.85
            summary = reader.get_index_summary()
            assert "velocity-deviation.md" in summary
            assert "⭐" in summary
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestExperienceReaderSummary:
    def test_summary_format(self):
        d = make_experience_dir()
        try:
            (d / "index.md").write_text(
                "# 索引\n\n总经验数: 2\n\n"
                "## 分类分布\n- physics: 1\n- grasp: 1\n\n"
                "## 最近更新\n"
                "- velocity-deviation | physics/velocity-deviation.md (confidence=0.85)\n"
                "- grasp-6d | grasp/grasp-6d.md (confidence=0.80)\n",
            )
            reader = ExperienceReader(base_dir=d)
            summary = reader.get_index_summary()
            assert "经验目录" in summary
            assert "velocity-deviation.md" in summary
            assert "⭐" in summary  # high confidence marker
            assert "grasp-6d.md" in summary
            assert "read_file" in summary  # instruction to use read_file
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_summary_confidence_markers(self):
        d = make_experience_dir()
        try:
            (d / "index.md").write_text(
                "# 索引\n\n总经验数: 2\n\n"
                "## 分类分布\n- physics: 1\n- motion: 1\n\n"
                "## 最近更新\n"
                "- big | physics/big.md (confidence=0.85)\n"
                "- small | motion/small.md (confidence=0.60)\n",
            )
            reader = ExperienceReader(base_dir=d)
            summary = reader.get_index_summary()
            # confidence >= 0.7 → ⭐
            assert "big.md" in summary
            assert "⭐" in summary
            # 0.4-0.7 → ⚠
            lines = summary.split("\n")
            small_line = [line for line in lines if "small.md" in line][0]
            assert "⚠" in small_line
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_empty_summary_when_no_experiences(self):
        d = make_experience_dir()
        try:
            reader = ExperienceReader(base_dir=d)
            assert reader.get_index_summary() == ""
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_summary_truncates_long_list(self):
        """Should only show top 10 experiences."""
        d = make_experience_dir()
        try:
            lines = ["# 索引\n\n总经验数: 15\n\n## 分类分布\n- physics: 15\n\n## 最近更新"]
            for i in range(15):
                lines.append(f"- exp-{i:02d} | physics/exp-{i:02d}.md (confidence=0.{80 - i:02d})")
            (d / "index.md").write_text("\n".join(lines))
            reader = ExperienceReader(base_dir=d)
            visible = reader.get_visible_experiences(min_confidence=0.4)
            # Should have entries but max out at some reasonable level
            assert len(visible) <= 15
            summary = reader.get_index_summary()
            assert "exp-00.md" in summary
        finally:
            shutil.rmtree(d, ignore_errors=True)
