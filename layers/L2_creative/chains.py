from __future__ import annotations

import logging
import json
import re
from pathlib import Path

import yaml

import re as _re
import shutil as _shutil

from config.settings import get_settings
from core.langfuse_client import observe
from core.parsers import parse_json_array, parse_json_object, VideoUnderstanding, AudioUnderstanding, parse_video_understanding
from core.dreaming_scheduler import read_generation_memory
from integrations.llm_client import get_deepseek, get_glm, call_glm4v_multi
from layers.L2_creative.style_engine import StyleTemplate
from layers.L2_creative.character_manager import CharacterProfile

log = logging.getLogger(__name__)


@observe(name="lobster_creative", as_type="generation")
async def lobster_creative(theme: str, style: StyleTemplate, extra_context: str = "") -> str:
    log.info("[创意链] theme=%s style=%s", theme, style.name)
    memory_context = read_generation_memory()
    merged_context = "\n\n".join(x for x in [extra_context, f"长期运营记忆：\n{memory_context}"] if x)
    system_prompt = (
        f"{style.system_prompt(merged_context)}\n\n"
        "你是一位短视频解说/旁白文案高手，擅长写抖音爆款图文混剪类文案。\n\n"
        "你的任务：基于上述风格档案，围绕给定主题，生成5条不同角度的解说稿方案。\n\n"
        "每条解说稿要求：\n"
        "1. hook（前3秒开场）：必须制造认知冲突或情感冲击，让观众停下来\n"
        "2. narration（解说正文）：口语化、信息密度高、节奏感强，像真人在讲\n"
        "3. scenes（配图描述列表）：3-6个画面，每个画面对应一段旁白，描述AI文生图应生成什么画面\n"
        "4. cta（结尾引导）：引发评论/关注的话术\n"
        "5. tags：5-8个话题标签\n\n"
        "输出5条JSON数组，每条含：\n"
        "- angle: 切入角度（一句话概括）\n"
        "- hook: 前3秒文案\n"
        "- narration: 完整解说稿（200-400字）\n"
        "- scenes: [{\"scene_no\": 1, \"image_desc\": \"配图描述\", \"narration_segment\": \"对应旁白片段\"}]\n"
        "- cta: 结尾引导语\n"
        "- tags: 话题标签列表\n\n"
        "重要：文案要像真人写的，不要AI味。多用短句、反问、数字、对比。"
    )
    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"主题：{theme}"},
        ],
        max_tokens=4000,
    )
    result = resp.choices[0].message.content
    log.info("[创意链] 返回%d字", len(result))
    return result


@observe(name="lobster_review", as_type="generation")
def lobster_review(ideas: str, style: StyleTemplate) -> str:
    log.info("[审核链] GLM审核")
    cfg = get_settings()
    system_prompt = (
        f"{style.system_prompt()}\n\n"
        "你是短视频内容审核专家，擅长判断哪种解说稿最有爆款潜力。\n\n"
        "你的任务：从以下解说稿方案中，挑出最有爆款潜力的3条。\n\n"
        "评估维度：\n"
        "1. Hook 吸引力（前3秒能否留住人）\n"
        "2. 信息密度（观众能否获得价值感）\n"
        "3. 情感共鸣（能否引发评论/转发）\n"
        "4. 配图可行性（AI文生图能否生成匹配画面）\n"
        "5. 争议性/讨论度（评论区是否会炸）\n\n"
        "输出JSON数组，每条含：\n"
        "- rank: 排名\n"
        "- angle: 切入角度\n"
        "- hook: 开场文案\n"
        "- narration: 完整解说稿\n"
        "- scenes: 配图描述列表\n"
        "- tags: 话题标签\n"
        "- score: 爆款潜力评分（1-10）\n"
        "- reason: 推荐理由（一句话）"
    )
    resp = get_glm().chat.completions.create(
        model=cfg.glm_model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": ideas},
        ],
    )
    result = resp.choices[0].message.content
    log.info("[审核链] 返回%d字", len(result))
    return result


