# -*- coding: utf-8 -*-
"""扫描用的 7 个仿真任务、探针项、隐藏偏差与编辑指令(2026-10-27)。

每个任务 = 预备阶段(只有辅助项)+ 主阶段(契约项 + 辅助项)。契约项都会被验收;其中标了 probe 的是这次扫描要改 / 要修的项,
其余契约项用来检查修改或修复有没有影响别的项。辅助项(helpers)只给规划器用,不验收。
目标值在 HOME 位形上按相对量给出(ctx0 = 初始 TCP 位姿、关节角、第 4 连杆原点)。
"""
from __future__ import annotations

import numpy as np

from cost_layers.robot import TABLE_Z

KEEP_ORI = {"id": "_keep_ori", "level": "tcp_motion", "attr": "ori", "frame": "start_tool", "axes": ["rx", "ry", "rz"], "mode": "target",
            "target": [0, 0, 0], "sigma": 0.02, "weight": 4}
TOOL_DOWN = {"id": "_tool_down", "level": "tcp_motion", "attr": "ori_cone", "frame": "base", "ref_axis": [0, 0, -1], "tool_axis": [0, 0, 1],
             "mode": "upper", "ub": 0.1, "sigma": 0.05, "weight": 2}
TABLE_ORIGIN = np.array([0.55, 0.0, TABLE_Z])


def _l(v):
    return [float(x) for x in np.asarray(v, float).reshape(-1)]


def free_contract(c):
    return [
        {"id": "reach", "cat": "G1", "desc": "末端到达基座坐标系下的目标位置", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["x", "y", "z"],
         "kind": "target", "target": _l(c["p0"] + [0.08, 0.06, -0.06]), "tol": 0.005, "unit": "m", "sigma": 0.005, "weight": 2,
         "profile": "ramp_from_current", "t_ramp": 0.8},
        {"id": "tilt", "cat": "G2", "desc": "工具轴相对竖直向下方向的倾角", "level": "tcp_motion", "attr": "ori_cone", "frame": "base",
         "ref_axis": [0, 0, -1], "tool_axis": [0, 0, 1], "kind": "target", "target": 0.2618, "tol": 0.035, "unit": "rad", "sigma": 0.02, "weight": 2},
        {"id": "elbow", "cat": "J3", "desc": "手肘(第 4 连杆原点)在基座系的 y 坐标", "level": "joint", "attr": "link_pos", "link": 4, "axes": ["y"],
         "kind": "target", "target": float(c["elbow_y"] + 0.06), "tol": 0.01, "unit": "m", "sigma": 0.01, "weight": 4},
    ]


def joint_contract(c):
    return [
        {"id": "q7", "cat": "J1", "desc": "第 7 关节角", "level": "joint", "attr": "q", "joints": [7], "kind": "target",
         "target": float(c["q0"][6] + 0.4), "tol": 0.03, "unit": "rad", "sigma": 0.05, "weight": 2},
        {"id": "hold", "cat": "G1", "desc": "末端保持在起始位置", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["x", "y", "z"],
         "kind": "target", "target": _l(c["p0"]), "tol": 0.005, "unit": "m", "sigma": 0.005, "weight": 2},
    ]


def move_contract(c):
    return [
        {"id": "vx", "cat": "K1", "desc": "末端沿基座 x 方向的线速度", "level": "tcp_motion", "attr": "lin_vel", "frame": "base", "axes": ["x"],
         "kind": "target", "target": 0.05, "tol": 0.005, "unit": "m/s", "sigma": 0.01, "weight": 2},
        {"id": "vyz", "cat": "K1", "desc": "末端 y、z 方向不漂移(速度区间)", "level": "tcp_motion", "attr": "lin_vel", "frame": "base", "axes": ["y", "z"],
         "kind": "range", "lb": [-0.005, -0.005], "ub": [0.005, 0.005], "tol": 0.002, "unit": "m/s", "sigma": 0.005},
        {"id": "dq7", "cat": "J2", "desc": "第 7 关节转速", "level": "joint", "attr": "dq", "joints": [7], "kind": "target",
         "target": 0.3, "tol": 0.03, "unit": "rad/s", "sigma": 0.05, "weight": 2},
    ]


def spin_contract(c):
    return [
        {"id": "spin", "cat": "K2", "desc": "末端绕基座 z 轴的角速度", "level": "tcp_motion", "attr": "ang_vel", "frame": "base", "axes": ["rz"],
         "kind": "target", "target": 0.2, "tol": 0.03, "unit": "rad/s", "sigma": 0.03, "weight": 2},
        {"id": "no_tilt", "cat": "K2", "desc": "绕 x、y 轴不转(角速度区间)", "level": "tcp_motion", "attr": "ang_vel", "frame": "base", "axes": ["rx", "ry"],
         "kind": "range", "lb": [-0.03, -0.03], "ub": [0.03, 0.03], "tol": 0.01, "unit": "rad/s", "sigma": 0.03},
        {"id": "hold", "cat": "G1", "desc": "末端保持在起始位置", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["x", "y", "z"],
         "kind": "target", "target": _l(c["p0"]), "tol": 0.005, "unit": "m", "sigma": 0.005, "weight": 2},
    ]


