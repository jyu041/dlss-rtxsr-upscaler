"""NVIDIA-reference same-resolution RTX VSR runner.

This isolated helper deliberately mirrors NVIDIA's Python sample for denoise and
deblur: PyAV decode -> CHW float32 CUDA tensor -> VideoSuperRes -> immediate
DLPack clone -> PyAV encode. It exists because the project's generic raw-frame
worker path is proven for upscaling but produced corrupted output for the
same-resolution mode families on the tested Windows/RTX 3070 configuration.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import sys
import traceback


def _quality_name(mode: str, quality: str) -> str:
    prefix = {"Deblur": "DEBLUR_", "Denoise": "DENOISE_"}.get(mode)
    if prefix is None:
        raise ValueError(f"unsupported same-resolution RTX VSR mode: {mode}")
    if quality not in {"LOW", "MEDIUM", "HIGH", "ULTRA"}:
        raise ValueError(f"unsupported RTX VSR quality: {quality}")
    return prefix + quality


def _process_tensor(rgb_input, effect, torch):
    stream_ptr = torch.cuda.current_stream().cuda_stream
    native = effect.run(rgb_input, stream_ptr=stream_ptr)
    output = torch.from_dlpack(native.image).clone()
    if output.ndim != 3 or int(output.shape[0]) != 3:
        raise RuntimeError(
            f"NVIDIA VFX returned unexpected output shape {tuple(output.shape)}; "
            "expected channels-first RGB"
        )
    return output


def _open_video_encoder(av, output_path: Path, codec: str, rate, width: int, height: int):
    candidates = (
        ("h264_nvenc", "libx264")
        if codec == "H.264"
        else ("hevc_nvenc", "libx265")
    )
    failures: list[str] = []
    for name in candidates:
        container = av.open(str(output_path), mode="w")
        try:
            stream = container.add_stream(name, rate=rate)
            stream.width = width
            stream.height = height
            stream.pix_fmt = "yuv420p"
            stream.bit_rate = 16_000_000
            stream.codec_context.open()
            return container, stream, name
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            try:
                container.close()
            except Exception:
                pass
    raise RuntimeError("no usable video encoder: " + "; ".join(failures))


def process_video(args) -> dict[str, object]:
    import av
    import torch
    import nvvfx

    torch.cuda.set_device(0)
    source = Path(args.input)
    output = Path(args.output)
    input_container = av.open(str(source))
    input_stream = input_container.streams.video[0]
    input_stream.thread_type = "AUTO"
    width = int(input_stream.codec_context.width)
    height = int(input_stream.codec_context.height)
    total = int(input_stream.frames or 0)
    average_rate = input_stream.average_rate
    if average_rate is None:
        raise RuntimeError("input video has no usable frame rate")
    rate = Fraction(float(average_rate)).limit_denominator(10000)

    quality = getattr(nvvfx.VideoSuperRes.QualityLevel, _quality_name(args.mode, args.quality))
    effect = nvvfx.VideoSuperRes(quality, device=0)
    effect.output_width = width
    effect.output_height = height
    effect.load()

    output_container, output_stream, encoder_name = _open_video_encoder(
        av, output, args.codec, rate, width, height
    )
    processed = 0
    try:
        for frame in input_container.decode(input_stream):
            arr = frame.to_ndarray(format="rgb24")
            rgb_input = (
                torch.from_numpy(arr)
                .to("cuda:0")
                .permute(2, 0, 1)
                .float()
                .div_(255.0)
                .contiguous()
            )
            rgb_output = _process_tensor(rgb_input, effect, torch)
            frame_np = (
                rgb_output.clamp(0.0, 1.0)
                .mul(255.0)
                .byte()
                .permute(1, 2, 0)
                .contiguous()
                .cpu()
                .numpy()
            )
            out_frame = av.VideoFrame.from_ndarray(frame_np, format="rgb24")
            for packet in output_stream.encode(out_frame):
                output_container.mux(packet)
            processed += 1
            print(f"NVE_PROGRESS {processed} {total}", flush=True)

        for packet in output_stream.encode(None):
            output_container.mux(packet)
    finally:
        output_container.close()
        input_container.close()

    return {
        "frames": processed,
        "width": width,
        "height": height,
        "encoder": encoder_name,
    }


def process_frame(args) -> dict[str, object]:
    import numpy as np
    from PIL import Image
    import torch
    import nvvfx

    torch.cuda.set_device(0)
    source = Path(args.frame_input)
    output_path = Path(args.frame_output)
    frame = np.asarray(Image.open(source).convert("RGB"), dtype=np.uint8)
    height, width = frame.shape[:2]

    quality = getattr(nvvfx.VideoSuperRes.QualityLevel, _quality_name(args.mode, args.quality))
    effect = nvvfx.VideoSuperRes(quality, device=0)
    effect.output_width = width
    effect.output_height = height
    effect.load()

    rgb_input = (
        torch.from_numpy(frame)
        .to("cuda:0")
        .permute(2, 0, 1)
        .float()
        .div_(255.0)
        .contiguous()
    )
    rgb_output = _process_tensor(rgb_input, effect, torch)
    frame_np = (
        rgb_output.clamp(0.0, 1.0)
        .mul(255.0)
        .byte()
        .permute(1, 2, 0)
        .contiguous()
        .cpu()
        .numpy()
    )
    Image.fromarray(frame_np).save(output_path)
    return {"width": width, "height": height}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("Deblur", "Denoise"))
    parser.add_argument("--quality", required=True, choices=("LOW", "MEDIUM", "HIGH", "ULTRA"))
    parser.add_argument("--codec", choices=("H.264", "HEVC"), default="H.264")
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--frame-input")
    parser.add_argument("--frame-output")
    args = parser.parse_args()

    try:
        if args.frame_input:
            if not args.frame_output:
                raise ValueError("--frame-output is required with --frame-input")
            result = process_frame(args)
        else:
            if not args.input or not args.output:
                raise ValueError("--input and --output are required")
            result = process_video(args)
        print("NVE_RESULT " + json.dumps(result, separators=(",", ":")), flush=True)
        return 0
    except BaseException:
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    code = main()
    # Do not ask the native VFX runtime to tear itself down during interpreter
    # finalization. The helper process is the resource boundary.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
