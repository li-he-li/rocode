"""VLM 感知工具 handler — observe + locate 喵~"""

from robocode.utils.models import ToolResult


def make_perception_tools(perception) -> dict:
    """返回 {"observe": handler, "locate": handler} 喵~"""

    def observe(*, prompt: str, **kwargs) -> dict:
        """通用视觉观察。Agent 编写 prompt 描述想观察什么喵~"""
        cap = perception.capture()
        if not cap.success:
            return ToolResult(
                success=False,
                message=f"相机捕获失败: {cap.error}",
            ).model_dump()

        result = perception.observe(cap.color_path, prompt)
        if not result.get("success"):
            return ToolResult(
                success=False,
                message=f"VLM 观察失败: {result.get('error', '未知错误')}",
            ).model_dump()

        objects_detected = [o.get("name", "") for o in result.get("objects", [])]
        return ToolResult(
            success=True,
            message=result.get("observation", ""),
            metrics={
                "image_path": cap.color_path,
                "objects_detected": objects_detected,
                "spatial_relations": result.get("spatial_relations", ""),
                "vlm_suggestions": result.get("suggestions", ""),
            },
        ).model_dump()

    def locate(*, target: str, **kwargs) -> dict:
        """定位特定物体，返回 3D 坐标喵~"""
        cap = perception.capture()
        if not cap.success:
            return ToolResult(
                success=False,
                message=f"相机捕获失败: {cap.error}",
            ).model_dump()

        result = perception.locate(
            cap.color_path,
            target,
            depth_image=cap.depth_image,
            intr_matrix=cap.intr_matrix,
        )
        if not result.get("success"):
            return ToolResult(
                success=False,
                message=f"VLM 定位失败: {result.get('error', '未知错误')}",
            ).model_dump()

        if not result.get("found"):
            return ToolResult(
                success=False,
                message=f"未找到目标: {target}",
                metrics={"target": target},
            ).model_dump()

        pos = result.get("position_3d")
        pos_str = f" ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f}) mm" if pos else " (3D坐标不可用)"
        return ToolResult(
            success=True,
            message=f"找到 {result['class_name']} 在{pos_str}",
            metrics={
                "target": target,
                "class_name": result["class_name"],
                "position_3d": pos,
                "bbox": result["bbox"],
                "confidence": result.get("confidence", 0),
                "image_path": cap.color_path,
            },
        ).model_dump()

    return {"observe": observe, "locate": locate}
