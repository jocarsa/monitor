#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
import socket
import sqlite3
import platform
import subprocess
from datetime import datetime

import psutil


DB_PATH = "/home/josevicente/Documentos/hardware_status.sqlite"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hardware_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            hostname TEXT,
            system TEXT,
            release_version TEXT,
            machine TEXT,
            boot_time TEXT,

            cpu_percent REAL,
            cpu_freq_current REAL,
            cpu_freq_min REAL,
            cpu_freq_max REAL,
            cpu_count_logical INTEGER,
            cpu_count_physical INTEGER,
            loadavg_1 REAL,
            loadavg_5 REAL,
            loadavg_15 REAL,

            ram_total INTEGER,
            ram_available INTEGER,
            ram_used INTEGER,
            ram_percent REAL,

            swap_total INTEGER,
            swap_used INTEGER,
            swap_free INTEGER,
            swap_percent REAL,

            root_total INTEGER,
            root_used INTEGER,
            root_free INTEGER,
            root_percent REAL,

            disk_io_read_bytes INTEGER,
            disk_io_write_bytes INTEGER,
            disk_io_read_count INTEGER,
            disk_io_write_count INTEGER,

            net_bytes_sent INTEGER,
            net_bytes_recv INTEGER,
            net_packets_sent INTEGER,
            net_packets_recv INTEGER,
            net_errin INTEGER,
            net_errout INTEGER,
            net_dropin INTEGER,
            net_dropout INTEGER,

            temperatures_json TEXT,
            disks_json TEXT,
            network_interfaces_json TEXT,
            gpu_json TEXT,
            extra_json TEXT
        )
    """)
    conn.commit()
    return conn


def safe_json(data):
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return json.dumps({"error": "json_encode_failed"}, ensure_ascii=False)


def get_boot_time_iso():
    try:
        return datetime.fromtimestamp(psutil.boot_time()).isoformat(sep=" ", timespec="seconds")
    except Exception:
        return None


def get_cpu_info():
    cpu_freq = psutil.cpu_freq()
    cpu_percent = psutil.cpu_percent(interval=1)

    load1 = load5 = load15 = None
    try:
        load1, load5, load15 = os.getloadavg()
    except Exception:
        pass

    return {
        "cpu_percent": cpu_percent,
        "cpu_freq_current": cpu_freq.current if cpu_freq else None,
        "cpu_freq_min": cpu_freq.min if cpu_freq else None,
        "cpu_freq_max": cpu_freq.max if cpu_freq else None,
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "loadavg_1": load1,
        "loadavg_5": load5,
        "loadavg_15": load15,
    }


def get_memory_info():
    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()

    return {
        "ram_total": vm.total,
        "ram_available": vm.available,
        "ram_used": vm.used,
        "ram_percent": vm.percent,
        "swap_total": sm.total,
        "swap_used": sm.used,
        "swap_free": sm.free,
        "swap_percent": sm.percent,
    }


def get_root_disk_usage():
    du = psutil.disk_usage("/")
    return {
        "root_total": du.total,
        "root_used": du.used,
        "root_free": du.free,
        "root_percent": du.percent,
    }


def get_all_disks_usage():
    disks = []
    seen = set()

    for part in psutil.disk_partitions(all=False):
        if part.mountpoint in seen:
            continue
        seen.add(part.mountpoint)

        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "opts": part.opts,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent
            })
        except PermissionError:
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "opts": part.opts,
                "error": "permission_denied"
            })
        except Exception as e:
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "opts": part.opts,
                "error": str(e)
            })
    return disks


def get_disk_io():
    io = psutil.disk_io_counters()
    if not io:
        return {
            "disk_io_read_bytes": None,
            "disk_io_write_bytes": None,
            "disk_io_read_count": None,
            "disk_io_write_count": None,
        }

    return {
        "disk_io_read_bytes": io.read_bytes,
        "disk_io_write_bytes": io.write_bytes,
        "disk_io_read_count": io.read_count,
        "disk_io_write_count": io.write_count,
    }


def get_network_io():
    net = psutil.net_io_counters()
    if not net:
        return {
            "net_bytes_sent": None,
            "net_bytes_recv": None,
            "net_packets_sent": None,
            "net_packets_recv": None,
            "net_errin": None,
            "net_errout": None,
            "net_dropin": None,
            "net_dropout": None,
        }

    return {
        "net_bytes_sent": net.bytes_sent,
        "net_bytes_recv": net.bytes_recv,
        "net_packets_sent": net.packets_sent,
        "net_packets_recv": net.packets_recv,
        "net_errin": net.errin,
        "net_errout": net.errout,
        "net_dropin": net.dropin,
        "net_dropout": net.dropout,
    }


def get_network_interfaces():
    result = []
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()

    for iface, entries in addrs.items():
        iface_info = {
            "interface": iface,
            "isup": stats.get(iface).isup if iface in stats else None,
            "speed": stats.get(iface).speed if iface in stats else None,
            "mtu": stats.get(iface).mtu if iface in stats else None,
            "addresses": []
        }

        for entry in entries:
            iface_info["addresses"].append({
                "family": str(entry.family),
                "address": entry.address,
                "netmask": entry.netmask,
                "broadcast": entry.broadcast,
                "ptp": entry.ptp
            })

        result.append(iface_info)

    return result


def get_temperatures():
    result = {}
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False)
        for chip, entries in temps.items():
            result[chip] = []
            for entry in entries:
                result[chip].append({
                    "label": entry.label,
                    "current": entry.current,
                    "high": entry.high,
                    "critical": entry.critical
                })
    except Exception as e:
        result = {"error": str(e)}
    return result


def get_gpu_info():
    """
    Uses nvidia-smi if available.
    Returns a list of GPUs or an error object.
    """
    cmd = [
        "nvidia-smi",
        "--query-gpu=index,name,utilization.gpu,utilization.memory,memory.total,memory.used,memory.free,temperature.gpu,power.draw,power.limit",
        "--format=csv,noheader,nounits"
    ]

    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=10)
        gpus = []

        for line in output.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 10:
                continue

            gpus.append({
                "index": int(parts[0]) if parts[0].isdigit() else parts[0],
                "name": parts[1],
                "utilization_gpu_percent": float(parts[2]) if parts[2] else None,
                "utilization_memory_percent": float(parts[3]) if parts[3] else None,
                "memory_total_mb": float(parts[4]) if parts[4] else None,
                "memory_used_mb": float(parts[5]) if parts[5] else None,
                "memory_free_mb": float(parts[6]) if parts[6] else None,
                "temperature_gpu_c": float(parts[7]) if parts[7] else None,
                "power_draw_w": float(parts[8]) if parts[8] else None,
                "power_limit_w": float(parts[9]) if parts[9] else None,
            })

        return gpus

    except FileNotFoundError:
        return {"error": "nvidia-smi_not_found"}
    except subprocess.CalledProcessError as e:
        return {"error": "nvidia-smi_failed", "details": e.output}
    except Exception as e:
        return {"error": str(e)}


def get_extra_info():
    uptime_seconds = None
    try:
        uptime_seconds = int(time.time() - psutil.boot_time())
    except Exception:
        pass

    users = []
    try:
        for u in psutil.users():
            users.append({
                "name": u.name,
                "terminal": u.terminal,
                "host": u.host,
                "started": datetime.fromtimestamp(u.started).isoformat(sep=" ", timespec="seconds")
            })
    except Exception:
        pass

    return {
        "uptime_seconds": uptime_seconds,
        "users_logged_in": users,
        "cpu_percent_per_core": psutil.cpu_percent(interval=0.2, percpu=True)
    }


def collect_snapshot():
    base = {
        "created_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "hostname": socket.gethostname(),
        "system": platform.system(),
        "release_version": platform.release(),
        "machine": platform.machine(),
        "boot_time": get_boot_time_iso(),
    }

    cpu = get_cpu_info()
    mem = get_memory_info()
    root = get_root_disk_usage()
    disk_io = get_disk_io()
    net = get_network_io()

    temps = get_temperatures()
    disks = get_all_disks_usage()
    ifaces = get_network_interfaces()
    gpu = get_gpu_info()
    extra = get_extra_info()

    snapshot = {
        **base,
        **cpu,
        **mem,
        **root,
        **disk_io,
        **net,
        "temperatures_json": safe_json(temps),
        "disks_json": safe_json(disks),
        "network_interfaces_json": safe_json(ifaces),
        "gpu_json": safe_json(gpu),
        "extra_json": safe_json(extra),
    }

    return snapshot


def save_snapshot(conn, snapshot):
    conn.execute("""
        INSERT INTO hardware_status (
            created_at,
            hostname,
            system,
            release_version,
            machine,
            boot_time,

            cpu_percent,
            cpu_freq_current,
            cpu_freq_min,
            cpu_freq_max,
            cpu_count_logical,
            cpu_count_physical,
            loadavg_1,
            loadavg_5,
            loadavg_15,

            ram_total,
            ram_available,
            ram_used,
            ram_percent,

            swap_total,
            swap_used,
            swap_free,
            swap_percent,

            root_total,
            root_used,
            root_free,
            root_percent,

            disk_io_read_bytes,
            disk_io_write_bytes,
            disk_io_read_count,
            disk_io_write_count,

            net_bytes_sent,
            net_bytes_recv,
            net_packets_sent,
            net_packets_recv,
            net_errin,
            net_errout,
            net_dropin,
            net_dropout,

            temperatures_json,
            disks_json,
            network_interfaces_json,
            gpu_json,
            extra_json
        ) VALUES (
            :created_at,
            :hostname,
            :system,
            :release_version,
            :machine,
            :boot_time,

            :cpu_percent,
            :cpu_freq_current,
            :cpu_freq_min,
            :cpu_freq_max,
            :cpu_count_logical,
            :cpu_count_physical,
            :loadavg_1,
            :loadavg_5,
            :loadavg_15,

            :ram_total,
            :ram_available,
            :ram_used,
            :ram_percent,

            :swap_total,
            :swap_used,
            :swap_free,
            :swap_percent,

            :root_total,
            :root_used,
            :root_free,
            :root_percent,

            :disk_io_read_bytes,
            :disk_io_write_bytes,
            :disk_io_read_count,
            :disk_io_write_count,

            :net_bytes_sent,
            :net_bytes_recv,
            :net_packets_sent,
            :net_packets_recv,
            :net_errin,
            :net_errout,
            :net_dropin,
            :net_dropout,

            :temperatures_json,
            :disks_json,
            :network_interfaces_json,
            :gpu_json,
            :extra_json
        )
    """, snapshot)
    conn.commit()


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_connection()
    snapshot = collect_snapshot()
    save_snapshot(conn, snapshot)
    conn.close()


if __name__ == "__main__":
    main()
