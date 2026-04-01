#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import sqlite3
import traceback
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter


# =========================================================
# Configuración robusta para cron
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.environ.get(
    "HARDWARE_STATUS_DB",
    "/home/josevicente/Documentos/hardware_status.sqlite"
)

OUTPUT_IMAGE = os.environ.get(
    "HARDWARE_STATUS_OUTPUT",
    "/home/josevicente/Documentos/hardware_status_analytics_detailed.png"
)

LOG_PATH = os.environ.get(
    "HARDWARE_STATUS_LOG",
    "/home/josevicente/Documentos/hardware_status_analytics.log"
)


# =========================================================
# Utilidades
# =========================================================

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None


def safe_json_loads(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def bytes_to_human(num):
    if num is None:
        return "N/D"
    num = float(num)
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if abs(num) < 1024.0:
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} EB"


def list_clean(values):
    return [v for v in values if isinstance(v, (int, float))]


def list_stats(values):
    clean = list_clean(values)
    if not clean:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "avg": None,
            "last": None,
            "p95": None
        }

    sorted_vals = sorted(clean)
    p95_index = min(len(sorted_vals) - 1, max(0, int(round(0.95 * (len(sorted_vals) - 1)))))

    return {
        "count": len(clean),
        "min": min(clean),
        "max": max(clean),
        "avg": sum(clean) / len(clean),
        "last": clean[-1],
        "p95": sorted_vals[p95_index]
    }


def moving_average(values, window=8):
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = [v for v in values[start:i + 1] if isinstance(v, (int, float))]
        result.append(sum(chunk) / len(chunk) if chunk else None)
    return result


def compute_rate_series(values, timestamps):
    out = [None]
    for i in range(1, len(values)):
        v0 = values[i - 1]
        v1 = values[i]
        t0 = timestamps[i - 1]
        t1 = timestamps[i]

        if not isinstance(v0, (int, float)) or not isinstance(v1, (int, float)) or t0 is None or t1 is None:
            out.append(None)
            continue

        dt = (t1 - t0).total_seconds()
        if dt <= 0:
            out.append(None)
            continue

        delta = v1 - v0
        if delta < 0:
            out.append(None)
            continue

        out.append(delta / dt)

    return out


def extract_avg_temp(temp_json):
    data = safe_json_loads(temp_json)
    if not data or not isinstance(data, dict):
        return None
    if "error" in data:
        return None

    vals = []
    try:
        for _, entries in data.items():
            if isinstance(entries, list):
                for entry in entries:
                    current = entry.get("current")
                    if isinstance(current, (int, float)):
                        vals.append(current)
    except Exception:
        return None

    if not vals:
        return None
    return sum(vals) / len(vals)


def extract_gpu_metric(gpu_json, field):
    data = safe_json_loads(gpu_json)
    if not data:
        return None
    if isinstance(data, dict) and "error" in data:
        return None
    if isinstance(data, list) and data:
        value = data[0].get(field)
        if isinstance(value, (int, float)):
            return value
    return None


def extract_uptime_hours(extra_json):
    data = safe_json_loads(extra_json)
    if not isinstance(data, dict):
        return None
    value = data.get("uptime_seconds")
    if isinstance(value, (int, float)):
        return value / 3600.0
    return None


def extract_logged_users(extra_json):
    data = safe_json_loads(extra_json)
    if not isinstance(data, dict):
        return None
    users = data.get("users_logged_in")
    if isinstance(users, list):
        return len(users)
    return None


def choose_time_formatter(time_span_days):
    if time_span_days <= 1:
        return DateFormatter("%H:%M")
    if time_span_days <= 8:
        return DateFormatter("%d %H:%M")
    if time_span_days <= 35:
        return DateFormatter("%d-%m")
    return DateFormatter("%Y-%m-%d")


# =========================================================
# Carga de datos
# =========================================================