def obj_contract(c):
    return [
        {"id": "above", "cat": "G4", "desc": "末端相对箱子(object:box 坐标系)的位置", "level": "tcp_motion", "attr": "pos", "frame": "object:box",
         "axes": ["x", "y", "z"], "kind": "target", "target": [0.0, 0.0, 0.12], "tol": 0.005, "unit": "m", "sigma": 0.005, "weight": 2,
         "profile": "ramp_from_current", "t_ramp": 0.8},
    ]


def clear_contract(c):
    return [
        {"id": "clear", "cat": "G5", "desc": "末端高度不得低于障碍上方的安全高度(硬下限)", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["z"],
         "kind": "lower", "lb": float(c["p0"][2] - 0.06), "tol": 0.002, "unit": "m", "sigma": 0.005, "weight": 2, "penalty": "hard"},
        {"id": "goal_xy", "cat": "G1", "desc": "末端水平位置", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["x", "y"],
         "kind": "target", "target": _l(c["p0"][:2] + [0.08, 0.0]), "tol": 0.005, "unit": "m", "sigma": 0.005, "weight": 2,
         "profile": "ramp_from_current", "t_ramp": 0.8},
    ]


WAYPOINTS = [[-0.10, -0.05], [-0.10, 0.03], [-0.05, 0.03]]


def contact_contract(c):
    return [
        {"id": "press", "cat": "C3", "desc": "笔尖对桌面的法向力(压向桌面为正)", "level": "tcp_force", "attr": "force", "frame": "surface:table", "axes": ["z"],
         "kind": "target", "target": 6.0, "tol": 1.5, "unit": "N", "sigma": 2.0, "weight": 3, "profile": "ramp_from_current", "t_ramp": 0.2},
        {"id": "path", "cat": "G3", "desc": "末端在桌面坐标系 xy 平面内沿折线走(验收:到折线的平均横向距离)", "level": "tcp_motion", "attr": "pos",
         "frame": "surface:table", "axes": ["x", "y"], "kind": "path", "waypoints": WAYPOINTS, "path_speed": 0.03, "tol": 0.004, "unit": "m",
         "sigma": 0.003, "weight": 2},
    ]


def contact_approach(ctx):
    return {"gripper": "close", "terms": [
        {"id": "_above", "level": "tcp_motion", "attr": "pos", "frame": "surface:table", "axes": ["x", "y", "z"], "mode": "target",
         "target": [WAYPOINTS[0][0], WAYPOINTS[0][1], 0.03], "sigma": 0.005, "weight": 2, "profile": "ramp_from_current", "t_ramp": 0.4},
        {"id": "_slow", "level": "tcp_motion", "attr": "speed", "frame": "base", "mode": "upper", "ub": 0.25, "sigma": 0.01, "penalty": "hard"}, KEEP_ORI]}


TASKS = {
    "free": {"contract_fn": free_contract, "helpers_fn": lambda ctx: [], "main_windows": 6, "verify_skip_s": {"*": 1.5}},
    "joint": {"contract_fn": joint_contract, "helpers_fn": lambda ctx: [TOOL_DOWN], "main_windows": 6, "verify_skip_s": {"*": 1.5}},
    "move": {"contract_fn": move_contract, "helpers_fn": lambda ctx: [TOOL_DOWN], "main_windows": 5, "verify_skip_s": {"*": 1.0}},
    "spin": {"contract_fn": spin_contract, "helpers_fn": lambda ctx: [], "main_windows": 5, "verify_skip_s": {"*": 1.0}},
    "obj": {"contract_fn": obj_contract, "helpers_fn": lambda ctx: [TOOL_DOWN], "main_windows": 6, "verify_skip_s": {"*": 1.5},
            "frames_fn": lambda p0, R0: {"object:box": (np.eye(3), p0 + np.array([0.10, -0.08, -0.22]))}},
    "clear": {"contract_fn": clear_contract, "main_windows": 6, "verify_skip_s": {"*": 1.5},
              "helpers_fn": lambda ctx: [TOOL_DOWN, {"id": "_pull", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["z"], "mode": "target",
                                                     "target": float(ctx["p0"][2] - 0.12), "sigma": 0.01, "weight": 1}]},
    "contact": {"contract_fn": contact_contract, "helpers_fn": lambda ctx: [KEEP_ORI], "main_windows": 14, "scene": True,
                "verify_skip_s": {"*": 1.0, "path": 0.5}, "pre": [(contact_approach, 6)],
                "frames_fn": lambda p0, R0: {"surface:table": (np.eye(3), TABLE_ORIGIN.copy())}},
}


