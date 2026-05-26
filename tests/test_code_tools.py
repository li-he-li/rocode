"""2.1 + 2.5: Workspace-limited code inspection tools — safety tests."""

from pathlib import Path


class TestReadFile:
    def test_read_allowed_file(self):
        """2.2: Workspace-limited file reading within allowed roots."""
        from robocode.tools.code_tools import read_file

        result = read_file(path="robocode/__init__.py")
        assert result["success"] is True
        assert "robocode" in result["message"]

    def test_reject_path_outside_workspace(self):
        """2.1: Workspace escape rejection."""
        from robocode.tools.code_tools import read_file

        result = read_file(path="/etc/passwd")
        assert result["success"] is False
        assert "workspace" in result["message"].lower() or "超出" in result["message"]

    def test_reject_absolute_path_outside(self):
        """2.1: Absolute path escape to /tmp."""
        from robocode.tools.code_tools import read_file

        result = read_file(path="/tmp/evil.py")
        assert result["success"] is False

    def test_reject_path_traversal(self):
        """2.1: Path traversal ../ escape."""
        from robocode.tools.code_tools import read_file

        result = read_file(path="robocode/../../../etc/passwd")
        assert result["success"] is False

    def test_reject_nonexistent_file(self):
        from robocode.tools.code_tools import read_file

        result = read_file(path="robocode/nonexistent.xyz")
        assert result["success"] is False

    def test_reject_directory(self):
        from robocode.tools.code_tools import read_file

        result = read_file(path="robocode")
        assert result["success"] is False


class TestSearchCode:
    def test_search_finds_matches(self):
        """2.3: Workspace-limited code search."""
        from robocode.tools.code_tools import search_code

        result = search_code(pattern="class AgentLoop", path="robocode/agent/")
        assert result["success"] is True
        assert "core.py" in str(result["metrics"].get("matches", ""))

    def test_search_reject_outside_workspace(self):
        """2.1: Search outside workspace rejected."""
        from robocode.tools.code_tools import search_code

        result = search_code(pattern=".*", path="/etc/")
        assert result["success"] is False

    def test_search_nonexistent_path(self):
        from robocode.tools.code_tools import search_code

        result = search_code(pattern=".*", path="robocode/nonexistent_dir/")
        assert result["success"] is False


class TestBinaryRejection:
    def test_binary_rejected_by_extension(self):
        """2.1: Binary files (.bin, .png) rejected."""
        from robocode.tools.code_tools import BINARY_EXTENSIONS

        # Create a temp file with binary extension inside workspace
        import tempfile

        tmp = Path(tempfile.gettempdir()) / "test_reject.bin"
        tmp.write_bytes(b"\x00\x01\x02")
        # This is outside workspace so it'll be rejected by workspace check
        # Test the binary check function directly
        for ext in [".bin", ".png", ".jpg", ".so", ".o", ".pyc", ".stl"]:
            assert Path(f"robocode/test{ext}").suffix in BINARY_EXTENSIONS

    def test_python_file_not_rejected(self):
        from robocode.tools.code_tools import BINARY_EXTENSIONS

        assert Path("robocode/test.py").suffix not in BINARY_EXTENSIONS


class TestDemosSummarizedNotExecuted:
    def test_search_does_not_execute(self):
        """2.5: Code search summarizes, never executes."""
        from robocode.tools.code_tools import search_code

        # Searching for a dangerous pattern should NOT execute it
        result = search_code(pattern="subprocess", path="robocode/")
        assert result["success"] is True
        # The result should be file paths + line numbers, not execution output
        metrics = result.get("metrics", {})
        output = str(metrics)
        assert "file" in output.lower() or "match" in output.lower()

    def test_read_file_does_not_execute(self):
        """2.5: Reading a demo script does not execute it."""
        from robocode.tools.code_tools import read_file

        # Find any Python script in robocode/
        result = read_file(path="robocode/tools/motion_tools.py")
        assert result["success"] is True
        # Returns file content, not execution result
        assert "def " in result["message"]  # source code, not output
