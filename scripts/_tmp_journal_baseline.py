import json
import re
import statistics

rets = []
n_exit = 0
for line in open("data/paper_trading_backtest/journal.jsonl"):
    line = line.strip()
    if not line:
        continue
    r = json.loads(line)
    if r.get("action") != "EXIT" or (r.get("setup") or "") != "btst_breakout":
        continue
    n_exit += 1
    m = re.search(r"realized=([+-]?[0-9.]+)%", r.get("reasoning", ""))
    if m:
        rets.append(float(m.group(1)))

print(f"btst EXIT records: {n_exit}, realized parsed: {len(rets)}")
if rets:
    wr = sum(1 for x in rets if x > 0) / len(rets)
    wins = [x for x in rets if x > 0]
    losses = [-x for x in rets if x < 0]
    payoff = statistics.mean(wins) / statistics.mean(losses) if wins and losses else float("nan")
    print(f"[OLD journal BTST baseline] n={len(rets)} winrate={wr*100:.1f}% "
          f"E[r]={statistics.mean(rets):+.2f}% median={statistics.median(rets):+.2f}% payoff={payoff:.2f}")
    print(f"  tail <-10%: {sum(1 for x in rets if x<-10)/len(rets)*100:.1f}%  "
          f"<-15%: {sum(1 for x in rets if x<-15)/len(rets)*100:.1f}%")