@observe(name="lobster_reference", as_type="generation")
async def lobster_reference(reference_info: str, style: StyleTemplate) -> str:
    log.info("[参考链] 改编，参考长度=%d", len(reference_info))
    system_prompt = (
        f"{style.system_prompt()}\n\n"
        "你的任务：解构参考内容的爆款结构，改编为符合风格档案的解说稿。\n\n"
        "工作步骤：\n"
        "1. 提炼参考内容的「开场钩子」「核心信息/观点」「结尾引导」\n"
        "2. 保留该叙事结构，用自己的语言重新组织内容\n"
        "3. 严格复刻参考内容的节奏和爆款逻辑，不要另起炉灶\n\n"
        "输出3条JSON数组，每条含：\n"
        "- angle: 切入角度\n"
        "- hook: 前3秒文案\n"
        "- narration: 完整解说稿（200-400字）\n"
        "- scenes: [{\"scene_no\": 1, \"image_desc\": \"配图描述\", \"narration_segment\": \"对应旁白\"}]\n"
        "- tags: 话题标签\n"
        "- adapt_reason: 说明如何复刻了原内容的爆款逻辑"
    )
    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"参考内容：\n{reference_info}"},
        ],
        max_tokens=3000,
    )
    result = resp.choices[0].message.content
    log.info("[参考链] 返回%d字", len(result))
    return result


@observe(name="lobster_baogai", as_type="generation")
async def lobster_baogai(source_info: str, style: StyleTemplate) -> str:
    log.info("[爆改链] 开始，素材长度=%d", len(source_info))
    system_prompt = (
        f"{style.system_prompt()}\n\n"
        "你的任务：「爆改」——基于原素材进行深度二次创作，不是简单换皮。\n\n"
        "爆改规则：\n"
        "1. 【提取核心】：原内容的核心信息/观点/故事是什么\n"
        "2. 【换角度重写】：用完全不同的切入角度重新阐述同一主题\n"
        "3. 【升级表达】：比原内容更有信息密度、更有节奏感、更能引发讨论\n"
        "4. 【配图重构】：根据新文案重新设计配图场景，不照搬原画面\n"
        "5. 【保留精华】：保留原内容中最有价值的数据/案例/金句\n\n"
        "输出3条爆改方案的JSON数组，每条含：\n"
        "- angle: 爆改切入角度\n"
        "- hook: 前3秒文案\n"
        "- narration: 完整解说稿（200-400字）\n"
        "- scenes: [{\"scene_no\": 1, \"image_desc\": \"配图描述\", \"narration_segment\": \"对应旁白\"}]\n"
        "- tags: 话题标签\n"
        "- baogai_diff: 与原内容的核心差异点（一句话）"
    )
    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"原始素材：\n{source_info}"},
        ],
        max_tokens=3000,
    )
    result = resp.choices[0].message.content
    log.info("[爆改链] 返回%d字", len(result))
    return result


@observe(name="lobster_evaluate", as_type="generation")
async def lobster_evaluate(scripts: str) -> dict:
    log.info("[评估链] 开始评估")
    cfg = get_settings()
    system_prompt = (
        "你是短视频解说类内容的制作规格评估专家。\n\n"
        "任务：分析给定的解说稿方案，为每条方案规划视频制作规格。\n\n"
        "评估维度（解说类/图文混剪标准）：\n"
        "1. 旁白节奏：解说稿有几个信息段落？每段配一个画面\n"
        "2. 分段建议：根据 scenes 列表拆分片段，每段3-10秒\n"
        "   - 信息密集段（数据/事实）→ 3-5秒配图+快切\n"
        "   - 情感/氛围段 → 5-8秒配图+缓动\n"
        "   - 开场Hook → 3-5秒（最关键的画面）\n"
        "3. 总时长建议：解说类最优区间 20-45秒\n"
        "4. 画质建议：standard（图文混剪足够）或 pro（关键封面帧）\n\n"
        "输出严格的JSON，格式：\n"
        "{\n"
        '  "plans": [\n'
        "    {\n"
        '      "script_index": 1,\n'
        '      "angle": "切入角度",\n'
        '      "total_duration_sec": 25,\n'
        '      "clips": [\n'
        '        {"clip_no": 1, "duration_sec": 5, "scene_summary": "配图场景简述", "narration_segment": "对应旁白", "reason": "时长理由"}\n'
        "      ],\n"
        '      "quality": "standard",\n'
        '      "quality_reason": "画质理由"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "只输出JSON，不要其他文字。"
    )
    resp = await get_deepseek().chat.completions.create(
        model=cfg.deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": scripts},
        ],
        max_tokens=3200,
    )
    raw = resp.choices[0].message.content.strip()
    log.info("[评估龙虾] 原始返回: %s", raw[:200])
    parsed = parse_json_object(raw)
    plans = parsed.get("plans", []) if isinstance(parsed, dict) else []
    if plans:
        return parsed

    log.warning("[评估龙虾] 首次解析失败，启动精简重试")
    retry_user = (
        "你上一次返回的 JSON 被截断了。现在不要重复长文解释，只输出更短、更紧凑的严格 JSON。\n\n"
        "要求：\n"
        "1. 只保留 3 条最佳方案\n"
        "2. 每条方案最多 4 个 clips\n"
        "3. reason / quality_reason 控制在 12 个字以内\n"
        "4. 只输出完整 JSON，不要 markdown 代码块\n\n"
        f"原始解说稿方案如下：\n{scripts}"
    )
    retry_resp = await get_deepseek().chat.completions.create(
        model=cfg.deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": retry_user},
        ],
        max_tokens=2200,
    )
    retry_raw = retry_resp.choices[0].message.content.strip()
    log.info("[评估龙虾] 重试返回: %s", retry_raw[:200])
    retry_parsed = parse_json_object(retry_raw)
    retry_plans = retry_parsed.get("plans", []) if isinstance(retry_parsed, dict) else []
    if retry_plans:
        return retry_parsed

    raise RuntimeError("评估链返回被截断，未解析出可用方案")


