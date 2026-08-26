"""测试 K线获取"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.eastmoney_fetcher import EastMoneyFetcher

em = EastMoneyFetcher(timeout=15)

# 测试茅台K线
print("=== 测试 get_history_kline ===")
kline = em.get_history_kline("600519", period="daily", adjust="qfq")
if kline and not kline.df.empty:
    print(f"✅ 获取成功: {len(kline.df)} 条数据")
    print(kline.df[["date","open","high","low","close","volume"]].tail(5))
else:
    print("❌ 获取失败或数据为空")

# 测试平安K线
print("\n=== 测试 000001 ===")
kline = em.get_history_kline("000001", period="daily", adjust="qfq")
if kline and not kline.df.empty:
    print(f"✅ 获取成功: {len(kline.df)} 条数据")
    print(kline.df[["date","open","high","low","close","volume"]].tail(5))
else:
    print("❌ 获取失败或数据为空")

# 测试创业板
print("\n=== 测试 300750 ===")
kline = em.get_history_kline("300750", period="daily", adjust="qfq")
if kline and not kline.df.empty:
    print(f"✅ 获取成功: {len(kline.df)} 条数据")
    print(kline.df[["date","open","high","low","close","volume"]].tail(5))
else:
    print("❌ 获取失败或数据为空")
