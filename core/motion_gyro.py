# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - Motion Gyro Engine
Tích hợp cảm biến con quay hồi chuyển 6-trục (Gyroscope + Accelerometer)
cho tay cầm Sony DualShock 4, DualSense PS5 và Nintendo Switch Pro.

Các chế độ hoạt động:
1. Gyro-to-Mouse Aiming: Ngắm bắn chính xác bằng cách nghiêng tay cầm (kích hoạt khi giữ L2 ngắm bắn hoặc luôn bật).
2. Cemuhook DSU Server: Máy chủ UDP Motion Server (127.0.0.1:26760) cho trình giả lập Cemu (Zelda BotW), Yuzu, Ryujinx, RPCS3.
3. Live Sensor Visualizer: Xem trực tiếp góc nghiêng Roll/Pitch/Yaw trên giao diện.
"""

import os
import sys
import time
import socket
import struct
import zlib
import winreg
import ctypes
import threading
from ctypes import wintypes
from typing import Optional, Dict, Any, Tuple

# Windows API
k32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [
    ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE
]

k32.ReadFile.restype = wintypes.BOOL
k32.ReadFile.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
]

k32.CloseHandle.restype = wintypes.BOOL
k32.CloseHandle.argtypes = [wintypes.HANDLE]

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
MOUSEEVENTF_MOVE = 0x0001


def find_motion_controller_device() -> Tuple[Optional[str], str]:
    """
    Quét Windows Registry để tìm đường dẫn thiết bị HID của tay cầm có con quay hồi chuyển.
    Hỗ trợ Sony DualShock 4 (VID 054C, PID 05C4 / 09CC / 0BA0), DualSense (PID 0CE6 / 0DF2),
    và Nintendo Switch Pro Controller (VID 057E, PID 2009).
    """
    guid_key = r"SYSTEM\CurrentControlSet\Control\DeviceClasses\{4d1e55b2-f16f-11cf-88cb-001111000030}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, guid_key) as k:
            num_subkeys, _, _ = winreg.QueryInfoKey(k)
            for i in range(num_subkeys):
                sk = winreg.EnumKey(k, i)
                skl = sk.lower()
                # Kiểm tra Sony hoặc Nintendo Switch Pro
                if "054c" in skl or "057e" in skl:
                    dev_path = r"\\?\\" + sk[4:]
                    # Thử mở thiết bị kiểm tra xem có cắm thực tế không
                    h = k32.CreateFileW(
                        dev_path,
                        GENERIC_READ | GENERIC_WRITE,
                        FILE_SHARE_READ | FILE_SHARE_WRITE,
                        None, OPEN_EXISTING, 0, None
                    )
                    if h == -1 or h == 0 or h == 0xFFFFFFFFFFFFFFFF:
                        h = k32.CreateFileW(
                            dev_path, 0,
                            FILE_SHARE_READ | FILE_SHARE_WRITE,
                            None, OPEN_EXISTING, 0, None
                        )
                    if h != -1 and h != 0 and h != 0xFFFFFFFFFFFFFFFF:
                        k32.CloseHandle(h)
                        # Xác định loại tay cầm
                        if "09cc" in skl or "05c4" in skl or "0ba0" in skl:
                            name = "Sony DualShock 4 (PS4)"
                        elif "0ce6" in skl or "0df2" in skl:
                            name = "Sony DualSense (PS5)"
                        elif "057e" in skl:
                            name = "Nintendo Switch Pro Controller"
                        else:
                            name = "PlayStation Compatible Controller"
                        return dev_path, name
    except Exception:
        pass
    return None, "Không tìm thấy tay cầm có con quay"


class MotionGyroEngine:
    """
    Engine con quay chuyển động đa năng:
    - Đọc raw sensor packet trực tiếp từ tay cầm qua Windows HID
    - Gyro-to-Mouse Aiming (L2 ADS hoặc Always-On)
    - Cemuhook UDP Motion Server (127.0.0.1:26760)
    """

    def __init__(self):
        self._running = False
        self._device_handle = None
        self._device_path = None
        self._device_name = "Chưa kết nối"
        self._worker_thread: Optional[threading.Thread] = None
        self._dsu_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Cấu hình Gyro Aiming
        self.aiming_enabled = False
        self.aiming_mode = "l2"        # "l2" (khi giữ L2) hoặc "always"
        self.sensitivity = 1.0         # 0.5 đến 3.0
        self.deadzone = 2.0            # lọc rung nhẹ dưới 2 deg/s
        self.invert_y = False
        
        # Cấu hình DSU Server
        self.dsu_enabled = False
        self.dsu_port = 26760
        self._dsu_socket: Optional[socket.socket] = None
        self._dsu_clients = {}  # { (ip, port): last_seen_ts }
        
        # State thời gian thực
        self._latest_state = {
            "connected": False,
            "device_name": "Chưa kết nối",
            "pitch": 0.0,
            "yaw": 0.0,
            "roll": 0.0,
            "accel_x": 0.0,
            "accel_y": 0.0,
            "accel_z": 0.0,
            "l2_trigger": 0,
            "r2_trigger": 0,
            "updated_at": 0.0
        }
        self._lock = threading.Lock()

    def get_hardware_status(self) -> Dict[str, Any]:
        """Kiểm tra phần cứng con quay trên máy."""
        path, name = find_motion_controller_device()
        is_ready = bool(path)
        return {
            "supported": is_ready,
            "device_name": name if is_ready else "Không phát hiện tay cầm có con quay",
            "device_path": path or "",
            "has_gyro": is_ready,
            "has_accel": is_ready,
            "running": self._running,
            "aiming_active": self.aiming_enabled and self._running,
            "dsu_active": self.dsu_enabled and self._running
        }

    def get_live_state(self) -> Dict[str, Any]:
        """Trả về giá trị cảm biến thời gian thực cho UI Live Visualizer."""
        with self._lock:
            return dict(self._latest_state)

    def start(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """Khởi động luồng đọc con quay và các dịch vụ đi kèm."""
        if self._running:
            return True

        if config:
            self.aiming_enabled = bool(config.get("aiming_enabled", True))
            self.aiming_mode = config.get("aiming_mode", "l2")
            self.sensitivity = float(config.get("sensitivity", 1.0))
            self.deadzone = float(config.get("deadzone", 2.0))
            self.invert_y = bool(config.get("invert_y", False))
            self.dsu_enabled = bool(config.get("dsu_enabled", False))

        path, name = find_motion_controller_device()
        if not path:
            return False

        h = k32.CreateFileW(
            path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, 0, None
        )
        if h == -1 or h == 0 or h == 0xFFFFFFFFFFFFFFFF:
            h = k32.CreateFileW(
                path, 0,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None, OPEN_EXISTING, 0, None
            )
        if h == -1 or h == 0 or h == 0xFFFFFFFFFFFFFFFF:
            return False

        self._device_handle = h
        self._device_path = path
        self._device_name = name
        self._stop_event.clear()
        self._running = True

        # 1. Khởi chạy luồng đọc cảm biến chính
        self._worker_thread = threading.Thread(target=self._sensor_loop, daemon=True)
        self._worker_thread.start()

        # 2. Khởi chạy DSU UDP Server nếu được bật
        if self.dsu_enabled:
            self._start_dsu_server()

        return True

    def stop(self):
        """Dừng an toàn mọi luồng và giải phóng tay cầm."""
        self._running = False
        self._stop_event.set()
        
        if self._device_handle:
            try:
                k32.CloseHandle(self._device_handle)
            except Exception:
                pass
            self._device_handle = None

        if self._dsu_socket:
            try:
                self._dsu_socket.close()
            except Exception:
                pass
            self._dsu_socket = None

        with self._lock:
            self._latest_state["connected"] = False

    def _sensor_loop(self):
        """Vòng lặp đọc gói tin HID liên tục từ tay cầm PS4/PS5 (~200Hz)."""
        buf = (ctypes.c_ubyte * 64)()
        read_bytes = wintypes.DWORD()
        h = self._device_handle

        smooth_dx = 0.0
        smooth_dy = 0.0

        while self._running and not self._stop_event.is_set():
            res = k32.ReadFile(h, ctypes.byref(buf), 64, ctypes.byref(read_bytes), None)
            if not res or read_bytes.value < 25:
                time.sleep(0.01)
                continue

            data = bytes(buf[:read_bytes.value])
            # Bóc tách dữ liệu DS4 qua USB:
            # Bytes 13..18: Gyro Pitch, Yaw, Roll (int16 signed)
            # Bytes 19..24: Accel X, Y, Z (int16 signed)
            # Byte 8: L2 trigger (0..255)
            # Byte 9: R2 trigger (0..255)
            pitch, yaw, roll = struct.unpack_from('<hhh', data, 13)
            ax, ay, az = struct.unpack_from('<hhh', data, 19)
            l2 = data[8]
            r2 = data[9]

            # Chuyển đổi chuẩn hóa:
            # DualShock 4: ~16 LSB per deg/s
            deg_pitch = pitch / 16.0
            deg_yaw = yaw / 16.0
            deg_roll = roll / 16.0

            # Accel: ~8192 LSB per g
            acc_x = ax / 8192.0
            acc_y = ay / 8192.0
            acc_z = az / 8192.0

            with self._lock:
                self._latest_state.update({
                    "connected": True,
                    "device_name": self._device_name,
                    "pitch": deg_pitch,
                    "yaw": deg_yaw,
                    "roll": deg_roll,
                    "accel_x": acc_x,
                    "accel_y": acc_y,
                    "accel_z": acc_z,
                    "l2_trigger": l2,
                    "r2_trigger": r2,
                    "updated_at": time.time()
                })

            # Xử lý Gyro Aiming (ngắm bắn chuột)
            if self.aiming_enabled:
                should_aim = (self.aiming_mode == "always") or (self.aiming_mode == "l2" and l2 > 30)
                if should_aim:
                    # Lọc deadzone chống rung tay
                    raw_yaw = deg_yaw if abs(deg_yaw) >= self.deadzone else 0.0
                    raw_pitch = deg_pitch if abs(deg_pitch) >= self.deadzone else 0.0

                    if raw_yaw != 0.0 or raw_pitch != 0.0:
                        # Tỷ lệ nhạy
                        scale = 0.5 * self.sensitivity
                        target_dx = -raw_yaw * scale
                        target_dy = (-raw_pitch if not self.invert_y else raw_pitch) * scale

                        # Lọc mượt EMA (Exponential Moving Average)
                        smooth_dx = smooth_dx * 0.3 + target_dx * 0.7
                        smooth_dy = smooth_dy * 0.3 + target_dy * 0.7

                        idx = int(smooth_dx)
                        idy = int(smooth_dy)
                        if idx != 0 or idy != 0:
                            user32.mouse_event(MOUSEEVENTF_MOVE, idx, idy, 0, 0)
                            smooth_dx -= idx
                            smooth_dy -= idy
                else:
                    smooth_dx = 0.0
                    smooth_dy = 0.0

            # Gửi gói tin cho client DSU nếu có client kết nối
            if self.dsu_enabled and self._dsu_clients and self._dsu_socket:
                self._broadcast_dsu_packet(data, deg_pitch, deg_yaw, deg_roll, acc_x, acc_y, acc_z)

        with self._lock:
            self._latest_state["connected"] = False

    # =========================================================================
    # CEMUHOOK DSU UDP SERVER (127.0.0.1:26760)
    # =========================================================================
    def _start_dsu_server(self):
        """Khởi tạo máy chủ UDP Motion Server theo chuẩn Cemuhook."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", self.dsu_port))
            sock.settimeout(0.5)
            self._dsu_socket = sock
            self._dsu_thread = threading.Thread(target=self._dsu_listen_loop, daemon=True)
            self._dsu_thread.start()
        except Exception as e:
            print(f"[DSU Server Warning]: Không thể lắng nghe trên cổng {self.dsu_port}: {e}")

    def _dsu_listen_loop(self):
        """Lắng nghe yêu cầu đăng ký nhận motion từ Cemu/Yuzu/Ryujinx."""
        while self._running and not self._stop_event.is_set():
            try:
                data, addr = self._dsu_socket.recvfrom(1024)
                if len(data) < 16:
                    continue
                magic, ver, length, crc, client_id = struct.unpack_from('<4sHHII', data, 0)
                if magic != b'DSUC':
                    continue

                event_type = struct.unpack_from('<I', data, 16)[0]
                now = time.time()
                self._dsu_clients[addr] = now

                # 1. Version Request (0x100000)
                if event_type == 0x100000:
                    resp = self._build_dsu_header(0x100000, struct.pack('<H', 1001))
                    self._dsu_socket.sendto(resp, addr)

                # 2. List Ports Request (0x100001)
                elif event_type == 0x100001:
                    pad_info = struct.pack(
                        '<BBBB6sB',
                        0,      # Pad id 0
                        2,      # Connected
                        2,      # Full Gyro (DualShock 4)
                        1,      # USB
                        b'\x00\x1A\x7D\xDA\x71\x13', # Fake MAC
                        0x05    # Battery Full
                    ) + b'\x01' # Is connected
                    resp = self._build_dsu_header(0x100001, pad_info)
                    self._dsu_socket.sendto(resp, addr)

                # 3. Data Request (0x100002) - Client đăng ký nhận stream
                elif event_type == 0x100002:
                    pass

            except socket.timeout:
                pass
            except Exception:
                pass

    def _build_dsu_header(self, event_type: int, payload: bytes) -> bytes:
        """Đóng gói khung bản tin chuẩn Cemuhook DSU kèm mã kiểm tra CRC32."""
        length = len(payload) + 4
        server_id = 0x56494554  # "VIET"
        header_no_crc = struct.pack('<4sHHII', b'DSUS', 1001, length, 0, server_id) + struct.pack('<I', event_type) + payload
        crc = zlib.crc32(header_no_crc) & 0xFFFFFFFF
        return struct.pack('<4sHHI', b'DSUS', 1001, length, crc) + struct.pack('<I', server_id) + struct.pack('<I', event_type) + payload

    def _broadcast_dsu_packet(self, raw_data: bytes, p: float, y: float, r: float, ax: float, ay: float, az: float):
        """Phát sóng chuyển động cho toàn bộ client giả lập đang lắng nghe."""
        now = time.time()
        # Dọn client không ping quá 10 giây
        stale = [addr for addr, last in self._dsu_clients.items() if now - last > 10.0]
        for s in stale:
            del self._dsu_clients[s]

        if not self._dsu_clients or not self._dsu_socket:
            return

        # Đóng gói bản tin DSUS_ActualData (0x100002)
        # Pad data format:
        # Pad ID (1) + State (1) + Model (1) + Connection (1) + MAC (6) + Battery (1) + Connected (1) + PacketCount (4)
        # Buttons1 (1) + Buttons2 (1) + PS (1) + Touch (1) + LX (1) + LY (1) + RX (1) + RY (1) + DPad (4) + Triggers (2)
        # Motion Timestamp (8) + Accel X,Y,Z (12) + Gyro Pitch,Yaw,Roll (12)
        packet_count = int(now * 1000) & 0xFFFFFFFF
        ts_micros = int(now * 1000000)

        data_payload = struct.pack(
            '<BBBB6sBBI',
            0, 2, 2, 1, b'\x00\x1A\x7D\xDA\x71\x13', 0x05, 1, packet_count
        ) + bytes(raw_data[1:13]) + struct.pack(
            '<Qffffff',
            ts_micros,
            ax, ay, az,
            p, y, r
        )

        packet = self._build_dsu_header(0x100002, data_payload)
        for client_addr in list(self._dsu_clients.keys()):
            try:
                self._dsu_socket.sendto(packet, client_addr)
            except Exception:
                pass


# Singleton toàn cục
MOTION_GYRO = MotionGyroEngine()
