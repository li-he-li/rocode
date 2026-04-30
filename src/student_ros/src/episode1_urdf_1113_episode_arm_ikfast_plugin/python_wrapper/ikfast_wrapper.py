"""
Python wrapper for IKFast solver using ctypes
Provides easy-to-use Python interface for forward and inverse kinematics
"""

import ctypes
import numpy as np
import os
from typing import List, Tuple, Optional


class IKFastSolver:
    """Python wrapper for IKFast kinematics solver"""

    def __init__(self, library_path: Optional[str] = None):
        """
        Initialize the IKFast solver

        Args:
            library_path: Path to the ikfast_wrapper shared library.
                         If None, searches in common locations.
        """
        if library_path is None:
            # Try to find the library in common locations
            search_paths = [
                './libikfast_wrapper.so',
                '../lib/libikfast_wrapper.so',
                './build/libikfast_wrapper.so',
                '/usr/local/lib/libikfast_wrapper.so',
            ]

            for path in search_paths:
                if os.path.exists(path):
                    library_path = path
                    break

            if library_path is None:
                raise FileNotFoundError(
                    "Could not find libikfast_wrapper.so. "
                    "Please specify library_path explicitly."
                )

        # Load the shared library
        self.lib = ctypes.CDLL(library_path)

        # Define function signatures

        # int ikfast_get_num_joints()
        self.lib.ikfast_get_num_joints.argtypes = []
        self.lib.ikfast_get_num_joints.restype = ctypes.c_int

        # void ikfast_compute_fk(const double* joints, double* eetrans, double* eerot)
        self.lib.ikfast_compute_fk.argtypes = [
            np.ctypeslib.ndpointer(dtype=np.float64, ndim=1, flags='C_CONTIGUOUS'),
            np.ctypeslib.ndpointer(dtype=np.float64, ndim=1, flags='C_CONTIGUOUS'),
            np.ctypeslib.ndpointer(dtype=np.float64, ndim=1, flags='C_CONTIGUOUS')
        ]
        self.lib.ikfast_compute_fk.restype = None

        # int ikfast_compute_ik(const double* eetrans, const double* eerot,
        #                       double* solutions_out, int* num_solutions)
        self.lib.ikfast_compute_ik.argtypes = [
            np.ctypeslib.ndpointer(dtype=np.float64, ndim=1, flags='C_CONTIGUOUS'),
            np.ctypeslib.ndpointer(dtype=np.float64, ndim=1, flags='C_CONTIGUOUS'),
            np.ctypeslib.ndpointer(dtype=np.float64, ndim=1, flags='C_CONTIGUOUS'),
            ctypes.POINTER(ctypes.c_int)
        ]
        self.lib.ikfast_compute_ik.restype = ctypes.c_int

        # void ikfast_rot_to_quat(const double* rot, double* quat)
        self.lib.ikfast_rot_to_quat.argtypes = [
            np.ctypeslib.ndpointer(dtype=np.float64, ndim=1, flags='C_CONTIGUOUS'),
            np.ctypeslib.ndpointer(dtype=np.float64, ndim=1, flags='C_CONTIGUOUS')
        ]
        self.lib.ikfast_rot_to_quat.restype = None

        # void ikfast_quat_to_rot(const double* quat, double* rot)
        self.lib.ikfast_quat_to_rot.argtypes = [
            np.ctypeslib.ndpointer(dtype=np.float64, ndim=1, flags='C_CONTIGUOUS'),
            np.ctypeslib.ndpointer(dtype=np.float64, ndim=1, flags='C_CONTIGUOUS')
        ]
        self.lib.ikfast_quat_to_rot.restype = None

        self.num_joints = self.lib.ikfast_get_num_joints()

    def compute_fk(self, joint_angles: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute forward kinematics

        Args:
            joint_angles: Array of joint angles in radians (shape: [6])

        Returns:
            position: End-effector position [x, y, z]
            rotation: End-effector rotation matrix (3x3)
        """
        if len(joint_angles) != self.num_joints:
            raise ValueError(f"Expected {self.num_joints} joint angles, got {len(joint_angles)}")

        joints = np.array(joint_angles, dtype=np.float64)
        eetrans = np.zeros(3, dtype=np.float64)
        eerot = np.zeros(9, dtype=np.float64)

        self.lib.ikfast_compute_fk(joints, eetrans, eerot)

        rotation_matrix = eerot.reshape(3, 3)

        return eetrans, rotation_matrix

    def compute_ik(self, position: np.ndarray, rotation: np.ndarray) -> List[np.ndarray]:
        """
        Compute inverse kinematics

        Args:
            position: End-effector position [x, y, z]
            rotation: End-effector rotation matrix (3x3) or quaternion [w, x, y, z]

        Returns:
            List of joint angle solutions (each solution is an array of 6 angles in radians)
        """
        if len(position) != 3:
            raise ValueError("Position must be [x, y, z]")

        eetrans = np.array(position, dtype=np.float64)

        # Handle both rotation matrix and quaternion input
        if rotation.shape == (3, 3):
            eerot = np.array(rotation, dtype=np.float64).flatten()
        elif rotation.shape == (4,):
            # Convert quaternion to rotation matrix
            eerot = np.zeros(9, dtype=np.float64)
            quat = np.array(rotation, dtype=np.float64)
            self.lib.ikfast_quat_to_rot(quat, eerot)
        else:
            raise ValueError("Rotation must be 3x3 matrix or quaternion [w, x, y, z]")

        # Allocate space for up to 8 solutions (common max for 6-DOF arms)
        max_solutions = 8
        solutions_out = np.zeros(max_solutions * self.num_joints, dtype=np.float64)
        num_solutions = ctypes.c_int(0)

        success = self.lib.ikfast_compute_ik(eetrans, eerot, solutions_out, ctypes.byref(num_solutions))

        if not success or num_solutions.value == 0:
            return []

        # Extract solutions
        solutions = []
        for i in range(num_solutions.value):
            sol = solutions_out[i * self.num_joints:(i + 1) * self.num_joints].copy()
            solutions.append(sol)

        return solutions

    def rot_to_quat(self, rotation_matrix: np.ndarray) -> np.ndarray:
        """
        Convert rotation matrix to quaternion

        Args:
            rotation_matrix: 3x3 rotation matrix

        Returns:
            Quaternion [w, x, y, z]
        """
        rot = np.array(rotation_matrix, dtype=np.float64).flatten()
        quat = np.zeros(4, dtype=np.float64)
        self.lib.ikfast_rot_to_quat(rot, quat)
        return quat

    def quat_to_rot(self, quaternion: np.ndarray) -> np.ndarray:
        """
        Convert quaternion to rotation matrix

        Args:
            quaternion: Quaternion [w, x, y, z]

        Returns:
            3x3 rotation matrix
        """
        quat = np.array(quaternion, dtype=np.float64)
        rot = np.zeros(9, dtype=np.float64)
        self.lib.ikfast_quat_to_rot(quat, rot)
        return rot.reshape(3, 3)

    def rot_to_euler_xyz(self, rotation_matrix: np.ndarray) -> np.ndarray:
        """
        Convert rotation matrix to Euler angles (XYZ order)

        Args:
            rotation_matrix: 3x3 rotation matrix

        Returns:
            Euler angles [roll, pitch, yaw] in radians (XYZ intrinsic rotations)
        """
        R = np.array(rotation_matrix)

        # XYZ Euler angles (intrinsic rotations)
        # R = Rz(yaw) * Ry(pitch) * Rx(roll)
        sy = np.sqrt(R[0, 0]**2 + R[1, 0]**2)

        singular = sy < 1e-6

        if not singular:
            roll = np.arctan2(R[2, 1], R[2, 2])
            pitch = np.arctan2(-R[2, 0], sy)
            yaw = np.arctan2(R[1, 0], R[0, 0])
        else:
            roll = np.arctan2(-R[1, 2], R[1, 1])
            pitch = np.arctan2(-R[2, 0], sy)
            yaw = 0

        return np.array([roll, pitch, yaw])

    def rot_to_euler_zyx(self, rotation_matrix: np.ndarray) -> np.ndarray:
        """
        Convert rotation matrix to Euler angles (ZYX order / Roll-Pitch-Yaw)

        Args:
            rotation_matrix: 3x3 rotation matrix

        Returns:
            Euler angles [roll, pitch, yaw] in radians (ZYX intrinsic rotations)
            This is the common Roll-Pitch-Yaw representation
        """
        R = np.array(rotation_matrix)

        # ZYX Euler angles (Roll-Pitch-Yaw)
        # R = Rz(yaw) * Ry(pitch) * Rx(roll)
        sy = np.sqrt(R[0, 0]**2 + R[1, 0]**2)

        singular = sy < 1e-6

        if not singular:
            roll = np.arctan2(R[2, 1], R[2, 2])
            pitch = np.arctan2(-R[2, 0], sy)
            yaw = np.arctan2(R[1, 0], R[0, 0])
        else:
            roll = np.arctan2(-R[1, 2], R[1, 1])
            pitch = np.arctan2(-R[2, 0], sy)
            yaw = 0

        return np.array([roll, pitch, yaw])

    def episode_ikfast_fk(self, degrees_list: List[float], euler_order: str = 'xyz') -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute forward kinematics with joint offsets and return Euler angles

        Args:
            degrees_list: List of 6 joint angles in degrees (as used in Episode robot)
            euler_order: 'xyz' or 'zyx' for Euler angle output order

        Returns:
            position: End-effector position [x, y, z] in meters
            euler_angles: Euler angles [roll, pitch, yaw] in degrees
        """
        # Joint offsets (relative to URDF 0 degree position)
        joint_offsets = np.array([180, 90, 83, 30, 110, 30])

        # Subtract offsets to get IKFast joint angles
        ikfast_degrees = np.array(degrees_list) - joint_offsets

        # Convert to radians
        joint_angles_rad = np.deg2rad(ikfast_degrees)

        # Compute FK
        position, rotation = self.compute_fk(joint_angles_rad)

        # Convert rotation to Euler angles
        euler_order = euler_order.lower()
        if euler_order == 'xyz':
            euler_rad = self.rot_to_euler_xyz(rotation)
        elif euler_order == 'zyx':
            euler_rad = self.rot_to_euler_zyx(rotation)
        else:
            raise ValueError(f"Invalid euler_order: {euler_order}. Must be 'xyz' or 'zyx'")

        # Convert to degrees
        euler_deg = np.rad2deg(euler_rad)

        return position, euler_deg

    def episode_ikfast_ik(self, xyz: List[float], euler_angles: List[float], euler_order: str = 'xyz') -> List[List[float]]:
        """
        Compute inverse kinematics with joint offsets from Euler angles

        Args:
            xyz: End-effector position [x, y, z] in meters
            euler_angles: Euler angles [roll, pitch, yaw] in degrees
            euler_order: 'xyz' or 'zyx' for Euler angle input order

        Returns:
            List of solutions, each is a list of 6 joint angles in degrees (as used in Episode robot)
        """
        # Joint offsets (relative to URDF 0 degree position)
        joint_offsets = np.array([180, 90, 83, 30, 110, 30])
        # 关节角度限制列表 [最小值, 最大值]
        degree_limit_list = [
            [0, 340],
            [0, 180],
            [0, 163],
            [0, 335],
            [0, 220],
            [0, 335],
        ]

        position = np.array(xyz)
        euler_rad = np.deg2rad(euler_angles)

        # Convert Euler angles to rotation matrix
        euler_order = euler_order.lower()
        if euler_order == 'xyz':
            # XYZ intrinsic rotations: R = Rz(yaw) * Ry(pitch) * Rx(roll)
            roll, pitch, yaw = euler_rad

            # Rotation matrices
            Rx = np.array([
                [1, 0, 0],
                [0, np.cos(roll), -np.sin(roll)],
                [0, np.sin(roll), np.cos(roll)]
            ])

            Ry = np.array([
                [np.cos(pitch), 0, np.sin(pitch)],
                [0, 1, 0],
                [-np.sin(pitch), 0, np.cos(pitch)]
            ])

            Rz = np.array([
                [np.cos(yaw), -np.sin(yaw), 0],
                [np.sin(yaw), np.cos(yaw), 0],
                [0, 0, 1]
            ])

            rotation = Rz @ Ry @ Rx

        elif euler_order == 'zyx':
            # ZYX intrinsic rotations (Roll-Pitch-Yaw): R = Rz(yaw) * Ry(pitch) * Rx(roll)
            roll, pitch, yaw = euler_rad

            # Same as XYZ for this representation
            Rx = np.array([
                [1, 0, 0],
                [0, np.cos(roll), -np.sin(roll)],
                [0, np.sin(roll), np.cos(roll)]
            ])

            Ry = np.array([
                [np.cos(pitch), 0, np.sin(pitch)],
                [0, 1, 0],
                [-np.sin(pitch), 0, np.cos(pitch)]
            ])

            Rz = np.array([
                [np.cos(yaw), -np.sin(yaw), 0],
                [np.sin(yaw), np.cos(yaw), 0],
                [0, 0, 1]
            ])

            rotation = Rz @ Ry @ Rx
        else:
            raise ValueError(f"Invalid euler_order: {euler_order}. Must be 'xyz' or 'zyx'")

        # Compute IK
        solutions = self.compute_ik(position, rotation)

        # Convert solutions to Episode robot degrees (add offsets) and filter by limits
        episode_solutions = []
        for sol in solutions:
            ikfast_degrees = np.rad2deg(sol)
            episode_degrees = ikfast_degrees + joint_offsets

            # Normalize angles to [0, 360) range by adding/subtracting 360°
            normalized_degrees = np.copy(episode_degrees)
            for i in range(len(normalized_degrees)):
                while normalized_degrees[i] < 0:
                    normalized_degrees[i] += 360.0
                while normalized_degrees[i] >= 360:
                    normalized_degrees[i] -= 360.0

            # Check if all joints are within limits
            within_limits = True
            for i, angle in enumerate(normalized_degrees):
                min_limit, max_limit = degree_limit_list[i]
                if angle < min_limit or angle > max_limit:
                    within_limits = False
                    break

            # Only add solution if all joints are within limits
            if within_limits:
                episode_solutions.append(normalized_degrees.tolist())

        return episode_solutions


def main():
    """Example usage"""
    solver = IKFastSolver()

    # Set print options for cleaner output
    np.set_printoptions(precision=2, suppress=True)

    episode_joints = [180, 90, 83, 30, 110, 30]  # Zero position
    print(f'Input Episode joints (deg): {episode_joints}')

    # Test XYZ order
    pos_xyz, euler_xyz = solver.episode_ikfast_fk(episode_joints, 'xyz')
    print(f'\nFK with XYZ Euler:')
    print(f'  Position [x,y,z]: [{pos_xyz[0]:.4f}, {pos_xyz[1]:.4f}, {pos_xyz[2]:.4f}]')
    print(f'  Euler XYZ [r,p,y] (deg): [{euler_xyz[0]:.2f}, {euler_xyz[1]:.2f}, {euler_xyz[2]:.2f}]')

    result = solver.episode_ikfast_ik([ 278.198/1000, 0.0/1000, 219.594/1000], [115.937,6.354,15.078], euler_order='xyz')
    # transl(278.198,0,219.594)*rotz(15.078)*roty(6.354)*rotx(115.937)
    print("IK Solutions:")
    for i, sol in enumerate(result):
        print(f" Solution {i+1}: {sol}")
    # [190.24, 105.59, 118.5, 315.73, 178.9, 70.47]
    # [190.07, 105.27, 119.2, 314.97, 178.32, 71.36]

if __name__ == "__main__":
    main()
