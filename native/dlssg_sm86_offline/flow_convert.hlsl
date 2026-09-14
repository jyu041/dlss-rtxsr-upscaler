Texture2D<int2> InputFlow : register(t0);
RWTexture2D<float2> OutputMotion : register(u0);
cbuffer Dimensions : register(b0) { uint width; uint height; };
[numthreads(16, 16, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    if (id.x >= width || id.y >= height) return;
    int2 raw = InputFlow.Load(int3(id.xy, 0));
    OutputMotion[id.xy] = float2(raw) / 32.0;
}
