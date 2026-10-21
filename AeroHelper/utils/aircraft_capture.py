"""Foreground-checked Windows capture, isolated from existing screenshot paths."""
from PIL import ImageGrab
from AeroHelper.utils import window


def capture_roblox_client():
    if not window.IS_WINDOWS or window.win32gui is None:
        raise RuntimeError('Live HUD capture requires Windows. Use Open screenshot for offline inspection.')
    gui = window.win32gui
    hwnd = window.find_roblox_window()
    if hwnd is None:
        raise RuntimeError('Roblox window not found. Open Roblox and enter cockpit view.')
    if gui.IsIconic(hwnd) or gui.GetForegroundWindow() != hwnd:
        raise RuntimeError('Roblox is not the foreground window. Retry, then switch to Roblox during the countdown.')
    left,top,right,bottom = gui.GetClientRect(hwnd)
    left,top = gui.ClientToScreen(hwnd,(left,top))
    right,bottom = gui.ClientToScreen(hwnd,(right,bottom))
    if right-left < 200 or bottom-top < 120:
        raise RuntimeError('Roblox client area is too small. Restore or maximize Roblox.')
    # all_screens supports negative virtual-desktop coordinates (second monitor).
    image = ImageGrab.grab(bbox=(left,top,right,bottom), all_screens=True).convert('RGB')
    if gui.GetForegroundWindow() != hwnd:
        image.close()
        raise RuntimeError('Focus changed during capture; frame discarded. Retry.')
    if image.getextrema() == ((0,0),(0,0),(0,0)):
        image.close()
        raise RuntimeError('Roblox capture is black. Try windowed/borderless mode and retry.')
    return image, (left,top,right,bottom)