def format_evaluation(evaluation: dict) -> tuple[str, float]:
    cfg = get_settings()
    plans = evaluation.get("plans", [])
    lines = ["解说视频制作方案\n"]
    total_cost = 0.0
    total_clips = 0

    for p in plans:
        clips = p.get("clips", [])
        clip_cost = sum(
            cfg.kling_cost_10s if c["duration_sec"] >= 10 else cfg.kling_cost_5s
            for c in clips
        )
        total_cost += clip_cost
        total_clips += len(clips)

        angle = p.get("angle", p.get("operator", ""))
        lines.append(
            f"== 方案{p['script_index']}：{angle} "
            f"（总时长 {p['total_duration_sec']}秒）"
        )
        for c in clips:
            narration = c.get("narration_segment", "")
            narration_preview = f" | 旁白：{narration[:30]}..." if narration else ""
            lines.append(
                f"  片段{c['clip_no']}：{c['duration_sec']}秒 | {c['scene_summary']}"
                f"{narration_preview}"
                f"\n        - {c['reason']}"
            )
        lines.append(
            f"  画质：{p['quality']} | 原因：{p.get('quality_reason', '')}"
            f"\n  费用：¥{clip_cost:.2f}（{len(clips)}段）\n"
        )

    lines.append(f"共 {len(plans)} 条方案 / {total_clips} 段配图片段")
    lines.append(f"预估总费用：¥{total_cost:.2f}")
    lines.append(f"\n发「确认」开始一键生成推荐方案")
    lines.append(f"也可发「确认 2」或「确认 3」指定生成方案")

    return "\n".join(lines), total_cost


