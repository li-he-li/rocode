#!/usr/bin/env python3
"""
Chess Piece Robot Controller - Integrated YOLO Detection and Robot Control

This script combines:
1. Hand-eye calibration for robot coordinate transformation
2. Camera calibration for chessboard perspective correction
3. YOLO-based chess piece detection
4. Robot control to move to detected pieces

Features:
- Real-time piece detection using YOLO
- Click-to-select pieces for robot movement
- Automatic coordinate transformation: Camera → Chessboard → Robot
- Visual feedback with piece highlighting
- Safety features for robot movement

Usage:
1. Ensure robot controller is running: ros2 launch episode_controller robot_controller.launch.py
2. Run: python3 6.chess_piece_robot_controller.py [camera_calib.yaml] [hand_eye_calib.yaml] [--camera INDEX]

Dependencies:
- camera_calibration.yaml (from camera calibration)
- hand_eye_calibration.yaml (from hand-eye calibration)
- YOLO model weights (best.pt)
- ROS2 robot controller
"""

import sys
import cv2
import numpy as np
import yaml
import time
import threading
from pathlib import Path

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from robot_arm_interfaces.action import MoveXyzRotation
from robot_arm_interfaces.srv import ReadMotorAngles

from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout,
                             QHBoxLayout, QWidget, QGroupBox, QGridLayout,
                             QPushButton, QFrame, QSpinBox, QDoubleSpinBox,
                             QFormLayout, QMessageBox, QTextEdit)
from PyQt5.QtGui import QImage, QPixmap, QFont, QPainter, QPen, QBrush, QColor
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal

# YOLO imports
try:
    from ultralytics import YOLO
    import torch
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("  YOLO not available. Install with: pip install ultralytics torch")


class RobotController(Node):
    """Robot controller interface for ROS2"""

    def __init__(self):
        super().__init__('chess_piece_robot_controller')

        # Action client for position control
        self._move_xyz_rotation_client = ActionClient(self, MoveXyzRotation, 'move_xyz_rotation')

        # Service client for reading motor angles
        self._service_client = self.create_client(ReadMotorAngles, 'read_motor_angles')

        # Current robot position [x, y, z, rx, ry, rz]
        self.current_position = [260.0, 0.0, 200.0, 180.0, 0.0, 90.0]
        self.current_rotation = [180.0, 0.0, 90.0]

        # Movement state tracking
        self._move_completed = True
        self._last_move_success = True

        # Don't move to home automatically during initialization
        self.get_logger().info('Robot controller initialized')

    def wait_for_services(self, timeout=10.0):
        """Wait for robot services to become available"""
        print(f"Waiting for robot services (timeout: {timeout}s)...")

        print("  - Checking MoveXyzRotation action server...")
        if not self._move_xyz_rotation_client.wait_for_server(timeout_sec=timeout):
            self.get_logger().error("MoveXyzRotation action server not available")
            print("     MoveXyzRotation action server not found")
            return False
        print("     MoveXyzRotation action server found")

        print("  - Checking ReadMotorAngles service...")
        if not self._service_client.wait_for_service(timeout_sec=timeout):
            self.get_logger().error("ReadMotorAngles service not available")
            print("     ReadMotorAngles service not found")
            return False
        print("     ReadMotorAngles service found")

        print(" All robot services available")
        return True

    def move_to_home(self):
        """Move robot to home position"""
        self.get_logger().info('Moving to home position...')
        self.move_to(260.0, 0.0, 200.0)

    def move_relative(self, dx: float, dy: float, dz: float):
        """Move robot relative to current position"""
        new_x = self.current_position[0] + dx
        new_y = self.current_position[1] + dy
        new_z = self.current_position[2] + dz

        self.get_logger().info(f"Move relative: dx={dx:.2f}, dy={dy:.2f}, dz={dz:.2f}")
        self.move_to(new_x, new_y, new_z)

    def wait_for_move_complete(self, timeout: float = 30.0):
        """Wait for current move to complete"""
        start_time = time.time()
        while not self._move_completed and (time.time() - start_time) < timeout:
            rclpy.spin_once(self, timeout_sec=0.1)
        return self._move_completed

    def move_to(self, x: float, y: float, z: float, rx: float = 180.0, ry: float = 0.0, rz: float = 90.0, speed_ratio: float = 1.0):
        """Move robot to absolute position"""
        if not self._move_completed:
            self.get_logger().warning("Robot is still moving, please wait...")
            return False

        # Update target position
        self.current_position[0] = x
        self.current_position[1] = y
        self.current_position[2] = z
        self.current_rotation = [rx, ry, rz]

        # Create goal with correct structure
        goal_msg = MoveXyzRotation.Goal()
        goal_msg.position = [x, y, z]
        goal_msg.rotation = [rx, ry, rz]
        goal_msg.ik_mode = "xyz"
        goal_msg.speed_ratio = speed_ratio

        self.get_logger().info(f"Moving to: x={x:.2f}, y={y:.2f}, z={z:.2f}")

        # Wait for action server
        if not self._move_xyz_rotation_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().error('Action server not available!')
            return False

        # Send goal
        self._move_completed = False
        self._last_move_success = False

        send_goal_future = self._move_xyz_rotation_client.send_goal_async(
            goal_msg, feedback_callback=self._move_feedback_callback
        )
        send_goal_future.add_done_callback(self._move_response_callback)

        return True

    def _move_feedback_callback(self, feedback_msg):
        """Movement feedback callback"""
        fb = feedback_msg.feedback
        # Update current angles if needed
        pass

    def _move_response_callback(self, future):
        """Movement response callback"""
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().warning('Move goal rejected')
            self._move_completed = True
            self._last_move_success = False
            return

        # Get result
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._move_result_callback)

    def _move_result_callback(self, future):
        """Movement result callback"""
        result = future.result().result
        self._last_move_success = result.success
        self._move_completed = True

        if result.success:
            self.get_logger().info(f'Move completed successfully')
            # Update actual position from result
            if hasattr(result, 'final_position') and len(result.final_position) >= 3:
                self.current_position[0] = result.final_position[0]
                self.current_position[1] = result.final_position[1]
                self.current_position[2] = result.final_position[2]
        else:
            self.get_logger().error(f'Move failed: {result.message if hasattr(result, "message") else "Unknown error"}')

    def is_moving(self):
        """Check if robot is currently moving"""
        return not self._move_completed

    def get_last_move_success(self):
        """Get success status of last move"""
        return self._last_move_success

    def get_current_position(self):
        """Get current robot position"""
        return self.current_position[:3]  # Return only xyz


