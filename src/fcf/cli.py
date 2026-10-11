from __future__ import annotations

import argparse
import sys
from datetime import date


def _d(s: str) -> date:
    return date.fromisoformat(s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fcf")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch-static", help="下載路段幾何與辦公日曆")

    p = sub.add_parser("fetch-history", help="下載 M05A 歷史整日壓縮檔")
    p.add_argument("--start", type=_d, required=True)
    p.add_argument("--end", type=_d, required=True)
    p.add_argument("--min-interval", type=float, default=41.0)

    sub.add_parser("build-dataset", help="tar → parquet")
    sub.add_parser("train", help="訓練模型")
    sub.add_parser("evaluate", help="TEST 期間評估")

    p = sub.add_parser("find-events", help="挑選壅塞事件日")
    p.add_argument("--top", type=int, default=5)

    p = sub.add_parser("replay", help="重播指定日期")
    p.add_argument("--date", type=_d, required=True)
    p.add_argument("--start", default="06:00")
    p.add_argument("--end", default="10:00")

    sub.add_parser("notify-test", help="LINE 推播測試（無 token 則 dry-run）")

    p = sub.add_parser("live", help="即時模式")
    p.add_argument("--push", action="store_true")
    p.add_argument("--poll", type=int, default=120)

    a = ap.parse_args(argv)

    if a.cmd == "fetch-static":
        from .static import fetch_static

        return fetch_static()
    if a.cmd == "fetch-history":
        from .tdcs import fetch_history

        failed = fetch_history(a.start, a.end, a.min_interval)
        print("failed dates:", [str(d) for d in failed] or "none")
        return 0
    if a.cmd == "build-dataset":
        from .dataset import build_dataset

        build_dataset()
        return 0
    if a.cmd == "train":
        from .model import train

        train()
        return 0
    if a.cmd == "evaluate":
        from .evaluate import evaluate

        evaluate()
        return 0
    if a.cmd == "find-events":
        from .replay import find_events

        find_events(a.top)
        return 0
    if a.cmd == "replay":
        from .replay import replay

        replay(a.date, a.start, a.end)
        return 0
    if a.cmd == "notify-test":
        from .notify import notify_test

        notify_test()
        return 0
    if a.cmd == "live":
        from .live import run_live

        run_live(push=a.push, poll=a.poll)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
