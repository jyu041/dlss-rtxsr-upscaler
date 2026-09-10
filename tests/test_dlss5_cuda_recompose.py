import numpy as np
import pytest

torch = pytest.importorskip("torch")


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA compositor requires CUDA")
def test_cuda_compositor_parity_lifetime_and_repeated_calls():
    from src.backends.dlss5_cuda_recompose import CudaResidualCompositor
    from src.backends.dlss5_recompose import residual_recompose_cpu
    from src.backends.dlss5_metrics import comparison_metrics

    compositor = CudaResidualCompositor(8, 8, 4, 4, device="cuda:0")
    native = np.zeros((8, 8, 4), dtype=np.uint8); native[..., :3] = 100; native[..., 3] = 23
    source = np.full((4, 4, 4), 100, dtype=np.uint8); source[..., 3] = 255
    neural = source.copy(); neural[..., :3] = 110
    first, timing = compositor.compose(native, source, neural)
    expected = residual_recompose_cpu(native, source, neural)
    second, _ = compositor.compose(native, source, source)
    assert comparison_metrics(first, expected)["max_error"] <= 2
    assert np.array_equal(first[..., 3], native[..., 3])
    assert np.array_equal(second, native)
    assert timing["gpu_total_ms"] >= 0
    compositor.close()
