"""经验管理 + 标注 UI —— 从 app.py 拆分，减少主文件臃肿喵~

这些函数按 `app` 作为第一参数设计，通过类属性赋值变成 bound method：
    class RobocodeApp:
        _run_exp_manage = run_exp_manage  # self._run_exp_manage() → run_exp_manage(self)
"""

import asyncio
import sys


def _merge_bullets_replace(
    existing: list[str], new: list[str], threshold: float = 0.55
) -> tuple[list[str], bool]:
    """合并 new bullets 入 existing，相似则替换，不相似则追加喵~

    相似度 > 75%: 直接替换（高置信）
    相似度 55%-75%: 保留旧 bullet 并标记待确认（冲突检测）
    相似度 < 55%: 追加为新 bullet

    Returns: (merged_bullets, has_pending_review)
    """
    import difflib

    replaced = set()
    merged = list(existing)
    has_pending = False

    for nb in new:
        best_idx = -1
        best_ratio = 0.0
        for i, eb in enumerate(merged):
            if i in replaced:
                continue
            ratio = difflib.SequenceMatcher(None, nb, eb).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = i

        if best_ratio > 0.75 and best_idx >= 0:
            merged[best_idx] = nb
            replaced.add(best_idx)
        elif best_ratio > threshold and best_idx >= 0:
            has_pending = True
            marker = (
                nb.replace("- [", "- [待确认|", 1) if nb.startswith("- [") else f"- [待确认] {nb}"
            )
            merged.append(marker)
        else:
            merged.append(nb)

    return merged, has_pending


async def _prompt_annotation_after_task(app, pending_count: int):
    """任务完成后提示标注喵~"""
    app.console.print(
        f"\n[dim]任务完成。标注本轮 {pending_count} 个操作？"
        f"[[green]Y[/green]/n/[[green]Enter[/green]][/dim] "
    )
    loop = asyncio.get_running_loop()
    try:
        ch = await loop.run_in_executor(None, sys.stdin.read, 1)
        if ch.lower() in ("y", "\n", "\r"):
            await app._run_annotation_panel()
        else:
            app.console.print("[dim]跳过标注（稍后可用 /done 标注）[/dim]")
    except Exception:
        pass


async def _run_annotation_panel(app):
    """启动标注面板喵~"""
    from robocode.cli.annotation_panel import AnnotationPanel

    panel = AnnotationPanel(
        app.annotation_collector,
        console=app.console,
        experience_reader=app.experience_reader,
    )
    results, chat_feedback = await panel.run()

    if results:
        failures = AnnotationPanel.get_failure_summary(results)
        if failures:
            for f in failures:
                app.agent.inject_failure_annotation(
                    f["tool_name"],
                    [f["failed_dimensions"]],
                )
            app.console.print(
                f"[yellow]⚠ {len(failures)} 个操作标注为失败，反馈已注入会话[/yellow]"
            )
        total = len(results)
        app.console.print(f"[green]✅ {total} 条已标注[/green]")
        await app._run_exp_manage()
        await app._apply_confidence_feedback(results)
    elif chat_feedback:
        app._chat_feedback = chat_feedback
        app.console.print("[green]✅ 反馈已记录[/green]")
        await app._run_exp_manage()


async def _apply_confidence_feedback(app, results):
    """根据标注结果调整经验置信度喵~"""
    from robocode.agent.experience_manager import ExperienceManager

    if not app.experience_reader or not app.experience_reader.has_experiences():
        return

    mgr = ExperienceManager(db=app.db, session_id=app._session_id)
    visible = app.experience_reader.get_visible_experiences()

    cat_adj = {}
    for r in results:
        cat = r.category
        if cat not in cat_adj:
            cat_adj[cat] = 0.0
        cat_adj[cat] += -0.05 if r.is_failure else 0.03

    updated = 0
    for exp in visible:
        exp_cat = exp.get("category", "")
        if exp_cat not in cat_adj:
            continue
        filename = exp.get("filename", "")
        if not filename:
            continue
        delta = min(0.1, max(-0.15, round(cat_adj[exp_cat], 2)))
        if abs(delta) < 0.01:
            continue
        new_conf = max(0.1, min(0.95, exp.get("confidence", 0.5) + delta))
        mgr.update_experience(
            exp_cat,
            filename,
            frontmatter_updates={"confidence": round(new_conf, 2)},
        )
        updated += 1

    if updated:
        app.console.print(f"[dim]🔄 {updated} 条经验置信度已更新[/dim]")


