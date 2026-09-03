from html import escape

from src.core.monitoring import MONITOR


def _bar(value):
    if value is None:
        return '<span class="metric-na">N/A</span>'
    value = max(0.0, min(100.0, float(value)))
    return f'<span class="metric-track"><span class="metric-fill" style="width:{value:.1f}%"></span></span>'


def metrics_html():
    snapshot = MONITOR.snapshot()
    ram_used = snapshot.ram_used / 1024**3
    ram_total = snapshot.ram_total / 1024**3
    vram_used = snapshot.vram_used / 1024**3 if snapshot.vram_used is not None else None
    vram_total = snapshot.vram_total / 1024**3 if snapshot.vram_total is not None else None
    cards = [
        ("CPU", f"{snapshot.cpu_percent:.0f}%", snapshot.cpu_percent),
        ("RAM", f"{ram_used:.1f} / {ram_total:.1f} GiB\n{snapshot.ram_percent:.0f}%", snapshot.ram_percent),
        ("GPU", f"{snapshot.gpu_percent:.0f}%" if snapshot.gpu_percent is not None else "N/A", snapshot.gpu_percent),
        ("VRAM", f"{vram_used:.1f} / {vram_total:.1f} GiB\n{snapshot.vram_percent:.0f}%" if vram_used is not None else "N/A", snapshot.vram_percent),
    ]
    html = ['<div class="metric-bar">']
    for name, value, percent in cards:
        html.append(f'<div class="metric-card"><div class="metric-name">{name}</div><div class="metric-value">{escape(value).replace(chr(10), "<br>")}</div>{_bar(percent)}</div>')
    html.append('</div>')
    return "".join(html)
