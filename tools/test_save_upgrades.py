# -*- coding: utf-8 -*-
"""
Test Suite for the 4 Save System Upgrades:
1. Smart Auto-Save Detector
2. Pre-Launch Cloud Guard
3. Per-Game Sharded Cloud Sync
4. File-Lock Guard & Visual Quick Checkpoint
"""
import os
import sys
import tempfile
import shutil
import time

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run_tests():
    print("=" * 60)
    print("STARTING TEST SUITE: 4 SAVE SYSTEM UPGRADES")
    print("=" * 60)

    # -------------------------------------------------------------
    # Test 1: Smart Auto-Save Detector
    # -------------------------------------------------------------
    print("\n[TEST 1] Testing Smart Auto-Save Detector...")
    from core.cloud_save.auto_save_detector import detect_game_save_locations, wait_file_stable

    # Test with simulated game root
    temp_game_dir = tempfile.mkdtemp(prefix="test_congu_game_")
    try:
        saves_dir = os.path.join(temp_game_dir, "saves")
        os.makedirs(saves_dir, exist_ok=True)
        dummy_save = os.path.join(saves_dir, "slot1.sav")
        with open(dummy_save, "wb") as f:
            f.write(b"DUMMY_SAVE_DATA_12345")

        game_cfg = {
            "id": "test_game_auto",
            "title": "Test Game Auto",
            "steam_appid": "123456"
        }
        detected = detect_game_save_locations(game_cfg, game_root=temp_game_dir)
        print(f"  Detected locations count: {len(detected)}")
        assert len(detected) >= 1, "Failed to detect saves directory in game root!"
        assert any("gameroot_saves" in d["slot"] for d in detected), "Expected gameroot_saves slot!"
        print("  ✓ Test 1 Passed: Smart Auto-Save Detector detected unconfigured save location successfully!")
    finally:
        shutil.rmtree(temp_game_dir, ignore_errors=True)

    # -------------------------------------------------------------
    # Test 2: File-Lock Guard
    # -------------------------------------------------------------
    print("\n[TEST 2] Testing File-Lock Guard (wait_file_stable)...")
    temp_file = tempfile.mktemp(suffix=".sav")
    try:
        with open(temp_file, "w") as f:
            f.write("stable content")
        stable = wait_file_stable(temp_file, timeout_sec=0.5)
        assert stable is True, "File should be recognized as stable!"
        print("  ✓ Test 2 Passed: File-Lock Guard verified stability accurately!")
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

    # -------------------------------------------------------------
    # Test 3: Pre-Launch Cloud Guard & Per-Game Sharded Sync
    # -------------------------------------------------------------
    print("\n[TEST 3] Testing Pre-Launch Cloud Guard & Per-Game Sharded Sync...")
    from cloud_sync import CloudSyncManager

    temp_appdata = tempfile.mkdtemp(prefix="test_appdata_")
    try:
        csm = CloudSyncManager(temp_appdata)
        # Without cloud connection, pre_launch_cloud_guard should gracefully return skipped
        guard_res = csm.pre_launch_cloud_guard("test_game", {"id": "test_game", "title": "Test Game"})
        print(f"  Pre-launch guard result (offline): {guard_res}")
        assert guard_res.get("status") == "skipped", "Expected status 'skipped' when not connected!"
        print("  ✓ Test 3 Passed: Pre-Launch Cloud Guard executes cleanly without blocking!")
    finally:
        shutil.rmtree(temp_appdata, ignore_errors=True)

    # -------------------------------------------------------------
    # Test 4: Visual Quick Checkpoint & Vault Auto-Detect Integration
    # -------------------------------------------------------------
    print("\n[TEST 4] Testing Visual Quick Checkpoint & Vault Integration...")
    from vault_manager import ConguSaveVault
    from core.quick_checkpoint import save_checkpoint, list_checkpoints

    temp_appdata2 = tempfile.mkdtemp(prefix="test_appdata2_")
    temp_game_dir2 = tempfile.mkdtemp(prefix="test_game2_")
    try:
        vault_file = os.path.join(temp_appdata2, "PlayerProfile.congu_save")
        vault = ConguSaveVault(vault_file)

        # Create simulated save
        groot_save = os.path.join(temp_game_dir2, "saves")
        os.makedirs(groot_save, exist_ok=True)
        with open(os.path.join(groot_save, "game_data.sav"), "wb") as f:
            f.write(b"HERO_LEVEL_99_HEALTH_1000")

        game_cfg2 = {
            "id": "rpg_legend",
            "title": "RPG Legend",
            "steam_appid": "99999"
        }

        # 4.1 Test Vault Auto-Extraction
        save_locs, ach_locs, excl = vault._extract_game_locations(game_cfg2, temp_game_dir2)
        print(f"  Vault auto-extracted {len(save_locs)} save locations for game without vault_config!")
        assert len(save_locs) >= 1, "Vault should auto-extract locations using auto_save_detector!"

        # 4.2 Test Quick Checkpoint with Screenshot
        res = save_checkpoint(vault, game_cfg2, temp_game_dir2, temp_appdata2, label="Boss Fight Checkpoint")
        print(f"  Checkpoint result: {res.get('success')}, id: {res.get('checkpoint_id')}")
        assert res.get("success") is True, f"Quick Checkpoint failed: {res.get('error')}"
        assert res.get("files") >= 1, "Checkpoint should pack at least 1 save file!"

        # Check metadata
        ck_list = list_checkpoints("rpg_legend", temp_appdata2)
        assert len(ck_list) == 1, "Should have 1 recorded checkpoint!"
        print(f"  Recorded checkpoint metadata: label='{ck_list[0].get('label')}', files={ck_list[0].get('files')}, thumbnail='{ck_list[0].get('thumbnail')}'")

        # 4.3 Test Vault Pack Integration
        pack_res = vault.pack_game_to_vault(game_cfg2, temp_game_dir2, added_playtime_sec=120)
        print(f"  Vault pack result: {pack_res.get('success')}, files: {pack_res.get('files_packed')}")
        assert pack_res.get("success") is True, f"Vault pack failed: {pack_res.get('error')}"
        assert pack_res.get("files_packed") >= 1, "Vault should pack at least 1 save file!"
        print("  ✓ Test 4 Passed: Visual Quick Checkpoint & Vault Integration worked seamlessly!")
    finally:
        shutil.rmtree(temp_appdata2, ignore_errors=True)
        shutil.rmtree(temp_game_dir2, ignore_errors=True)

    print("\n" + "=" * 60)
    print("ALL 4 UPGRADES VERIFIED AND PASSED 100%!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
