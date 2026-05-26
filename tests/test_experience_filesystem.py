"""Tests for experience filesystem — directory init, file format, backup, archive, index."""

import tempfile
import shutil
from pathlib import Path
import pytest


EXPERIENCE_DIR = Path(__file__).resolve().parent.parent / "robocode" / "experience"


# ── Helpers ──────────────────────────────────────────────────────────


def make_temp_experience_dir():
    tmp = Path(tempfile.mkdtemp(prefix="exp_test_"))
    for cat in ["physics", "motion", "gripper", "grasp", "code", "general"]:
        (tmp / cat).mkdir(parents=True, exist_ok=True)
    (tmp / "_archive").mkdir(parents=True, exist_ok=True)
    (tmp / "_history").mkdir(parents=True, exist_ok=True)
    return tmp


# ── Tests ────────────────────────────────────────────────────────────


class TestDirectoryInit:
    @pytest.fixture(autouse=True)
    def _ensure_dirs(self):
        """Create missing directories for tests."""
        (EXPERIENCE_DIR / "_archive").mkdir(parents=True, exist_ok=True)
        (EXPERIENCE_DIR / "_history").mkdir(parents=True, exist_ok=True)
        # Create root index.md if missing
        root_idx = EXPERIENCE_DIR / "index.md"
        if not root_idx.exists():
            root_idx.write_text("# 机械臂经验索引\n\n总经验数: 0\n", encoding="utf-8")

    def test_directory_structure_exists(self):
        assert EXPERIENCE_DIR.exists(), f"{EXPERIENCE_DIR} does not exist"
        for sub in ["_archive", "_history"]:
            assert (EXPERIENCE_DIR / sub).is_dir(), f"subdirectory {sub} missing"

    def test_index_files_exist(self):
        assert (EXPERIENCE_DIR / "index.md").exists()


