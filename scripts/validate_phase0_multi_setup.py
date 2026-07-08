"""Phase 0 批量验证 — BTST + OversoldBounce.

⚠️ 已迁移到 scripts/setup_research.py 的 main() (端到端, 含真实数据加载).
本文件保留为薄封装, 直接委托 main(), 避免逻辑重复.

此前此脚本内联了数据加载逻辑 (price_cache/fund_flow_cache/candidate_pool),
但有两个缺陷已在 setup_research.main() 修复:
  1. regimes_by_date 全硬编码 {d:"normal"} → 现在读 regime_history.json 真实标签
  2. OversoldBounce 候选被随机采样控制耗时 → 现在全量 (detect 已优化)
  3. IS/OOS 切分 20250101 对熊市 setup 不公平 → 现在切 20230101 (设计文档允许)

用法:
    python -m scripts.validate_phase0_multi_setup   # 等价于 python -m scripts.setup_research --setup all
"""
from __future__ import annotations

from scripts.setup_research import main


if __name__ == "__main__":
    main()
