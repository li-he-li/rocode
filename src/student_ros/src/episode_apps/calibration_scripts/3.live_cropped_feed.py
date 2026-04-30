#!/usr/bin/env python3
"""
YOLO-Enhanced Cropped Camera Feed with Virtual Chessboard

This script loads a previously saved camera calibration YAML file
and displays the perspective-transformed (cropped) camera feed in real-time
with YOLO-based stone detection, counting, and virtual chessboard mapping.

Usage:
    python3 3.live_cropped_feed.py [calibration_file.yaml] [-c CAMERA_INDEX]

Features:
- Loads transformation matrix from YAML file
- Applies perspective transformation to live camera feed
- YOLO-based stone detection and counting
- Virtual chessboard overlay with configurable size
- Real-time piece mapping to board coordinates
- Board state visualization
- Press 'q' to quit, 's' to save board state
"""

import sys
import cv2
import numpy as np
import yaml
import time
import argparse
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QHBoxLayout, QInputDialog, QPushButton, QGridLayout, QFrame, QSpinBox, QDoubleSpinBox, QGroupBox, QFormLayout, QCheckBox
from PyQt5.QtGui import QImage, QPixmap, QFont, QPainter, QPen, QBrush
from PyQt5.QtCore import Qt, QTimer

# Set OpenCV backend to not conflict with Qt
import os
os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = ''

# Import YOLO
try:
    from ultralytics import YOLO
    import torch
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("  YOLO not available. Install with: pip install ultralytics torch")


