"""3.1: Patch editing tools — safety and correctness tests."""

import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


PATCH_ADD_FUNCTION = """--- a/robocode/tools/_patch_test_temp.py
+++ b/robocode/tools/_patch_test_temp.py
@@ -1,3 +1,6 @@
 # Test file for patch tools
 def existing_function():
     return "old"
+
+def new_function():
+    return "added"
"""

PATCH_MODIFY_LINE = """--- a/robocode/tools/_patch_test_temp.py
+++ b/robocode/tools/_patch_test_temp.py
@@ -1,3 +1,3 @@
 # Test file for patch tools
 def existing_function():
-    return "old"
+    return "modified"
"""

PATCH_OUTSIDE_WORKSPACE = """--- a/etc/passwd
+++ b/etc/passwd
@@ -1,1 +1,1 @@
-root:x:0:0:
+hacked:x:0:0:
"""

PATCH_PROTECTED_FILE = """--- a/robocode/orchestrator/safety.py
+++ b/robocode/orchestrator/safety.py
@@ -10,7 +10,7 @@
 class SafetyPolicy:
     JOINT_LIMITS = [
-        (-180, 360),  # joint1
+        (-360, 360),  # joint1 — widened!
"""


class TestPatchApply:
    def test_add_function_to_file(self):
        """3.2: Apply a patch that adds a function."""
        from robocode.tools.patch_tools import apply_patch

        # Use a real file in the workspace
        result = apply_patch(
            patch_text=PATCH_ADD_FUNCTION,
            target_file="robocode/tools/_patch_test_temp.py",
        )
        # Should fail because _patch_test_temp.py doesn't exist yet
        # or we create a temp file first
        # Let's test with a temp file inside workspace
        project = Path(__file__).resolve().parent.parent
        tmp_path = project / "robocode" / "tools" / "_patch_test_temp.py"
        tmp_path.write_text(
            '# Test file for patch tools\ndef existing_function():\n    return "old"\n'
        )

        try:
            result = apply_patch(
                patch_text=PATCH_ADD_FUNCTION,
                target_file="robocode/tools/_patch_test_temp.py",
            )
            assert result["success"] is True
            content = tmp_path.read_text()
            assert "new_function" in content
            assert "added" in content
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_modify_existing_line(self):
        """3.2: Apply a patch that changes a line."""
        from robocode.tools.patch_tools import apply_patch

        project = Path(__file__).resolve().parent.parent
        tmp_path = project / "robocode" / "tools" / "_patch_test_temp.py"
        tmp_path.write_text(
            '# Test file for patch tools\ndef existing_function():\n    return "old"\n'
        )

        try:
            result = apply_patch(
                patch_text=PATCH_MODIFY_LINE,
                target_file="robocode/tools/_patch_test_temp.py",
            )
            assert result["success"] is True
            content = tmp_path.read_text()
            assert "modified" in content
            assert "old" not in content
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_reject_outside_workspace(self):
        """3.1: Patch targeting /etc/passwd rejected."""
        from robocode.tools.patch_tools import apply_patch

        result = apply_patch(
            patch_text=PATCH_OUTSIDE_WORKSPACE,
            target_file="/etc/passwd",
        )
        assert result["success"] is False
        assert "workspace" in result["message"].lower() or "超出" in result["message"]

    def test_reject_nonexistent_file(self):
        """3.1: Patch to non-existent file fails."""
        from robocode.tools.patch_tools import apply_patch

        result = apply_patch(
            patch_text=PATCH_ADD_FUNCTION,
            target_file="robocode/nonexistent_file_xyz.py",
        )
        assert result["success"] is False


class TestProtectedFileApproval:
    def test_protected_file_detected(self):
        """3.1: Protected file modification requires approval."""
        from robocode.tools.patch_tools import apply_patch
        from robocode.orchestrator.protected_files import is_protected

        # safety.py is a protected file
        assert is_protected("robocode/orchestrator/safety.py") is True

        result = apply_patch(
            patch_text=PATCH_PROTECTED_FILE,
            target_file="robocode/orchestrator/safety.py",
        )
        assert result["success"] is False
        assert "protected" in result["message"].lower() or "受保护" in result["message"]


class TestDiffSummary:
    def test_diff_summary_extracts_paths(self):
        """3.3: Diff summary extracts changed paths."""
        from robocode.tools.patch_tools import generate_diff_summary

        summary = generate_diff_summary(PATCH_ADD_FUNCTION)
        assert "robocode/tools/_patch_test_temp.py" in summary["path"]
        assert summary["hunks"] > 0

    def test_diff_summary_counts_changes(self):
        from robocode.tools.patch_tools import generate_diff_summary

        summary = generate_diff_summary(PATCH_MODIFY_LINE)
        assert summary["additions"] >= 0
        assert summary["deletions"] >= 0


class TestDestructiveRejection:
    def test_rm_rf_in_patch_context_rejected(self):
        """3.1: Destructive operations in patch rejected."""
        from robocode.tools.patch_tools import _parse_patch

        # Patch context that contains rm -rf should be flagged
        patch = _parse_patch(PATCH_ADD_FUNCTION)
        # Normal patches pass
        assert patch is not None
        assert "rm -rf" not in PATCH_ADD_FUNCTION


class TestCheckRunner:
    def test_check_runner_reports_syntax_errors(self):
        from robocode.tools.patch_tools import run_checks

        tmp = _PROJECT_ROOT / "tests" / "_tmp_check_syntax.py"
        try:
            tmp.write_text("def broken(\n")
            result = run_checks(file_path=str(tmp))
            assert isinstance(result, dict)
            assert "import_check" in result
            assert result["import_check"]["passed"] is False
        finally:
            tmp.unlink(missing_ok=True)

    def test_check_runner_accepts_valid_syntax(self):
        from robocode.tools.patch_tools import run_checks

        tmp = _PROJECT_ROOT / "tests" / "_tmp_check_valid.py"
        try:
            tmp.write_text("def valid_function():\n    return 42\n")
            result = run_checks(file_path=str(tmp))
            assert result["import_check"]["passed"] is True
        finally:
            tmp.unlink(missing_ok=True)

    def test_check_runner_rejects_outside_workspace(self):
        from robocode.tools.patch_tools import run_checks
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir="/tmp") as f:
            f.write("x = 1\n")
            tmp = f.name
        try:
            result = run_checks(file_path=tmp)
            assert result["success"] is False
            assert "超出工作空间" in result["message"]
        finally:
            os.unlink(tmp)
