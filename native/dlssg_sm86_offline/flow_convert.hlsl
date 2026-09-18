Texture2D<int2> InputFlow : register(t0);
RWTexture2D<float2> OutputMotion : register(u0);
cbuffer Dimensions : register(b0) { uint width; uint height; uint gridSize; uint reserved; };
[numthreads(16, 16, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    if (id.x >= width || id.y >= height) return;
    uint grid = max(gridSize, 1u);
    uint2 source = id.xy / grid;
    int2 raw = InputFlow.Load(int3(source, 0));
    // NVOFA vectors remain expressed in input-pixel displacement units even
    // when one vector represents a coarser output grid block. Replicate the
    // block vector; do not scale its magnitude by the grid size.
    OutputMotion[id.xy] = float2(raw) / 32.0;
}