async def _run_exp_manage(app):
    """经验管家：采集 → LLM 反思 → 写入经验文件 → 合并/剪枝 → 重建索引喵~"""
    from robocode.agent.experience_manager import ExperienceManager
    from robocode.agent.reflector import Reflector, deduplicate_bullets
    from robocode.agent.experience_filesystem import (
        EXPERIENCE_ROOT,
        write_experience,
        rebuild_index,
        backup_before_update,
        _category_from_filename,
    )
    from robocode.agent.experience_reader import ExperienceReader

    mgr = ExperienceManager(db=app.db, session_id=app._session_id)

    app.console.print("[bold]经验管家运行中...[/bold]")

    # ── Step 1: 采集 ──
    transcript = app.agent.get_conversation_transcript()
    physics = mgr.analyze_physics()
    annotations = mgr.process_annotations()
    call_flows = mgr.analyze_call_flow()
    conv_analysis = ExperienceManager.analyze_conversation(transcript)

    all_feedback: list[str] = []
    if annotations:
        for cat_data in annotations.values():
            for ft in cat_data.get("free_texts", []):
                if ft and ft not in all_feedback:
                    all_feedback.append(ft)
    chat_fb = getattr(app, "_chat_feedback", "")
    if chat_fb and chat_fb not in all_feedback:
        all_feedback.append(chat_fb)
    app._chat_feedback = ""
    feedback = " | ".join(all_feedback)

    has_data = bool(transcript) or physics or annotations or call_flows or feedback

    index_path = EXPERIENCE_ROOT / "index.md"
    experience_index = ""
    if index_path.exists():
        experience_index = index_path.read_text(encoding="utf-8")

    # ── Step 2: LLM 反思 ──
    reflector_results: list[dict] = []
    if has_data:
        try:
            reflector = Reflector(provider=app.agent.provider, max_bullets=10)
            reflector_results = await reflector.reflect(
                transcript=transcript,
                physics=physics,
                annotations=annotations,
                call_flows=call_flows,
                conv_analysis=conv_analysis,
                experience_index=experience_index,
            )
            if reflector_results:
                app.console.print(f"[dim]💡 反思产出 {len(reflector_results)} 条洞察[/dim]")
        except Exception:
            app.console.print("[dim]⚠ LLM 反思失败，跳过反思层[/dim]")

    # ── 经验管家处理完成后保存数据到 .temp/exp-reflector/ 喵~ ──
    if has_data:
        import json as _json
        import time as _time
        from pathlib import Path as _Path

        dump_dir = _Path(".temp/exp-reflector")
        dump_dir.mkdir(parents=True, exist_ok=True)
        ts = _time.strftime("%Y%m%d_%H%M%S")
        dump_file = dump_dir / f"{ts}.json"

        dump_data = {
            "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S"),
            "transcript": transcript or [],
            "physics": physics,
            "annotations": annotations,
            "call_flows": call_flows,
            "conv_analysis": conv_analysis,
            "feedback": feedback,
            "experience_index_chars": len(experience_index),
            "reflector_results": reflector_results,
        }
        dump_file.write_text(_json.dumps(dump_data, ensure_ascii=False, indent=2), encoding="utf-8")
        app.console.print(f"[dim]📁 经验数据已保存到 {dump_file}[/dim]")

    # ── Step 3: 写入 ──
    if has_data:
        import time as _time

        date_str = _time.strftime("%Y-%m-%d")

        def _make_filename(bullets, fb, sid):
            for b in bullets:
                intent = b.get("intent", "")
                if intent:
                    slug = intent.replace(" ", "-").replace("/", "-")
                    return f"{slug}.md"
            if fb:
                words = fb[:20].replace(" ", "-").replace("，", "").replace("。", "")
                return f"{words}.md"
            sid_short = sid[:8] if sid else "unknown"
            return f"session-{date_str}-{sid_short}.md"

        filename = _make_filename(reflector_results, feedback, app._session_id)

        data_points = sum(cat_data.get("total", 0) for cat_data in (annotations or {}).values())
        data_points += sum(d.get("total_data_points", 0) for d in (physics or {}).values())
        confidence = 0.6

        body_parts = [f"# 会话经验 ({date_str})", ""]

        if feedback:
            body_parts.append("## 用户反馈")
            body_parts.append("")
            body_parts.append(feedback[:500])
            body_parts.append("")

        if physics:
            body_parts.append("## 物理规律")
            body_parts.append("")
            body_parts.extend(mgr._render_physics_data(physics))
            body_parts.append("")
            body_parts.append("## 数据支撑")
            body_parts.append("")
            body_parts.extend(mgr._render_data_table(physics))
            body_parts.append("")

        if annotations:
            body_parts.append("## 标注统计")
            body_parts.append("")
            for cat, cat_data in annotations.items():
                total = cat_data.get("total", 0)
                failures = len(cat_data.get("failures", []))
                successes = len(cat_data.get("successes", []))
                body_parts.append(f"- {cat}: 总{total} 成功{successes} 失败{failures}")
            body_parts.append("")

        if call_flows:
            body_parts.append("## 工具调用模式")
            body_parts.append("")
            body_parts.extend(mgr._render_call_flows(call_flows))
            body_parts.append("")

        if transcript:
            body_parts.append("## 关键事件（失败+修正路径）")
            body_parts.append("")
            seen_fail = set()
            for msg in transcript:
                role = msg.get("role", "")
                if role == "tool_result" and not msg.get("success", True):
                    short = msg.get("message", "")[:80]
                    if short not in seen_fail:
                        seen_fail.add(short)
                        body_parts.append(f"- ❌ {short}")
            last_success_tools = set()
            for msg in reversed(transcript):
                role = msg.get("role", "")
                if role == "tool_call":
                    tool = msg.get("tool", "")
                    if tool not in last_success_tools:
                        last_success_tools.add(tool)
                        body_parts.append(f"- ✅ {tool} 最终成功")
                if len(last_success_tools) >= 5:
                    break
            body_parts.append("")

        new_body = "\n".join(body_parts)

        update_groups: dict[str, list[str]] = {}
        new_bullets: list[str] = []

        for result in reflector_results:
            raw = result["raw"]
            target = result.get("update_target")
            if target:
                update_groups.setdefault(target, []).append(raw)
            else:
                new_bullets.append(raw)

        for target_name, bullets_to_add in update_groups.items():
            target_path = EXPERIENCE_ROOT / target_name
            if not target_path.exists():
                new_bullets.extend(bullets_to_add)
                continue

            existing_bullets = ExperienceManager.extract_existing_bullets(target_path)
            deduped = deduplicate_bullets(bullets_to_add, existing_bullets)

            if not deduped:
                app.console.print(f"  [dim]⊘ {target_name} 所有内容已存在，跳过[/dim]")
                continue

            merged_bullets, has_pending = _merge_bullets_replace(existing_bullets, deduped)

            existing_body = mgr._read_body(target_path)
            body_before_suggestions = existing_body
            if "## 建议" in existing_body:
                body_before_suggestions = existing_body.split("## 建议")[0].rstrip()
            updated_body = body_before_suggestions + "\n\n## 建议\n\n" + "\n".join(merged_bullets)

            existing_fm = mgr._read_frontmatter(target_path)
            old_dp = existing_fm.get("data_points", 0)
            old_conf = existing_fm.get("confidence", 0.5)
            existing_fm["data_points"] = old_dp + data_points
            existing_fm["confidence"] = min(round(old_conf + 0.03, 2), 0.95)
            existing_fm["updated"] = date_str

            if has_pending:
                existing_fm["pending_review"] = True

            # Merge new tags from incoming bullets into existing tags
            existing_tags: list[str] = existing_fm.get("tags", [])
            if isinstance(existing_tags, str):
                existing_tags = [
                    t.strip() for t in existing_tags.strip("[]").split(",") if t.strip()
                ]
            new_tags: set[str] = set()
            for b in bullets_to_add:
                if b.startswith("- [") and "]" in b:
                    for part in b[3:].split("]")[0].split("|"):
                        tag = part.strip()
                        if tag and tag not in existing_tags:
                            new_tags.add(tag)
            if new_tags:
                existing_fm["tags"] = existing_tags + sorted(new_tags)

            parts = target_name.split("/", 1)
            cat, fname = (parts[0], parts[1]) if len(parts) == 2 else ("general", parts[0])

            backup_before_update(cat, fname)
            write_experience(cat, fname, existing_fm, updated_body)
            app.db.insert_experience_log(
                "experience_updated",
                file_path=target_name,
                details={
                    "confidence": existing_fm["confidence"],
                    "data_points": existing_fm["data_points"],
                    "new_bullets": len(deduped),
                    "source": "llm_update_target",
                },
            )
            app.console.print(f"  [cyan]⊕[/cyan] {target_name} (更新 {len(deduped)} 条)")

        if new_bullets:
            new_body += "## 建议\n\n" + "\n".join(new_bullets) + "\n"

            # Derive description from first bullet's intent + content
            description = ""
            if new_bullets:
                first = new_bullets[0]
                if "] " in first:
                    description = first.split("] ", 1)[1].strip()[:80]

            # Extract tags from bullet intents
            tags: list[str] = []
            seen_tags: set[str] = set()
            for b in new_bullets:
                if b.startswith("- [") and "]" in b:
                    tag = b[3:].split("]")[0].split("|")[0].strip()
                    if tag and tag not in seen_tags:
                        tags.append(tag)
                        seen_tags.add(tag)

            frontmatter = {
                "type": "operational",
                "tags": tags,
                "confidence": confidence,
                "data_points": data_points,
                "sources": app._session_id,
                "created": date_str,
                "updated": date_str,
                "description": description,
            }

            cat = _category_from_filename(filename)
            write_experience(cat, filename, frontmatter, new_body)
            app.db.insert_experience_log(
                "experience_created",
                file_path=f"{cat}/{filename}",
                details={
                    "confidence": confidence,
                    "data_points": data_points,
                    "bullets": len(new_bullets),
                },
            )
            app.console.print(f"  [green]+[/green] {cat}/{filename} ({len(new_bullets)} 条新洞察)")

    # ── Step 4: 合并 + 剪枝 ──
    merged = mgr.merge_experiences()
    if merged:
        app.console.print(f"[dim]🔄 {merged} 组经验已合并[/dim]")
    pruned = mgr.prune_experiences()
    if pruned:
        app.console.print(f"[dim]🗑 {pruned} 条低置信度经验已归档[/dim]")

    # ── Step 5: 置信度衰减 + 回涨 ──
    _decay_and_reinforce(app)

    rebuild_index()
    if has_data:
        app.db.mark_physics_processed()
        app.db.mark_annotations_processed()
    app.experience_reader = ExperienceReader()
    app.agent._system_prompt = app.agent._build_system_prompt()

    # ── Step 6: 质量仪表盘 ──
    _print_quality_dashboard(app)

    app.console.print("[green]✅ 经验整理完成（已同步到当前会话）[/green]")