def load_rows():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"No existe la base de datos: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT *
        FROM hardware_status
        ORDER BY datetime(created_at) ASC, id ASC
    """).fetchall()
    conn.close()

    if not rows:
        raise RuntimeError("La tabla hardware_status está vacía")

    return rows


def build_dataset(rows):
    data = {
        "timestamps": [],

        "cpu_percent": [],
        "cpu_freq_current": [],
        "cpu_count_logical": [],
        "cpu_count_physical": [],
        "loadavg_1": [],
        "loadavg_5": [],
        "loadavg_15": [],

        "ram_percent": [],
        "swap_percent": [],
        "ram_used": [],
        "ram_available": [],

        "root_percent": [],
        "root_used": [],
        "root_free": [],

        "disk_io_read_bytes": [],
        "disk_io_write_bytes": [],
        "disk_io_read_count": [],
        "disk_io_write_count": [],

        "net_bytes_sent": [],
        "net_bytes_recv": [],
        "net_packets_sent": [],
        "net_packets_recv": [],
        "net_errin": [],
        "net_errout": [],
        "net_dropin": [],
        "net_dropout": [],

        "avg_temp_c": [],
        "gpu_util_percent": [],
        "gpu_mem_used_mb": [],
        "gpu_mem_free_mb": [],
        "gpu_temp_c": [],
        "gpu_power_draw_w": [],

        "uptime_hours": [],
        "logged_users": []
    }

    meta = {
        "hostname": None,
        "system": None,
        "release_version": None,
        "machine": None,
        "boot_time": None,
        "samples": len(rows),
        "first_timestamp": None,
        "last_timestamp": None
    }

    for i, row in enumerate(rows):
        ts = parse_dt(row["created_at"])
        data["timestamps"].append(ts)

        data["cpu_percent"].append(row["cpu_percent"])
        data["cpu_freq_current"].append(row["cpu_freq_current"])
        data["cpu_count_logical"].append(row["cpu_count_logical"])
        data["cpu_count_physical"].append(row["cpu_count_physical"])
        data["loadavg_1"].append(row["loadavg_1"])
        data["loadavg_5"].append(row["loadavg_5"])
        data["loadavg_15"].append(row["loadavg_15"])

        data["ram_percent"].append(row["ram_percent"])
        data["swap_percent"].append(row["swap_percent"])
        data["ram_used"].append(row["ram_used"])
        data["ram_available"].append(row["ram_available"])

        data["root_percent"].append(row["root_percent"])
        data["root_used"].append(row["root_used"])
        data["root_free"].append(row["root_free"])

        data["disk_io_read_bytes"].append(row["disk_io_read_bytes"])
        data["disk_io_write_bytes"].append(row["disk_io_write_bytes"])
        data["disk_io_read_count"].append(row["disk_io_read_count"])
        data["disk_io_write_count"].append(row["disk_io_write_count"])

        data["net_bytes_sent"].append(row["net_bytes_sent"])
        data["net_bytes_recv"].append(row["net_bytes_recv"])
        data["net_packets_sent"].append(row["net_packets_sent"])
        data["net_packets_recv"].append(row["net_packets_recv"])
        data["net_errin"].append(row["net_errin"])
        data["net_errout"].append(row["net_errout"])
        data["net_dropin"].append(row["net_dropin"])
        data["net_dropout"].append(row["net_dropout"])

        data["avg_temp_c"].append(extract_avg_temp(row["temperatures_json"]))
        data["gpu_util_percent"].append(extract_gpu_metric(row["gpu_json"], "utilization_gpu_percent"))
        data["gpu_mem_used_mb"].append(extract_gpu_metric(row["gpu_json"], "memory_used_mb"))
        data["gpu_mem_free_mb"].append(extract_gpu_metric(row["gpu_json"], "memory_free_mb"))
        data["gpu_temp_c"].append(extract_gpu_metric(row["gpu_json"], "temperature_gpu_c"))
        data["gpu_power_draw_w"].append(extract_gpu_metric(row["gpu_json"], "power_draw_w"))

        data["uptime_hours"].append(extract_uptime_hours(row["extra_json"]))
        data["logged_users"].append(extract_logged_users(row["extra_json"]))

        if i == 0:
            meta["hostname"] = row["hostname"]
            meta["system"] = row["system"]
            meta["release_version"] = row["release_version"]
            meta["machine"] = row["machine"]
            meta["boot_time"] = row["boot_time"]
            meta["first_timestamp"] = row["created_at"]

        if i == len(rows) - 1:
            meta["last_timestamp"] = row["created_at"]

    data["net_rx_rate"] = compute_rate_series(data["net_bytes_recv"], data["timestamps"])
    data["net_tx_rate"] = compute_rate_series(data["net_bytes_sent"], data["timestamps"])
    data["disk_read_rate"] = compute_rate_series(data["disk_io_read_bytes"], data["timestamps"])
    data["disk_write_rate"] = compute_rate_series(data["disk_io_write_bytes"], data["timestamps"])
    data["disk_read_ops_rate"] = compute_rate_series(data["disk_io_read_count"], data["timestamps"])
    data["disk_write_ops_rate"] = compute_rate_series(data["disk_io_write_count"], data["timestamps"])

    return data, meta


def slice_dataset(data, start_dt=None):
    if start_dt is None:
        return data

    indexes = [i for i, ts in enumerate(data["timestamps"]) if ts is not None and ts >= start_dt]

    sliced = {}
    for key, series in data.items():
        sliced[key] = [series[i] for i in indexes]
    return sliced


# =========================================================
# Render
# =========================================================

def setup_line_ax(ax, title, ylabel, time_span_days):
    ax.set_title(title, fontsize=11, fontweight="bold", loc="left")
    ax.set_ylabel(ylabel, fontsize=9)
    ax.grid(True, alpha=0.25)
    ax.tick_params(axis="x", labelrotation=20, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)
    ax.xaxis.set_major_formatter(choose_time_formatter(time_span_days))


def render_text_block(ax, title, lines):
    ax.axis("off")
    ax.text(0.0, 1.0, title, fontsize=13, fontweight="bold", va="top")
    ax.text(0.0, 0.94, "\n".join(lines), fontsize=9, va="top", family="monospace")


def build_summary_lines(section_name, section_data):
    timestamps = section_data["timestamps"]
    if not timestamps:
        return [
            f"Sección: {section_name}",
            "Sin datos."
        ]

    ts_valid = [t for t in timestamps if t is not None]
    start_txt = ts_valid[0].isoformat(sep=" ", timespec="seconds") if ts_valid else "N/D"
    end_txt = ts_valid[-1].isoformat(sep=" ", timespec="seconds") if ts_valid else "N/D"

    cpu = list_stats(section_data["cpu_percent"])
    ram = list_stats(section_data["ram_percent"])
    root = list_stats(section_data["root_percent"])
    temp = list_stats(section_data["avg_temp_c"])
    gpu = list_stats(section_data["gpu_util_percent"])

    net_rx = list_stats(section_data["net_rx_rate"])
    net_tx = list_stats(section_data["net_tx_rate"])
    disk_r = list_stats(section_data["disk_read_rate"])
    disk_w = list_stats(section_data["disk_write_rate"])

    def fmt_stats(name, st, suffix=""):
        if st["count"] == 0:
            return f"{name:<18} N/D"
        return (
            f"{name:<18} "
            f"last={st['last']:.2f}{suffix}  "
            f"avg={st['avg']:.2f}{suffix}  "
            f"min={st['min']:.2f}{suffix}  "
            f"max={st['max']:.2f}{suffix}  "
            f"p95={st['p95']:.2f}{suffix}"
        )

    lines = [
        f"Sección: {section_name}",
        f"Desde:   {start_txt}",
        f"Hasta:   {end_txt}",
        f"Muestras:{len(timestamps)}",
        "",
        fmt_stats("CPU %", cpu, "%"),
        fmt_stats("RAM %", ram, "%"),
        fmt_stats("Disco raíz %", root, "%"),
        fmt_stats("Temperatura", temp, "C"),
        fmt_stats("GPU %", gpu, "%"),
        "",
        f"{'Red RX media':<18} {bytes_to_human(net_rx['avg'])}/s" if net_rx["avg"] is not None else f"{'Red RX media':<18} N/D",
        f"{'Red TX media':<18} {bytes_to_human(net_tx['avg'])}/s" if net_tx["avg"] is not None else f"{'Red TX media':<18} N/D",
        f"{'Disco R media':<18} {bytes_to_human(disk_r['avg'])}/s" if disk_r["avg"] is not None else f"{'Disco R media':<18} N/D",
        f"{'Disco W media':<18} {bytes_to_human(disk_w['avg'])}/s" if disk_w["avg"] is not None else f"{'Disco W media':<18} N/D",
    ]

    return lines


def plot_single_series(ax, timestamps, values, title, ylabel, time_span_days, add_ma=True):
    setup_line_ax(ax, title, ylabel, time_span_days)
    clean_exists = any(isinstance(v, (int, float)) for v in values)

    if not clean_exists:
        ax.text(0.5, 0.5, "Sin datos", ha="center", va="center", transform=ax.transAxes, fontsize=10)
        return

    ax.plot(timestamps, values, linewidth=1.2)
    if add_ma:
        ax.plot(timestamps, moving_average(values, 8), linestyle="--", linewidth=1.0)


def render_section(fig, gs, row_start, section_name, section_data, time_span_days):
    rows_used = 9

    ax_title = fig.add_subplot(gs[row_start, :])
    ax_title.axis("off")
    ax_title.text(0.0, 0.5, section_name, fontsize=18, fontweight="bold", va="center")

    ax_text = fig.add_subplot(gs[row_start + 1, :])

    ax1 = fig.add_subplot(gs[row_start + 2, 0])
    ax2 = fig.add_subplot(gs[row_start + 2, 1])
    ax3 = fig.add_subplot(gs[row_start + 2, 2])

    ax4 = fig.add_subplot(gs[row_start + 3, 0])
    ax5 = fig.add_subplot(gs[row_start + 3, 1])
    ax6 = fig.add_subplot(gs[row_start + 3, 2])

    ax7 = fig.add_subplot(gs[row_start + 4, 0])
    ax8 = fig.add_subplot(gs[row_start + 4, 1])
    ax9 = fig.add_subplot(gs[row_start + 4, 2])

    ax10 = fig.add_subplot(gs[row_start + 5, 0])
    ax11 = fig.add_subplot(gs[row_start + 5, 1])
    ax12 = fig.add_subplot(gs[row_start + 5, 2])

    ax13 = fig.add_subplot(gs[row_start + 6, 0])
    ax14 = fig.add_subplot(gs[row_start + 6, 1])
    ax15 = fig.add_subplot(gs[row_start + 6, 2])

    ax16 = fig.add_subplot(gs[row_start + 7, 0])
    ax17 = fig.add_subplot(gs[row_start + 7, 1])
    ax18 = fig.add_subplot(gs[row_start + 7, 2])

    ax19 = fig.add_subplot(gs[row_start + 8, 0])
    ax20 = fig.add_subplot(gs[row_start + 8, 1])
    ax21 = fig.add_subplot(gs[row_start + 8, 2])

    timestamps = section_data["timestamps"]

    render_text_block(ax_text, "Resumen de la sección", build_summary_lines(section_name, section_data))

    plot_single_series(ax1, timestamps, section_data["cpu_percent"], "CPU usage", "%", time_span_days)
    plot_single_series(ax2, timestamps, section_data["cpu_freq_current"], "CPU frequency", "MHz", time_span_days)
    plot_single_series(ax3, timestamps, section_data["loadavg_1"], "Load average 1m", "load", time_span_days, add_ma=False)

    plot_single_series(ax4, timestamps, section_data["loadavg_5"], "Load average 5m", "load", time_span_days, add_ma=False)
    plot_single_series(ax5, timestamps, section_data["loadavg_15"], "Load average 15m", "load", time_span_days, add_ma=False)
    plot_single_series(ax6, timestamps, section_data["ram_percent"], "RAM usage", "%", time_span_days)

    plot_single_series(ax7, timestamps, section_data["swap_percent"], "Swap usage", "%", time_span_days)
    plot_single_series(ax8, timestamps, section_data["root_percent"], "Root disk usage", "%", time_span_days)
    plot_single_series(ax9, timestamps, section_data["avg_temp_c"], "Average temperature", "°C", time_span_days)

    plot_single_series(ax10, timestamps, section_data["net_rx_rate"], "Network RX rate", "bytes/s", time_span_days)
    plot_single_series(ax11, timestamps, section_data["net_tx_rate"], "Network TX rate", "bytes/s", time_span_days)
    plot_single_series(ax12, timestamps, section_data["disk_read_rate"], "Disk read rate", "bytes/s", time_span_days)

    plot_single_series(ax13, timestamps, section_data["disk_write_rate"], "Disk write rate", "bytes/s", time_span_days)
    plot_single_series(ax14, timestamps, section_data["disk_read_ops_rate"], "Disk read ops rate", "ops/s", time_span_days)
    plot_single_series(ax15, timestamps, section_data["disk_write_ops_rate"], "Disk write ops rate", "ops/s", time_span_days)

    plot_single_series(ax16, timestamps, section_data["gpu_util_percent"], "GPU usage", "%", time_span_days)
    plot_single_series(ax17, timestamps, section_data["gpu_mem_used_mb"], "GPU memory used", "MB", time_span_days)
    plot_single_series(ax18, timestamps, section_data["gpu_temp_c"], "GPU temperature", "°C", time_span_days)

    plot_single_series(ax19, timestamps, section_data["gpu_power_draw_w"], "GPU power draw", "W", time_span_days)
    plot_single_series(ax20, timestamps, section_data["uptime_hours"], "System uptime", "hours", time_span_days)
    plot_single_series(ax21, timestamps, section_data["logged_users"], "Logged users", "count", time_span_days, add_ma=False)

    return rows_used


def render_dashboard():
    log("Inicio de render_dashboard()")
    rows = load_rows()
    data, meta = build_dataset(rows)

    now = data["timestamps"][-1]
    if now is None:
        now = datetime.now()

    first_ts = data["timestamps"][0]
    if first_ts is None:
        full_days = 365
    else:
        full_days = max(31, (now - first_ts).days)

    sections = [
        ("Últimas 20 horas", slice_dataset(data, now - timedelta(hours=20)), 20 / 24.0),
        ("Última semana", slice_dataset(data, now - timedelta(days=7)), 7),
        ("Último mes", slice_dataset(data, now - timedelta(days=30)), 30),
        ("Histórico completo", data, full_days),
    ]

    total_rows = 1 + len(sections) * 9

    fig = plt.figure(figsize=(24, total_rows * 2.8), dpi=140)
    gs = fig.add_gridspec(total_rows, 3, height_ratios=[1.0] + [1.0] * (total_rows - 1))

    ax_header = fig.add_subplot(gs[0, :])
    ax_header.axis("off")

    title = "Hardware analytics dashboard"
    subtitle = (
        f"{meta['hostname'] or 'equipo'} · "
        f"{meta['system'] or 'SO'} {meta['release_version'] or ''} · "
        f"{meta['machine'] or ''}"
    ).strip()

    global_cpu = list_stats(data["cpu_percent"])
    global_ram = list_stats(data["ram_percent"])
    global_disk = list_stats(data["root_percent"])
    global_temp = list_stats(data["avg_temp_c"])
    global_gpu = list_stats(data["gpu_util_percent"])

    header_lines = [
        f"Muestras totales: {meta['samples']}",
        f"Desde: {meta['first_timestamp'] or 'N/D'}",
        f"Hasta: {meta['last_timestamp'] or 'N/D'}",
        f"Boot time: {meta['boot_time'] or 'N/D'}",
        "",
        f"CPU media global:  {global_cpu['avg']:.2f} %" if global_cpu["avg"] is not None else "CPU media global: N/D",
        f"RAM media global:  {global_ram['avg']:.2f} %" if global_ram["avg"] is not None else "RAM media global: N/D",
        f"Disco media global:{global_disk['avg']:.2f} %" if global_disk["avg"] is not None else "Disco media global: N/D",
        f"Temp media global: {global_temp['avg']:.2f} C" if global_temp["avg"] is not None else "Temp media global: N/D",
        f"GPU media global:  {global_gpu['avg']:.2f} %" if global_gpu["avg"] is not None else "GPU media global: N/D",
    ]

    ax_header.text(0.00, 0.95, title, fontsize=24, fontweight="bold", va="top")
    ax_header.text(0.00, 0.65, subtitle, fontsize=12, va="top")
    ax_header.text(0.52, 0.95, "\n".join(header_lines), fontsize=10, va="top", family="monospace")

    row_cursor = 1
    for section_name, section_data, time_span_days in sections:
        render_section(fig, gs, row_cursor, section_name, section_data, time_span_days)
        row_cursor += 9

    os.makedirs(os.path.dirname(OUTPUT_IMAGE), exist_ok=True)
    plt.tight_layout()
    plt.savefig(OUTPUT_IMAGE, bbox_inches="tight")
    plt.close(fig)

    log(f"Imagen generada correctamente en: {OUTPUT_IMAGE}")


def main():
    try:
        log("========================================")
        log("Inicio del script")
        log(f"BASE_DIR={BASE_DIR}")
        log(f"DB_PATH={DB_PATH}")
        log(f"OUTPUT_IMAGE={OUTPUT_IMAGE}")
        log(f"LOG_PATH={LOG_PATH}")

        if not os.path.exists(DB_PATH):
            raise FileNotFoundError(f"La base de datos no existe: {DB_PATH}")

        render_dashboard()
        log("Fin correcto del script")

    except Exception as e:
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
