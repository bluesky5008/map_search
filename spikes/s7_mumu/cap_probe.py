"""게이트 4 / 1단계 — MuMu 창 WGC 바인딩 검증 (입력 없음, 캡처만).

top(Qt) / MuMuNxDevice / nemudisplay 각각에 WGC 바인딩을 시도해 프레임 크기와
성공 여부를 기록하고, top 프레임에서 게임 영역(탭바 40px 아래 2544×657)을
기하 계산으로 크롭해 저장한다. HWND는 실행 시점에 자동 발견한다(재시작 대응).
"""

import ctypes
import ctypes.wintypes as wt
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from PIL import Image

u32 = ctypes.windll.user32
u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
WORK = Path(__file__).parent / "work"


def class_of(h):
    buf = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(h, buf, 256)
    return buf.value


def text_of(h):
    n = u32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(h, buf, n + 1)
    return buf.value


def rect_of(h):
    r = wt.RECT()
    u32.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def client_of(h):
    r = wt.RECT()
    u32.GetClientRect(h, ctypes.byref(r))
    return (r.right, r.bottom)


def client_origin_screen(h):
    pt = wt.POINT(0, 0)
    u32.ClientToScreen(h, ctypes.byref(pt))
    return (pt.x, pt.y)


def find_mumu_instances():
    """제목이 아니라 구조로 판별: Qt 클래스 top + MuMuNxDevice 자식."""
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def on_top(h, _):
        if not u32.IsWindowVisible(h) or not class_of(h).startswith("Qt"):
            return True
        kids = {}

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        def on_child(ch, _2):
            kids.setdefault(text_of(ch), ch)
            return True

        u32.EnumChildWindows(h, on_child, 0)
        if "MuMuNxDevice" in kids and "nemudisplay" in kids:
            out.append({"title": text_of(h), "top": h,
                        "device": kids["MuMuNxDevice"], "display": kids["nemudisplay"]})
        return True

    u32.EnumWindows(on_top, 0)
    return out


def try_wgc(hwnd, timeout=6.0):
    """한 프레임만 받아 (frame, err) 반환. 실패 원인은 문자열로 남긴다."""
    from windows_capture import Frame, InternalCaptureControl, WindowsCapture
    holder = {"frame": None}
    ready = threading.Event()
    try:
        cap = WindowsCapture(cursor_capture=False, draw_border=False,
                             window_hwnd=hwnd)
    except BaseException as e:
        return None, f"세션 생성 실패: {type(e).__name__}: {e}"

    @cap.event
    def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
        holder["frame"] = frame.frame_buffer[:, :, :3][:, :, ::-1].copy()
        ready.set()
        control.stop()

    @cap.event
    def on_closed():
        ready.set()

    try:
        ctl = cap.start_free_threaded()
    except BaseException as e:
        return None, f"시작 실패: {type(e).__name__}: {e}"
    got = ready.wait(timeout)
    try:
        ctl.stop()
    except BaseException:
        pass
    if holder["frame"] is None:
        return None, "첫 프레임 시간 초과" if not got else "프레임 없이 세션 종료"
    return holder["frame"], None


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    WORK.mkdir(exist_ok=True)
    want = sys.argv[1] if len(sys.argv) > 1 else "용스"
    inst = next((i for i in find_mumu_instances() if i["title"] == want), None)
    if inst is None:
        print(f"인스턴스 '{want}' 미발견. 발견 목록: "
              f"{[i['title'] for i in find_mumu_instances()]}")
        return 1

    top, dev, disp = inst["top"], inst["device"], inst["display"]
    top_rect = rect_of(top)
    top_client_org = client_origin_screen(top)
    disp_org = client_origin_screen(disp)
    tab_offset = (disp_org[0] - top_client_org[0], disp_org[1] - top_client_org[1])
    results = {
        "instance": want,
        "hwnds": {"top": hex(top), "device": hex(dev), "display": hex(disp)},
        "top_rect": top_rect, "top_client": client_of(top),
        "display_client": client_of(disp),
        "tab_offset_in_client": tab_offset,
        "targets": {},
    }
    print(f"'{want}' top={top:#x} device={dev:#x} display={disp:#x}")
    print(f"top rect={top_rect} client={client_of(top)} | "
          f"게임 영역 클라이언트 오프셋={tab_offset} (기대 (0,40))")

    for name, h in (("top", top), ("device", dev), ("display", disp)):
        frame, err = try_wgc(h)
        if frame is None:
            results["targets"][name] = {"ok": False, "error": err}
            print(f"  WGC {name:8s} 실패 — {err}")
            continue
        Image.fromarray(frame).save(WORK / f"cap_{name}.png")
        results["targets"][name] = {
            "ok": True, "frame": [frame.shape[1], frame.shape[0]]}
        print(f"  WGC {name:8s} 성공 — 프레임 {frame.shape[1]}x{frame.shape[0]} "
              f"→ work/cap_{name}.png")
        if name == "top":
            # 프레임 = 창 외곽 가정(기존 실측)으로 게임 영역 크롭
            fx = disp_org[0] - top_rect[0]
            fy = disp_org[1] - top_rect[1]
            gw, gh = client_of(disp)
            crop = frame[fy:fy + gh, fx:fx + gw]
            Image.fromarray(crop).save(WORK / "game_from_top.png")
            results["targets"][name]["game_origin_in_frame"] = [fx, fy]
            print(f"    게임 영역 원점(프레임 좌표) ({fx},{fy}) 크기 {gw}x{gh} "
                  f"→ work/game_from_top.png")

    (WORK / "cap_probe.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과: {WORK / 'cap_probe.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