def _t(c, iid):
    return next(i for i in c if i["id"] == iid)


def _shift(v, d):
    return _l(np.asarray(v, float) + np.asarray(d, float))


# 探针:任务、隐藏偏差、两条编辑指令(说法, 由原契约算出正确补丁的函数)
PROBES = {
    "reach": {"task": "free", "bias": {"kind": "add", "value": [0.0, 0.0, -0.015]},
              "edits": [("把末端的目标位置抬高 3 厘米。", lambda c: [{"id": "reach", "field": "target", "value": _shift(_t(c, "reach")["target"], [0, 0, 0.03])}]),
                        ("末端位置的允许误差放宽到 1 厘米。", lambda c: [{"id": "reach", "field": "tol", "value": 0.01}])]},
    "tilt": {"task": "free", "bias": {"kind": "add", "value": -0.09},
             "edits": [("把工具的倾角改成 25 度。", lambda c: [{"id": "tilt", "field": "target", "value": 0.4363}]),
                       ("工具倾角的允许误差收紧到 1 度。", lambda c: [{"id": "tilt", "field": "tol", "value": 0.01745}])]},
    "elbow": {"task": "free", "bias": {"kind": "add", "value": 0.03},
              "edits": [("手肘再往 y 正方向多偏 3 厘米。", lambda c: [{"id": "elbow", "field": "target", "value": _t(c, "elbow")["target"] + 0.03}]),
                        ("手肘位置的允许误差放宽到 2 厘米。", lambda c: [{"id": "elbow", "field": "tol", "value": 0.02}])]},
    "q7": {"task": "joint", "bias": {"kind": "add", "value": 0.1},
           "edits": [("第 7 关节的目标角度减小 0.2 弧度。", lambda c: [{"id": "q7", "field": "target", "value": _t(c, "q7")["target"] - 0.2}]),
                     ("第 7 关节角的允许误差放宽到 0.05 弧度。", lambda c: [{"id": "q7", "field": "tol", "value": 0.05}])]},
    "vx": {"task": "move", "bias": {"kind": "scale", "value": 0.8},
           "edits": [("x 方向的速度改为每秒 3 厘米。", lambda c: [{"id": "vx", "field": "target", "value": 0.03}]),
                     ("x 方向速度的允许误差放宽到每秒 1 厘米。", lambda c: [{"id": "vx", "field": "tol", "value": 0.01}])]},
    "dq7": {"task": "move", "bias": {"kind": "scale", "value": 0.8},
            "edits": [("第 7 关节的转速改为每秒 0.5 弧度。", lambda c: [{"id": "dq7", "field": "target", "value": 0.5}]),
                      ("第 7 关节转速的允许误差放宽到每秒 0.05 弧度。", lambda c: [{"id": "dq7", "field": "tol", "value": 0.05}])]},
    "spin": {"task": "spin", "bias": {"kind": "scale", "value": 0.8},
             "edits": [("绕 z 轴的角速度改为每秒 0.3 弧度。", lambda c: [{"id": "spin", "field": "target", "value": 0.3}]),
                       ("绕 z 轴角速度的允许误差放宽到每秒 0.05 弧度。", lambda c: [{"id": "spin", "field": "tol", "value": 0.05}])]},
    "above": {"task": "obj", "bias": {"kind": "frame", "frame": "object:box", "value": [0.012, -0.010, 0.0]},
              "edits": [("末端在箱子正上方的高度改为 8 厘米。", lambda c: [{"id": "above", "field": "target", "value": [0.0, 0.0, 0.08]}]),
                        ("末端相对箱子再往箱子坐标系 x 正方向偏 2 厘米。", lambda c: [{"id": "above", "field": "target", "value": _shift(_t(c, "above")["target"], [0.02, 0, 0])}])]},
    "clear": {"task": "clear", "bias": {"kind": "add", "value": -0.02},
              "edits": [("安全高度的下限再抬高 2 厘米。", lambda c: [{"id": "clear", "field": "lb", "value": _t(c, "clear")["lb"] + 0.02}]),
                        ("安全高度下限的允许余量放宽到 5 毫米。", lambda c: [{"id": "clear", "field": "tol", "value": 0.005}])]},
    "press": {"task": "contact", "bias": {"kind": "scale", "value": 1.6},
              "edits": [("压力改成 4 牛。", lambda c: [{"id": "press", "field": "target", "value": 4.0}]),
                        ("压力的允许误差放宽到 2 牛。", lambda c: [{"id": "press", "field": "tol", "value": 2.0}])]},
    "path": {"task": "contact", "bias": {"kind": "frame", "frame": "surface:table", "value": [0.010, 0.0, 0.0]},
             "edits": [("路径的允许横向偏差放宽到 5 毫米。", lambda c: [{"id": "path", "field": "tol", "value": 0.005}]),
                       ("整条路径沿桌面 y 正方向平移 1 厘米。", lambda c: [{"id": "path", "field": "waypoints",
                                                               "value": (np.asarray(_t(c, "path")["waypoints"]) + [0, 0.01]).tolist()}])]},
}


