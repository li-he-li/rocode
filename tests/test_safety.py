"""Safety policy tests — workspace, joints, speed, payload, gripper, L2 marking."""

from robocode.orchestrator.safety import SafetyPolicy


class TestJointLimits:
    def test_joint_within_limits(self):
        sp = SafetyPolicy()
        result = sp.check_joint_limits([180, 90, 83, 30, 110, 30])
        assert result.passed is True

    def test_joint_exceeds_upper_limit(self):
        sp = SafetyPolicy()
        result = sp.check_joint_limits([999, 0, 0, 0, 0, 0])
        assert result.passed is False

    def test_joint_wrong_count(self):
        sp = SafetyPolicy()
        result = sp.check_joint_limits([0, 0])
        assert result.passed is False
        assert "6" in result.reason

    def test_joint_at_lower_bound(self):
        sp = SafetyPolicy()
        result = sp.check_joint_limits([-180, -90, -180, -180, -180, -180])
        assert result.passed is True

    def test_joint_at_upper_bound(self):
        sp = SafetyPolicy()
        result = sp.check_joint_limits([360, 270, 180, 180, 180, 180])
        assert result.passed is True

    def test_joint_just_below_lower_bound(self):
        sp = SafetyPolicy()
        result = sp.check_joint_limits([-180.1, 0, 0, 0, 0, 0])
        assert result.passed is False


class TestPayloadCheck:
    def test_payload_ok(self):
        sp = SafetyPolicy()
        result = sp.check_payload(300)
        assert result.passed is True

    def test_payload_exceeds(self):
        sp = SafetyPolicy()
        result = sp.check_payload(600)  # > 500g
        assert result.passed is False


class TestGripperCompatibility:
    def test_suction_gripper_valid(self):
        sp = SafetyPolicy()
        assert sp.is_gripper_supported("suction") is True

    def test_servo_gripper_valid(self):
        sp = SafetyPolicy()
        assert sp.is_gripper_supported("servo") is True

    def test_unknown_gripper_rejected(self):
        sp = SafetyPolicy()
        assert sp.is_gripper_supported("magnetic") is False


class TestL2Actions:
    def test_l2_requires_approval(self):
        sp = SafetyPolicy()
        assert sp.requires_approval("L2") is True

    def test_l0_no_approval(self):
        sp = SafetyPolicy()
        assert sp.requires_approval("L0") is False

    def test_l1_no_approval(self):
        sp = SafetyPolicy()
        assert sp.requires_approval("L1") is False
