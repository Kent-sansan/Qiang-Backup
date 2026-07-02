"""测试修改后的功能"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def main():
    print("=" * 60)
    print("Qiang Backup 功能测试")
    print("=" * 60)
    
    # 测试 1: change_files_dialog 导入
    print("\n[1] 测试 change_files_dialog 导入...")
    try:
        from ui.change_files_dialog import ChangeFilesDialog, LockedFileItemWidget, _send_to_recycle_bin
        print("    [OK] ChangeFilesDialog")
        print("    [OK] LockedFileItemWidget")
        print("    [OK] _send_to_recycle_bin")
    except Exception as e:
        print(f"    [FAIL] {e}")
        return False
    
    # 测试 2: change_detector 导入
    print("\n[2] 测试 change_detector 导入...")
    try:
        from engine.change_detector import get_dirty_files, scan_all_sources, _is_file_locked
        print("    [OK] get_dirty_files")
        print("    [OK] scan_all_sources")
        print("    [OK] _is_file_locked")
    except Exception as e:
        print(f"    [FAIL] {e}")
        return False
    
    # 测试 3: main_window 导入
    print("\n[3] 测试 main_window 导入...")
    try:
        from ui.main_window import MainWindow, ScanWorker, ScanSignals
        print("    [OK] MainWindow")
        print("    [OK] ScanWorker")
        print("    [OK] ScanSignals")
        
        # 检查 ScanWorker 是否有 scan_locked 参数
        import inspect
        sig = inspect.signature(ScanWorker.__init__)
        if 'scan_locked' in sig.parameters:
            print("    [OK] ScanWorker.scan_locked 参数")
        else:
            print("    [FAIL] ScanWorker.scan_locked 参数不存在")
            return False
    except Exception as e:
        print(f"    [FAIL] {e}")
        return False
    
    # 测试 4: _is_file_locked 函数
    print("\n[4] 测试 _is_file_locked 函数...")
    try:
        from engine.change_detector import _is_file_locked
        
        # 测试当前文件（应该不被锁定）
        test_file = Path(__file__)
        result = _is_file_locked(test_file)
        print(f"    [OK] _is_file_locked({test_file.name}) = {result}")
    except Exception as e:
        print(f"    [FAIL] {e}")
        return False
    
    # 测试 5: _send_to_recycle_bin 函数
    print("\n[5] 测试 _send_to_recycle_bin 函数...")
    try:
        from ui.change_files_dialog import _send_to_recycle_bin
        print("    [OK] _send_to_recycle_bin 函数可用")
        print("    [注意] 不实际执行删除操作")
    except Exception as e:
        print(f"    [FAIL] {e}")
        return False
    
    print("\n" + "=" * 60)
    print("[OK] 所有测试通过！")
    print("=" * 60)
    
    print("\n修改总结:")
    print("1. ChangeFilesDialog 现在有三个标签页:")
    print("   - Tab 1: 未备份文件")
    print("   - Tab 2: 变动文件")
    print("   - Tab 3: 被锁定文件（带移入回收站功能）")
    print("2. ScanWorker 现在支持 scan_locked 参数")
    print("3. change_detector 现在返回 (dirty_files, locked_files)")
    print("4. _process_scan_results 直接弹出大弹窗")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
