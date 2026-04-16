import time
from typing import Optional

import pandas as pd


def extract_open_trade_dates(df: pd.DataFrame | None) -> list[str]:
    if df is None or df.empty:
        return []
    return sorted({str(row["cal_date"]) for _, row in df.iterrows() if str(row.get("cal_date") or "").strip()})


def resolve_cached_sw_industry_mapping(
    *,
    cached_mapping: dict[str, str] | None,
    load_index_df,
    build_mapping,
    cache_mapping,
) -> Optional[dict[str, str]]:
    if cached_mapping is not None:
        return cached_mapping.copy()

    index_df = load_index_df()
    if index_df is None or index_df.empty:
        return None

    result = build_mapping(index_df)
    if result:
        cache_mapping(result)
        return result.copy()
    return None


def load_sw_index_classification(fetch_dataframe, pro) -> Optional[pd.DataFrame]:
    index_df = fetch_dataframe(pro, "index_classify", level="L1", src="SW2021", ttl=7 * 86400)
    if index_df is None or index_df.empty:
        index_df = fetch_dataframe(pro, "index_classify", level="L1", src="SW2014", ttl=7 * 86400)
    return index_df


def build_sw_industry_mapping(fetch_dataframe, pro, index_df: pd.DataFrame) -> dict[str, str]:
    result: dict[str, str] = {}
    for _, row in index_df.iterrows():
        index_code = str(row["index_code"])
        industry_name = str(row["industry_name"])
        try:
            time.sleep(0.35)
            member_df = fetch_dataframe(pro, "index_member", index_code=index_code, ttl=7 * 86400)
            if member_df is None or member_df.empty:
                continue
            for _, member_row in member_df.iterrows():
                if pd.isna(member_row.get("out_date")):
                    result[str(member_row["con_code"])] = industry_name
        except Exception as e:
            print(f"[Tushare] 获取行业 {industry_name}({index_code}) 成分失败: {e}")
            continue
    return result