def _load_shot_template(style_name: str) -> list[dict]:
    """加载对应垂类的分镜模板，返回 shots 列表。无匹配时返回默认4镜模板。"""
    cfg = get_settings()
    shot_dir = Path(cfg.style_templates_dir).parent / "shot_templates"
    shot_file = shot_dir / f"{style_name}.yaml"

    # 垂类映射（knowledge_explainer 和 hot_blooded/cyberpunk 使用相近模板）
    _fallback_map = {
        "knowledge_explainer": "curiosity_facts",
        "hot_blooded": "cute_healing",
        "cyberpunk_military": "cute_healing",
        "funny_comedy": "cute_healing",
    }

    if not shot_file.exists():
        fallback_name = _fallback_map.get(style_name, "social_insight")
        shot_file = shot_dir / f"{fallback_name}.yaml"

    if shot_file.exists():
        with open(shot_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("shots", [])

    # 硬编码默认4镜（防止模板文件缺失时崩溃）
    return [
        {"shot_no": i, "duration_sec": 5,
         "camera_control": {"type": "push_in", "config": {"horizontal": 0, "vertical": 0, "zoom": 3}},
         "prompt_hint": "cinematic shot"}
        for i in range(1, 5)
    ]


def get_shot_template(style_name: str) -> list[dict]:
    """Public wrapper used by the runtime pipeline to apply stable shot controls."""
    return _load_shot_template(style_name)


@observe(name="lobster_visual", as_type="generation")
async def lobster_visual(
    selected: str,
    style: StyleTemplate,
    character: CharacterProfile | None = None,
) -> str:
    """生成多镜头配图提示词（修复硬伤2：分镜分发，不再一镜到底）。"""
    log.info("[视觉链] 多镜头生成 (垂类=%s 角色=%s)", style.name, character.display_name if character else "无")

    shots = _load_shot_template(style.name)
    shot_desc = "\n".join(
        f"  镜头{s['shot_no']}（{s.get('label', '')} {s['duration_sec']}秒）: "
        f"{s.get('prompt_hint', '')} | camera_control={json.dumps(s.get('camera_control', {}), ensure_ascii=False)}"
        for s in shots
    )

    character_instruction = ""
    if character:
        character_instruction = (
            f"\n\n=== 角色形象（如画面需要人物，必须遵守）===\n"
            f"角色名：{character.display_name}\n"
            f"外观描述：{character.description}\n"
            f"视觉标签：{character.visual_tags}\n"
            f"=== 角色形象结束 ===\n"
        )

    system_prompt = (
        f"{style.system_prompt()}\n\n"
        f"{character_instruction}\n\n"
        "你的任务：为这条解说稿生成【多镜头】配图和视频提示词。\n\n"
        "⚠️ 重要：必须严格按照以下分镜结构输出，每个镜头对应一段画面：\n\n"
        f"{shot_desc}\n\n"
        "解说类视频的配图原则：\n"
        "1. 每个镜头配图必须与对应旁白段落强相关\n"
        "2. 镜头间画面要有变化（景别/角度/内容），不要全是同一构图\n"
        "3. 画面风格统一，符合风格档案\n"
        "4. camera_control 必须逐字复制上方分镜结构里的值，不要改类型和数值\n\n"
        "输出严格JSON对象（不要代码围栏）：\n"
        "{\n"
        '  "shots": [\n'
        '    {"shot_no": 1, "image_prompt": "英文配图描述,≤50词", "kling_prompt": "英文动态描述,≤20词", "camera_control": {"type": "push_in", "config": {"horizontal": 0, "vertical": 0, "zoom": 5}}, "narration_segment": "对应中文旁白"}\n'
        "  ],\n"
        '  "captions": ["字幕1", "字幕2", ...],\n'
        '  "tags": ["tag1", ...]\n'
        "}"
    )
    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": selected},
        ],
        max_tokens=2500,
    )
    result = resp.choices[0].message.content
    log.info("[视觉链] 多镜头返回%d字", len(result))
    return result


_FFMPEG_FALLBACK_PATHS = [
    "ffmpeg",
    r"D:\oopz\ffmpeg.exe",
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
]


def _find_ffmpeg() -> str:
    """找到可用的 ffmpeg 可执行文件路径。"""
    for path in _FFMPEG_FALLBACK_PATHS:
        if _shutil.which(path) or (path != "ffmpeg" and Path(path).is_file()):
            return path
    raise RuntimeError(
        "找不到 ffmpeg，请安装后加入 PATH，或将路径加入 _FFMPEG_FALLBACK_PATHS"
    )


def _parse_duration_from_ffmpeg_stderr(stderr: str) -> float:
    """从 ffmpeg -i 的 stderr 输出中解析视频时长，单位秒。"""
    m = _re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", stderr)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mn * 60 + s
    return 30.0  # 解析失败时默认 30 秒


