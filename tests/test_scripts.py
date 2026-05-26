"""Script inventory and detection tool tests."""

from pathlib import Path
from robocode.tools.script_tools import SCRIPT_INVENTORY


class TestScriptInventory:
    def test_all_scripts_have_required_fields(self):
        for script in SCRIPT_INVENTORY:
            assert "name" in script
            assert "path" in script
            assert "category" in script
            assert "requires_human" in script
            assert "output_files" in script

    def test_scripts_have_valid_path_strings(self):
        for script in SCRIPT_INVENTORY:
            path = script["path"]
            assert isinstance(path, str)
            assert Path(path).suffix == ".py"

    def test_calibration_scripts_found(self):
        calib_scripts = [s for s in SCRIPT_INVENTORY if s["category"] == "calibration"]
        assert len(calib_scripts) > 0

    def test_detection_scripts_found(self):
        det_scripts = [s for s in SCRIPT_INVENTORY if s["category"] == "detection"]
        assert len(det_scripts) > 0

    def test_application_scripts_found(self):
        app_scripts = [s for s in SCRIPT_INVENTORY if s["category"] == "application"]
        assert len(app_scripts) > 0


class TestRunScriptTool:
    def setup_method(self):
        from robocode.tools.script_tools import make_script_tools

        self.tools = make_script_tools()

    def test_known_script_with_human_required(self):
        result = self.tools["run_script"](script_name="perspective_calibration")
        assert result["success"] is False
        assert "GUI" in result["message"] or "手动" in result["message"]
        assert result["metrics"]["requires_human"] is True

    def test_unknown_script_returns_error(self):
        result = self.tools["run_script"](script_name="nonexistent_script_xyz")
        assert result["success"] is False
        assert "未知" in result["message"]
