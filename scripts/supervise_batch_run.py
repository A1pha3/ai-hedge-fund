import datetime as dt
import glob
import os
import re
import subprocess
import time

REPO = '/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork'
INPUT_FILE = os.path.join(REPO, 'data/stock/daliy/daily_gainers_20260227_gt5p0_20260227_224118.md')
CMD = [
    'uv', 'run', 'python', 'scripts/batch_run_hedge_fund.py',
    '--file', 'data/stock/daliy/daily_gainers_20260227_gt5p0_20260227_224118.md',
    '--start-date', '2024-05-30',
    '--analysts-all',
    '--show-reasoning',
]
PATTERN = 'scripts/batch_run_hedge_fund.py --file data/stock/daliy/daily_gainers_20260227_gt5p0_20260227_224118.md'


def now_str() -> str:
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def all_tickers() -> list[str]:
    text = open(INPUT_FILE, 'r', encoding='utf-8').read()
    return sorted(set(re.findall(r'\b\d{6}\b', text)))


def completed_count(tickers: list[str]) -> tuple[int, int]:
    reports = glob.glob(os.path.join(REPO, 'data/reports/*.md'))
    done = [ticker for ticker in tickers if any(os.path.basename(report).startswith(ticker + '_') for report in reports)]
    return len(done), len(tickers)


def running_pids() -> list[str]:
    proc = subprocess.run(['pgrep', '-f', PATTERN], capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main() -> None:
    print(f'[{now_str()}] batch supervisor started', flush=True)

    now = dt.datetime.now()
    target = now.replace(hour=10, minute=0, second=0, microsecond=0)
    if now >= target:
        target += dt.timedelta(days=1)

    print(f'[{now_str()}] waiting until {target.strftime("%Y-%m-%d %H:%M:%S")}', flush=True)
    while dt.datetime.now() < target:
        time.sleep(15)

    print(f'[{now_str()}] monitor loop entered', flush=True)
    tickers = all_tickers()
    last_heartbeat = 0.0

    while True:
        done, total = completed_count(tickers)
        if done >= total:
            print(f'[{now_str()}] completed {done}/{total}, supervisor exit', flush=True)
            break

        pids = running_pids()
        if not pids:
            print(f'[{now_str()}] no batch process, start command; progress={done}/{total}', flush=True)
            started = subprocess.Popen(CMD, cwd=REPO)
            print(f'[{now_str()}] started pid={started.pid}', flush=True)
            time.sleep(8)
        else:
            current = time.time()
            if current - last_heartbeat >= 300:
                print(f'[{now_str()}] alive pids={",".join(pids)} progress={done}/{total}', flush=True)
                last_heartbeat = current

        time.sleep(30)


if __name__ == '__main__':
    main()
