from .ffmpeg import validate
def codec_args(codec, quality, cq, preset):
    validate(codec, "MP4")
    c={"H.264":"h264_nvenc","HEVC":"hevc_nvenc","AV1":"av1_nvenc"}[codec]
    return ["-c:v",c,"-preset",preset,"-cq",str(cq)]