class ChessPieceDetector:
    """YOLO-based chess piece detection"""

    def __init__(self, weights_path="train_yolo/best.pt"):
        self.model = None
        self.weights_path = weights_path
        self.device = 'cpu'  # Use CPU for stability

        if YOLO_AVAILABLE:
            weights_file = Path(weights_path)
            if not weights_file.exists():
                # Try relative path from current script location
                script_dir = Path(__file__).parent
                weights_file = script_dir / weights_path

            if weights_file.exists():
                try:
                    self.model = YOLO(str(weights_file))
                    self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
                    print(f" YOLO model loaded: {weights_file}")
                    print(f"  Using device: {self.device}")
                except Exception as e:
                    print(f" Error loading YOLO model: {e}")
                    self.model = None
            else:
                print(f"  YOLO weights not found: {weights_file}")
                print("   Detection will be disabled")
                self.model = None
        else:
            print(" YOLO not available. Install with: pip install ultralytics torch")

    def detect(self, frame):
        """Detect chess pieces in frame and return detection data"""
        pieces = []

        if self.model is None:
            return pieces

        try:
            # Run YOLO inference
            results = self.model(frame, conf=0.5, device=self.device, verbose=False)

            # Process detections
            for r in results:
                boxes = r.boxes
                if boxes is not None:
                    for box in boxes:
                        # Extract bounding box coordinates
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        conf = box.conf[0].cpu().numpy()
                        cls_id = int(box.cls[0].cpu().numpy())

                        # Convert to integers
                        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                        center_x = (x1 + x2) // 2
                        center_y = (y1 + y2) // 2

                        pieces.append({
                            'bbox': (x1, y1, x2, y2),
                            'center': (center_x, center_y),
                            'class_id': cls_id,
                            'confidence': conf,
                            'type': 'black' if cls_id == 0 else 'white'
                        })

        except Exception as e:
            print(f"Detection error: {e}")

        return pieces

    def detect_and_draw_stones(self, frame, transformer=None, board_rows=11, board_cols=13):
        """Detect stones and draw bounding boxes with board coordinates

        Args:
            frame: Perspective-transformed frame (rectified view)
            transformer: CoordinateTransformer instance
            board_rows, board_cols: Board dimensions for grid mapping

        Returns:
            tuple: (annotated_frame, detected_pieces_list)
        """
        pieces = self.detect(frame)
        annotated_frame = frame.copy()

        # Draw detections on frame
        for i, piece in enumerate(pieces):
            x1, y1, x2, y2 = piece['bbox']
            center_x, center_y = piece['center']

            # Choose color based on piece type
            if piece['type'] == 'black':
                color = (0, 0, 255)  # Red for black pieces (BGR format)
                label = f"Black: {piece['confidence']:.2f}"
            else:
                color = (255, 0, 0)  # Blue for white pieces (BGR format)
                label = f"White: {piece['confidence']:.2f}"

            # Convert to robot coordinates if transformer is available
            # Note: center_x, center_y are already perspective-transformed coordinates
            if transformer and transformer.is_calibrated():
                robot_x, robot_y, robot_z = transformer.camera_to_robot(center_x, center_y, 20.0)
                if robot_x is not None:
                    label += f" R({robot_x:.1f},{robot_y:.1f})"

            # Draw bounding box
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)

            # Draw center point
            cv2.circle(annotated_frame, (center_x, center_y), 3, (0, 255, 255), -1)

            # Draw label background
            (text_width, text_height), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1
            )
            cv2.rectangle(
                annotated_frame,
                (x1, y1 - text_height - 10),
                (x1 + text_width, y1),
                color,
                -1
            )

            # Draw label text
            cv2.putText(
                annotated_frame,
                label,
                (x1, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (255, 255, 255),
                1
            )

        return annotated_frame, pieces


class CoordinateTransformer:
    """Handle coordinate transformations between camera, chessboard, and robot"""

    def __init__(self, camera_calib_file, hand_eye_calib_file):
        self.camera_calibrated = False
        self.robot_calibrated = False

        # Camera calibration data
        self.camera_matrix = None
        self.transform_matrix = None
        self.output_width = 640
        self.output_height = 480

        # Hand-eye calibration data
        self.T_matrix = None  # Table to robot transformation
        self.table_points = None  # Calibration points from hand-eye calibration
        self.board_width = 272.0  # mm (default, will be calculated from table_points)
        self.board_height = 240.0  # mm (default, will be calculated from table_points)

        self.load_camera_calibration(camera_calib_file)
        self.load_hand_eye_calibration(hand_eye_calib_file)

    def load_camera_calibration(self, filename):
        """Load camera calibration from YAML"""
        try:
            with open(filename, 'r') as f:
                data = yaml.safe_load(f)

            # Extract pixel corners (where user clicked)
            self.pixel_corners = np.array(data['pixel_corners'], dtype=np.float32)

            # Extract camera resolution
            self.camera_width = data['camera_resolution']['width']
            self.camera_height = data['camera_resolution']['height']

            # Extract output size
            self.output_width = data['output_size']['width']
            self.output_height = data['output_size']['height']

            # Extract board size for display
            self.board_width = data['board_size_mm']['width']
            self.board_height = data['board_size_mm']['height']

            # Calculate transformation matrix using the same logic as calibration tool
            # Output corners: Bottom-Left, Bottom-Right, Top-Right, Top-Left
            output_corners = np.array([
                [0, self.output_height],           # Bottom-Left -> (0, height)
                [self.output_width, self.output_height],   # Bottom-Right -> (width, height)
                [self.output_width, 0],            # Top-Right -> (width, 0)
                [0, 0],                           # Top-Left -> (0, 0)
            ], dtype=np.float32)

            # Generate transformation matrix from clicked points to output corners
            self.transform_matrix = cv2.getPerspectiveTransform(self.pixel_corners, output_corners)
            self.camera_calibrated = True

            print(f" Camera calibration loaded: {filename}")
            print(f"   Board size: {self.board_width}x{self.board_height}mm")
            print(f"   Output size: {self.output_width}x{self.output_height}px")
            print(f"   Camera resolution: {self.camera_width}x{self.camera_height}px")

        except FileNotFoundError:
            print(f" Calibration file '{filename}' not found")
            self.camera_calibrated = False
        except KeyError as e:
            print(f" Missing key in calibration file: {e}")
            self.camera_calibrated = False
        except Exception as e:
            print(f" Failed to load camera calibration: {e}")
            self.camera_calibrated = False

    def load_hand_eye_calibration(self, filename):
        """Load hand-eye calibration from YAML"""
        try:
            with open(filename, 'r') as f:
                data = yaml.safe_load(f)

            # Load T_matrix
            if 'T_matrix' in data and data['T_matrix'] is not None:
                self.T_matrix = np.array(data['T_matrix'], dtype=np.float64)
                self.robot_calibrated = True
                print(f" Hand-eye calibration T_matrix loaded: {filename}")
            else:
                print(f" T_matrix not found in {filename}")
                self.robot_calibrated = False

            # Load table_points and calculate board dimensions
            if 'table_points' in data and data['table_points'] is not None:
                self.table_points = np.array(data['table_points'], dtype=np.float32)

                # Calculate board dimensions from table points
                # X direction: P1 to P2, Y direction: P1 to P3
                if len(self.table_points) >= 3:
                    self.board_width = self.table_points[1][0] - self.table_points[0][0]
                    self.board_height = self.table_points[2][1] - self.table_points[0][1]
                    print(f" Board dimensions calculated from table points:")
                    print(f"   Width: {self.board_width:.1f} mm")
                    print(f"   Height: {self.board_height:.1f} mm")
                else:
                    print(f" Insufficient table_points for board dimension calculation")
            else:
                print(f" table_points not found in {filename}, using default dimensions")

        except Exception as e:
            print(f" Failed to load hand-eye calibration: {e}")
            self.robot_calibrated = False

    def camera_to_chessboard(self, transformed_x, transformed_y):
        """Convert perspective-transformed pixel coordinates to chessboard coordinates (mm)

        IMPORTANT: This assumes input coordinates are already perspective-transformed!
        transformed_x, transformed_y should be from the rectified/cropped view.
        """
        if not self.camera_calibrated:
            return None, None

        # Convert normalized coordinates to board coordinates
        # Note: Y coordinate is flipped because camera origin is top-left, board origin is bottom-left
        board_x = (transformed_x / self.output_width) * self.board_width
        board_y = ((self.output_height - transformed_y) / self.output_height) * self.board_height

        return board_x, board_y

    def camera_to_grid_position(self, camera_x, camera_y, board_rows, board_cols):
        """Convert camera coordinates to grid position (row, col)"""
        if not self.camera_calibrated or board_rows <= 1 or board_cols <= 1:
            return None, None

        # Calculate grid spacing (intersection-based)
        grid_width = self.output_width / (board_cols - 1)
        grid_height = self.output_height / (board_rows - 1)

        # Convert to grid coordinates
        col_float = camera_x / grid_width
        row_float = camera_y / grid_height

        # Round to nearest intersection
        board_col = max(0, min(round(col_float), board_cols - 1))
        board_row = max(0, min(round(row_float), board_rows - 1))

        return board_row, board_col

    def chessboard_to_robot(self, board_x, board_y, board_z=0.0):
        """Convert chessboard coordinates to robot coordinates"""
        if not self.robot_calibrated:
            return None, None, None

        # Create homogeneous coordinates
        pt_table_h = np.array([board_x, board_y, board_z, 1.0])

        # Transform to robot coordinates
        pt_robot = (self.T_matrix @ pt_table_h)[:3]

        return pt_robot[0], pt_robot[1], pt_robot[2]

    def camera_to_robot(self, transformed_x, transformed_y, z_offset=0.0):
        """Direct conversion from perspective-transformed pixels to robot coordinates

        Note: transformed_x, transformed_y should be coordinates from the perspective-corrected view!
        """
        # Perspective-transformed camera -> Chessboard
        board_x, board_y = self.camera_to_chessboard(transformed_x, transformed_y)
        if board_x is None:
            return None, None, None

        # Chessboard -> Robot
        robot_x, robot_y, robot_z = self.chessboard_to_robot(board_x, board_y, z_offset)

        return robot_x, robot_y, robot_z

    def is_calibrated(self):
        """Check if both calibrations are loaded"""
        return self.camera_calibrated and self.robot_calibrated


class ChessPieceRobotController(QMainWindow):
    """Main application window"""

    def __init__(self, camera_calib_file, hand_eye_calib_file, camera_index=0):
        super().__init__()

        # Initialize components
        self.detector = ChessPieceDetector()
        self.transformer = CoordinateTransformer(camera_calib_file, hand_eye_calib_file)
        self.robot = None
        self.camera_index = camera_index

        # Initialize grid UI elements (will be created in init_ui)
        self.grid_col_spin = None
        self.grid_row_spin = None
        self.grid_z_spin = None
        self.grid_board_coord_label = None
        self.grid_robot_coord_label = None
        self.move_to_grid_btn = None
        self.cell_size_label = None

        # Camera and detection variables
        self.cap = None
        self.current_frame = None
        self.detected_pieces = []
        self.selected_piece = None

        # Board dimensions for grid mapping
        self.board_rows = 11
        self.board_cols = 13

        # Piece counting
        self.black_count = 0
        self.white_count = 0

        # Z-offset for robot movement (mm above board)
        self.z_offset = 20.0  # 20mm above the board

        # Grid configuration (matching hand-eye calibration)
        self.total_cols = 12  # Default grid columns
        self.total_rows = 10  # Default grid rows

        # Initialize ROS2 and robot
        self.init_robot()

        # Initialize camera
        self.init_camera()

        # Setup UI
        self.init_ui()

        # Timer for camera updates
        self.camera_timer = QTimer()
        self.camera_timer.timeout.connect(self.update_camera)
        self.camera_timer.start(33)  # ~30 FPS

        # ROS2 spinner timer
        self.ros_timer = QTimer()
        self.ros_timer.timeout.connect(self.spin_ros)
        self.ros_timer.start(50)  # 20 Hz

        print(" Chess Piece Robot Controller initialized")

    def init_robot(self):
        """Initialize robot controller"""
        try:
            # Create robot node
            self.robot = RobotController()

            # Wait for services with longer timeout
            if not self.robot.wait_for_services(timeout=5.0):
                print(" Robot services not available - make sure robot controller is running:")
                print("   ros2 launch episode_controller robot_controller.launch.py")
                self.robot.destroy_node()
                self.robot = None
                return

            print(" Robot controller ready")

        except Exception as e:
            print(f" Failed to initialize robot: {e}")
            if self.robot:
                try:
                    self.robot.destroy_node()
                except:
                    pass
            self.robot = None

    def init_camera(self):
        """Initialize camera"""
        try:
            self.cap = cv2.VideoCapture(self.camera_index)
            if not self.cap.isOpened():
                raise RuntimeError("Cannot open camera")

            # Set camera resolution to match calibration if available
            if hasattr(self.transformer, 'camera_width') and hasattr(self.transformer, 'camera_height'):
                print(f"Setting camera resolution to {self.transformer.camera_width}x{self.transformer.camera_height} (from calibration)")
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.transformer.camera_width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.transformer.camera_height)
            else:
                # Fallback to high resolution
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize latency

            # Check actual camera resolution
            actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if (hasattr(self.transformer, 'camera_width') and
                (actual_width != self.transformer.camera_width or actual_height != self.transformer.camera_height)):
                print(f"  WARNING: Camera resolution mismatch!")
                print(f"   Calibration expects: {self.transformer.camera_width}x{self.transformer.camera_height}")
                print(f"   Camera provides: {actual_width}x{actual_height}")
                print(f"   Transformation may be inaccurate!")

            print(f" Camera initialized: {actual_width}x{actual_height}")

        except Exception as e:
            print(f" Failed to initialize camera: {e}")
            self.cap = None

    def init_ui(self):
        """Initialize user interface"""
        self.setWindowTitle("Chess Piece Robot Controller")
        self.setMinimumSize(1200, 800)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Left panel: Camera feed
        left_panel = QVBoxLayout()

        # Camera display
        camera_title = QLabel("Camera Feed with Piece Detection")
        camera_title.setAlignment(Qt.AlignCenter)
        camera_title.setFont(QFont("Arial", 14, QFont.Bold))
        left_panel.addWidget(camera_title)

        self.camera_label = QLabel()
        # Use output size from calibration if available (perspective-corrected view size)
        if self.transformer.camera_calibrated:
            display_width = self.transformer.output_width
            display_height = self.transformer.output_height
        else:
            display_width, display_height = 640, 480

        self.camera_label.setMinimumSize(display_width, display_height)
        self.camera_label.setFixedSize(display_width, display_height)  # Fixed size to avoid scaling issues
        self.camera_label.setStyleSheet("border: 2px solid #0066cc; background-color: black;")
        self.camera_label.setAlignment(Qt.AlignCenter)
        # Don't use setScaledContents to avoid coordinate scaling issues
        self.camera_label.mousePressEvent = self.on_camera_click
        left_panel.addWidget(self.camera_label)

        print(f"  Camera display widget size: {display_width}x{display_height} pixels")

        # Piece counter
        counter_layout = QHBoxLayout()
        self.black_count_label = QLabel("Black: 0")
        self.black_count_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px; background-color: #333; color: white;")
        counter_layout.addWidget(self.black_count_label)

        self.white_count_label = QLabel("White: 0")
        self.white_count_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px; background-color: #eee; color: black;")
        counter_layout.addWidget(self.white_count_label)

        counter_layout.addStretch()
        left_panel.addLayout(counter_layout)

        main_layout.addLayout(left_panel)

        # Right panel: Controls
        right_panel = QVBoxLayout()

        # Status group
        status_group = QGroupBox("System Status")
        status_layout = QVBoxLayout()

        self.camera_status = QLabel(" Camera: Not Ready")
        self.detector_status = QLabel(" YOLO: Not Ready")
        self.calibration_status = QLabel(" Calibration: Not Ready")
        self.robot_status = QLabel(" Robot: Not Ready")

        for label in [self.camera_status, self.detector_status, self.calibration_status, self.robot_status]:
            label.setFont(QFont("Arial", 10))
            status_layout.addWidget(label)

        status_group.setLayout(status_layout)
        right_panel.addWidget(status_group)

        # Control group
        control_group = QGroupBox("Robot Control")
        control_layout = QFormLayout()

        # Z-offset control
        self.z_offset_spin = QDoubleSpinBox()
        self.z_offset_spin.setRange(5.0, 100.0)
        self.z_offset_spin.setValue(self.z_offset)
        self.z_offset_spin.setSingleStep(5.0)
        self.z_offset_spin.setSuffix(" mm")
        self.z_offset_spin.valueChanged.connect(self.on_z_offset_changed)
        control_layout.addRow("Z Offset:", self.z_offset_spin)

        # Movement buttons
        self.move_selected_btn = QPushButton("Move to Selected Piece")
        self.move_selected_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px; font-size: 14px;")
        self.move_selected_btn.clicked.connect(self.move_to_selected_piece)
        self.move_selected_btn.setEnabled(False)
        control_layout.addRow(self.move_selected_btn)

        self.move_home_btn = QPushButton("Move to Home")
        self.move_home_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 8px;")
        self.move_home_btn.clicked.connect(self.move_to_home)
        control_layout.addRow(self.move_home_btn)

        control_group.setLayout(control_layout)
        right_panel.addWidget(control_group)

        # Selected piece info
        piece_group = QGroupBox("Selected Piece")
        piece_layout = QVBoxLayout()

        self.selected_piece_label = QLabel("No piece selected")
        self.selected_piece_label.setFont(QFont("Arial", 12))
        piece_layout.addWidget(self.selected_piece_label)

        self.coordinates_label = QLabel("Coordinates: --")
        self.coordinates_label.setFont(QFont("Courier", 10))
        piece_layout.addWidget(self.coordinates_label)

        piece_group.setLayout(piece_layout)
        right_panel.addWidget(piece_group)

        # Log area
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(200)
        self.log_text.setFont(QFont("Courier", 9))
        log_layout.addWidget(self.log_text)

        log_group.setLayout(log_layout)
        right_panel.addWidget(log_group)

        # Grid Position Control
        grid_group = QGroupBox("Grid Position Control")
        grid_layout = QGridLayout()

        # Grid configuration
        grid_layout.addWidget(QLabel("Grid Config:"), 0, 0)
        grid_layout.addWidget(QLabel("Cols:"), 0, 1)
        self.total_cols_spin = QSpinBox()
        self.total_cols_spin.setRange(2, 20)
        self.total_cols_spin.setValue(self.total_cols)
        self.total_cols_spin.valueChanged.connect(self.on_grid_config_changed)
        grid_layout.addWidget(self.total_cols_spin, 0, 2)

        grid_layout.addWidget(QLabel("Rows:"), 0, 3)
        self.total_rows_spin = QSpinBox()
        self.total_rows_spin.setRange(2, 20)
        self.total_rows_spin.setValue(self.total_rows)
        self.total_rows_spin.valueChanged.connect(self.on_grid_config_changed)
        grid_layout.addWidget(self.total_rows_spin, 0, 4)

        # Cell size display
        self.cell_size_label = QLabel()
        self.update_cell_size_display()
        grid_layout.addWidget(self.cell_size_label, 0, 5, 1, 2)

        # Grid position input
        grid_layout.addWidget(QLabel("Move to Position:"), 1, 0)
        grid_layout.addWidget(QLabel("Col:"), 1, 1)
        self.grid_col_spin = QSpinBox()
        self.grid_col_spin.setRange(0, 999)
        self.grid_col_spin.setValue(0)
        self.grid_col_spin.valueChanged.connect(self.on_grid_position_changed)
        grid_layout.addWidget(self.grid_col_spin, 1, 2)

        grid_layout.addWidget(QLabel("Row:"), 1, 3)
        self.grid_row_spin = QSpinBox()
        self.grid_row_spin.setRange(0, 999)
        self.grid_row_spin.setValue(0)
        self.grid_row_spin.valueChanged.connect(self.on_grid_position_changed)
        grid_layout.addWidget(self.grid_row_spin, 1, 4)

        # Z offset for grid moves
        grid_layout.addWidget(QLabel("Z:"), 1, 5)
        self.grid_z_spin = QDoubleSpinBox()
        self.grid_z_spin.setRange(-100.0, 100.0)
        self.grid_z_spin.setValue(self.z_offset)
        self.grid_z_spin.setSingleStep(1.0)
        self.grid_z_spin.setSuffix(" mm")
        self.grid_z_spin.valueChanged.connect(self.on_grid_position_changed)
        grid_layout.addWidget(self.grid_z_spin, 1, 6)

        # Calculated coordinates display
        grid_layout.addWidget(QLabel("Board Coord:"), 2, 0)
        self.grid_board_coord_label = QLabel("[0.00, 0.00, 20.00]")
        self.grid_board_coord_label.setFont(QFont("Courier", 9))
        self.grid_board_coord_label.setStyleSheet("color: blue;")
        grid_layout.addWidget(self.grid_board_coord_label, 2, 1, 1, 3)

        grid_layout.addWidget(QLabel("Robot Coord:"), 2, 4)
        self.grid_robot_coord_label = QLabel("[---, ---, ---]")
        self.grid_robot_coord_label.setFont(QFont("Courier", 9))
        self.grid_robot_coord_label.setStyleSheet("color: green;")
        grid_layout.addWidget(self.grid_robot_coord_label, 2, 5, 1, 2)

        # Move to grid position button
        self.move_to_grid_btn = QPushButton("Move to Grid Position")
        self.move_to_grid_btn.setStyleSheet("background-color: #FF9800; color: white; padding: 8px;")
        self.move_to_grid_btn.clicked.connect(self.move_to_grid_position)
        self.move_to_grid_btn.setEnabled(False)
        grid_layout.addWidget(self.move_to_grid_btn, 3, 0, 1, 7)

        grid_group.setLayout(grid_layout)
        right_panel.addWidget(grid_group)

        right_panel.addStretch()
        main_layout.addLayout(right_panel)

        # Update status
        self.update_status()
        self.update_cell_size_display()
        self.on_grid_position_changed()

    def update_status(self):
        """Update system status indicators"""
        # Camera status
        if self.cap and self.cap.isOpened():
            self.camera_status.setText(" Camera: Ready")
        else:
            self.camera_status.setText(" Camera: Not Ready")

        # YOLO status
        if self.detector.model is not None:
            self.detector_status.setText(" YOLO: Ready")
        else:
            self.detector_status.setText(" YOLO: Not Ready")

        # Calibration status
        if self.transformer.is_calibrated():
            self.calibration_status.setText(" Calibration: Ready")
        else:
            self.calibration_status.setText(" Calibration: Not Ready")

        # Robot status
        if self.robot is not None:
            if self.robot.is_moving():
                self.robot_status.setText(" Robot: Moving...")
                # Disable move buttons when robot is moving
                self.move_selected_btn.setEnabled(False)
                self.move_to_grid_btn.setEnabled(False)
            else:
                self.robot_status.setText(" Robot: Ready")
                # Re-enable buttons if conditions are met
                if self.selected_piece and self.transformer.is_calibrated():
                    self.move_selected_btn.setEnabled(True)
                if self.transformer.is_calibrated():
                    self.move_to_grid_btn.setEnabled(True)
        else:
            self.robot_status.setText(" Robot: Not Ready")
            self.move_selected_btn.setEnabled(False)
            self.move_to_grid_btn.setEnabled(False)

    def spin_ros(self):
        """Spin ROS node"""
        if self.robot:
            rclpy.spin_once(self.robot, timeout_sec=0.0)
        self.update_status()  # Update robot status

    def update_camera(self):
        """Update camera feed and detect pieces - implements 3-step transformation chain"""
        if not self.cap or not self.cap.isOpened():
            return

        ret, raw_frame = self.cap.read()
        if not ret:
            return

        self.current_frame = raw_frame.copy()  # Store for click handling

        # STEP 1: Apply perspective transformation if calibrated
        if self.transformer.camera_calibrated:
            # Transform raw camera frame to rectified top-down view
            transformed_frame = cv2.warpPerspective(
                raw_frame,
                self.transformer.transform_matrix,
                (self.transformer.output_width, self.transformer.output_height)
            )
        else:
            # If no calibration, use raw frame (this will cause coordinate errors)
            transformed_frame = raw_frame

        # STEP 2: Detect pieces on perspective-transformed frame
        if self.detector.model is not None:
            # Run YOLO detection on transformed frame and get annotated result
            display_frame, self.detected_pieces = self.detector.detect_and_draw_stones(
                transformed_frame, self.transformer, self.board_rows, self.board_cols
            )

            # Update piece counts
            self.black_count = sum(1 for p in self.detected_pieces if p['type'] == 'black')
            self.white_count = sum(1 for p in self.detected_pieces if p['type'] == 'white')
        else:
            # No YOLO model available
            display_frame = transformed_frame
            self.detected_pieces = []
            self.black_count = 0
            self.white_count = 0

        # STEP 3: Highlight selected piece if any
        if self.selected_piece is not None:
            display_frame = self.highlight_selected_piece(display_frame)

        # Convert to Qt format and display
        height, width, channel = display_frame.shape
        bytes_per_line = 3 * width
        q_image = QImage(display_frame.data, width, height, bytes_per_line, QImage.Format_RGB888).rgbSwapped()
        pixmap = QPixmap.fromImage(q_image)
        self.camera_label.setPixmap(pixmap)

        # Update counters
        self.black_count_label.setText(f"Black: {self.black_count}")
        self.white_count_label.setText(f"White: {self.white_count}")

    def highlight_selected_piece(self, frame):
        """Add highlighting for selected piece"""
        if self.selected_piece is not None and self.detected_pieces:
            # Find the selected piece in current detections and highlight it
            for piece in self.detected_pieces:
                if (piece.get('center') == self.selected_piece.get('center') and
                    piece.get('type') == self.selected_piece.get('type')):
                    x1, y1, x2, y2 = piece['bbox']
                    # Draw thick yellow border for selected piece
                    cv2.rectangle(frame, (x1-3, y1-3), (x2+3, y2+3), (0, 255, 255), 4)
                    break

        return frame

    def on_camera_click(self, event):
        """Handle click on camera display"""
        if not self.detected_pieces:
            self.log("No pieces detected to select")
            return

        # Get click coordinates (scale to actual image size)
        widget_size = self.camera_label.size()
        image_size = (self.transformer.output_width, self.transformer.output_height)

        scale_x = image_size[0] / widget_size.width()
        scale_y = image_size[1] / widget_size.height()

        click_x = int(event.x() * scale_x)
        click_y = int(event.y() * scale_y)

        # Debug click coordinates
        self.log(f"  Click at widget ({event.x()}, {event.y()}) -> image ({click_x}, {click_y})")
        self.log(f"   Widget size: {widget_size.width()}x{widget_size.height()}")
        self.log(f"   Image size: {image_size[0]}x{image_size[1]}")
        self.log(f"   Scale factors: {scale_x:.2f}, {scale_y:.2f}")

        # Find closest piece
        min_distance = float('inf')
        closest_piece = None

        for i, piece in enumerate(self.detected_pieces):
            center_x, center_y = piece['center']
            distance = np.sqrt((click_x - center_x)**2 + (click_y - center_y)**2)

            self.log(f"   Piece {i} ({piece['type']}) at ({center_x}, {center_y}), distance: {distance:.1f}")

            if distance < min_distance:
                min_distance = distance
                closest_piece = piece

        # Select piece if close enough (within 50 pixels)
        if closest_piece and min_distance < 50:
            self.selected_piece = closest_piece
            self.update_selected_piece_info()
            self.log(f" Selected {closest_piece['type']} piece at {closest_piece['center']} (distance: {min_distance:.1f})")

            # Enable move button if calibrated
            can_move = (self.transformer.is_calibrated() and
                       self.robot is not None and
                       not self.robot.is_moving())
            self.move_selected_btn.setEnabled(can_move)
        else:
            if closest_piece:
                self.log(f" Click too far from nearest piece (distance: {min_distance:.1f})")
            else:
                self.log(" No pieces found")

    def update_selected_piece_info(self):
        """Update selected piece information display"""
        if not self.selected_piece:
            self.selected_piece_label.setText("No piece selected")
            self.coordinates_label.setText("Coordinates: --")
            return

        piece = self.selected_piece
        center_x, center_y = piece['center']

        # Basic info
        info = f"{piece['type'].title()} piece (conf: {piece['confidence']:.2f})\nCamera: ({center_x}, {center_y}) px"

        # Add coordinate transformations if calibrated
        coord_info = f"Camera: ({center_x}, {center_y}) px\n"

        if self.transformer.camera_calibrated:
            board_x, board_y = self.transformer.camera_to_chessboard(center_x, center_y)
            if board_x is not None:
                coord_info += f"Board: ({board_x:.1f}, {board_y:.1f}) mm\n"

                if self.transformer.robot_calibrated:
                    robot_x, robot_y, robot_z = self.transformer.chessboard_to_robot(
                        board_x, board_y, self.z_offset
                    )
                    if robot_x is not None:
                        coord_info += f"Robot: ({robot_x:.1f}, {robot_y:.1f}, {robot_z:.1f}) mm"

        self.selected_piece_label.setText(info)
        self.coordinates_label.setText(coord_info)

    def on_z_offset_changed(self, value):
        """Handle Z-offset change"""
        self.z_offset = value
        self.update_selected_piece_info()  # Update coordinates display
        # Also update grid Z offset
        self.grid_z_spin.setValue(value)

    def on_grid_config_changed(self):
        """Handle grid configuration change"""
        self.total_cols = self.total_cols_spin.value()
        self.total_rows = self.total_rows_spin.value()

        # Update cell size display
        self.update_cell_size_display()

        # Update coordinates display
        self.on_grid_position_changed()

        self.log(f"Grid config changed to {self.total_cols}x{self.total_rows}")

    def update_cell_size_display(self):
        """Update cell size display based on board dimensions and grid config"""
        if self.transformer.camera_calibrated:
            cell_width = self.transformer.board_width / self.total_cols
            cell_height = self.transformer.board_height / self.total_rows
            self.cell_size_label.setText(f"Cell: {cell_width:.1f} x {cell_height:.1f} mm")
        else:
            self.cell_size_label.setText("Cell: -- x -- mm")

    def on_grid_position_changed(self):
        """Handle grid position change - update coordinate displays"""
        if not self.transformer.camera_calibrated:
            return

        col = self.grid_col_spin.value()
        row = self.grid_row_spin.value()
        z_offset = self.grid_z_spin.value()

        # Calculate cell size
        cell_width = self.transformer.board_width / self.total_cols
        cell_height = self.transformer.board_height / self.total_rows

        # Calculate board coordinates (grid intersection)
        x_board = col * cell_width
        y_board = row * cell_height
        z_board = z_offset

        self.grid_board_coord_label.setText(f"[{x_board:.2f}, {y_board:.2f}, {z_board:.2f}]")

        # Calculate robot coordinates if calibrated
        if self.transformer.robot_calibrated:
            robot_x, robot_y, robot_z = self.transformer.chessboard_to_robot(x_board, y_board, z_board)
            if robot_x is not None:
                self.grid_robot_coord_label.setText(f"[{robot_x:.1f}, {robot_y:.1f}, {robot_z:.1f}]")
                # Enable move button
                self.move_to_grid_btn.setEnabled(self.robot is not None and not self.robot.is_moving())
            else:
                self.grid_robot_coord_label.setText("[Error, Error, Error]")
                self.move_to_grid_btn.setEnabled(False)
        else:
            self.grid_robot_coord_label.setText("[---, ---, ---]")
            self.move_to_grid_btn.setEnabled(False)

    def move_to_selected_piece(self):
        """Move robot to selected piece"""
        if not self.selected_piece:
            self.log("No piece selected")
            return

        if not self.transformer.is_calibrated():
            self.log(" Calibration not complete")
            return

        if not self.robot or self.robot.is_moving():
            self.log(" Robot not ready or moving")
            return

        # Get piece coordinates (these are already perspective-transformed coordinates)
        center_x, center_y = self.selected_piece['center']
        piece_type = self.selected_piece['type']

        self.log(f" Selected {piece_type} piece at transformed coords ({center_x}, {center_y})")

        # Step 1: Convert perspective-transformed coordinates to chessboard coordinates
        board_x, board_y = self.transformer.camera_to_chessboard(center_x, center_y)
        if board_x is None:
            self.log(" Failed to convert to chessboard coordinates")
            return

        self.log(f" Board coordinates: ({board_x:.1f}, {board_y:.1f}) mm")

        # Step 2: Convert chessboard coordinates to robot coordinates
        robot_x, robot_y, robot_z = self.transformer.chessboard_to_robot(board_x, board_y, self.z_offset)
        if robot_x is None:
            self.log(" Failed to convert to robot coordinates")
            return

        self.log(f" Robot coordinates: ({robot_x:.1f}, {robot_y:.1f}, {robot_z:.1f}) mm")

        # Validate robot coordinates are reasonable
        if abs(robot_x) > 1000 or abs(robot_y) > 1000 or robot_z < 0 or robot_z > 500:
            self.log(f" Robot coordinates seem unreasonable - check calibration")

        # Move robot
        self.log(f" Moving to {piece_type} piece...")

        success = self.robot.move_to(robot_x, robot_y, robot_z)
        if not success:
            self.log(" Failed to start robot movement")
        else:
            self.move_selected_btn.setEnabled(False)  # Disable until move completes

    def move_to_home(self):
        """Move robot to home position"""
        if not self.robot:
            self.log(" Robot not available")
            return

        if self.robot.is_moving():
            self.log(" Robot is currently moving")
            return

        self.log(" Moving to home position")
        self.robot.move_to_home()
        self.move_selected_btn.setEnabled(False)
        self.move_to_grid_btn.setEnabled(False)

    def move_to_grid_position(self):
        """Move robot to specified grid position"""
        if not self.transformer.is_calibrated():
            self.log(" Calibration not complete")
            return

        if not self.robot or self.robot.is_moving():
            self.log(" Robot not ready or moving")
            return

        col = self.grid_col_spin.value()
        row = self.grid_row_spin.value()
        z_offset = self.grid_z_spin.value()

        # Calculate board coordinates
        cell_width = self.transformer.board_width / self.total_cols
        cell_height = self.transformer.board_height / self.total_rows
        x_board = col * cell_width
        y_board = row * cell_height

        # Transform to robot coordinates
        robot_x, robot_y, robot_z = self.transformer.chessboard_to_robot(x_board, y_board, z_offset)

        if robot_x is None:
            self.log(" Grid coordinate transformation failed")
            return

        # Move robot with safety: home first, then to target
        self.log(f" Moving to grid position (col={col}, row={row})")
        self.log(f"   Board: ({x_board:.1f}, {y_board:.1f}, {z_offset:.1f}) mm")
        self.log(f"   Robot: ({robot_x:.1f}, {robot_y:.1f}, {robot_z:.1f}) mm")

        # First move to safe home position
        self.log("   Step 1: Moving to safe position...")
        self.robot.move_to_home()

        # Schedule move to target after delay
        QTimer.singleShot(3000, lambda: self._move_to_grid_target(robot_x, robot_y, robot_z))

        # Disable buttons during move
        self.move_selected_btn.setEnabled(False)
        self.move_to_grid_btn.setEnabled(False)

    def _move_to_grid_target(self, robot_x, robot_y, robot_z):
        """Move to grid target position after safe position reached"""
        if self.robot and not self.robot.is_moving():
            self.log(f"   Step 2: Moving to target ({robot_x:.1f}, {robot_y:.1f}, {robot_z:.1f})...")
            success = self.robot.move_to(robot_x, robot_y, robot_z)
            if not success:
                self.log(" Failed to move to grid position")
        else:
            # Still moving, wait more
            QTimer.singleShot(500, lambda: self._move_to_grid_target(robot_x, robot_y, robot_z))

    def log(self, message):
        """Add message to log"""
        timestamp = time.strftime("%H:%M:%S")
        full_message = f"[{timestamp}] {message}"
        self.log_text.append(full_message)
        print(full_message)  # Also print to console

    def closeEvent(self, event):
        """Handle application close"""
        self.log("Shutting down...")

        # Stop timers
        self.camera_timer.stop()
        self.ros_timer.stop()

        # Release camera
        if self.cap:
            self.cap.release()

        # Cleanup robot
        if self.robot:
            self.robot.destroy_node()

        event.accept()