class CroppedCameraFeed(QMainWindow):
    """Live cropped camera feed display with YOLO detection and virtual chessboard"""

    def __init__(self, calibration_file="camera_calibration.yaml", weights_file="train_yolo/best.pt", camera_index=2):
        super().__init__()

        # Initialize with default board dimensions (will be adjustable in GUI)
        self.board_rows = 11
        self.board_cols = 13

        # Initialize detection variables
        self.black_count = 0
        self.white_count = 0
        self.yolo_model = None

        # Virtual chessboard state (0=empty, 1=black, -1=white)
        self.virtual_board = [[0 for _ in range(self.board_cols)] for _ in range(self.board_rows)]
        self.detected_pieces = []  # List of (x, y, class_id, confidence)

        # Precision adjustment parameters
        self.grid_offset_x = 0  # X-axis grid offset in pixels
        self.grid_offset_y = 0  # Y-axis grid offset in pixels
        self.grid_scale_x = 1.0  # X-axis grid scaling factor
        self.grid_scale_y = 1.0  # Y-axis grid scaling factor
        self.snap_threshold = 0.8  # Threshold for snapping to nearest intersection

        # Temporal stability parameters to filter out finger detections
        self.stability_delay = 0.5  # Seconds to wait after piece count change
        self.last_piece_count = 0  # Track previous total piece count
        self.last_change_time = 0  # Timestamp of last piece count change
        self.stable_detected_pieces = []  # Stable pieces for board mapping
        self.is_stable = True  # Whether current detection is stable

        # Grid overlay settings
        self.show_grid_overlay = False  # Whether to show grid lines on camera feed

        # Board visualization settings
        self.board_display_size = 400
        # For intersection-based grid, cell size is distance between intersections
        # Use smaller dimension for cell size calculation to fit display
        max_dim = max(self.board_rows - 1, self.board_cols - 1, 1)
        self.cell_size = self.board_display_size // max_dim if max_dim > 0 else self.board_display_size

        # Load calibration data
        self.load_calibration(calibration_file)

        # Load YOLO model if available
        self.load_yolo_model(weights_file)

        # Initialize board mapping
        self.setup_board_mapping()

        # Initialize camera
        self.camera_index = camera_index
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            raise RuntimeError("Cannot open camera")

        # Set camera resolution to match calibration
        print(f"Setting camera resolution to {self.camera_width}x{self.camera_height} (from calibration)")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.camera_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.camera_height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize latency

        # Check actual camera resolution
        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if actual_width != self.camera_width or actual_height != self.camera_height:
            print(f"  WARNING: Camera resolution mismatch!")
            print(f"   Calibration expects: {self.camera_width}x{self.camera_height}")
            print(f"   Camera provides: {actual_width}x{actual_height}")
            print(f"   Transformation may be inaccurate!")

        self.setup_ui()

        # Timer for camera capture
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(33)  # ~30 FPS

        print(f"Loaded calibration: {calibration_file}")
        print(f"Camera resolution: {self.camera_width}x{self.camera_height}")
        print(f"Output size: {self.output_width}x{self.output_height}")
        print("Press 'q' to quit")

    def load_calibration(self, filename):
        """Load calibration data from YAML file"""
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
            self.transformation_matrix = cv2.getPerspectiveTransform(self.pixel_corners, output_corners)

            print(f"Successfully loaded calibration from {filename}")
            print(f"Pixel corners: {self.pixel_corners.tolist()}")
            print(f"Output corners: {output_corners.tolist()}")

        except FileNotFoundError:
            raise FileNotFoundError(f"Calibration file '{filename}' not found")
        except KeyError as e:
            raise ValueError(f"Missing key in calibration file: {e}")
        except Exception as e:
            raise ValueError(f"Error loading calibration file: {e}")

    def setup_board_mapping(self):
        """Setup coordinate mapping from camera to board positions (intersection-based)"""
        # Create grid mapping for the transformed image
        # For intersection-based placement, we divide by (board_cols - 1) for width and (board_rows - 1) for height
        base_width = self.output_width / (self.board_cols - 1) if self.board_cols > 1 else self.output_width
        base_height = self.output_height / (self.board_rows - 1) if self.board_rows > 1 else self.output_height

        # Apply precision adjustments
        self.grid_width = base_width * self.grid_scale_x
        self.grid_height = base_height * self.grid_scale_y

        print(f"Board mapping: {self.board_rows}x{self.board_cols} (intersection-based)")
        print(f"Grid size: {self.grid_width:.1f} x {self.grid_height:.1f} pixels")
        print(f"Offsets: X={self.grid_offset_x}, Y={self.grid_offset_y}")
        print(f"Scales: X={self.grid_scale_x:.3f}, Y={self.grid_scale_y:.3f}")

    def change_board_dimensions(self, new_rows, new_cols):
        """Change board dimensions (for rectangular boards) and update related settings"""
        self.board_rows = new_rows
        self.board_cols = new_cols
        self.virtual_board = [[0 for _ in range(new_cols)] for _ in range(new_rows)]
        max_dim = max(new_rows - 1, new_cols - 1, 1)
        self.cell_size = self.board_display_size // max_dim if max_dim > 0 else self.board_display_size
        self.setup_board_mapping()
        self.update_virtual_board_display()
        print(f"Board dimensions changed to: {new_rows}x{new_cols}")

    def load_yolo_model(self, weights_file):
        """Load YOLO model for stone detection"""
        if not YOLO_AVAILABLE:
            print("  YOLO not available - detection disabled")
            return

        weights_path = Path(weights_file)
        if not weights_path.exists():
            # Try relative path from current script location
            script_dir = Path(__file__).parent
            weights_path = script_dir / weights_file

        if weights_path.exists():
            try:
                self.yolo_model = YOLO(str(weights_path))
                self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
                print(f" Loaded YOLO model: {weights_path}")
                print(f"  Using device: {self.device}")
            except Exception as e:
                print(f" Error loading YOLO model: {e}")
                self.yolo_model = None
        else:
            print(f"  YOLO weights not found: {weights_path}")
            print("   Detection will be disabled")
            self.yolo_model = None

    def setup_ui(self):
        """Setup the user interface"""
        detection_status = "with YOLO Detection" if self.yolo_model else "(Detection Disabled)"
        self.setWindowTitle(f"Live Feed {detection_status} - {self.board_rows}x{self.board_cols} Board - {self.board_width}x{self.board_height}mm")

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Column 1: Controls
        controls_panel = QWidget()
        controls_layout = QVBoxLayout(controls_panel)
        main_layout.addWidget(controls_panel)

        # Add control panel to column 1
        self.create_control_panel(controls_layout)

        # Piece counter display (only if YOLO is available)
        if self.yolo_model:
            counter_layout = QHBoxLayout()

            self.black_label = QLabel("Black Stones: 0")
            self.black_label.setStyleSheet("font-size: 16px; font-weight: bold; color: black; background-color: white; padding: 5px; border: 2px solid black;")
            counter_layout.addWidget(self.black_label)

            self.white_label = QLabel("White Stones: 0")
            self.white_label.setStyleSheet("font-size: 16px; font-weight: bold; color: white; background-color: black; padding: 5px; border: 2px solid white;")
            counter_layout.addWidget(self.white_label)

            counter_layout.addStretch()
            controls_layout.addLayout(counter_layout)

        controls_layout.addStretch()

        # Column 2: Virtual Board Display
        board_panel = QWidget()
        board_layout = QVBoxLayout(board_panel)
        main_layout.addWidget(board_panel)

        board_title = QLabel(f"Virtual {self.board_rows}x{self.board_cols} Go/Gomoku Board")
        board_title.setAlignment(Qt.AlignCenter)
        board_title.setFont(QFont("Arial", 14, QFont.Bold))
        board_layout.addWidget(board_title)

        # Board canvas
        self.board_canvas = QLabel()
        self.board_canvas.setMinimumSize(self.board_display_size + 40, self.board_display_size + 40)
        self.board_canvas.setStyleSheet("border: 2px solid #8B4513; background-color: #DEB887;")
        self.board_canvas.setAlignment(Qt.AlignCenter)
        board_layout.addWidget(self.board_canvas)

        # Board state info
        self.board_info = QLabel("Board State: Empty")
        self.board_info.setAlignment(Qt.AlignCenter)
        board_layout.addWidget(self.board_info)

        # Control buttons
        button_layout = QHBoxLayout()

        self.clear_board_btn = QPushButton("Clear Board")
        self.clear_board_btn.clicked.connect(self.clear_virtual_board)
        button_layout.addWidget(self.clear_board_btn)

        self.save_board_btn = QPushButton("Save Board")
        self.save_board_btn.clicked.connect(self.save_board_state)
        button_layout.addWidget(self.save_board_btn)

        board_layout.addLayout(button_layout)
        board_layout.addStretch()

        # Column 3: Real Board View (Camera Feed)
        camera_panel = QWidget()
        camera_layout = QVBoxLayout(camera_panel)
        main_layout.addWidget(camera_panel)

        camera_title = QLabel("Real Board View")
        camera_title.setAlignment(Qt.AlignCenter)
        camera_title.setFont(QFont("Arial", 14, QFont.Bold))
        camera_layout.addWidget(camera_title)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(self.output_width, self.output_height)
        self.image_label.setStyleSheet("border: 2px solid #0066cc; background-color: black;")
        camera_layout.addWidget(self.image_label)
        camera_layout.addStretch()

        # Initialize board display
        self.update_virtual_board_display()

        # Window size - accommodate three columns
        total_width = 300 + self.board_display_size + self.output_width + 100
        total_height = max(self.output_height, self.board_display_size) + 150
        self.resize(total_width, total_height)

    def create_control_panel(self, parent_layout):
        """Create control panel with board size and precision adjustments"""
        # Board Settings Group
        board_group = QGroupBox("Board Settings")
        board_layout = QFormLayout(board_group)

        # Row selector
        self.board_rows_spin = QSpinBox()
        self.board_rows_spin.setRange(5, 25)
        self.board_rows_spin.setValue(self.board_rows)
        self.board_rows_spin.valueChanged.connect(self.on_dimensions_changed)
        board_layout.addRow("Board Rows:", self.board_rows_spin)

        # Separate column selector
        self.board_cols_spin = QSpinBox()
        self.board_cols_spin.setRange(5, 25)
        self.board_cols_spin.setValue(self.board_cols)
        self.board_cols_spin.valueChanged.connect(self.on_dimensions_changed)
        board_layout.addRow("Board Columns:", self.board_cols_spin)

        parent_layout.addWidget(board_group)

        # Precision Adjustment Group
        precision_group = QGroupBox("Precision Adjustments")
        precision_layout = QFormLayout(precision_group)

        # X Offset
        self.x_offset_spin = QSpinBox()
        self.x_offset_spin.setRange(-50, 50)
        self.x_offset_spin.setValue(self.grid_offset_x)
        self.x_offset_spin.setSuffix(" px")
        self.x_offset_spin.valueChanged.connect(self.update_x_offset)
        precision_layout.addRow("X Offset:", self.x_offset_spin)

        # Y Offset
        self.y_offset_spin = QSpinBox()
        self.y_offset_spin.setRange(-50, 50)
        self.y_offset_spin.setValue(self.grid_offset_y)
        self.y_offset_spin.setSuffix(" px")
        self.y_offset_spin.valueChanged.connect(self.update_y_offset)
        precision_layout.addRow("Y Offset:", self.y_offset_spin)

        # X Scale
        self.x_scale_spin = QDoubleSpinBox()
        self.x_scale_spin.setRange(0.5, 2.0)
        self.x_scale_spin.setValue(self.grid_scale_x)
        self.x_scale_spin.setSingleStep(0.01)
        self.x_scale_spin.setDecimals(3)
        self.x_scale_spin.valueChanged.connect(self.update_x_scale)
        precision_layout.addRow("X Scale:", self.x_scale_spin)

        # Y Scale
        self.y_scale_spin = QDoubleSpinBox()
        self.y_scale_spin.setRange(0.5, 2.0)
        self.y_scale_spin.setValue(self.grid_scale_y)
        self.y_scale_spin.setSingleStep(0.01)
        self.y_scale_spin.setDecimals(3)
        self.y_scale_spin.valueChanged.connect(self.update_y_scale)
        precision_layout.addRow("Y Scale:", self.y_scale_spin)

        # Snap Threshold
        self.snap_threshold_spin = QDoubleSpinBox()
        self.snap_threshold_spin.setRange(0.1, 1.0)
        self.snap_threshold_spin.setValue(self.snap_threshold)
        self.snap_threshold_spin.setSingleStep(0.05)
        self.snap_threshold_spin.setDecimals(2)
        self.snap_threshold_spin.valueChanged.connect(self.update_snap_threshold)
        precision_layout.addRow("Snap Threshold:", self.snap_threshold_spin)

        # Stability Delay
        self.stability_delay_spin = QDoubleSpinBox()
        self.stability_delay_spin.setRange(0.5, 10.0)
        self.stability_delay_spin.setValue(self.stability_delay)
        self.stability_delay_spin.setSingleStep(0.5)
        self.stability_delay_spin.setDecimals(1)
        self.stability_delay_spin.setSuffix(" s")
        self.stability_delay_spin.valueChanged.connect(self.update_stability_delay)
        precision_layout.addRow("Stability Delay:", self.stability_delay_spin)

        parent_layout.addWidget(precision_group)

        parent_layout.addWidget(precision_group)

        # Grid Overlay Group
        overlay_group = QGroupBox("Visual Overlay")
        overlay_layout = QFormLayout(overlay_group)

        # Grid Overlay Checkbox
        self.grid_overlay_checkbox = QCheckBox("Show Grid Overlay")
        self.grid_overlay_checkbox.setChecked(self.show_grid_overlay)
        self.grid_overlay_checkbox.toggled.connect(self.toggle_grid_overlay)
        overlay_layout.addRow(self.grid_overlay_checkbox)

        parent_layout.addWidget(overlay_group)

        # Reset button
        reset_btn = QPushButton("Reset Adjustments")
        reset_btn.clicked.connect(self.reset_adjustments)
        parent_layout.addWidget(reset_btn)

    def update_x_offset(self, value):
        """Update X offset and refresh mapping"""
        self.grid_offset_x = value
        self.setup_board_mapping()

    def update_y_offset(self, value):
        """Update Y offset and refresh mapping"""
        self.grid_offset_y = value
        self.setup_board_mapping()

    def update_x_scale(self, value):
        """Update X scale and refresh mapping"""
        self.grid_scale_x = value
        self.setup_board_mapping()

    def update_y_scale(self, value):
        """Update Y scale and refresh mapping"""
        self.grid_scale_y = value
        self.setup_board_mapping()

    def update_snap_threshold(self, value):
        """Update snap threshold"""
        self.snap_threshold = value

    def on_dimensions_changed(self):
        """Handle board dimension changes from row/col spinboxes"""
        new_rows = self.board_rows_spin.value()
        new_cols = self.board_cols_spin.value()
        self.change_board_dimensions(new_rows, new_cols)

    def update_stability_delay(self, value):
        """Update stability delay for temporal filtering"""
        self.stability_delay = value
        print(f"Stability delay updated to: {value:.1f}s")

    def toggle_grid_overlay(self, checked):
        """Toggle grid overlay on camera feed"""
        self.show_grid_overlay = checked
        print(f"Grid overlay {'enabled' if checked else 'disabled'}")

    def reset_adjustments(self):
        """Reset all precision adjustments to defaults"""
        self.grid_offset_x = 0
        self.grid_offset_y = 0
        self.grid_scale_x = 1.0
        self.grid_scale_y = 1.0
        self.snap_threshold = 0.3
        self.stability_delay = 3.0
        self.show_grid_overlay = False

        # Reset stability tracking
        self.last_piece_count = 0
        self.last_change_time = 0
        self.stable_detected_pieces = []
        self.is_stable = True

        # Update GUI controls
        self.x_offset_spin.setValue(0)
        self.y_offset_spin.setValue(0)
        self.x_scale_spin.setValue(1.0)
        self.y_scale_spin.setValue(1.0)
        self.snap_threshold_spin.setValue(0.3)
        self.stability_delay_spin.setValue(3.0)
        self.grid_overlay_checkbox.setChecked(False)

        self.setup_board_mapping()
        print("Precision adjustments reset to defaults")

    def update_frame(self):
        """Capture and display transformed frame with detection"""
        ret, frame = self.cap.read()
        if not ret:
            return

        # Apply perspective transformation
        transformed = cv2.warpPerspective(
            frame,
            self.transformation_matrix,
            (self.output_width, self.output_height)
        )

        # Apply YOLO detection if available
        if self.yolo_model:
            transformed = self.detect_and_draw_stones(transformed)
            self.update_piece_counters()
            self.check_stability()  # Check if detection is stable
            if self.is_stable:  # Only update board if stable
                self.map_pieces_to_board()
                self.update_virtual_board_display()

        # Convert to Qt image format
        h, w = transformed.shape[:2]
        rgb = cv2.cvtColor(transformed, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        qimg = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888)

        # Display image
        pixmap = QPixmap.fromImage(qimg)
        self.image_label.setPixmap(pixmap)

    def detect_and_draw_stones(self, frame):
        """Detect stones using YOLO and draw bounding boxes"""
        try:
            # Reset counts and piece data
            self.black_count = 0
            self.white_count = 0
            self.detected_pieces = []

            # Run YOLO inference
            results = self.yolo_model(frame, conf=0.5, device=self.device)

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

                        # Store piece data for board mapping
                        self.detected_pieces.append((x1, y1, x2, y2, cls_id, conf))

                        # Count stones by class
                        if cls_id == 0:  # blackstone
                            self.black_count += 1
                            color = (0, 0, 255)  # Red for black stones
                            label = f"Black: {conf:.2f}"
                        elif cls_id == 1:  # whitestone
                            self.white_count += 1
                            color = (255, 0, 0)  # Blue for white stones
                            label = f"White: {conf:.2f}"
                        else:
                            color = (0, 255, 0)  # Green for unknown
                            label = f"Unknown: {conf:.2f}"

                        # Calculate board coordinates for display with precision adjustments
                        center_x = (x1 + x2) // 2
                        center_y = (y1 + y2) // 2

                        # Apply precision adjustments
                        adjusted_x = center_x + self.grid_offset_x
                        adjusted_y = center_y + self.grid_offset_y

                        if self.board_cols > 1 and self.board_rows > 1:
                            col_float = adjusted_x / self.grid_width
                            row_float = adjusted_y / self.grid_height
                            board_col = max(0, min(self.smart_round(col_float, self.snap_threshold), self.board_cols - 1))
                            board_row = max(0, min(self.smart_round(row_float, self.snap_threshold), self.board_rows - 1))
                        else:
                            board_col = 0
                            board_row = 0

                        # Draw bounding box
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

                        # Draw center point
                        cv2.circle(frame, (center_x, center_y), 3, (0, 255, 255), -1)

                        # Update label to include board coordinates
                        coord_label = f"{label} ({board_row},{board_col})"

                        # Draw label background
                        (text_width, text_height), baseline = cv2.getTextSize(
                            coord_label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1
                        )
                        cv2.rectangle(
                            frame,
                            (x1, y1 - text_height - 10),
                            (x1 + text_width, y1),
                            color,
                            -1
                        )

                        # Draw label text
                        cv2.putText(
                            frame,
                            coord_label,
                            (x1, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.4,
                            (255, 255, 255),
                            1
                        )

        except Exception as e:
            print(f"Detection error: {e}")

        # Draw grid overlay if enabled
        if self.show_grid_overlay:
            frame = self.draw_grid_overlay(frame)

        return frame

    def check_stability(self):
        """Check if piece detection is stable (temporal filtering)"""
        import time

        current_time = time.time()
        current_piece_count = len(self.detected_pieces)

        # Check if piece count has changed
        if current_piece_count != self.last_piece_count:
            # Piece count changed - start stability timer
            self.last_piece_count = current_piece_count
            self.last_change_time = current_time
            self.is_stable = False
            print(f"Piece count changed to {current_piece_count} - waiting {self.stability_delay}s for stability")
        else:
            # Piece count unchanged - check if enough time has passed
            time_since_change = current_time - self.last_change_time
            if time_since_change >= self.stability_delay:
                if not self.is_stable:
                    # Just became stable
                    self.stable_detected_pieces = self.detected_pieces.copy()
                    self.is_stable = True
                    print(f"Detection stabilized with {current_piece_count} pieces")
                # Update stable pieces with current detection
                self.stable_detected_pieces = self.detected_pieces.copy()

    def map_pieces_to_board(self):
        """Map stable detected pieces to virtual board coordinates with precision adjustments"""
        # Clear current board state
        self.virtual_board = [[0 for _ in range(self.board_cols)] for _ in range(self.board_rows)]

        # Map each stable detected piece to board coordinates
        for piece_data in self.stable_detected_pieces:
            x1, y1, x2, y2, cls_id, conf = piece_data

            # Calculate center of bounding box
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2

            # Apply precision adjustments
            adjusted_x = center_x + self.grid_offset_x
            adjusted_y = center_y + self.grid_offset_y

            # Convert to board intersection coordinates with improved precision
            if self.board_cols > 1 and self.board_rows > 1:
                col_float = adjusted_x / self.grid_width
                # Flip Y-axis: bottom-left origin means row 0 is at the bottom
                row_float = (self.output_height - adjusted_y) / self.grid_height

                # Use snap threshold for better precision
                board_col = self.smart_round(col_float, self.snap_threshold)
                board_row = self.smart_round(row_float, self.snap_threshold)

                # Clamp to valid range
                board_col = max(0, min(board_col, self.board_cols - 1))
                board_row = max(0, min(board_row, self.board_rows - 1))
            else:
                board_col = 0
                board_row = 0

            # Ensure coordinates are within bounds and position is not occupied
            if (0 <= board_row < self.board_rows and 0 <= board_col < self.board_cols and
                self.virtual_board[board_row][board_col] == 0):  # Only place if position is empty
                piece_value = 1 if cls_id == 0 else -1  # 1=black, -1=white
                self.virtual_board[board_row][board_col] = piece_value

    def draw_grid_overlay(self, frame):
        """Draw grid overlay on the camera frame to match virtual board"""
        try:
            # Calculate grid spacing with precision adjustments
            base_width = self.output_width / (self.board_cols - 1) if self.board_cols > 1 else self.output_width
            base_height = self.output_height / (self.board_rows - 1) if self.board_rows > 1 else self.output_height

            grid_width = base_width * self.grid_scale_x
            grid_height = base_height * self.grid_scale_y

            # Grid line color (semi-transparent green)
            grid_color = (0, 255, 0)  # Green in BGR
            line_thickness = 1

            # Draw vertical lines
            for col in range(self.board_cols):
                x = int(col * grid_width + self.grid_offset_x)
                if 0 <= x < self.output_width:
                    cv2.line(frame, (x, 0), (x, self.output_height), grid_color, line_thickness)

            # Draw horizontal lines
            for row in range(self.board_rows):
                y = int(row * grid_height + self.grid_offset_y)
                if 0 <= y < self.output_height:
                    cv2.line(frame, (0, y), (self.output_width, y), grid_color, line_thickness)

            # Draw intersection points for better visibility
            for row in range(self.board_rows):
                for col in range(self.board_cols):
                    x = int(col * grid_width + self.grid_offset_x)
                    y = int(row * grid_height + self.grid_offset_y)
                    if 0 <= x < self.output_width and 0 <= y < self.output_height:
                        cv2.circle(frame, (x, y), 2, grid_color, -1)

            # Draw grid info text
            info_text = f"Grid: {self.board_rows}x{self.board_cols}, Scale: {self.grid_scale_x:.2f}x{self.grid_scale_y:.2f}"
            cv2.putText(frame, info_text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, grid_color, 1)

        except Exception as e:
            print(f"Grid overlay error: {e}")

        return frame

    def smart_round(self, value, threshold):
        """Smart rounding with threshold for better intersection snapping"""
        floor_val = int(value)
        remainder = value - floor_val

        if remainder < threshold:
            return floor_val
        elif remainder > (1 - threshold):
            return floor_val + 1
        else:
            return round(value)

    def update_virtual_board_display(self):
        """Update the virtual board display with intersection-based pieces"""
        # Create pixmap for board
        pixmap = QPixmap(self.board_display_size + 40, self.board_display_size + 40)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw board background
        painter.setBrush(QBrush(Qt.darkYellow))  # Board color
        painter.drawRect(20, 20, self.board_display_size, self.board_display_size)

        # Calculate cell sizes for rectangular board
        cell_width = self.board_display_size / (self.board_cols - 1) if self.board_cols > 1 else self.board_display_size
        cell_height = self.board_display_size / (self.board_rows - 1) if self.board_rows > 1 else self.board_display_size

        # Draw grid lines (intersection-based)
        painter.setPen(QPen(Qt.darkRed, 1))

        # Vertical lines
        for col in range(self.board_cols):
            x = 20 + col * cell_width
            painter.drawLine(int(x), 20, int(x), 20 + self.board_display_size)

        # Horizontal lines
        for row in range(self.board_rows):
            y = 20 + row * cell_height
            painter.drawLine(20, int(y), 20 + self.board_display_size, int(y))

        # Draw pieces at intersections
        piece_radius = int(max(min(cell_width, cell_height) // 4, 6))  # Use smaller dimension, ensure int
        for row in range(self.board_rows):
            for col in range(self.board_cols):
                if self.virtual_board[row][col] != 0:
                    # Place pieces exactly at grid intersections
                    # Flip Y-axis: row 0 should be at bottom, so invert the row position
                    center_x = 20 + col * cell_width
                    center_y = 20 + (self.board_rows - 1 - row) * cell_height

                    if self.virtual_board[row][col] == 1:  # Black piece
                        painter.setBrush(QBrush(Qt.black))
                        painter.setPen(QPen(Qt.white, 2))
                    else:  # White piece
                        painter.setBrush(QBrush(Qt.white))
                        painter.setPen(QPen(Qt.black, 2))

                    painter.drawEllipse(int(center_x - piece_radius), int(center_y - piece_radius),
                                      int(piece_radius * 2), int(piece_radius * 2))

        # Draw coordinate labels at intersections if board is not too large
        if max(self.board_rows, self.board_cols) <= 15:
            painter.setPen(QPen(Qt.black, 1))
            painter.setFont(QFont("Arial", 8))

            # Row numbers (at intersections) - flip Y-axis for bottom-left origin
            for row in range(self.board_rows):
                y_pos = 20 + (self.board_rows - 1 - row) * cell_height
                painter.drawText(5, int(y_pos + 3), str(row))

            # Column numbers (at intersections)
            for col in range(self.board_cols):
                x_pos = 20 + col * cell_width
                painter.drawText(int(x_pos - 3), 15, str(col))

        painter.end()

        # Set the pixmap to the label
        self.board_canvas.setPixmap(pixmap)

        # Update board info
        total_pieces = sum(row.count(1) + row.count(-1) for row in self.virtual_board)
        black_pieces = sum(row.count(1) for row in self.virtual_board)
        white_pieces = sum(row.count(-1) for row in self.virtual_board)

        # Add stability status to info
        stability_status = "STABLE" if self.is_stable else "WAITING..."
        detected_count = len(self.detected_pieces) if hasattr(self, 'detected_pieces') else 0

        info_text = f"Pieces: {total_pieces} | Black: {black_pieces} | White: {white_pieces} | Status: {stability_status}"
        if not self.is_stable and detected_count > 0:
            info_text += f" (Detected: {detected_count})"

        self.board_info.setText(info_text)

    def clear_virtual_board(self):
        """Clear the virtual board"""
        self.virtual_board = [[0 for _ in range(self.board_cols)] for _ in range(self.board_rows)]
        self.update_virtual_board_display()
        print("Virtual board cleared")

    def save_board_state(self):
        """Save current board state to file"""
        import json
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"board_state_{self.board_rows}x{self.board_cols}_{timestamp}.json"

        board_data = {
            'timestamp': timestamp,
            'board_rows': self.board_rows,
            'board_cols': self.board_cols,
            'board_state': self.virtual_board,
            'piece_counts': {
                'black': sum(row.count(1) for row in self.virtual_board),
                'white': sum(row.count(-1) for row in self.virtual_board),
                'total': sum(row.count(1) + row.count(-1) for row in self.virtual_board)
            }
        }

        try:
            with open(filename, 'w') as f:
                json.dump(board_data, f, indent=2)
            print(f"Board state saved to: {filename}")
        except Exception as e:
            print(f"Error saving board state: {e}")

    def update_piece_counters(self):
        """Update the piece counter labels"""
        if hasattr(self, 'black_label'):
            self.black_label.setText(f"Black Stones: {self.black_count}")
        if hasattr(self, 'white_label'):
            self.white_label.setText(f"White Stones: {self.white_count}")

    def keyPressEvent(self, event):
        """Handle keyboard events"""
        if event.key() == Qt.Key_Q:
            if self.yolo_model:
                print(f"Final count - Black: {self.black_count}, White: {self.white_count}")
            print("Exiting...")
            self.close()
        elif event.key() == Qt.Key_S:
            self.save_board_state()
        elif event.key() == Qt.Key_C:
            self.clear_virtual_board()
        elif event.key() == Qt.Key_P:
            self.print_board_state()

    def print_board_state(self):
        """Print current board state to console"""
        print(f"\n=== {self.board_rows}x{self.board_cols} Board State ===")
        symbols = {0: '·', 1: '', -1: ''}

        # Column headers
        print('   ', end='')
        for j in range(self.board_cols):
            print(f'{j:2}', end=' ')
        print()

        # Rows with data
        for i in range(self.board_rows):
            print(f'{i:2} ', end='')
            for j in range(self.board_cols):
                print(f' {symbols[self.virtual_board[i][j]]} ', end='')
            print()

        print(f"Black pieces: {sum(row.count(1) for row in self.virtual_board)}")
        print(f"White pieces: {sum(row.count(-1) for row in self.virtual_board)}")
        print("===============================\n")

    def closeEvent(self, event):
        """Clean up on close"""
        self.timer.stop()
        if self.cap is not None:
            self.cap.release()
        print("Camera released.")
        event.accept()


def test_functionality():
    """Test helper function to display key information"""
    print("\n=== ENHANCED CHESSBOARD DETECTION ===")
    print("This enhanced script will:")
    print("1.  Get user input for board size (NxN or MxN)")
    print("2.  Load YAML calibration file")
    print("3.  Display cropped camera feed in real-time")
    print("4.  Apply perspective transformation")
    print("5.  Detect and count stones using YOLO")
    print("6.  Map detected pieces to virtual chessboard")
    print("7.  Display virtual board with piece positions")
    print("8.  Show board coordinates on detected pieces")
    print("\nNew Features:")
    print("• Configurable board dimensions (5-25 rows/cols)")
    print("• Support for rectangular boards (MxN where M≠N)")
    print("• Virtual chessboard visualization")
    print("• Real-time piece-to-coordinate mapping")
    print("• Board state saving and clearing")
    print("• Enhanced piece position display")
    print("\nTest checklist:")
    print(" Board size input dialog appears")
    print(" Camera initializes properly")
    print(" YAML file loads successfully")
    print(" YOLO model loads (best.pt)")
    print(" Video feed displays in left panel")
    print(" Virtual board displays in right panel")
    print(" Perspective transformation is applied correctly")
    print(" Stone detection works (bounding boxes with coordinates)")
    print(" Detected pieces appear on virtual board")
    print(" Piece counters update in real-time")
    print(" Board coordinates show on each detected piece")
    print("\nKeyboard shortcuts:")
    print("- 'Q': Quit application")
    print("- 'S': Save current board state to JSON")
    print("- 'C': Clear virtual board")
    print("- 'P': Print board state to console")
    print("\nTroubleshooting:")
    print("- If camera doesn't work: Check if camera is connected and not in use")
    print("- If YAML doesn't load: Verify file path and format")
    print("- If YOLO doesn't load: Check if best.pt exists in train_yolo/")
    print("- If no detection: Ensure stones are visible and well-lit")
    print("- If transformation looks wrong: Check calibration corners")
    print("- If pieces don't map correctly: Check board size matches physical board")
    print("=========================================\n")


def main():
    parser = argparse.ArgumentParser(description="YOLO-Enhanced Cropped Camera Feed with Virtual Chessboard")
    parser.add_argument("calibration_file", nargs="?", default="camera_calibration.yaml",
                        help="Path to calibration YAML file (default: camera_calibration.yaml)")
    parser.add_argument("-c", "--camera-index", type=int, default=2,
                        help="Camera device index (default: 2)")
    args = parser.parse_args()

    # Display test information
    test_functionality()

    app = QApplication(sys.argv)

    try:
        window = CroppedCameraFeed(args.calibration_file, camera_index=args.camera_index)
        window.show()
        print(f" Application started successfully! (camera index: {args.camera_index})")
        print(" Window displayed - check if video feed is working")
        sys.exit(app.exec_())
    except Exception as e:
        print(f" Error: {e}")
        print("\n Usage: python3 3.live_cropped_feed.py [calibration_file.yaml] [-c CAMERA_INDEX]")
        print("Make sure:")
        print("  - Your camera is connected and working")
        print("  - The calibration YAML file exists and is readable")
        print("  - The calibration was done with the same camera/resolution")
        sys.exit(1)


if __name__ == "__main__":
    main()
