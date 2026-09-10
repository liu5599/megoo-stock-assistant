"""
策略条件引擎（v4.1 P1）—— YAML 量化骨架
====================================================================
评审缺陷三：策略 YAML 只换了话术，无法承载可量化逻辑、无法客观回测。
本引擎让 YAML 可声明 entry_conditions/exit_conditions，用安全表达式对
行情数据求值，产出布尔信号 —— 可被回测引擎消费，也可作为问股/决策的前置过滤。

条件语法（安全白名单，禁函数调用/属性访问）：
    close > MA20
    MA5 > MA20
    volume > 1.5 * VMA5
    RSI < 70
    close > BOLL_up
    pct_chg > 2

可用变量（由 evaluate 时传入）：
    close, open, high, low, volume, pct_chg,
    MA5, MA10, MA20, MA60, VMA5, VMA10, RSI, MACD, MACD_signal, KDJ_K, BOLL_up, BOLL_low
"""
import ast
import operator
import re
from typing import Dict, List, Optional

from utils.logger import logger

# 允许的运算符（无函数调用、无属性访问、无下标）
_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
}
_CMP_OPS = {
    ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
    ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne,
}
_BOOL_OPS = {ast.And: all, ast.Or: any}


class _SafeEval(ast.NodeVisitor):
    """安全表达式求值：只允许数字/变量/运算符/比较/布尔，无函数调用"""

    def __init__(self, env: Dict[str, float]):
        self.env = env

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        if isinstance(node.value, (int, float, bool)):
            return node.value
        raise ValueError(f"非法常量: {node.value!r}")

    def visit_Name(self, node):
        if node.id in self.env and self.env[node.id] is not None:
            return self.env[node.id]
        raise ValueError(f"未知变量: {node.id}")

    def visit_BinOp(self, node):
        op = _BIN_OPS.get(type(node.op))
        if not op:
            raise ValueError(f"非法运算符: {type(node.op).__name__}")
        return op(self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node):
        v = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return v
        if isinstance(node.op, ast.Not):
            return not v
        raise ValueError("非法一元运算符")

    def visit_Compare(self, node):
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            fn = _CMP_OPS.get(type(op))
            if not fn:
                raise ValueError(f"非法比较符: {type(op).__name__}")
            right = self.visit(comparator)
            if not fn(left, right):
                return False
            left = right
        return True

    def visit_BoolOp(self, node):
        fn = _BOOL_OPS.get(type(node.op))
        if not fn:
            raise ValueError("非法布尔运算符")
        return fn([bool(self.visit(v)) for v in node.values])

    def generic_visit(self, node):
        raise ValueError(f"不支持的语法: {type(node).__name__}（仅允许变量/数字/运算符/比较）")


def eval_condition(expr: str, env: Dict[str, float]) -> Optional[bool]:
    """对单个条件表达式求值。变量缺失或语法非法返回 None（视为不可判定）。"""
    try:
        tree = ast.parse(expr, mode="eval")
        return bool(_SafeEval(env).visit(tree))
    except Exception as e:
        logger.debug(f"条件求值失败 [{expr}]: {e}")
        return None


def eval_conditions(conditions: List[str], env: Dict[str, float],
                    mode: str = "all") -> Dict:
    """对条件列表求值。mode='all' 全真才真 / 'any' 任一真即真。

    返回 {passed, results:[{expr, result}], evaluable}
    """
    results = []
    values = []
    for c in conditions or []:
        r = eval_condition(c, env)
        results.append({"expr": c, "result": r})
        if r is not None:
            values.append(r)
    evaluable = len(values)
    if evaluable == 0:
        passed = False
    elif mode == "any":
        passed = any(values)
    else:
        passed = all(values)
    return {"passed": passed, "results": results, "evaluable": evaluable,
            "total": len(conditions or [])}


def check_strategy(strategy: Dict, env: Dict[str, float]) -> Dict:
    """对策略 YAML 的 entry/exit 条件求值。

    返回 {entry:{passed,results}, exit:{passed,results}, hit}
      hit: 'entry' | 'exit' | None
    """
    entry = eval_conditions(strategy.get("entry_conditions", []), env, mode="all")
    exit_ = eval_conditions(strategy.get("exit_conditions", []), env, mode="any")
    hit = None
    if entry["total"] and entry["passed"]:
        hit = "entry"
    elif exit_["total"] and exit_["passed"]:
        hit = "exit"
    return {"entry": entry, "exit": exit_, "hit": hit}