# ───────────────────────────────────────────── 2026-10-27 第二批:多阶段(T1–T4、C1)与动态参照(D1–D4),由 program.py 执行
def _Rx(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def mov_traj(t, f0):
    """移动物体:沿 y 正弦往复(幅值 6 cm,周期 6 s),同时绕 x 轴摆动(幅值 0.25 rad,周期 8 s)。"""
    R0, p0 = f0
    return R0 @ _Rx(0.25 * np.sin(2 * np.pi * t / 8.0)), p0 + np.array([0.0, 0.06 * np.sin(2 * np.pi * t / 6.0), 0.0])


XY_A = (-0.05, 0.0)


def _xy_hold(xy):
    return {"id": "_xy", "level": "tcp_motion", "attr": "pos", "frame": "surface:table", "axes": ["x", "y"], "mode": "target", "target": list(xy),
            "sigma": 0.005, "weight": 2}


def _approach(xy):
    def f(ctx):
        return {"gripper": "close", "terms": [
            {"id": "_above", "level": "tcp_motion", "attr": "pos", "frame": "surface:table", "axes": ["x", "y", "z"], "mode": "target",
             "target": [xy[0], xy[1], 0.02], "sigma": 0.005, "weight": 2, "profile": "ramp_from_current", "t_ramp": 0.4},
            {"id": "_slow", "level": "tcp_motion", "attr": "speed", "frame": "base", "mode": "upper", "ub": 0.25, "sigma": 0.01, "penalty": "hard"}, KEEP_ORI]}
    return f


DOWN = {"id": "_down", "level": "tcp_motion", "attr": "lin_vel", "frame": "surface:table", "axes": ["z"], "mode": "target", "target": -0.004, "sigma": 0.002, "weight": 2}


def seq_contract(c):
    return [
        {"id": "order", "cat": "T1", "desc": "阶段顺序(只有按自己的退出条件完成的阶段才算完成)", "kind": "sequence", "target": ["descend", "press_hold", "lift"],
         "tol": 0.0, "unit": "-"},
        {"id": "touch", "cat": "T3", "desc": "下探阶段:法向力达到阈值时切换到下一阶段(验收看切换时刻的实测法向力)", "kind": "trigger", "stage": "descend",
         "target": 2.0, "tol": 0.6, "unit": "N"},
        {"id": "hold", "cat": "T2", "desc": "按压保持阶段的时长", "kind": "duration", "stage": "press_hold", "target": 2.0, "tol": 0.15, "unit": "s"},
        {"id": "keep", "cat": "C1", "desc": "按压保持阶段内处于接触的时间比例", "kind": "contact", "stage": "press_hold", "target": 1.0, "tol": 0.05, "unit": "-"},
        {"id": "press2", "cat": "C3", "desc": "按压保持阶段的法向力", "level": "tcp_force", "attr": "force", "frame": "surface:table", "axes": ["z"], "stage": "press_hold",
         "kind": "target", "target": 5.0, "tol": 1.5, "unit": "N", "sigma": 2.0, "weight": 3, "profile": "ramp_from_current", "t_ramp": 0.3},
    ]


def period_contract(c):
    return [
        {"id": "tap", "cat": "T4", "desc": "周期性按压:法向力按周期在 2 N 与 6 N 之间变化(验收看实测法向力的周期)", "kind": "period", "stage": "tap",
         "frame": "surface:table", "force_base": 2.0, "force_peak": 6.0, "target": 1.2, "tol": 0.1, "unit": "s"},
    ]


def follow_contract(c):
    return [
        {"id": "follow", "cat": "D1", "desc": "末端跟随移动物体,保持在物体坐标系中的相对位置", "level": "tcp_motion", "attr": "pos", "frame": "object:mov",
         "axes": ["x", "y", "z"], "stage": "track", "kind": "target", "target": [0.0, 0.0, 0.10], "tol": 0.008, "unit": "m", "sigma": 0.005, "weight": 2,
         "profile": "ramp_from_current", "t_ramp": 0.8},
        {"id": "align", "cat": "D2", "desc": "工具轴与移动物体法向(物体坐标系 -z)的夹角", "level": "tcp_motion", "attr": "ori_cone", "frame": "object:mov",
         "ref_axis": [0, 0, -1], "tool_axis": [0, 0, 1], "stage": "track", "kind": "target", "target": 0.2, "tol": 0.04, "unit": "rad", "sigma": 0.02, "weight": 4},
    ]


def tip_contract(c):
    return [
        {"id": "tip", "cat": "D4", "desc": "工具上的附着点(TCP 沿工具 z 前方 8 cm,如笔尖)跟随移动物体", "level": "tcp_motion", "attr": "pos", "frame": "object:mov",
         "axes": ["x", "y", "z"], "point": [0.0, 0.0, 0.08], "stage": "track", "kind": "target", "target": [0.0, 0.0, 0.03], "tol": 0.008, "unit": "m",
         "sigma": 0.005, "weight": 2, "profile": "ramp_from_current", "t_ramp": 0.8},
    ]


def near_contract(c):
    return [
        {"id": "near", "cat": "D3", "desc": "末端保持在移动物体上方球形区域内(到球心的距离上限)", "level": "tcp_motion", "attr": "pos_ball", "frame": "object:mov",
         "center": [0.0, 0.0, 0.10], "stage": "track", "kind": "upper", "ub": 0.03, "tol": 0.005, "unit": "m", "sigma": 0.003, "weight": 4, "penalty": "hard"},
    ]


def _track_stage(helpers=()):
    return [{"id": "track", "time_s": 6.0, "timeout_s": 7.0, "helpers_fn": lambda ctx: list(helpers)}]


MOV_FRAME = lambda p0, R0: {"object:mov": (np.eye(3), p0 + np.array([0.12, 0.0, -0.15]))}

TASKS.update({
    "seq": {"contract_fn": seq_contract, "scene": True, "chunk": 1, "pre": [(_approach(XY_A), 6)],
            "frames_fn": lambda p0, R0: {"surface:table": (np.eye(3), TABLE_ORIGIN.copy())},
            "verify_skip_s": {"*": 0.3, "press2": 0.8},
            "stages": [{"id": "descend", "timeout_s": 6.0, "helpers_fn": lambda ctx: [DOWN, _xy_hold(XY_A), KEEP_ORI]},
                       {"id": "press_hold", "timeout_s": 10.0, "helpers_fn": lambda ctx: [_xy_hold(XY_A), KEEP_ORI]},
                       {"id": "lift", "time_s": 1.5, "timeout_s": 3.0, "helpers_fn": lambda ctx: [
                           {"id": "_up", "level": "tcp_motion", "attr": "pos", "frame": "surface:table", "axes": ["z"], "mode": "target", "target": 0.05,
                            "sigma": 0.005, "weight": 2, "profile": "ramp_from_current", "t_ramp": 0.5}, _xy_hold(XY_A), KEEP_ORI]}]},
    "period": {"contract_fn": period_contract, "scene": True, "chunk": 5, "pre": [(_approach(XY_A), 6)],
               "frames_fn": lambda p0, R0: {"surface:table": (np.eye(3), TABLE_ORIGIN.copy())},
               "verify_skip_s": {"*": 1.0},
               "stages": [{"id": "settle", "time_s": 2.5, "timeout_s": 3.0, "helpers_fn": lambda ctx: [
                              {"id": "_f1", "level": "tcp_force", "attr": "force", "frame": "surface:table", "axes": ["z"], "mode": "target", "target": 2.0,
                               "sigma": 2.0, "weight": 3}, _xy_hold(XY_A), KEEP_ORI]},
                          {"id": "tap", "time_s": 8.0, "timeout_s": 9.0, "helpers_fn": lambda ctx: [_xy_hold(XY_A), KEEP_ORI]}]},
    "follow": {"contract_fn": follow_contract, "chunk": 1, "frames_fn": MOV_FRAME, "dynamic": {"object:mov": mov_traj},
               "verify_skip_s": {"*": 1.5}, "stages": _track_stage()},
    "tip": {"contract_fn": tip_contract, "chunk": 1, "frames_fn": MOV_FRAME, "dynamic": {"object:mov": mov_traj},
            "verify_skip_s": {"*": 1.5}, "stages": _track_stage([TOOL_DOWN])},
    "near": {"contract_fn": near_contract, "chunk": 1, "frames_fn": MOV_FRAME, "dynamic": {"object:mov": mov_traj},
             "verify_skip_s": {"*": 1.5}, "stages": _track_stage([TOOL_DOWN, {"id": "_pull", "level": "tcp_motion", "attr": "pos", "frame": "base",
                                                                               "axes": ["x", "y", "z"], "mode": "target", "target": [0.55, 0.15, 0.30],
                                                                               "sigma": 0.02, "weight": 0.5}])},
})

PROBES.update({
    "order": {"task": "seq", "bias": None,
              "edits": [("按压保持之后不用抬起,直接结束。", lambda c: [{"id": "order", "field": "target", "value": ["descend", "press_hold"]}]),
                        ("去掉按压保持这一步:下探碰到桌面后直接抬起。", lambda c: [{"id": "order", "field": "target", "value": ["descend", "lift"]}])]},
    "touch": {"task": "seq", "bias": {"kind": "sensor_scale", "value": 0.6},
              "edits": [("下探时等法向力达到 3 牛再切换。", lambda c: [{"id": "touch", "field": "target", "value": 3.0}]),
                        ("切换时刻的力允许误差放宽到 1 牛。", lambda c: [{"id": "touch", "field": "tol", "value": 1.0}])]},
    "hold": {"task": "seq", "bias": {"kind": "scale", "value": 0.8},
             "edits": [("按压保持的时间改为 3 秒。", lambda c: [{"id": "hold", "field": "target", "value": 3.0}]),
                       ("按压保持时长的允许误差放宽到 0.3 秒。", lambda c: [{"id": "hold", "field": "tol", "value": 0.3}])]},
    "keep": {"task": "seq", "bias": None,
             "edits": [("按压保持阶段接触时间比例的要求降到 0.9。", lambda c: [{"id": "keep", "field": "target", "value": 0.9}]),
                       ("接触比例的允许误差改为 0.02。", lambda c: [{"id": "keep", "field": "tol", "value": 0.02}])]},
    "tap": {"task": "period", "bias": {"kind": "scale", "value": 0.85},
            "edits": [("按压周期改为 1.5 秒。", lambda c: [{"id": "tap", "field": "target", "value": 1.5}]),
                      ("按压周期的允许误差放宽到 0.15 秒。", lambda c: [{"id": "tap", "field": "tol", "value": 0.15}])]},
    "follow": {"task": "follow", "bias": {"kind": "frame", "frame": "object:mov", "value": [0.012, -0.010, 0.0]},
               "edits": [("跟随时末端保持在物体上方 15 厘米。", lambda c: [{"id": "follow", "field": "target", "value": [0.0, 0.0, 0.15]}]),
                         ("跟随位置的允许误差放宽到 1.2 厘米。", lambda c: [{"id": "follow", "field": "tol", "value": 0.012}])]},
    "align": {"task": "follow", "bias": {"kind": "add", "value": 0.1},
              "edits": [("工具轴与物体法向的夹角改为 0.3 弧度。", lambda c: [{"id": "align", "field": "target", "value": 0.3}]),
                        ("这个夹角的允许误差放宽到 0.06 弧度。", lambda c: [{"id": "align", "field": "tol", "value": 0.06}])]},
    "near": {"task": "near", "bias": {"kind": "frame", "frame": "object:mov", "value": [0.0, 0.02, 0.0]},
             "edits": [("允许离开球心的最大距离改为 5 厘米。", lambda c: [{"id": "near", "field": "ub", "value": 0.05}]),
                       ("这个距离上限的余量放宽到 1 厘米。", lambda c: [{"id": "near", "field": "tol", "value": 0.01}])]},
    "tip": {"task": "tip", "bias": {"kind": "frame", "frame": "object:mov", "value": [0.012, -0.010, 0.0]},
            "edits": [("笔尖改为保持在物体上方 5 厘米。", lambda c: [{"id": "tip", "field": "target", "value": [0.0, 0.0, 0.05]}]),
                      ("笔尖跟随的允许误差放宽到 1.2 厘米。", lambda c: [{"id": "tip", "field": "tol", "value": 0.012}])]},
})


# ───────────────────────────────────────────── 2026-10-27 第三批:K3 加速度(运行时新增种类 lin_acc)、K4 到达时长、C2 接触位置、C5 刚度、J4 构型类别
import exp_sweep.ext_attrs  # noqa: E402,F401  (注册 lin_acc)


def accel_contract(c):
    return [
        # 11-07:attr lin_acc → acc。11-06 核心把 lin_acc 改成要写 axes 的向量量(ext_attrs 的「模」定义随之不再生效),
        # 这一项的本意是加速度的模,对应核心新加的 acc。改前见 backup_20261107_before_pms/exp_sweep/tasks.py
        {"id": "acc", "cat": "K3", "desc": "末端线加速度的上限(m/s²)", "level": "tcp_motion", "attr": "acc", "frame": "base", "stage": "go",
         "kind": "upper", "ub": 0.3, "tol": 0.05, "unit": "m/s^2", "sigma": 0.03, "weight": 6},
        {"id": "vx2", "cat": "K1", "desc": "末端沿基座 x 方向的线速度", "level": "tcp_motion", "attr": "lin_vel", "frame": "base", "axes": ["x"], "stage": "go",
         "kind": "target", "target": 0.12, "tol": 0.012, "unit": "m/s", "sigma": 0.01, "weight": 2},
    ]


def timed_contract(c):
    return [
        {"id": "arrive", "cat": "K4", "desc": "从当前位置到达目标位置所用的时间(到达 = 距目标 5 mm 以内)", "kind": "arrival", "stage": "go", "frame": "base",
         "axes": ["x", "y", "z"], "goal": _l(c["p0"] + [0.10, 0.05, -0.08]), "arrive_radius": 0.005, "target": 1.5, "tol": 0.25, "unit": "s"},
    ]


def config_contract(c):
    return [
        {"id": "arm", "cat": "J4", "desc": "手臂构型类别:手肘在左侧(基座 +y)或右侧(-y)", "kind": "config", "stage": "go", "target": "left",
         "margin": 0.06, "class_th": 0.03, "tol": 0.0, "unit": "-"},
        {"id": "hold3", "cat": "G1", "desc": "末端保持在起始位置", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["x", "y", "z"], "stage": "go",
         "kind": "target", "target": _l(c["p0"]), "tol": 0.005, "unit": "m", "sigma": 0.005, "weight": 2},
    ]


def stiff_contract(c):
    return [
        {"id": "soft", "cat": "C5", "desc": "执行层平动刚度(N/m,工具坐标系 x、y、z)", "kind": "stiffness", "stage": "go", "frame": "tool",
         "target": [1500.0, 1500.0, 1500.0], "tol": 0.0, "unit": "N/m"},
        {"id": "hold4", "cat": "G1", "desc": "末端保持在起始位置", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["x", "y", "z"], "stage": "go",
         "kind": "target", "target": _l(c["p0"]), "tol": 0.005, "unit": "m", "sigma": 0.005, "weight": 2},
    ]


_go = lambda t, helpers=(): [{"id": "go", "time_s": t, "timeout_s": t + 1.0, "helpers_fn": lambda ctx: list(helpers)}]

TASKS.update({
    "accel": {"contract_fn": accel_contract, "chunk": 5, "verify_skip_s": {"*": 0.0, "vx2": 1.8}, "stages": _go(2.6, [TOOL_DOWN])},
    "timed": {"contract_fn": timed_contract, "chunk": 5, "verify_skip_s": {"*": 0.0}, "stages": _go(3.5, [TOOL_DOWN])},
    "config": {"contract_fn": config_contract, "chunk": 5, "verify_skip_s": {"*": 1.5}, "stages": _go(3.0, [TOOL_DOWN])},
    "stiff": {"contract_fn": stiff_contract, "chunk": 5, "verify_skip_s": {"*": 1.0}, "stages": _go(2.5, [TOOL_DOWN])},
})

# C2:接触位置,加到 seq 任务的按压保持阶段(同时取代那一阶段的 xy 保持辅助项)
_seq_old = seq_contract


def seq_contract(c):  # noqa: F811
    return _seq_old(c) + [
        {"id": "spot", "cat": "C2", "desc": "接触位置(桌面坐标系 xy;下探与按压保持阶段都按它定位,验收只统计按压保持阶段处于接触的时刻)", "kind": "contact_at",
         "stage": "press_hold", "also_stages": ["descend"],
         "level": "tcp_motion", "attr": "pos", "frame": "surface:table", "axes": ["x", "y"], "target": list(XY_A), "tol": 0.004, "unit": "m",
         "sigma": 0.005, "weight": 2}]


TASKS["seq"]["contract_fn"] = seq_contract
TASKS["seq"]["stages"][1]["helpers_fn"] = lambda ctx: [KEEP_ORI]

PROBES.update({
    "acc": {"task": "accel", "bias": {"kind": "add", "value": 0.4},
            "edits": [("加速度上限改为 0.5 米每二次方秒。", lambda c: [{"id": "acc", "field": "ub", "value": 0.5}]),
                      ("加速度上限的余量放宽到 0.1。", lambda c: [{"id": "acc", "field": "tol", "value": 0.1}])]},
    "arrive": {"task": "timed", "bias": {"kind": "scale", "value": 0.5},
               "edits": [("改为 2.5 秒到达目标。", lambda c: [{"id": "arrive", "field": "target", "value": 2.5}]),
                         ("到达时间的允许误差放宽到 0.4 秒。", lambda c: [{"id": "arrive", "field": "tol", "value": 0.4}])]},
    "arm": {"task": "config", "bias": {"kind": "add", "value": -0.07},
            "edits": [("手臂改成右侧位形。", lambda c: [{"id": "arm", "field": "target", "value": "right"}]),
                      ("手臂改成手肘在 -y 一侧。", lambda c: [{"id": "arm", "field": "target", "value": "right"}])]},
    "soft": {"task": "stiff", "bias": None,
             "edits": [("把末端沿工具 z 方向的刚度降到 300 牛每米,其余方向不变。", lambda c: [{"id": "soft", "field": "target", "value": [1500.0, 1500.0, 300.0]}]),
                       ("三个方向的刚度都改为 800 牛每米。", lambda c: [{"id": "soft", "field": "target", "value": [800.0, 800.0, 800.0]}])]},
    "spot": {"task": "seq", "bias": {"kind": "frame", "frame": "surface:table", "value": [0.008, -0.006, 0.0]},
             "edits": [("按压位置沿桌面 x 正方向挪 2 厘米。", lambda c: [{"id": "spot", "field": "target", "value": [XY_A[0] + 0.02, XY_A[1]]}]),
                       ("按压位置的允许误差放宽到 6 毫米。", lambda c: [{"id": "spot", "field": "tol", "value": 0.006}])]},
})

TASKS["seq"]["stages"][0]["helpers_fn"] = lambda ctx: [DOWN, KEEP_ORI]          # 下探阶段的 xy 由接触位置项 spot 给定


# ───────────────────────────────────────────── C1 的修复探针:滑动中靠法向力下限维持接触;隐藏偏差 = 力传感零点偏移(下限被抵掉,末端被上抬项带离桌面)
def slide_contract(c):
    return [
        {"id": "keep2", "cat": "C1", "desc": "滑动阶段内处于接触的时间比例(执行侧以法向力下限维持接触,comp 加在下限上)", "kind": "contact", "stage": "slide",
         "target": 1.0, "tol": 0.05, "unit": "-", "floor": 4.0, "frame": "surface:table"},
        {"id": "vy", "cat": "K1", "desc": "沿桌面 y 方向滑动的速度", "level": "tcp_motion", "attr": "lin_vel", "frame": "surface:table", "axes": ["y"],
         "stage": "slide", "kind": "target", "target": 0.02, "tol": 0.004, "unit": "m/s", "sigma": 0.005, "weight": 2},
    ]


TASKS["slide"] = {"contract_fn": slide_contract, "scene": True, "chunk": 5, "pre": [(_approach(XY_A), 6)],
                  "frames_fn": lambda p0, R0: {"surface:table": (np.eye(3), TABLE_ORIGIN.copy())},
                  "verify_skip_s": {"*": 0.5},
                  "stages": [{"id": "touchdown", "time_s": 2.5, "timeout_s": 3.0, "helpers_fn": lambda ctx: [
                                 {"id": "_f2", "level": "tcp_force", "attr": "force", "frame": "surface:table", "axes": ["z"], "mode": "target", "target": 2.0,
                                  "sigma": 2.0, "weight": 3}, _xy_hold(XY_A), KEEP_ORI]},
                             {"id": "slide", "time_s": 3.0, "timeout_s": 3.5, "helpers_fn": lambda ctx: [
                                 {"id": "_x", "level": "tcp_motion", "attr": "pos", "frame": "surface:table", "axes": ["x"], "mode": "target",
                                  "target": XY_A[0], "sigma": 0.005, "weight": 2},
                                 {"id": "_lift", "level": "tcp_motion", "attr": "lin_vel", "frame": "surface:table", "axes": ["z"], "mode": "target",
                                  "target": 0.003, "sigma": 0.004, "weight": 0.5}, KEEP_ORI]}]}
PROBES["keep2"] = {"task": "slide", "bias": {"kind": "add", "value": -5.0},
                   "edits": [("滑动阶段接触时间比例的要求降到 0.9。", lambda c: [{"id": "keep2", "field": "target", "value": 0.9}]),
                             ("滑动速度改为每秒 3 厘米。", lambda c: [{"id": "vy", "field": "target", "value": 0.03}])]}


# ───────────────────────────────────────────── C4 末端力矩:按压桌面的同时绕法向施加力矩(边压边拧);执行层力矩导纳,力矩传感有隐藏比例偏差
def twist_contract(c):
    return [
        {"id": "twist", "cat": "C4", "desc": "按压桌面时绕桌面法向(基座 +z)施加的力矩(机器人对桌面,N·m)", "kind": "torque", "stage": "twist",
         "target": 0.08, "tol": 0.015, "unit": "N*m", "k_adm": 1.0},
        {"id": "press3", "cat": "C3", "desc": "拧的同时保持的法向力", "level": "tcp_force", "attr": "force", "frame": "surface:table", "axes": ["z"], "stage": "twist",
         "kind": "target", "target": 5.0, "tol": 1.5, "unit": "N", "sigma": 2.0, "weight": 3},
    ]


TASKS["twist"] = {"contract_fn": twist_contract, "scene": True, "chunk": 1, "pre": [(_approach(XY_A), 6)], "friction_mod": [1.0, 0.03, 1e-4],
                  "frames_fn": lambda p0, R0: {"surface:table": (np.eye(3), TABLE_ORIGIN.copy())},
                  "verify_skip_s": {"*": 1.5},
                  "stages": [{"id": "settle", "time_s": 2.5, "timeout_s": 3.0, "helpers_fn": lambda ctx: [
                                 {"id": "_f3", "level": "tcp_force", "attr": "force", "frame": "surface:table", "axes": ["z"], "mode": "target", "target": 5.0,
                                  "sigma": 2.0, "weight": 3}, _xy_hold(XY_A), KEEP_ORI]},
                             {"id": "twist", "time_s": 4.0, "timeout_s": 4.5, "helpers_fn": lambda ctx: [_xy_hold(XY_A)]}]}
PROBES["twist"] = {"task": "twist", "bias": {"kind": "sensor_scale", "value": 0.6},
                   "edits": [("拧的力矩改为 0.12 牛米。", lambda c: [{"id": "twist", "field": "target", "value": 0.12}]),
                             ("力矩的允许误差放宽到 0.03 牛米。", lambda c: [{"id": "twist", "field": "tol", "value": 0.03}])]}
