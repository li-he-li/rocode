"""相机桥接脚本 — 在 conda episode 环境中运行，捕获 RealSense 帧并输出 JSON 到 stdout。

用法: python3 camera_bridge.py capture [--output-dir /tmp/vlm_perception]

输出 JSON: {"success": true, "color_path": "...", "depth_path": "...", "intr_matrix": [[fx,0,cx],[0,fy,cy],[0,0,1]]}
"""

import json
import os
import argparse
import numpy as np
import pyrealsense2 as rs

CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 30


def capture_frame(output_dir: str) -> dict:
    """打开相机 → 捕获一帧 → 保存 → 返回路径信息喵~"""
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.depth, CAMERA_WIDTH, CAMERA_HEIGHT, rs.format.z16, CAMERA_FPS)
    config.enable_stream(rs.stream.color, CAMERA_WIDTH, CAMERA_HEIGHT, rs.format.bgr8, CAMERA_FPS)
    align = rs.align(rs.stream.color)

    started = False
    try:
        pipeline.start(config)
        started = True
        # 丢弃前几帧让自动曝光稳定
        for _ in range(10):
            pipeline.wait_for_frames()

        frames = pipeline.wait_for_frames()
        frames = align.process(frames)

        color_frame = frames.get_color_frame()
        depth_frame = frames.get_depth_frame()
        if not color_frame or not depth_frame:
            return {"success": False, "error": "无法获取相机帧"}

        color_image = np.asanyarray(color_frame.get_data())
        depth_image = np.asanyarray(depth_frame.get_data())

        intr = color_frame.profile.as_video_stream_profile().intrinsics
        intr_matrix = [[intr.fx, 0, intr.ppx], [0, intr.fy, intr.ppy], [0, 0, 1]]

        os.makedirs(output_dir, exist_ok=True)
        color_path = os.path.join(output_dir, "color.jpg")
        depth_path = os.path.join(output_dir, "depth.npy")

        import cv2

        cv2.imwrite(color_path, color_image)
        np.save(depth_path, depth_image)

        return {
            "success": True,
            "color_path": color_path,
            "depth_path": depth_path,
            "intr_matrix": intr_matrix,
        }
    except Exception as e:
        return {"success": False, "error": f"相机错误: {e}"}
    finally:
        if started:
            pipeline.stop()


def main():
    parser = argparse.ArgumentParser(description="RealSense 相机桥接")
    parser.add_argument("action", choices=["capture"], help="操作类型")
    parser.add_argument("--output-dir", default="/tmp/vlm_perception", help="输出目录")
    args = parser.parse_args()

    if args.action == "capture":
        result = capture_frame(args.output_dir)
    else:
        result = {"success": False, "error": f"未知操作: {args.action}"}

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
