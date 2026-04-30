#!/usr/bin/env python3
"""
Modified demo launch file for Episode1 with perception (obstacle detection) enabled.

This launch file extends the standard MoveIt demo.launch.py to include:
- 3D sensor configuration (sensors_3d.yaml) for obstacle detection
- Octomap-based collision avoidance
- RealSense D435 camera integration

The perception pipeline uses an octomap to represent obstacles detected by
the depth camera, which MoveIt uses for collision-free motion planning.
"""

import os
from moveit_configs_utils import MoveItConfigsBuilder
from moveit_configs_utils.launches import generate_demo_launch
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Build MoveIt configuration with perception enabled
    moveit_config = (
        MoveItConfigsBuilder("episode1_urdf_1113", package_name="episode1_urdf_1113_moveit")
        .sensors_3d(
            file_path=os.path.join(
                get_package_share_directory("episode1_urdf_1113_moveit"),
                "config",
                "sensors_3d.yaml"
            )
        )
        .to_moveit_configs()
    )

    return generate_demo_launch(moveit_config)