_VLM_UNDERSTAND_PROMPT_TMPL = """\
以下是一段短视频均匀抽取的 {n} 帧画面（按时间顺序排列，第1帧最早，第{n}帧最晚）。

【关键提示】先判断视频类型再描述动作：
- 若画面中人物有明显肢体律动（手臂挥舞/身体扭动/步伐节奏感/舞蹈姿势），类型必须是"跳舞"
- 若人物在连续说话/展示产品，类型是"Vlog/解说"
- 若人物在准备/食用食物，类型是"吃播"
- 多帧连续动作代表视频节奏，不要把舞蹈动作描述成"站立/摆姿势"

请输出以下 JSON，不要输出其他内容：
{{
  "video_type": "视频类型，从以下选一个：跳舞/唱歌/吃播/Vlog/穿搭/健身/美妆/解说/剧情/其他",
  "character_appearance": "主要角色外观（发色/发型/服装/体态），精确描述，中文",
  "sub_type": "细分子类型。跳舞类必填以下之一：热舞/街舞/古典舞/抒情舞/民族舞/芭蕾/宅舞/爵士舞/韩团舞；非跳舞类可填空字符串",
  "energy_level": "动作强度等级，从「极低/低/中/高/极高」选一个。判断依据：肢体动作幅度、身体起伏、镜头切换频率",
  "core_action": "核心动作，必须反映 video_type 和 sub_type。热舞示例：「腰胯扭动、手臂大幅挥舞、有起伏律动」。古典舞示例：「水袖飘动、兰花指、缓步移形」。禁止用"优雅展现/姿态展示"这种弱化描述带过激烈动作",
  "movement_rhythm": "动作节奏感（快速/缓慢/节奏性律动/静态展示等），用于推断 BGM 节奏",
  "setting": "主要场景环境，如「室内客厅，简约风，暖光」",
  "emotion": "整体情绪基调。热舞类应是「性感火辣/活力炸裂」，古典舞类才用「优雅抒情」，禁止张冠李戴",
  "key_message": "一句话概括（改编基础，必须准确反映 video_type 和 sub_type，不允许弱化或张冠李戴）"
}}

【特别注意：跳舞类型识别避免误判】
- 服装是运动背心/紧身衣 + 动作有腰胯扭动 → 是「热舞」，sub_type 填"热舞"，emotion 不能写"优雅"
- 服装是汉服/古装 + 水袖/兰花指 → 才是「古典舞」
- 服装是宽松街头风 + 锁舞/震感 → 是「街舞」
- 服装是芭蕾紧身衣 + 立足尖 → 才是「芭蕾/抒情舞」
- 不要因为单帧定格姿势看似"静止优雅"就判定为抒情类——多帧间的位移和姿态变化才反映真实强度

只输出 JSON，不要 markdown 代码围栏。"""


