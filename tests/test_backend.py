"""Backend adapter tests — interface contract, SDK adapter, fake backend."""

from robocode.backends.base import RobotBackend
from robocode.backends.sdk_backend import SdkBackend, EpisodeVariant
from robocode.utils.models import RobotStatus


class TestRobotBackendInterface:
    def test_abstract_methods(self):
        assert "get_status" in RobotBackend.__abstractmethods__
        assert "emergency_stop" in RobotBackend.__abstractmethods__
        assert "move_xyz_rotation" in RobotBackend.__abstractmethods__
        assert "angle_mode" in RobotBackend.__abstractmethods__


class TestEpisodeVariant:
    def test_variants_exist(self):
        assert EpisodeVariant.SDK == "sdk"
        assert EpisodeVariant.D3 == "3d"
        assert EpisodeVariant.D6 == "6d"


class TestSdkBackendWithFake:
    def make_backend(self):
        from robocode.backends.sdk_backend import FakeEpisodeAPP

        return SdkBackend(client=FakeEpisodeAPP(), variant=EpisodeVariant.SDK)

    def test_get_status(self):
        backend = self.make_backend()
        status = backend.get_status()
        assert isinstance(status, RobotStatus)
        assert status.connected is True
        assert "sdk" in status.backend
        assert len(status.motor_angles) == 6

    def test_health_check(self):
        backend = self.make_backend()
        health = backend.health_check()
        assert health.healthy is True
        assert health.backend == "sdk"

    def test_emergency_stop(self):
        backend = self.make_backend()
        backend.emergency_stop(True)
        status = backend.get_status()
        assert status.estop_active is True
        backend.emergency_stop(False)
        assert backend.get_status().estop_active is False

    def test_move_xyz_rotation(self):
        backend = self.make_backend()
        result = backend.move_xyz_rotation([300, 0, 200], [180, 0, 90], "zyx", 0.5)
        assert result > 0

    def test_angle_mode(self):
        backend = self.make_backend()
        result = backend.angle_mode([180, 90, 83, 30, 110, 30], 1.0)
        assert result > 0

    def test_gripper_on_off(self):
        backend = self.make_backend()
        backend.gripper_on()
        status = backend.get_status()
        # after gripper_on, robot stays connected
        assert status.connected is True
        backend.gripper_off()

    def test_get_status_client_raises_returns_disconnected(self):
        class RaisingClient:
            def get_motor_angles(self):
                raise ConnectionError("no connection")

            def get_pose(self):
                raise ConnectionError("no connection")

        backend = SdkBackend(client=RaisingClient())
        status = backend.get_status()
        assert status.connected is False

    def test_health_check_client_raises_returns_unhealthy(self):
        class RaisingClient:
            def get_motor_angles(self):
                raise ConnectionError("no connection")

        backend = SdkBackend(client=RaisingClient())
        health = backend.health_check()
        assert health.healthy is False

    def test_servo_gripper(self):
        backend = self.make_backend()
        result = backend.servo_gripper(45)
        assert result > 0

    def test_shutdown(self):
        backend = self.make_backend()
        backend.shutdown()
        assert backend.get_status().connected is False


class TestActiveBackend:
    def test_active_backend_selection(self):
        from robocode.backends.sdk_backend import FakeEpisodeAPP

        backend = SdkBackend(client=FakeEpisodeAPP(), variant=EpisodeVariant.SDK)
        assert backend.active_backend == "sdk"

    def test_variant_3d(self):
        from robocode.backends.sdk_backend import FakeEpisodeAPP

        backend = SdkBackend(client=FakeEpisodeAPP(), variant=EpisodeVariant.D3)
        assert backend.active_backend == "sdk"
        assert backend.variant == "3d"

    def test_variant_6d(self):
        from robocode.backends.sdk_backend import FakeEpisodeAPP

        backend = SdkBackend(client=FakeEpisodeAPP(), variant=EpisodeVariant.D6)
        assert backend.active_backend == "sdk"
        assert backend.variant == "6d"


class TestFakeBackendFixture:
    def test_fake_backend(self):
        from tests.fixtures import FakeRobotBackend

        fb = FakeRobotBackend()
        status = fb.get_status()
        assert status.connected is True
        assert status.estop_active is False

        fb.emergency_stop(True)
        assert fb.get_status().estop_active is True

        t = fb.move_xyz_rotation([300, 0, 200], [180, 0, 90])
        assert t > 0

        t = fb.angle_mode([180, 90, 83, 30, 110, 30])
        assert t > 0
