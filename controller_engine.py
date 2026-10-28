"""
CỔ NGỮ (VietModHub Pro) - Steam Input Offline & Controller Engine
Hệ thống giả lập tay cầm chuẩn Steam Input cho game Offline:
1. Nhận diện mọi loại tay cầm (Sony DualShock 4 / DualSense, Xbox, Switch Pro, DirectInput).
2. XInput Wrapper Injection & Clean Exit (Tự nạp xinput1_3/4.dll vào game x64/x86 và dọn sạch khi game tắt).
3. SDL2 GameControllerDB Mapping (Tự thiết lập SDL_GAMECONTROLLERCONFIG cho game Unity/Indie).
4. Virtual Keyboard & Mouse Mapper (Cho game cổ chỉ có phím/chuột qua Windows SendInput ScanCodes).
5. Lưu cấu hình tay cầm từng game vào chung file PlayerProfile.congu_save!
"""

import os
import sys
import time
import json
import shutil
import ctypes
import threading
from ctypes import wintypes
from typing import Dict, List, Optional, Any

if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr is not None and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Windows Multimedia API definitions (winmm.dll)
class JOYCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("szPname", wintypes.WCHAR * 32),
        ("wXmin", wintypes.UINT),
        ("wXmax", wintypes.UINT),
        ("wYmin", wintypes.UINT),
        ("wYmax", wintypes.UINT),
        ("wZmin", wintypes.UINT),
        ("wZmax", wintypes.UINT),
        ("wNumButtons", wintypes.UINT),
        ("wPeriodMin", wintypes.UINT),
        ("wPeriodMax", wintypes.UINT),
        ("wRmin", wintypes.UINT),
        ("wRmax", wintypes.UINT),
        ("wUmin", wintypes.UINT),
        ("wUmax", wintypes.UINT),
        ("wVmin", wintypes.UINT),
        ("wVmax", wintypes.UINT),
        ("wCaps", wintypes.UINT),
        ("wMaxAxes", wintypes.UINT),
        ("wNumAxes", wintypes.UINT),
        ("wMaxButtons", wintypes.UINT),
        ("szRegKey", wintypes.WCHAR * 32),
        ("szOEMVxD", wintypes.WCHAR * 260),
    ]

class JOYINFOEX(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("dwXpos", wintypes.DWORD),
        ("dwYpos", wintypes.DWORD),
        ("dwZpos", wintypes.DWORD),
        ("dwRpos", wintypes.DWORD),
        ("dwUpos", wintypes.DWORD),
        ("dwVpos", wintypes.DWORD),
        ("dwButtons", wintypes.DWORD),
        ("dwButtonNumber", wintypes.DWORD),
        ("dwPOV", wintypes.DWORD),
        ("dwReserved1", wintypes.DWORD),
        ("dwReserved2", wintypes.DWORD),
    ]

# XInput Structs
class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", wintypes.BYTE),
        ("bRightTrigger", wintypes.BYTE),
        ("sThumbLX", wintypes.SHORT),
        ("sThumbLY", wintypes.SHORT),
        ("sThumbRX", wintypes.SHORT),
        ("sThumbRY", wintypes.SHORT),
    ]

class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", wintypes.DWORD),
        ("Gamepad", XINPUT_GAMEPAD),
    ]

class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [
        ("wLeftMotorSpeed", wintypes.WORD),
        ("wRightMotorSpeed", wintypes.WORD),
    ]

# Windows SendInput Structs
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulong),
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulong),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUT_UNION),
    ]


# Mapping Hardware Scan Codes for common keys
VK_MAP = {
    "UP": 0x48,     # Arrow Up (E0 48)
    "DOWN": 0x50,   # Arrow Down
    "LEFT": 0x4B,   # Arrow Left
    "RIGHT": 0x4D,  # Arrow Right
    "W": 0x11,
    "A": 0x1E,
    "S": 0x1F,
    "D": 0x20,
    "SPACE": 0x39,
    "ENTER": 0x1C,
    "ESCAPE": 0x01,
    "TAB": 0x0F,
    "SHIFT": 0x2A,
    "CTRL": 0x1D,
    "ALT": 0x38,
    "J": 0x24,
    "K": 0x25,
    "L": 0x26,
    "U": 0x16,
    "I": 0x17,
    "O": 0x18,
    "Z": 0x2C,
    "X": 0x2D,
    "C": 0x2E,
}