async def analyze_video_with_vlm(
    video_path: str | Path,
    num_frames: int = 6,
) -> VideoUnderstanding:
    """均匀抽取多帧后全部发给 GLM-4V，获得对视频完整内容的理解（修复硬伤1）。

    num_frames=6：默认抽6帧，覆盖视频开头/中段/结尾，足以理解叙事弧线。
    抽帧用 FFmpeg，帧图写入临时目录，分析完自动清理。
    """
    import tempfile, shutil, asyncio as _asyncio
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="vlm_frames_"))
    try:
        out_pattern = str(tmp_dir / "frame_%02d.jpg")

        # 找可用的 ffmpeg 可执行文件
        ffmpeg_bin = _find_ffmpeg()

        # 用 ffmpeg -i 解析时长（兼容没有 ffprobe 的环境）
        probe = await _asyncio.create_subprocess_exec(
            ffmpeg_bin, "-i", str(video_path),
            stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.PIPE,
        )
        _, stderr_bytes = await probe.communicate()
        duration = _parse_duration_from_ffmpeg_stderr(stderr_bytes.decode(errors="replace"))

        # 计算抽帧间隔，保证首尾都有帧
        interval = max(duration / num_frames, 0.5)
        fps_filter = f"fps=1/{interval:.2f}"

        proc = await _asyncio.create_subprocess_exec(
            ffmpeg_bin, "-y", "-i", str(video_path),
            "-vf", f"{fps_filter},scale=720:-2",
            "-frames:v", str(num_frames),
            "-q:v", "3",
            out_pattern,
            stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        frame_files = sorted(tmp_dir.glob("frame_*.jpg"))
        if not frame_files:
            raise RuntimeError(f"FFmpeg 抽帧失败，未生成任何帧：{video_path}")

        log.info("[VLM] 抽帧完成: %d 帧 (视频时长=%.1fs, 间隔=%.1fs)", len(frame_files), duration, interval)

        prompt = _VLM_UNDERSTAND_PROMPT_TMPL.format(n=len(frame_files))
        raw = call_glm4v_multi(frame_files, prompt)
        understanding = parse_video_understanding(raw)

        log.info(
            "[VLM理解] type=%s/%s energy=%s | character=%s | action=%s | key_message=%s",
            understanding.video_type,
            understanding.sub_type or "-",
            understanding.energy_level or "-",
            understanding.character_appearance[:25],
            understanding.core_action[:25],
            understanding.key_message[:30],
        )
        return understanding
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@observe(name="lobster_rewrite_vlm", as_type="generation")
async def lobster_rewrite_vlm(
    source_text: str,
    style: StyleTemplate,
    video_path: str | Path | None = None,
    understanding: VideoUnderstanding | None = None,
    audio: AudioUnderstanding | None = None,
    character_name: str = "",
) -> str:
    """改编链 VLM 版：理解原视频类型 → 为指定角色创作同类型内容。

    发什么类型的视频就改编什么类型：
    - 跳舞视频 → 角色跳舞的脚本
    - 吃播视频 → 角色吃播的脚本
    - Vlog → 角色同类 Vlog 脚本
    - 解说视频 → 角色解说同类话题的脚本

    不套用风格模板的 system_prompt，完全由 VLM 理解结果驱动。
    """
    log.info("[改写VLM] 开始，有视频=%s, 角色=%s", bool(video_path or understanding), character_name)

    if understanding is None and video_path:
        understanding = await analyze_video_with_vlm(video_path)

    if understanding is None:
        log.warning("[改写VLM] 无视频/理解结果，降级为普通改写")
        return await lobster_rewrite(source_text, style)

    char_label = f"角色「{character_name}」" if character_name else "我的角色"

    video_type = understanding.video_type or "其他"
    sub_type = understanding.sub_type or ""
    energy = understanding.energy_level or ""

    locked_label = f"{video_type}·{sub_type}" if sub_type else video_type

    # 构造 BGM/音频信息块（若可用），加入 prompt 帮助节奏对齐
    audio_block = ""
    if audio and audio.has_audio:
        audio_block = (
            f"\n【原视频 BGM/音频实测】（重要，用于校准节奏与方案风格）\n"
            f"  BPM：{audio.bpm}（节奏档：{audio.tempo_label}）\n"
            f"  能量：{audio.energy_db} dB\n"
            f"  人声：{'有（已转写）' if audio.has_vocals else '纯 BGM 无歌词'}\n"
        )
        if audio.has_vocals and audio.lyrics_excerpt:
            audio_block += f"  歌词/语音节选：{audio.lyrics_excerpt[:120]}\n"
            audio_block += f"  语言：{audio.language or '未知'}\n"
        audio_block += (
            f"  → 校准规则：BPM≥120 必须是「快节奏热舞/街舞/电音」类风格；"
            f"BPM<80 才允许「抒情慢舞/柔美」；"
            f"如果实测节奏与画面识别的子类型矛盾（例如画面识别为抒情但 BPM=130），"
            f"以 BPM 为准，把 sub_type 修正为快节奏舞种。\n"
        )
    elif audio and not audio.has_audio:
        audio_block = "\n【原视频音频】无音轨（纯画面），节奏完全由画面动作决定\n"

    system_prompt = (
        f"你是一个短视频内容创作者。\n\n"
        f"【最高级锁定】原视频是「{locked_label}」类型，能量等级「{energy}」。\n"
        f"  - 输出的 3 个方案必须**全部**是「{locked_label}」，禁止出现任何其他子类型\n"
        f"  - 严禁把热舞改成抒情舞/古典舞/国风舞；严禁把街舞改成芭蕾；反之亦然\n"
        f"  - 严禁出现「水袖」「兰花指」「水墨」「禅意」「下午茶」「穿搭」等跨类型词汇，除非原视频本身是该子类型\n\n"
        f"【任务】基于对原视频的理解，为{char_label}创作 3 个「{locked_label}」短视频脚本。\n\n"
        f"【3 个方案的差异化方式】\n"
        f"  3 个方案是**同一种「{locked_label}」**的不同呈现，差异**只能**来自下列维度，不能改变舞种/类型：\n"
        f"  - 镜头景别（全身远景 / 半身中景 / 特写局部）\n"
        f"  - 拍摄机位/视角（正面平视 / 俯拍 / 侧面跟拍 / 第一视角）\n"
        f"  - 滤镜/色调（高饱和霓虹 / 冷调电影感 / 暖调日落）\n"
        f"  - 节奏切点（卡每个 beat 切换 / 4 拍一切 / 长镜头一镜到底）\n"
        f"  - 场景搭建（同一{locked_label}舞种放在不同环境：练功房 / 街头 / 舞台 / 卧室）\n\n"
        f"【硬性禁止】\n"
        f"- 禁止把任何视频改成「解说/旁白讲述」风格，除非原视频本身就是解说\n"
        f"- 跳舞类不准生成穿搭展示/下午茶/自拍日常等与跳舞无关的方案\n"
        f"- scenes 的 image_desc 必须是具体画面（动作+表情+环境），且舞蹈动作必须是「{locked_label}」典型动作\n\n"
        f"【原视频分析结果】\n"
        f"  类型/子类型：{locked_label}\n"
        f"  能量等级：{energy}\n"
        f"  核心行为：{understanding.core_action}\n"
        f"  动作节奏：{understanding.movement_rhythm}\n"
        f"  场景：{understanding.setting}\n"
        f"  情绪：{understanding.emotion}\n"
        f"  核心信息：{understanding.key_message}\n"
        f"{audio_block}\n"
        f"输出 3 个方案的 JSON 数组，每条包含：\n"
        f'- "angle": 本方案的差异化角度（必须以镜头/机位/滤镜/节奏切点/场景为差异点，禁止以舞种为差异点）\n'
        f'- "hook": 前3秒的画面钩子（视觉描述，不是台词）\n'
        f'- "narration": 台词或旁白（纯视觉舞蹈类填空字符串）\n'
        f'- "scenes": [{{"scene_no":1,"image_desc":"具体画面，含{char_label}的{locked_label}动作和表情","narration_segment":"","duration_sec":5}}]\n'
        f'- "tags": 话题标签列表\n'
        f'- "content_type": 必须填："{locked_label}"'
    )

    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"请为{char_label}创作 3 个「{locked_label}」（能量等级「{energy}」）的视频脚本。\n"
                f"原视频核心动作：{understanding.core_action}\n"
                f"动作节奏：{understanding.movement_rhythm}\n"
                f"情绪基调：{understanding.emotion}\n\n"
                f"再次强调：3 个方案必须全部是「{locked_label}」，差异只来自镜头/机位/滤镜/节奏切点/场景，禁止跨子类型。"
            )},
        ],
        max_tokens=3000,
    )
    result = resp.choices[0].message.content
    audio_tag = (
        f"BPM={audio.bpm}({audio.tempo_label}) 人声={'有' if audio.has_vocals else '无'}"
        if audio and audio.has_audio else ("无音轨" if audio else "未分析")
    )
    log.info("[改写VLM] 类型=%s 能量=%s 音频=[%s] 返回%d字", locked_label, energy, audio_tag, len(result))
    return result


