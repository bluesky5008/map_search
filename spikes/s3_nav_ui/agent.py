"""S-3/S-4 상주형 관리자 에이전트 — UAC 1회로 파일 명령을 처리한다 (스파이크 전용).

프로토콜 (--dir 안):
  cmd_<NNNN>.txt  : 명령 1줄, 순번대로 소비
  res_<NNNN>.txt  : 실행 결과 1줄
  agent_status.txt: 수명주기 로그

명령:
  cap <name.png>        현재 프레임 저장
  click <cx> <cy>       클라이언트 좌표 클릭
  dbl <cx> <cy>         더블클릭
  move <cx> <cy>        마우스 이동만
  type <text>           WM_CHAR 문자 입력
  key <vk> [count]      가상 키 (예: key 8 10 = 백스페이스 10회)
  drag <x0> <y0> <x1> <y1> [steps]  버튼 누른 채 이동 (팬)
  wheel <n> <cx> <cy>   휠 n노치 (음수 = 축소)
  sleep <sec>           대기
  quit                  종료
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image

from mapscan.win import PostMessageInput, WgcCapture, WindowSession


def log(dirp: Path, msg: str) -> None:
    with open(dirp / "agent_status.txt", "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--idle-quit", type=float, default=900.0)
    args = ap.parse_args()
    dirp = Path(args.dir)
    dirp.mkdir(parents=True, exist_ok=True)

    session = WindowSession.attach(args.hwnd)
    info = session.info()
    log(dirp, f"attach hwnd={info.hwnd:#x} client={info.client} elevated={info.elevated}")
    inp = PostMessageInput(args.hwnd, delay_range=(0.15, 0.3))
    cap = WgcCapture(args.hwnd, info.title)
    cap.start()
    log(dirp, "capture bound")

    seq = 1
    last_cmd = time.monotonic()
    while time.monotonic() - last_cmd < args.idle_quit:
        cmd_file = dirp / f"cmd_{seq:04d}.txt"
        if not cmd_file.exists():
            time.sleep(0.15)
            continue
        time.sleep(0.1)  # 파일 쓰기 완료 대기
        line = cmd_file.read_text(encoding="utf-8").strip()
        last_cmd = time.monotonic()
        try:
            result = execute(line, cap, inp, dirp)
        except Exception as exc:  # 명령 하나의 실패로 에이전트가 죽지 않게
            result = f"ERROR {exc!r}"
        (dirp / f"res_{seq:04d}.txt").write_text(result, encoding="utf-8")
        log(dirp, f"#{seq} {line} -> {result}")
        if line == "quit":
            break
        seq += 1
    cap.stop()
    log(dirp, "agent exit")
    return 0


def execute(line: str, cap: WgcCapture, inp: PostMessageInput, dirp: Path) -> str:
    parts = line.split(maxsplit=1)
    op = parts[0]
    if op == "cap":
        frame = cap.grab_fresh()
        Image.fromarray(frame).save(dirp / parts[1])
        return f"cap {parts[1]} {frame.shape[1]}x{frame.shape[0]}"
    if op in ("click", "move", "dbl"):
        x, y = (int(v) for v in parts[1].split())
        fn = {"click": inp.click, "move": inp.move, "dbl": inp.double_click}[op]
        fn(x, y)
        return f"{op} ({x},{y}) ok"
    if op == "key":
        vals = [int(v) for v in parts[1].split()]
        inp.key(vals[0], vals[1] if len(vals) > 1 else 1)
        return f"key {vals} ok"
    if op == "drag":
        vals = [int(v) for v in parts[1].split()]
        steps = vals[4] if len(vals) > 4 else 12
        inp.drag(vals[0], vals[1], vals[2], vals[3], steps=steps)
        return f"drag {vals[:4]} ok"
    if op == "type":
        inp.type_text(parts[1])
        return f"type {parts[1]!r} ok"
    if op == "wheel":
        vals = [int(v) for v in parts[1].split()]
        n, x, y = vals[0], vals[1], vals[2]
        inp.wheel(x, y, n)
        return f"wheel {n} at ({x},{y}) ok"
    if op == "sleep":
        time.sleep(float(parts[1]))
        return "sleep ok"
    if op == "quit":
        return "quit"
    return f"ERROR unknown op {op}"


if __name__ == "__main__":
    sys.exit(main())