def _decay_and_reinforce(app):
    """置信度衰减 + 回涨：所有经验 -0.01，被使用过的经验 +0.02 回涨喵~"""
    from robocode.agent.experience_manager import ExperienceManager

    reader = app.experience_reader
    if reader is None or not reader.has_experiences():
        return

    used = reader.used_files
    mgr = ExperienceManager(db=app.db, session_id=app._session_id)
    visible = reader.get_visible_experiences(min_confidence=0.0)
    decayed = 0
    reinforced = 0

    for exp in visible:
        rel_path = exp.get("rel_path", "")
        cat = exp.get("category", "")
        fname = exp.get("filename", "")
        if not cat or not fname:
            continue

        old_conf = exp.get("confidence", 0.5)
        new_conf = old_conf - 0.01

        if rel_path in used:
            new_conf += 0.02
            reinforced += 1

        new_conf = max(0.1, min(0.95, round(new_conf, 2)))
        if abs(new_conf - old_conf) < 0.005:
            continue

        mgr.update_experience(cat, fname, frontmatter_updates={"confidence": new_conf})
        decayed += 1

    if decayed:
        app.console.print(
            f"[dim]📉 {decayed} 条经验置信度已调整"
            f"（{reinforced} 条回涨，{decayed - reinforced} 条衰减）[/dim]"
        )


def _print_quality_dashboard(app):
    """输出经验质量仪表盘喵~"""
    reader = app.experience_reader
    if reader is None or not reader.has_experiences():
        return

    visible = reader.get_visible_experiences(min_confidence=0.0)
    if not visible:
        return

    confs = [e.get("confidence", 0.5) for e in visible]
    avg_conf = sum(confs) / len(confs)
    max_conf = max(confs)
    min_conf = min(confs)

    tip_counts = {}
    for tool, tips in reader._tool_tips.items():
        if tips:
            tip_counts[tool] = len(tips)

    pending = sum(1 for e in visible if e.get("pending_review"))

    parts = [
        f"📊 经验质量: {len(visible)}个文件"
        f" | avg={avg_conf:.2f} max={max_conf:.2f} min={min_conf:.2f}"
    ]
    if pending:
        parts.append(f" | ⚠待确认={pending}")
    if tip_counts:
        top3 = sorted(tip_counts.items(), key=lambda x: -x[1])[:3]
        hits = " ".join(f"{t}={c}" for t, c in top3)
        parts.append(f" | tips: {hits}")

    app.console.print(f"[dim]{''.join(parts)}[/dim]")
