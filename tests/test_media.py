from src.core.media_info import format_info
def test_media_format():
    s=format_info({"filename":"中 文.mp4","width":720,"height":405,"fps":30,"duration":3,"codec":"h264","pixel_format":"yuv420p","bit_depth":"8","audio_codec":"aac","frames":90})
    assert "720 x 405" in s and "中 文.mp4" in s