@observe(name="lobster_rewrite", as_type="generation")
async def lobster_rewrite(source_text: str, style: StyleTemplate) -> str:
    log.info("[改写链] 开始，素材长度=%d", len(source_text))
    system_prompt = (
        f"{style.system_prompt()}\n\n"
        "你的任务：基于原文进行「真正的改写」——不是换皮，而是深度二创。\n\n"
        "改写规则：\n"
        "1. 【信息提取】：从原文中提取核心事实、数据、案例\n"
        "2. 【角度创新】：用原文没有的切入角度重新组织叙述\n"
        "3. 【表达升级】：口语化、短句化、适合短视频朗读\n"
        "4. 【增加价值】：补充原文没提到的背景知识或延伸观点\n"
        "5. 【Hook 强化】：开头必须比原文更抓人\n\n"
        "输出3条改写方案的JSON数组，每条含：\n"
        "- angle: 改写切入角度\n"
        "- hook: 前3秒文案\n"
        "- narration: 完整解说稿（200-400字）\n"
        "- scenes: [{\"scene_no\": 1, \"image_desc\": \"配图描述\", \"narration_segment\": \"对应旁白\"}]\n"
        "- tags: 话题标签\n"
        "- rewrite_strategy: 改写策略说明（一句话）"
    )
    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"原文：\n{source_text}"},
        ],
        max_tokens=3000,
    )
    result = resp.choices[0].message.content
    log.info("[改写链] 返回%d字", len(result))
    return result


# ── 垂类快捷创意（解说/科普/故事/奇闻/观点）──