class TestExperienceFileFormat:
    def test_write_and_parse_frontmatter(self):
        """Experience files must have YAML frontmatter with required fields."""
        from robocode.agent.experience_filesystem import write_experience as m_write

        d = make_temp_experience_dir()
        try:
            fm = {
                "type": "physics",
                "domain": "velocity",
                "tags": ["speed", "deviation"],
                "confidence": 0.85,
                "data_points": 15,
                "sources": "session-abc",
                "created": "2026-05-14",
                "updated": "2026-05-14",
            }
            body = "## 物理规律\n\n速度偏差关联分析。\n\n## 数据支撑\n\n| speed | deviation |\n|-------|-----------|"
            fpath = m_write("physics", "velocity-deviation.md", fm, body, base_dir=d)
            assert fpath.exists()

            content = fpath.read_text()
            assert "type: physics" in content
            assert "confidence: 0.85" in content
            assert "data_points: 15" in content
            assert "物理规律" in content
            assert "数据支撑" in content
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_operational_experience_format(self):
        """Operational experience includes recommended workflow section."""
        from robocode.agent.experience_filesystem import write_experience as m_write

        d = make_temp_experience_dir()
        try:
            fm = {
                "type": "operational",
                "tags": ["grasp", "6d"],
                "refs": "physics/velocity-deviation.md",
                "success": True,
                "confidence": 0.72,
                "data_points": 8,
                "sources": "session-xyz",
                "created": "2026-05-14",
                "updated": "2026-05-14",
            }
            body = (
                "## 案例\n\n6d_grasp 抓取海绵块。\n"
                "## 关联物理规律\n\n速度与偏差。\n"
                "## 推荐工具流程\n\n"
                "check_calibration_status → move_robot_xyz → 6d_grasp\n"
                "## 重试模式\n\n"
                "IK 无解时换用 move_robot_joints。\n"
                "## 建议\n\n抓取前确认标定文件存在。\n"
            )
            fpath = m_write("physics", "grasp-6d.md", fm, body, base_dir=d)
            content = fpath.read_text()
            assert "type: operational" in content
            assert "推荐工具流程" in content
            assert "重试模式" in content
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestBackupAndArchive:
    def test_backup_before_update(self):
        from robocode.agent.experience_filesystem import write_experience as m_write
        from robocode.agent.experience_filesystem import backup_before_update as m_backup

        d = make_temp_experience_dir()
        try:
            fm = {
                "type": "physics",
                "confidence": 0.5,
                "data_points": 3,
                "sources": "test",
                "created": "2026-01-01",
                "updated": "2026-01-01",
            }
            m_write("physics", "test.md", fm, "v1 content", base_dir=d)
            m_backup("physics", "test.md", base_dir=d)

            history_files = list((d / "_history").glob("*.md"))
            assert len(history_files) == 1
            assert "v1 content" in history_files[0].read_text()

            # Now update the file
            m_write("physics", "test.md", fm, "v2 content", base_dir=d)
            assert "v2 content" in (d / "physics" / "test.md").read_text()
            assert "v1 content" in history_files[0].read_text()
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_archive_file(self):
        from robocode.agent.experience_filesystem import write_experience as m_write
        from robocode.agent.experience_filesystem import archive_file as m_archive

        d = make_temp_experience_dir()
        try:
            fm = {
                "type": "physics",
                "confidence": 0.2,
                "data_points": 2,
                "sources": "test",
                "created": "2026-01-01",
                "updated": "2026-01-01",
            }
            m_write("physics", "stale.md", fm, "stale", base_dir=d)
            m_archive("physics", "stale.md", base_dir=d)

            assert not (d / "physics" / "stale.md").exists()
            archive_dirs = list((d / "_archive").glob("*"))
            assert len(archive_dirs) == 1
            archived = list(archive_dirs[0].glob("stale.md"))
            assert len(archived) == 1
            assert "stale" in archived[0].read_text()
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_archive_never_deletes(self):
        """Archived files are moved, never deleted."""
        from robocode.agent.experience_filesystem import write_experience as m_write
        from robocode.agent.experience_filesystem import archive_file as m_archive

        d = make_temp_experience_dir()
        try:
            fm = {
                "type": "physics",
                "confidence": 0.2,
                "data_points": 2,
                "sources": "test",
                "created": "2026-01-01",
                "updated": "2026-01-01",
            }
            m_write("physics", "old.md", fm, "content", base_dir=d)
            m_archive("physics", "old.md", base_dir=d)

            # File is in _archive, not deleted
            archive_dirs = list((d / "_archive").glob("*"))
            archived_files = list(archive_dirs[0].glob("*.md"))
            assert len(archived_files) == 1
            assert archived_files[0].name == "old.md"
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestIndexRebuild:
    def test_rebuild_index(self):
        from robocode.agent.experience_filesystem import write_experience as m_write
        from robocode.agent.experience_filesystem import rebuild_index as m_rebuild

        d = make_temp_experience_dir()
        try:
            fm1 = {
                "type": "physics",
                "confidence": 0.8,
                "data_points": 10,
                "sources": "s1",
                "created": "2026-05-01",
                "updated": "2026-05-10",
            }
            fm2 = {
                "type": "operational",
                "confidence": 0.7,
                "data_points": 5,
                "refs": "",
                "success": True,
                "tags": ["grasp"],
                "sources": "s2",
                "created": "2026-05-02",
                "updated": "2026-05-11",
            }
            m_write("physics", "angle-deviation.md", fm1, "phys body", base_dir=d)
            m_write("physics", "grasp-6d.md", fm2, "grasp body", base_dir=d)

            m_rebuild(d)

            assert (d / "index.md").exists()
            idx = (d / "index.md").read_text()
            assert "总经验数: 2" in idx
            assert "0.80" in idx
            assert "0.70" in idx
            assert "angle-deviation.md" in idx
            assert "grasp-6d.md" in idx
            assert "## 目录" in idx
        finally:
            shutil.rmtree(d, ignore_errors=True)
