# Media helper for Discord images and video attachments.
# Scales pictures and extracts representative video keyframes for vision-capable models.
import base64
import io
import logging
import os
import tempfile
import time

import cv2
import discord
from PIL import Image

logger = logging.getLogger("DiscoMediaUtils")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi"}

MAX_IMG_DIM = 1280
MAX_VIDEO_FRAME_DIM = 800
VIDEO_SAMPLES = 5


def _safe_remove(path: str, retries: int = 3):
    # Windows can hold file locks briefly even after cap.release()
    for attempt in range(retries):
        try:
            if os.path.exists(path):
                os.remove(path)
            return
        except (PermissionError, OSError):
            time.sleep(0.05 * (attempt + 1))
    logger.debug(f"Could not immediately delete temp video {path}")


def encode_pil_image_to_base64_jpeg(
    img: Image.Image, max_dim: int = MAX_IMG_DIM, quality: int = 85
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


def extract_frames_from_video_bytes(
    video_bytes: bytes, num_frames: int = VIDEO_SAMPLES
) -> list[str]:
    frames_b64 = []
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(video_bytes)

        cap = cv2.VideoCapture(tmp_path)
        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            # Edge case: ultra short clips or rare codecs report 0 frames
            if total_frames <= 0:
                logger.warning("Video has 0 frames or could not be parsed by OpenCV.")
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
                        pil_img, max_dim=MAX_VIDEO_FRAME_DIM, quality=75
                    )
                    frames_b64.append(b64_uri)
        finally:
            cap.release()
    except (cv2.error, OSError, ValueError) as e:
        logger.error(f"Failed extracting video frames: {e}")
    finally:
        _safe_remove(tmp_path)

    return frames_b64


async def process_discord_attachments(
    attachments: list[discord.Attachment],
) -> tuple[list[dict], str]:
    blocks = []
    descriptions = []

    for att in attachments:
        ext = os.path.splitext(att.filename.lower())[1]

        if ext in IMAGE_EXTS:
            try:
                raw_data = await att.read()
                pil_img = Image.open(io.BytesIO(raw_data))
                data_uri = encode_pil_image_to_base64_jpeg(pil_img)
                blocks.append({"type": "image_url", "image_url": {"url": data_uri}})
                descriptions.append(f"[Attached Image: {att.filename}]")
            except (Image.DecompressionBombError, OSError, ValueError) as e:
                logger.error(f"Could not decode image {att.filename}: {e}")
            except discord.DiscordException as e:
                logger.error(f"Network error downloading image attachment {att.filename}: {e}")

        elif ext in VIDEO_EXTS:
            try:
                raw_data = await att.read()
                frames = extract_frames_from_video_bytes(raw_data, num_frames=VIDEO_SAMPLES)
                for f_uri in frames:
                    blocks.append({"type": "image_url", "image_url": {"url": f_uri}})
                if frames:
                    descriptions.append(
                        f"[Attached Video: {att.filename}, {len(frames)} keyframes sampled across duration]"
                    )
            except discord.DiscordException as e:
                logger.error(f"Network error downloading video attachment {att.filename}: {e}")
            except OSError as e:
                logger.error(f"Filesystem error processing video {att.filename}: {e}")

    return blocks, "\n".join(descriptions)
