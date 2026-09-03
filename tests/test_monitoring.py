import time

from src.core.monitoring import SystemMonitor
from src.ui.monitoring import metrics_html


def test_monitor_snapshot_has_cpu_and_ram_values():
    monitor = SystemMonitor().start()
    try:
        time.sleep(.1)
        snapshot = monitor.snapshot()
        assert 0 <= snapshot.cpu_percent <= 100
        assert snapshot.ram_total > 0 and 0 <= snapshot.ram_percent <= 100
    finally:
        monitor.stop()


def test_metric_markup_has_four_cards():
    markup = metrics_html()
    assert all(f'class="metric-card"' in markup for _ in range(1))
    assert markup.count('class="metric-card"') == 4