def get_pe_architecture(exe_path: str) -> str:
    """Xác định file .exe là 64-bit (x64) hay 32-bit (x86)."""
    try:
        with open(exe_path, "rb") as f:
            if f.read(2) != b"MZ":
                return "x64"
            f.seek(0x3C)
            pe_offset = int.from_bytes(f.read(4), "little")
            f.seek(pe_offset)
            if f.read(4) != b"PE\x00\x00":
                return "x64"
            machine = int.from_bytes(f.read(2), "little")
            if machine == 0x8664:
                return "x64"
            elif machine == 0x014C:
                return "x86"
    except Exception as e:
        print(f"[PE Architecture Check Warning]: {e}")
    return "x64"


class ControllerEngine:
    """
    Quản lý tính năng Steam Input Offline cho CỔ NGỮ.
    """
    def __init__(self, tools_dir: str, vault_getter=None):
        self.tools_dir = os.path.abspath(tools_dir)
        self.gamepad_tools_dir = os.path.join(self.tools_dir, "gamepad")
        self.vault_getter = vault_getter
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.mapper_thread: Optional[threading.Thread] = None
        self.mapper_stop_event = threading.Event()
        self.active_game_id: Optional[str] = None
        
        # Windows libraries
        try:
            self.winmm = ctypes.windll.winmm
        except Exception:
            self.winmm = None
            
        self.xinput = None
        for dll_name in ["xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"]:
            try:
                self.xinput = ctypes.windll.LoadLibrary(dll_name)
                break
            except Exception:
                pass

    # ========================================================
    # 1. NHẬN DIỆN TAY CẦM KẾT NỐI (DEVICE DISCOVERY)
    # ========================================================
    def detect_controllers(self) -> List[Dict[str, Any]]:
        """Quét và trả về danh sách toàn bộ tay cầm đang kết nối với máy tính."""
        controllers = []
        seen_names = set()

        # 1. Quét qua XInput (Xbox & tương thích)
        if self.xinput:
            for i in range(4):
                try:
                    st = XINPUT_STATE()
                    if self.xinput.XInputGetState(i, ctypes.byref(st)) == 0:
                        cid = f"xinput_{i}"
                        controllers.append({
                            "id": cid,
                            "index": i,
                            "api": "xinput",
                            "name": f"Xbox 360 / Xbox One Controller (Slot {i+1})",
                            "type": "xbox",
                            "type_label": "Microsoft Xbox Controller",
                            "icon": "xbox",
                            "vendor_id": "0x045E",
                            "product_id": "0x028E",
                            "is_xinput_native": True,
                            "buttons_count": 14,
                            "axes_count": 6
                        })
                        seen_names.add(f"slot_{i}")
                except Exception:
                    pass

        # 2. Quét qua winmm DirectInput (PS4, PS5, Switch, Generic)
        if self.winmm:
            try:
                num_devs = self.winmm.joyGetNumDevs()
                for slot in range(min(num_devs, 16)):
                    info = JOYINFOEX()
                    info.dwSize = ctypes.sizeof(JOYINFOEX)
                    info.dwFlags = 0xFF  # JOY_RETURNALL
                    if self.winmm.joyGetPosEx(slot, ctypes.byref(info)) == 0:
                        caps = JOYCAPSW()
                        self.winmm.joyGetDevCapsW(slot, ctypes.byref(caps), ctypes.sizeof(JOYCAPSW))
                        pname = str(caps.szPname)
                        mid = caps.wMid
                        pid = caps.wPid

                        # Phân loại tay cầm
                        ctype = "generic"
                        type_label = "Tay cầm Generic DirectInput / USB"
                        icon = "gamepad-2"

                        if mid == 0x054C or "dualshock" in pname.lower() or "dualsense" in pname.lower() or "wireless controller" in pname.lower():
                            ctype = "playstation"
                            type_label = "Sony PlayStation (DualShock 4 / DualSense)"
                            icon = "playstation"
                        elif mid == 0x045E or "xbox" in pname.lower():
                            ctype = "xbox"
                            type_label = "Microsoft Xbox Controller"
                            icon = "xbox"
                        elif mid == 0x057E or "switch" in pname.lower() or "pro controller" in pname.lower():
                            ctype = "switch"
                            type_label = "Nintendo Switch Pro Controller"
                            icon = "gamepad"

                        # Tránh duplicate nếu XInput đã nhận
                        is_dup = False
                        if ctype == "xbox" and len([c for c in controllers if c["type"] == "xbox"]) > 0 and slot < 4:
                            is_dup = True

                        if not is_dup:
                            controllers.append({
                                "id": f"dinput_{slot}",
                                "index": slot,
                                "api": "directinput",
                                "name": pname or f"Tay cầm DirectInput #{slot+1}",
                                "type": ctype,
                                "type_label": type_label,
                                "icon": icon,
                                "vendor_id": hex(mid),
                                "product_id": hex(pid),
                                "is_xinput_native": False,
                                "buttons_count": caps.wNumButtons,
                                "axes_count": caps.wNumAxes
                            })
            except Exception as e:
                print(f"[Detect Controllers WinMM Warning]: {e}")

        return controllers

    def test_vibration(self, controller_index: int = 0, duration_sec: float = 0.5) -> bool:
        """Kích hoạt rung thử nghiệm phản hồi xúc giác (Haptic Feedback) trên tay cầm."""
        if self.xinput:
            try:
                vib = XINPUT_VIBRATION()
                vib.wLeftMotorSpeed = 45000   # Rung trầm mạnh
                vib.wRightMotorSpeed = 45000  # Rung nhẹ nhanh
                self.xinput.XInputSetState(controller_index, ctypes.byref(vib))
                
                def stop_vib():
                    time.sleep(duration_sec)
                    stop_v = XINPUT_VIBRATION()
                    stop_v.wLeftMotorSpeed = 0
                    stop_v.wRightMotorSpeed = 0
                    self.xinput.XInputSetState(controller_index, ctypes.byref(stop_v))
                    
                threading.Thread(target=stop_vib, daemon=True).start()
                return True
            except Exception as e:
                print(f"[Test Vibration Error]: {e}")
        return False

    def _cleanup_game_dir_wrappers(self, game_dir: str, candidate_exe: str = ""):
        """Dọn dẹp triệt để các file DLL và INI giả lập cũ khỏi thư mục game."""
        for fn in ["xinput1_3.dll", "xinput1_4.dll", "x360ce.ini"]:
            fp = os.path.join(game_dir, fn)
            if os.path.exists(fp):
                try:
                    if fn.endswith(".ini"):
                        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                            c = f.read()
                        if "VietModHub" in c or "x360ce" in c or "PromptOnInit" in c:
                            os.remove(fp)
                    else:
                        arch = get_pe_architecture(candidate_exe) if candidate_exe else "x64"
                        src_dll = os.path.join(self.gamepad_tools_dir, arch, "xinput1_3.dll")
                        if os.path.exists(src_dll) and os.path.getsize(fp) == os.path.getsize(src_dll):
                            os.remove(fp)
                except Exception as e:
                    print(f"[Cleanup Wrapper Warning]: {e}")

    def get_universal_x360ce_ini_content(self) -> str:
        """Tạo nội dung file cấu hình x360ce.ini ánh xạ vạn năng cho mọi tay cầm, triệt tiêu hoàn toàn popup cảnh báo."""
        return """[Options]
UseInitBeep=0
Log=0
Console=0
DebugMode=0
InternetDatabaseUrl=
InternetFeatures=0
InternetAutodefer=0
InternetCheckVersion=0
Version=1
PromptOnInit=0

[InputHook]
HookMode=1

[PAD1]
AutoSelectController=1
ControllerType=1
DInput=1
PassThrough=0
A=1
B=2
X=3
Y=4
Left Shoulder=5
Right Shoulder=6
Back=7
Start=8
Left Thumb=9
Right Thumb=10
DPad=POV 1
Left Motor Period=100
Right Motor Period=100
Left Trigger=a-3
Right Trigger=a+3
Left Analog X=1
Left Analog Y=-2
Right Analog X=3
Right Analog Y=-6
"""

    def prepare_game_launch(self, game_id: str, candidate_exe: str, custom_env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Hook tiền khởi chạy: Chuẩn bị môi trường Steam Input cho game.
        Tự động nạp XInput wrapper vào thư mục .exe hoặc thiết lập biến môi trường SDL2.
        Tích hợp Smart Guard: Chỉ can thiệp khi thực sự cần thiết, tuyệt đối không làm phiền game thủ.
        """
        if not candidate_exe or not os.path.isfile(candidate_exe):
            return {"success": False, "message": "Không tìm thấy file thực thi của game!"}

        game_dir = os.path.dirname(os.path.abspath(candidate_exe))
        cfg = self.get_game_gamepad_config(game_id)
        
        # 1. Nếu tính năng TẮT: Tự động dọn dẹp các file wrapper cũ (nếu có) để game chạy nguyên bản 100%
        if not cfg.get("enabled", False):
            self._cleanup_game_dir_wrappers(game_dir, candidate_exe)
            return {"success": True, "applied": False, "message": "Tính năng giả lập tay cầm đang tắt cho game này."}

        # 2. SMART GUARD: Kiểm tra tay cầm thực tế đang kết nối
        controllers = self.detect_controllers()
        if not controllers:
            self._cleanup_game_dir_wrappers(game_dir, candidate_exe)
            return {
                "success": True,
                "applied": False,
                "message": "Không phát hiện tay cầm kết nối, chạy game nguyên bản cho chuột + bàn phím."
            }

        # Nếu tất cả tay cầm kết nối đều là XInput Native (Xbox Controller hoặc đã qua DS4Windows)
        has_non_native = any(not c.get("is_xinput_native", False) for c in controllers)
        if not has_non_native:
            self._cleanup_game_dir_wrappers(game_dir, candidate_exe)
            return {
                "success": True,
                "applied": False,
                "message": "Đã phát hiện tay cầm Xbox / XInput Native, game sẽ tự nhận diện trực tiếp không cần x360ce."
            }

        # 3. KHI CÓ TAY CẦM DIRECTINPUT / PLAYSTATION CẦN GIẢ LẬP:
        mode = cfg.get("mode", "xinput_wrapper")
        injected_files = []

        # Chế độ XInput Wrapper (cho game Unity, Unreal, C++)
        if mode == "xinput_wrapper":
            arch = get_pe_architecture(candidate_exe)
            source_dir = os.path.join(self.gamepad_tools_dir, arch)

            source_dll = os.path.join(source_dir, "xinput1_3.dll")
            if os.path.exists(source_dll):
                source_size = os.path.getsize(source_dll)

                # Copy / Track xinput1_3.dll
                target_1_3 = os.path.join(game_dir, "xinput1_3.dll")
                if not os.path.exists(target_1_3):
                    shutil.copy2(source_dll, target_1_3)
                    injected_files.append(target_1_3)
                elif os.path.getsize(target_1_3) == source_size:
                    injected_files.append(target_1_3)

                # Copy / Track xinput1_4.dll
                target_1_4 = os.path.join(game_dir, "xinput1_4.dll")
                if not os.path.exists(target_1_4):
                    shutil.copy2(source_dll, target_1_4)
                    injected_files.append(target_1_4)
                elif os.path.getsize(target_1_4) == source_size:
                    injected_files.append(target_1_4)

                # Tạo / Track x360ce.ini
                target_ini = os.path.join(game_dir, "x360ce.ini")
                ini_content = self.get_universal_x360ce_ini_content()
                if not os.path.exists(target_ini):
                    with open(target_ini, "w", encoding="utf-8") as f:
                        f.write(ini_content)
                    injected_files.append(target_ini)
                else:
                    try:
                        with open(target_ini, "r", encoding="utf-8", errors="ignore") as f:
                            if "VietModHub" in f.read() or "x360ce" in f.read():
                                injected_files.append(target_ini)
                    except Exception:
                        pass

        # 2. Chế độ SDL2 Controller Database
        db_path = os.path.join(self.gamepad_tools_dir, "gamecontrollerdb.txt")
        if os.path.exists(db_path) and custom_env is not None:
            try:
                # Đọc database và đặt biến môi trường SDL_GAMECONTROLLERCONFIG
                custom_env["SDL_GAMECONTROLLERCONFIG_FILE"] = db_path
            except Exception:
                pass

        # 3. Chế độ Virtual Keyboard & Mouse Mapper (cho game cổ)
        if mode == "keyboard_mapper":
            preset = cfg.get("preset", "platformer")
            custom_map = cfg.get("custom_mappings", {})
            self.start_keyboard_mapper(game_id, preset=preset, custom_map=custom_map)

        self.active_sessions[game_id] = {
            "game_dir": game_dir,
            "candidate_exe": candidate_exe,
            "mode": mode,
            "injected_files": injected_files,
            "launched_at": time.time()
        }

        return {
            "success": True,
            "applied": True,
            "enabled": True,
            "mode": mode,
            "injected_count": len(injected_files),
            "injected_files": [os.path.basename(f) for f in injected_files]
        }

    def handle_game_exit(self, game_id: str):
        """
        Hook hậu thoát game: Tự động dọn dẹp sạch sẽ toàn bộ file DLL/INI wrapper đã inject
        và dừng luồng Virtual Keyboard Mapper.
        """
        # 1. Dừng mapper nếu đang chạy cho game này
        if self.active_game_id == game_id:
            self.stop_keyboard_mapper()

        # 2. Xóa sạch các file DLL / INI đã inject
        session = self.active_sessions.pop(game_id, None)
        if session:
            injected = session.get("injected_files", [])
            for file_path in injected:
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        print(f"[SteamInput CleanExit] Đã dọn dẹp file wrapper: {os.path.basename(file_path)}")
                    except Exception as e:
                        print(f"[SteamInput CleanExit Warning] Không thể xóa {file_path}: {e}")

    # ========================================================
    # 3. VIRTUAL KEYBOARD & MOUSE MAPPER (CHO GAME CỔ)
    # ========================================================
    def start_keyboard_mapper(self, game_id: str, preset: str = "platformer", custom_map: Optional[Dict[str, str]] = None):
        """Khởi động luồng đọc tay cầm và ánh xạ thành phím bấm bàn phím (SendInput)."""
        self.stop_keyboard_mapper()
        self.active_game_id = game_id
        self.mapper_stop_event.clear()

        # Xây dựng bảng ánh xạ nút
        active_map = {}
        if preset == "rpg_vn":
            active_map = {
                "DPAD_UP": "UP",
                "DPAD_DOWN": "DOWN",
                "DPAD_LEFT": "LEFT",
                "DPAD_RIGHT": "RIGHT",
                "BTN_A": "ENTER",
                "BTN_B": "ESCAPE",
                "BTN_X": "CTRL",
                "BTN_Y": "SPACE",
                "BTN_START": "ENTER",
                "BTN_SELECT": "TAB",
                "BTN_LB": "SHIFT",
                "BTN_RB": "Z",
            }
        else:  # platformer default
            active_map = {
                "DPAD_UP": "W",
                "DPAD_DOWN": "S",
                "DPAD_LEFT": "A",
                "DPAD_RIGHT": "D",
                "BTN_A": "SPACE",
                "BTN_B": "ESCAPE",
                "BTN_X": "J",
                "BTN_Y": "K",
                "BTN_START": "ENTER",
                "BTN_SELECT": "TAB",
                "BTN_LB": "SHIFT",
                "BTN_RB": "L",
            }

        if custom_map:
            active_map.update(custom_map)

        self.mapper_thread = threading.Thread(
            target=self._mapper_worker_loop,
            args=(active_map,),
            daemon=True
        )
        self.mapper_thread.start()
        print(f"[ControllerEngine] Khởi động Virtual Keyboard Mapper cho '{game_id}' (Preset: {preset})")

    def stop_keyboard_mapper(self):
        """Dừng luồng mapper."""
        if self.mapper_thread and self.mapper_thread.is_alive():
            self.mapper_stop_event.set()
            self.mapper_thread.join(timeout=1.0)
            self.mapper_thread = None
        self.active_game_id = None

    def _mapper_worker_loop(self, key_map: Dict[str, str]):
        """Vòng lặp đọc gamepad 60Hz và gửi SendInput."""
        pressed_keys = set()
        user32 = ctypes.windll.user32

        def send_key(scan_code: int, is_down: bool):
            extra = ctypes.c_ulong(0)
            flags = KEYEVENTF_SCANCODE if is_down else (KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP)
            ii_ = _INPUT_UNION()
            ii_.ki = KEYBDINPUT(0, scan_code, flags, 0, ctypes.addressof(extra))
            x = INPUT(ctypes.c_ulong(INPUT_KEYBOARD), ii_)
            user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

        while not self.mapper_stop_event.is_set():
            time.sleep(0.016)  # ~60Hz
            current_active_keys = set()

            # Đọc XInput trước nếu có
            if self.xinput:
                try:
                    st = XINPUT_STATE()
                    if self.xinput.XInputGetState(0, ctypes.byref(st)) == 0:
                        wBtn = st.Gamepad.wButtons
                        if wBtn & 0x0001: current_active_keys.add(key_map.get("DPAD_UP"))
                        if wBtn & 0x0002: current_active_keys.add(key_map.get("DPAD_DOWN"))
                        if wBtn & 0x0004: current_active_keys.add(key_map.get("DPAD_LEFT"))
                        if wBtn & 0x0008: current_active_keys.add(key_map.get("DPAD_RIGHT"))
                        if wBtn & 0x1000: current_active_keys.add(key_map.get("BTN_A"))
                        if wBtn & 0x2000: current_active_keys.add(key_map.get("BTN_B"))
                        if wBtn & 0x4000: current_active_keys.add(key_map.get("BTN_X"))
                        if wBtn & 0x8000: current_active_keys.add(key_map.get("BTN_Y"))
                        if wBtn & 0x0100: current_active_keys.add(key_map.get("BTN_LB"))
                        if wBtn & 0x0200: current_active_keys.add(key_map.get("BTN_RB"))
                        if wBtn & 0x0010: current_active_keys.add(key_map.get("BTN_START"))
                        if wBtn & 0x0020: current_active_keys.add(key_map.get("BTN_SELECT"))
                        # Analog stick di chuyển
                        if st.Gamepad.sThumbLY > 16000: current_active_keys.add(key_map.get("DPAD_UP"))
                        elif st.Gamepad.sThumbLY < -16000: current_active_keys.add(key_map.get("DPAD_DOWN"))
                        if st.Gamepad.sThumbLX > 16000: current_active_keys.add(key_map.get("DPAD_RIGHT"))
                        elif st.Gamepad.sThumbLX < -16000: current_active_keys.add(key_map.get("DPAD_LEFT"))
                except Exception:
                    pass

            # Đọc winmm DirectInput nếu XInput không có phím
            elif self.winmm:
                try:
                    info = JOYINFOEX()
                    info.dwSize = ctypes.sizeof(JOYINFOEX)
                    info.dwFlags = 0xFF
                    if self.winmm.joyGetPosEx(0, ctypes.byref(info)) == 0:
                        btns = info.dwButtons
                        if btns & 0x01: current_active_keys.add(key_map.get("BTN_A"))
                        if btns & 0x02: current_active_keys.add(key_map.get("BTN_B"))
                        if btns & 0x04: current_active_keys.add(key_map.get("BTN_X"))
                        if btns & 0x08: current_active_keys.add(key_map.get("BTN_Y"))
                        if btns & 0x10: current_active_keys.add(key_map.get("BTN_LB"))
                        if btns & 0x20: current_active_keys.add(key_map.get("BTN_RB"))
                        if btns & 0x40: current_active_keys.add(key_map.get("BTN_SELECT"))
                        if btns & 0x80: current_active_keys.add(key_map.get("BTN_START"))
                        
                        # D-Pad POV
                        pov = info.dwPOV
                        if pov != 65535:
                            if pov in (0, 4500, 31500): current_active_keys.add(key_map.get("DPAD_UP"))
                            if pov in (9000, 4500, 13500): current_active_keys.add(key_map.get("DPAD_RIGHT"))
                            if pov in (18000, 13500, 22500): current_active_keys.add(key_map.get("DPAD_DOWN"))
                            if pov in (27000, 22500, 31500): current_active_keys.add(key_map.get("DPAD_LEFT"))
                except Exception:
                    pass

            current_active_keys.discard(None)

            # Phím mới bấm -> Nhấn xuống
            for k in current_active_keys - pressed_keys:
                sc = VK_MAP.get(k)
                if sc:
                    send_key(sc, True)

            # Phím vừa nhả -> Nhả ra
            for k in pressed_keys - current_active_keys:
                sc = VK_MAP.get(k)
                if sc:
                    send_key(sc, False)

            pressed_keys = current_active_keys

        # Nhả toàn bộ phím khi tắt luồng
        for k in pressed_keys:
            sc = VK_MAP.get(k)
            if sc:
                send_key(sc, False)

    # ========================================================
    # 4. TÍCH HỢP LƯU VÀO .congu_save (VAULT INTEGRATION)
    # ========================================================
    def get_game_gamepad_config(self, game_id: str) -> Dict[str, Any]:
        """Đọc cấu hình tay cầm của game từ file PlayerProfile.congu_save."""
        default_cfg = {
            "enabled": False,  # Mặc định TẮT! Chỉ bật khi người chơi cần giả lập cho tay cầm PS4/PS5/DInput
            "mode": "xinput_wrapper",  # "xinput_wrapper" | "keyboard_mapper"
            "preset": "platformer",    # "platformer" | "rpg_vn" | "custom"
            "vibration": True,
            "deadzone": 0.15,
            "custom_mappings": {}
        }
        if self.vault_getter:
            try:
                vault = self.vault_getter()
                if vault:
                    manifest = vault.read_manifest()
                    gstat = manifest.get("games", {}).get(game_id, {})
                    if "gamepad_config" in gstat:
                        default_cfg.update(gstat["gamepad_config"])
            except Exception as e:
                print(f"[Read Gamepad Config Warning]: {e}")
        return default_cfg

    def save_game_gamepad_config(self, game_id: str, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """Lưu cấu hình tay cầm của game thẳng vào file PlayerProfile.congu_save."""
        if not self.vault_getter:
            return {"success": False, "error": "Chưa khởi tạo Vault Manager!"}

        try:
            vault = self.vault_getter()
            manifest = vault.read_manifest()
            if "games" not in manifest:
                manifest["games"] = {}
            if game_id not in manifest["games"]:
                manifest["games"][game_id] = {
                    "title": game_id,
                    "playtime_seconds": 0,
                    "unlocked_achievements": []
                }

            current_cfg = manifest["games"][game_id].get("gamepad_config", {})
            current_cfg.update(new_config)
            manifest["games"][game_id]["gamepad_config"] = current_cfg
            manifest["updated_at"] = int(time.time())

            # Ghi đè nguyên tử vào file .congu_save
            import zipfile
            import tempfile
            vault_dir = os.path.dirname(vault.vault_path)
            temp_fd, temp_zip = tempfile.mkstemp(suffix=".congu_save_tmp", dir=vault_dir)
            os.close(temp_fd)

            try:
                with zipfile.ZipFile(vault.vault_path, "r") as old_zf, \
                     zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as new_zf:
                    for item in old_zf.infolist():
                        if item.filename != "profile_manifest.json":
                            new_zf.writestr(item, old_zf.read(item.filename))
                    new_zf.writestr("profile_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
                os.replace(temp_zip, vault.vault_path)
            finally:
                if os.path.exists(temp_zip):
                    try:
                        os.remove(temp_zip)
                    except OSError:
                        pass

            return {
                "success": True,
                "message": "Đã lưu cấu hình tay cầm vào Hồ Sơ CỔ NGỮ (.congu_save)!",
                "gamepad_config": current_cfg
            }
        except Exception as e:
            return {"success": False, "error": f"Lỗi khi lưu cấu hình tay cầm: {e}"}
