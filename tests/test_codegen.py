"""SDK code generation tests — escape hatch: sandbox, execute, forbidden patterns."""

import pytest
from robocode.tools.codegen_tools import (
    make_codegen_tools,
    CodeSandbox,
)


class TestCodeSandbox:
    def test_valid_code_runs(self):
        result = CodeSandbox.run("print('hello')")
        assert result["success"] is True
        assert "hello" in result["stdout"]

    def test_invalid_code_returns_error(self):
        result = CodeSandbox.run("raise ValueError('bad')")
        assert result["success"] is False
        assert "bad" in result["stderr"]

    def test_timeout_kills_process(self):
        result = CodeSandbox.run("import time; time.sleep(10)", timeout_s=1)
        assert result["success"] is False
        assert result.get("timeout", False) is True

    def test_captures_stdout_and_stderr(self):
        code = "import sys; print('out'); print('err', file=sys.stderr)"
        result = CodeSandbox.run(code)
        assert "out" in result["stdout"]
        assert "err" in result["stderr"]

    def test_legitimate_open_read_not_blocked(self):
        result = CodeSandbox.run("open('/dev/null', 'r')")
        assert result["success"] is True

    def test_kwargs_match_real_api(self):
        """LLM uses keyword args per API docs — sandbox must accept them."""
        code = "r = robot.move_xyz_rotation(position=[300,0,200], orientation=[180,0,90], speed_ratio=0.5); print(r)"
        result = CodeSandbox.run(code)
        assert result["success"] is True

    @pytest.mark.parametrize(
        "forbidden_code",
        [
            "import socket; s = socket.socket()",
            "from socket import socket; socket()",
            "import os; os.remove('/tmp/x')",
            "import os; os.unlink('/tmp/x')",
            "import os; os.rmdir('/tmp/x')",
            "import os; os.system('ls')",
            "import os; os.popen('ls')",
            "import shutil; shutil.rmtree('/tmp/x')",
            "import subprocess; subprocess.run('ls')",
            "__import__('os')",
            "eval('1+1')",
            "exec('x=1')",
            "import ctypes; ctypes.CDLL('libc.so')",
        ],
    )
    def test_forbidden_pattern_blocked(self, forbidden_code):
        violations = CodeSandbox.scan_forbidden(forbidden_code)
        assert len(violations) >= 1, f"未拦截: {forbidden_code}"


class TestCodeGenTools:
    def setup_method(self):
        self.tools = make_codegen_tools()

    def test_generate_and_run_valid_code(self):
        code = """
result = robot.move_xyz_rotation(
    position=[300.0, 0.0, 200.0],
    orientation=[180.0, 0.0, 90.0],
    speed_ratio=0.5,
)
print(f"OK: moved in {result}s")
"""
        result = self.tools["generate_and_run_sdk_code"](code=code, summary="test move")
        assert result["success"] is True
        assert "OK" in result["metrics"]["stdout"]

    def test_generate_and_run_invalid_code(self):
        result = self.tools["generate_and_run_sdk_code"](
            code="this_is_not_valid_python !!!",
            summary="bad",
        )
        assert result["success"] is False

    def test_block_raw_socket_access(self):
        code = "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)"
        result = self.tools["generate_and_run_sdk_code"](code=code, summary="raw socket")
        assert result["success"] is False
