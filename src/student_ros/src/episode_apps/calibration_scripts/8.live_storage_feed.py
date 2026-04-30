#!/usr/bin/env python3
"""
Live Storage Area Feed with YOLO Detection

This script loads a previously saved storage camera calibration YAML file
and displays the perspective-transformed (cropped) camera feed in real-time
for the storage area monitoring with YOLO-based stone detection.

Usage:
    python3 8.live_storage_feed.py [storage_calibration_file.yaml] [weights_file.pt]

Features:
- Loads transformation matrix from storage calibration YAML file
- Applies perspective transformation to live camera feed
- YOLO-based stone detection and counting
- Real-time piece counting display
- Bounding box visualization with confidence scores
- Press 'q' to quit, 's' to save current frame

Based on calibration from calibrate_storage_camera.py
Requires YOLO model weights for detection functionality
"""

import sys
import cv2
import numpy as np
import yaml
import time
import os
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QHBoxLayout, QPushButton
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtCore import Qt, QTimer

# Set OpenCV backend to not conflict with Qt
os.environ['OPENCV_VIDEOIO_PRIORITY_MSMF'] = '0'
os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = ''

# Import YOLO
try:
    from ultralytics import YOLO
    import torch
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("  YOLO not available. Install with: pip install ultralytics torch")