VERTICAL_PROMPTS: dict[str, str] = {
    "hot_news_commentary": (
        "你现在是热搜解说博主。请围绕以下话题写一篇短视频解说稿：\n"
        "要求：信息密度高、节奏快、有观点输出、数据说话。\n"
        "语气：沉稳专业但不枯燥，像一个见多识广的朋友在跟你聊新闻。"
    ),
    "knowledge_explainer": (
        "你现在是知识科普博主。请围绕以下主题写一篇科普解说稿：\n"
        "要求：用通俗语言讲清楚、有反常识的信息、让观众觉得涨知识了。\n"
        "语气：知性但亲切，像一个学霸朋友在给你讲有趣的事。"
    ),
    "emotional_story": (
        "你现在是情感故事博主。请围绕以下主题写一篇情感故事稿：\n"
        "要求：触动人心、有细节、有画面感、让人想转发。\n"
        "语气：温柔舒缓，像深夜电台主播在讲一个故事。"
    ),
    "curiosity_facts": (
        "你现在是奇闻猎奇博主。请围绕以下话题写一篇猎奇解说稿：\n"
        "要求：制造好奇心、悬念层层递进、信息震撼。\n"
        "语气：神秘感十足，像在讲一个不可思议的发现。"
    ),
    "social_insight": (
        "你现在是社会观察博主。请围绕以下话题写一篇观点输出稿：\n"
        "要求：观点鲜明犀利、引发讨论、有真实案例支撑。\n"
        "语气：直白犀利但理性，像一个敢说真话的朋友。"
    ),
}


@observe(name="lobster_vertical", as_type="generation")
async def lobster_vertical(
    theme: str, style: StyleTemplate, vertical_key: str | None = None
) -> str:
    log.info("[垂类链] theme=%s style=%s vertical=%s", theme, style.name, vertical_key)
    vertical_prompt = VERTICAL_PROMPTS.get(
        vertical_key or style.name,
        VERTICAL_PROMPTS.get("hot_news_commentary", ""),
    )
    memory_context = read_generation_memory()
    memory_block = f"长期运营记忆：\n{memory_context}"
    system_prompt = (
        f"{style.system_prompt(memory_block)}\n\n"
        f"{vertical_prompt}\n\n"
        "输出格式：3条JSON数组，每条含：\n"
        "- angle: 切入角度\n"
        "- hook: 前3秒文案\n"
        "- narration: 完整解说稿（200-400字）\n"
        "- scenes: [{\"scene_no\": 1, \"image_desc\": \"配图描述\", \"narration_segment\": \"对应旁白\"}]\n"
        "- cta: 结尾引导语\n"
        "- tags: 话题标签\n\n"
        "文案必须像真人写的，多用短句、反问、数字。"
    )
    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"主题：{theme}"},
        ],
        max_tokens=3000,
    )
    result = resp.choices[0].message.content
    log.info("[垂类链] 返回%d字", len(result))
    return result


@observe(name="lobster_operation", as_type="generation")
def lobster_operation(scripts: str) -> str:
    log.info("[运营链] 生成运营方案")
    cfg = get_settings()
    resp = get_glm().chat.completions.create(
        model=cfg.glm_model_id,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是短视频运营专家，擅长解说类/图文混剪类内容的运营。\n"
                    "为每条视频生成：\n"
                    "- title: 标题（≤15字，制造好奇心）\n"
                    "- tags: 话题标签（5-8个，含热搜相关）\n"
                    "- best_time: 发布时间建议（精确到小时）\n"
                    "- first_comment: 首条评论文案（引导讨论）\n"
                    "- description: 视频简介（≤50字）\n"
                    "输出JSON数组。"
                ),
            },
            {"role": "user", "content": scripts},
        ],
    )
    result = resp.choices[0].message.content
    log.info("[运营链] 返回%d字", len(result))
    return result


# ── 风格→配音映射 ──

STYLE_VOICE_MAP: dict[str, str] = {
    "hot_news_commentary": "narrator_male",
    "knowledge_explainer": "narrator_female_calm",
    "emotional_story": "su_wan",
    "curiosity_facts": "narrator_male",
    "social_insight": "narrator_male_sharp",
}


def get_voice_for_style(style_name: str) -> str:
    return STYLE_VOICE_MAP.get(style_name, "narrator_male")