def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(description="Chess Piece Robot Controller")
    parser.add_argument('camera_calib', nargs='?', default='camera_calibration.yaml',
                        help='Camera calibration YAML file (default: camera_calibration.yaml)')
    parser.add_argument('hand_eye_calib', nargs='?', default='hand_eye_calibration.yaml',
                        help='Hand-eye calibration YAML file (default: hand_eye_calibration.yaml)')
    parser.add_argument('-c', '--camera', type=int, default=0,
                        help='Camera device index (default: 0)')

    args = parser.parse_args()

    camera_calib_file = args.camera_calib
    hand_eye_calib_file = args.hand_eye_calib
    camera_index = args.camera

    print("=" * 60)
    print("Chess Piece Robot Controller")
    print("=" * 60)
    print(f"Camera calibration: {camera_calib_file}")
    print(f"Hand-eye calibration: {hand_eye_calib_file}")
    print(f"Camera index: {camera_index}")
    print("-" * 60)

    # Initialize ROS2 first
    print("Initializing ROS2...")
    try:
        rclpy.init()
        print(" ROS2 initialized")
    except Exception as e:
        print(f" Failed to initialize ROS2: {e}")
        sys.exit(1)

    # Create Qt application
    app = QApplication(sys.argv)

    try:
        # Create main window
        window = ChessPieceRobotController(camera_calib_file, hand_eye_calib_file, camera_index)
        window.show()

        # Print usage instructions
        print("\n Usage Instructions:")
        print("1.  Ensure camera shows cropped chessboard view")
        print("2.  YOLO should detect chess pieces (bounding boxes)")
        print("3.  Click on any detected piece to select it")
        print("4.  Check coordinates transformation in right panel")
        print("5.  Click 'Move to Selected Piece' to move robot")
        print("6.  Use 'Move to Home' to return robot to safe position")
        print("\n Settings:")
        print("- Adjust Z-offset to control height above board")
        print("- Check system status indicators")
        print("- Monitor log for detailed information")
        print("\n Troubleshooting:")
        print("If robot shows as 'Not Ready', ensure:")
        print("1. Robot controller is running: ros2 launch episode_controller robot_controller.launch.py")
        print("2. Robot hardware is connected and powered on")
        print("3. No other programs are using the robot")
        print("\n System ready!")

        # Run application
        exit_code = app.exec_()

    except Exception as e:
        print(f" Application error: {e}")
        exit_code = 1

    finally:
        # Cleanup ROS2
        rclpy.shutdown()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