class StorageAreaFeed(QMainWindow):
    """Live storage area camera feed display with YOLO detection"""

    def __init__(self, calibration_file="storage_camera_calibration.yaml", weights_file="train_yolo/best.pt", camera_index=0):
        super().__init__()

        # Initialize detection variables
        self.yolo_model = None
        self.camera_index = camera_index

        # Load calibration data
        self.load_calibration(calibration_file)

        # Load YOLO model if available
        self.load_yolo_model(weights_file)

        # Initialize camera
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            raise RuntimeError("Could not open camera")

        # Set camera resolution to match calibration
        print(f"Setting camera resolution to {self.camera_width}x{self.camera_height} (from calibration)")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.camera_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.camera_height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize latency

        # Check actual camera resolution
        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if actual_width != self.camera_width or actual_height != self.camera_height:
            print(f" Warning: Requested {self.camera_width}x{self.camera_height}, got {actual_width}x{actual_height}")
            print("This might affect calibration accuracy!")
            # Update to actual resolution for display purposes
            self.camera_width, self.camera_height = actual_width, actual_height

        self.setup_ui()

        # Timer for camera capture
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(33)  # ~30 FPS

        print(f" Storage Area Feed Started")
        print(f"Loaded calibration: {calibration_file}")
        print(f"Camera resolution: {self.camera_width}x{self.camera_height}")
        print(f"Storage output size: {self.output_width}x{self.output_height}")
        print(f"Storage area: {self.storage_width}x{self.storage_height}mm")
        print("Press 'q' to quit, 's' to save current frame")

    def load_calibration(self, filename):
        """Load storage calibration data from YAML file"""
        try:
            with open(filename, 'r') as f:
                data = yaml.safe_load(f)

            # Extract transformation matrix
            self.transformation_matrix = np.array(data['transformation_matrix'], dtype=np.float32)

            # Extract calibration parameters
            self.storage_width = data['storage_size_mm']['width']
            self.storage_height = data['storage_size_mm']['height']

            # Output dimensions for transformed image
            self.output_width = data['output_size']['width']
            self.output_height = data['output_size']['height']

            # Camera resolution from calibration
            self.camera_width = data['camera_resolution']['width']
            self.camera_height = data['camera_resolution']['height']

            print(f" Calibration loaded from {filename}")

        except FileNotFoundError:
            print(f" Error: Calibration file '{filename}' not found!")
            print("Please run calibrate_storage_camera.py first to create the calibration file.")
            sys.exit(1)
        except KeyError as e:
            print(f" Error: Missing key in calibration file: {e}")
            sys.exit(1)
        except Exception as e:
            print(f" Error loading calibration: {e}")
            sys.exit(1)

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
        self.setWindowTitle(f"Storage Area Feed {detection_status} - {self.storage_width}x{self.storage_height}mm")

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Title
        title_label = QLabel(" Storage Area Monitor")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        title_label.setStyleSheet("color: #FF6600; padding: 10px; background-color: #FFF3E0; border: 2px solid #FF6600; border-radius: 5px;")
        layout.addWidget(title_label)

        # Storage info
        info_text = f"Calibrated storage area: {self.storage_width} × {self.storage_height} mm"
        info_label = QLabel(info_text)
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setStyleSheet("padding: 5px; font-size: 12px; color: #333;")
        layout.addWidget(info_label)

        # Image display
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(self.output_width, self.output_height)
        self.image_label.setStyleSheet("border: 2px solid #FF6600; background-color: black;")
        layout.addWidget(self.image_label)

        # Control buttons
        button_layout = QHBoxLayout()

        self.save_btn = QPushButton(" Save Current Frame")
        self.save_btn.clicked.connect(self.save_current_frame)
        self.save_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px; font-weight: bold;")
        button_layout.addWidget(self.save_btn)

        self.quit_btn = QPushButton(" Quit")
        self.quit_btn.clicked.connect(self.close)
        self.quit_btn.setStyleSheet("background-color: #f44336; color: white; padding: 8px;")
        button_layout.addWidget(self.quit_btn)

        layout.addLayout(button_layout)

        # Status label
        self.status_label = QLabel("Storage area feed active - Press 'Q' to quit, 'S' to save frame")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 12px; padding: 5px; background-color: #E8F5E8; border: 1px solid #4CAF50; border-radius: 3px;")
        layout.addWidget(self.status_label)

        # Window size
        total_width = max(self.output_width + 50, 600)
        total_height = self.output_height + 200
        self.resize(total_width, total_height)

    def update_frame(self):
        """Capture and display transformed frame with detection"""
        ret, frame = self.cap.read()
        if not ret:
            return

        # Apply YOLO detection on raw frame if available
        detected_boxes = []
        if self.yolo_model:
            detected_boxes = self.detect_stones_on_raw_frame(frame)

        # Apply perspective transformation
        transformed = cv2.warpPerspective(
            frame,
            self.transformation_matrix,
            (self.output_width, self.output_height)
        )

        # Draw transformed bounding boxes on the cropped frame
        if self.yolo_model and detected_boxes:
            transformed = self.draw_transformed_boxes(transformed, detected_boxes)

        # Convert to Qt image format
        h, w = transformed.shape[:2]
        rgb = cv2.cvtColor(transformed, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        qimg = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888)

        # Display image
        pixmap = QPixmap.fromImage(qimg)
        self.image_label.setPixmap(pixmap)

        # Store current transformed frame with overlayed detections for saving
        self.current_transformed = transformed

    def detect_stones_on_raw_frame(self, frame):
        """Detect stones using YOLO on raw camera frame and return detection data"""
        detected_boxes = []
        try:
            # Run YOLO inference on raw frame
            results = self.yolo_model(frame, conf=0.1, device=self.device)

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

                        # Set colors and labels by class
                        if cls_id == 0:  # blackstone
                            color = (0, 0, 255)  # Red for black stones
                            label = f"Black: {conf:.2f}"
                        elif cls_id == 1:  # whitestone
                            color = (255, 0, 0)  # Blue for white stones
                            label = f"White: {conf:.2f}"
                        else:
                            color = (0, 255, 0)  # Green for unknown
                            label = f"Unknown: {conf:.2f}"

                        # Store detection data for transformation
                        detected_boxes.append({
                            'bbox': (x1, y1, x2, y2),
                            'conf': conf,
                            'cls_id': cls_id,
                            'color': color,
                            'label': label
                        })

        except Exception as e:
            print(f"Detection error: {e}")

        return detected_boxes

    def draw_transformed_boxes(self, transformed_frame, detected_boxes):
        """Transform detection boxes and draw them on the cropped frame"""
        try:
            for detection in detected_boxes:
                x1, y1, x2, y2 = detection['bbox']
                color = detection['color']
                label = detection['label']

                # Transform bounding box corners
                corners = np.array([
                    [x1, y1],  # Top-left
                    [x2, y1],  # Top-right
                    [x2, y2],  # Bottom-right
                    [x1, y2]   # Bottom-left
                ], dtype=np.float32).reshape(-1, 1, 2)

                # Apply perspective transformation to corners
                transformed_corners = cv2.perspectiveTransform(corners, self.transformation_matrix)
                transformed_corners = transformed_corners.reshape(-1, 2)

                # Check if any part of the transformed box is within the frame
                if self.is_box_in_frame(transformed_corners, self.output_width, self.output_height):
                    # Draw transformed bounding box as polygon
                    pts = np.array(transformed_corners, np.int32)
                    pts = pts.reshape((-1, 1, 2))
                    cv2.polylines(transformed_frame, [pts], True, color, 2)

                    # Calculate center of transformed box for center point and label
                    center_x = int(np.mean(transformed_corners[:, 0]))
                    center_y = int(np.mean(transformed_corners[:, 1]))

                    # Draw center point if it's within frame
                    if 0 <= center_x < self.output_width and 0 <= center_y < self.output_height:
                        cv2.circle(transformed_frame, (center_x, center_y), 3, (0, 255, 255), -1)

                    # Find top-left corner of transformed box for label placement
                    top_left_x = int(min(transformed_corners[:, 0]))
                    top_left_y = int(min(transformed_corners[:, 1]))

                    # Draw label if top-left is within reasonable bounds
                    if (-20 <= top_left_x < self.output_width + 20 and
                        -20 <= top_left_y < self.output_height + 20):

                        # Ensure label position is within frame
                        label_x = max(0, min(top_left_x, self.output_width - 100))
                        label_y = max(20, min(top_left_y, self.output_height - 5))

                        # Draw label background
                        (text_width, text_height), baseline = cv2.getTextSize(
                            label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1
                        )
                        cv2.rectangle(
                            transformed_frame,
                            (label_x, label_y - text_height - 5),
                            (label_x + text_width, label_y),
                            color,
                            -1
                        )

                        # Draw label text
                        cv2.putText(
                            transformed_frame,
                            label,
                            (label_x, label_y - 2),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.4,
                            (255, 255, 255),
                            1
                        )

        except Exception as e:
            print(f"Error drawing transformed boxes: {e}")

        return transformed_frame

    def is_box_in_frame(self, corners, width, height):
        """Check if any part of the transformed box is within the frame bounds"""
        # Check if any corner is within the frame, or if frame corners are within the box
        for corner in corners:
            x, y = corner
            if 0 <= x <= width and 0 <= y <= height:
                return True

        # Check if the box completely contains the frame
        min_x, min_y = np.min(corners, axis=0)
        max_x, max_y = np.max(corners, axis=0)
        if min_x <= 0 and max_x >= width and min_y <= 0 and max_y >= height:
            return True

        return False


    def save_current_frame(self):
        """Save current transformed frame to file"""
        if hasattr(self, 'current_transformed'):
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"storage_frame_{timestamp}.png"
            cv2.imwrite(filename, self.current_transformed)

            self.status_label.setText(f"Frame saved as: {filename}")
            self.status_label.setStyleSheet("font-size: 12px; padding: 5px; background-color: #E3F2FD; border: 1px solid #2196F3; border-radius: 3px;")
            print(f" Frame saved: {filename}")

            # Reset status after 3 seconds
            QTimer.singleShot(3000, self.reset_status)
        else:
            print(" No frame to save yet")

    def reset_status(self):
        """Reset status label to default"""
        self.status_label.setText("Storage area feed active - Press 'Q' to quit, 'S' to save frame")
        self.status_label.setStyleSheet("font-size: 12px; padding: 5px; background-color: #E8F5E8; border: 1px solid #4CAF50; border-radius: 3px;")

    def keyPressEvent(self, event):
        """Keyboard event handler"""
        key = event.key()

        if key == Qt.Key_Q:
            print(" Quitting storage area feed...")
            self.close()
        elif key == Qt.Key_S:
            self.save_current_frame()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        """Clean up when closing"""
        if hasattr(self, 'cap') and self.cap.isOpened():
            self.cap.release()

        if hasattr(self, 'timer'):
            self.timer.stop()

        print(" Storage area feed closed")
        event.accept()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Live Storage Area Feed with YOLO Detection")
    parser.add_argument('calibration_file', nargs='?', default='storage_camera_calibration.yaml',
                        help='Storage calibration YAML file (default: storage_camera_calibration.yaml)')
    parser.add_argument('weights_file', nargs='?', default='train_yolo/best.pt',
                        help='YOLO weights file (default: train_yolo/best.pt)')
    parser.add_argument('-c', '--camera', type=int, default=0,
                        help='Camera device index (default: 0)')

    args = parser.parse_args()
    calibration_file = args.calibration_file
    weights_file = args.weights_file
    camera_index = args.camera

    # Display information
    print(" STORAGE AREA LIVE FEED WITH YOLO DETECTION")
    print("=" * 60)
    print("This script displays the calibrated storage area feed with YOLO detection.")
    print("Features:")
    print("- Real-time storage area monitoring")
    print("- YOLO-based stone detection and counting")
    print("- Perspective transformation from calibration")
    print("")
    print("Requirements:")
    print("1. Run calibrate_storage_camera.py first to create calibration file")
    print("2. Have YOLO model weights (train_yolo/best.pt) for detection")
    print("3. Install: pip install ultralytics torch")
    print("")
    print("Controls:")
    print("- Press 'Q' to quit")
    print("- Press 'S' to save current frame")
    print("=" * 60)

    app = QApplication(sys.argv)

    try:
        window = StorageAreaFeed(calibration_file, weights_file, camera_index)
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        print(f" Error: {e}")
        print("\n Usage: python3 8.live_storage_feed.py [calibration_file.yaml] [weights_file.pt]")
        print("Make sure:")
        print("  - Your camera is connected and working")
        print("  - The storage calibration YAML file exists")
        print("  - The YOLO weights file exists (optional for detection)")
        sys.exit(1)


if __name__ == "__main__":
    main()
