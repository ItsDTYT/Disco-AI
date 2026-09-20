import base64
import io
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import discord
import httpx
from PIL import Image, ImageSequence

logger = logging.getLogger("DiscoMedia")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi"}

MAX_IMAGE_DIMENSION = 1280
MAX_KEYFRAME_DIMENSION = 800
DEFAULT_VIDEO_SAMPLES = 5
DEFAULT_GIF_SAMPLES = 3


@dataclass(frozen=True)
class MediaPayload:
    visual_blocks: list[dict[str, Any]] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)

    @property
    def has_visuals(self) -> bool:
        return len(self.visual_blocks) > 0

    @property
    def summary_text(self) -> str:
        return "\n".join(self.descriptions)


def _safe_remove(path: str, retries: int = 3) -> None:
    for attempt in range(retries):
        try:
            if os.path.exists(path):
                os.remove(path)
            return
        except OSError:
            time.sleep(0.05 * (attempt + 1))


def encode_pil_image_to_base64_jpeg(
    img: Image.Image, max_dim: int = MAX_IMAGE_DIMENSION, quality: int = 85
) -> str:
    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / float(max(w, h))
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def extract_gif_frames(gif_bytes: bytes, max_frames: int = DEFAULT_GIF_SAMPLES) -> list[str]:
    frames_b64: list[str] = []
    try:
        with Image.open(io.BytesIO(gif_bytes)) as im:
            total_frames = getattr(im, "n_frames", 1)
            if total_frames <= 1:
                frames_b64.append(encode_pil_image_to_base64_jpeg(im, max_dim=MAX_KEYFRAME_DIMENSION))
                return frames_b64

            step = max(1, total_frames // max_frames)
            target_indices = [min(total_frames - 1, step * i) for i in range(max_frames)]

            for idx in target_indices:
                im.seek(idx)
                frames_b64.append(encode_pil_image_to_base64_jpeg(im, max_dim=MAX_KEYFRAME_DIMENSION))
    except (OSError, ValueError) as err:
        logger.warning("GIF frame extraction failed: %s", err)

    return frames_b64


def extract_frames_from_video_bytes(
    video_bytes: bytes, num_frames: int = DEFAULT_VIDEO_SAMPLES
) -> list[str]:
    frames_b64: list[str] = []
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(video_bytes)

        cap = cv2.VideoCapture(tmp_path)
        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                logger.warning("Video has 0 frames or invalid codec.")
                return []

            step = max(1, total_frames // (num_frames + 1))
            indices = [min(total_frames - 1, step * i) for i in range(1, num_frames + 1)]

            for idx in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                success, frame = cap.read()
                if success and frame is not None:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil_img = Image.fromarray(rgb)
                    b64_uri = encode_pil_image_to_base64_jpeg(
                        pil_img, max_dim=MAX_KEYFRAME_DIMENSION, quality=75
                    )
                    frames_b64.append(b64_uri)
        finally:
            cap.release()
    except (cv2.error, OSError, ValueError) as err:
        logger.error("Failed extracting video keyframes: %s", err)
    finally:
        _safe_remove(tmp_path)

    return frames_b64


async def process_discord_attachments(
    attachments: list[discord.Attachment],
) -> tuple[list[dict[str, Any]], list[str]]:
    blocks: list[dict[str, Any]] = []
    descriptions: list[str] = []

    for att in attachments:
        ext = os.path.splitext(att.filename.lower())[1]

        if ext == ".gif":
            try:
                raw_data = await att.read()
                frames = extract_gif_frames(raw_data, max_frames=DEFAULT_GIF_SAMPLES)
                for f_uri in frames:
                    blocks.append({"type": "image_url", "image_url": {"url": f_uri}})
                if frames:
                    descriptions.append(f"[Attached GIF: {att.filename} ({len(frames)} keyframe(s))]")
            except (discord.DiscordException, OSError) as err:
                logger.error("Error processing GIF attachment %s: %s", att.filename, err)

        elif ext in IMAGE_EXTENSIONS:
            try:
                raw_data = await att.read()
                with Image.open(io.BytesIO(raw_data)) as pil_img:
                    data_uri = encode_pil_image_to_base64_jpeg(pil_img)
                    blocks.append({"type": "image_url", "image_url": {"url": data_uri}})
                    descriptions.append(f"[Attached Image: {att.filename}]")
            except (Image.DecompressionBombError, OSError, ValueError, discord.DiscordException) as err:
                logger.error("Error processing image attachment %s: %s", att.filename, err)

        elif ext in VIDEO_EXTENSIONS:
            try:
                raw_data = await att.read()
                frames = extract_frames_from_video_bytes(raw_data, num_frames=DEFAULT_VIDEO_SAMPLES)
                for f_uri in frames:
                    blocks.append({"type": "image_url", "image_url": {"url": f_uri}})
                if frames:
                    descriptions.append(f"[Attached Video: {att.filename} ({len(frames)} keyframes sampled)]")
            except (discord.DiscordException, OSError) as err:
                logger.error("Error processing video attachment %s: %s", att.filename, err)

    return blocks, descriptions


async def process_discord_stickers(
    stickers: list[discord.StickerItem],
    client: httpx.AsyncClient,
) -> tuple[list[dict[str, Any]], list[str]]:
    blocks: list[dict[str, Any]] = []
    descriptions: list[str] = []

    for sticker in stickers:
        sticker_name = sticker.name
        descriptions.append(f"[Sent Sticker: {sticker_name}]")
        if not sticker.url:
            continue

        try:
            resp = await client.get(sticker.url, timeout=10.0)
            if resp.status_code == 200:
                raw_data = resp.content
                if sticker.format == discord.StickerFormatType.lottie:
                    continue
                if sticker.format == discord.StickerFormatType.gif:
                    frames = extract_gif_frames(raw_data, max_frames=2)
                    for f_uri in frames:
                        blocks.append({"type": "image_url", "image_url": {"url": f_uri}})
                else:
                    with Image.open(io.BytesIO(raw_data)) as img:
                        data_uri = encode_pil_image_to_base64_jpeg(img, max_dim=MAX_KEYFRAME_DIMENSION)
                        blocks.append({"type": "image_url", "image_url": {"url": data_uri}})
        except (httpx.HTTPError, OSError, ValueError) as err:
            logger.warning("Failed fetching sticker %s (%s): %s", sticker_name, sticker.url, err)

    return blocks, descriptions


async def process_message_embeds(
    embeds: list[discord.Embed],
    client: httpx.AsyncClient,
) -> tuple[list[dict[str, Any]], list[str]]:
    blocks: list[dict[str, Any]] = []
    descriptions: list[str] = []

    for embed in embeds:
        target_url = None
        if embed.image and embed.image.url:
            target_url = embed.image.url
        elif embed.thumbnail and embed.thumbnail.url:
            target_url = embed.thumbnail.url

        if not target_url or not target_url.startswith("http"):
            continue

        try:
            resp = await client.get(target_url, timeout=10.0)
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "").lower()
                raw_data = resp.content
                if "gif" in content_type or target_url.lower().endswith(".gif"):
                    frames = extract_gif_frames(raw_data, max_frames=2)
                    for f_uri in frames:
                        blocks.append({"type": "image_url", "image_url": {"url": f_uri}})
                    if frames:
                        descriptions.append(f"[Embedded GIF: {embed.title or 'Media'}]")
                elif "image" in content_type or any(target_url.lower().endswith(e) for e in IMAGE_EXTENSIONS):
                    with Image.open(io.BytesIO(raw_data)) as img:
                        data_uri = encode_pil_image_to_base64_jpeg(img, max_dim=MAX_KEYFRAME_DIMENSION)
                        blocks.append({"type": "image_url", "image_url": {"url": data_uri}})
                        descriptions.append(f"[Embedded Image: {embed.title or 'Media'}]")
        except (httpx.HTTPError, OSError, ValueError) as err:
            logger.debug("Failed downloading embed media %s: %s", target_url, err)

    return blocks, descriptions


async def process_message_media(
    message: discord.Message,
    http_client: httpx.AsyncClient,
) -> MediaPayload:
    all_blocks: list[dict[str, Any]] = []
    all_descriptions: list[str] = []

    if message.attachments:
        att_blocks, att_descs = await process_discord_attachments(message.attachments)
        all_blocks.extend(att_blocks)
        all_descriptions.extend(att_descs)

    if message.stickers:
        stk_blocks, stk_descs = await process_discord_stickers(message.stickers, http_client)
        all_blocks.extend(stk_blocks)
        all_descriptions.extend(stk_descs)

    if message.embeds:
        emb_blocks, emb_descs = await process_message_embeds(message.embeds, http_client)
        all_blocks.extend(emb_blocks)
        all_descriptions.extend(emb_descs)

    return MediaPayload(visual_blocks=all_blocks, descriptions=all_descriptions)
