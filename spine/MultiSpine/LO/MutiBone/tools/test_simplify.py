# -*- coding: utf-8 -*-
"""骨时间轴抽稀的最小回归测试（不加载 Unity 工程）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from convert_bones import (  # noqa: E402
    _planar_apply, _planar_inverse_point, _planar_inverse_vector,
    _simplify, _simplify_deform)


def main():
    linear = [
        {"time": 0.0, "x": 0.0, "y": 0.0},
        {"time": 1.0, "x": 1.0, "y": 1.0},
        {"time": 2.0, "x": 2.0, "y": 2.0},
    ]
    spike = [
        {"time": 0.0, "x": 0.0, "y": 0.0},
        {"time": 1.0, "x": 1.0, "y": 10.0},
        {"time": 2.0, "x": 2.0, "y": 0.0},
    ]
    assert len(_simplify(linear, ("x", "y"), 0.01)) == 2
    assert len(_simplify(spike, ("x", "y"), 0.01)) == 3
    assert len(_simplify(spike, ("x", "y"), 20.0)) == 2

    deform_linear = [
        {"time": 0.0, "vertices": [0.0, 0.0, 1.0, -1.0]},
        {"time": 1.0, "vertices": [1.0, 2.0, 2.0, 1.0]},
        {"time": 2.0, "vertices": [2.0, 4.0, 3.0, 3.0]},
    ]
    deform_spike = [
        {"time": 0.0, "vertices": [0.0, 0.0]},
        {"time": 1.0, "vertices": [1.0, 10.0]},
        {"time": 2.0, "vertices": [2.0, 0.0]},
    ]
    assert len(_simplify_deform(deform_linear, 0.01)) == 2
    assert len(_simplify_deform(deform_spike, 0.01)) == 3

    # Matrix4x4 is row-major in this converter: translation is (12,13)
    # in Unity serialization, but the shared 4x4 flat tuple stores it at 3,7.
    matrix = [0.0, -2.0, 0.0, 5.0,
              3.0, 0.0, 0.0, -4.0,
              0.0, 0.0, 1.0, 0.0,
              0.0, 0.0, 0.0, 1.0]
    wx, wy = _planar_apply(matrix, 7.0, 11.0)
    lx, ly = _planar_inverse_point(matrix, (wx, wy))
    assert abs(lx - 7.0) < 1e-9 and abs(ly - 11.0) < 1e-9
    vx, vy = _planar_inverse_vector(matrix, 6.0, -4.0)
    assert abs(vx - (-4.0 / 3.0)) < 1e-9
    assert abs(vy - (-3.0)) < 1e-9
    print("simplify, deform and planar inverse tests OK")


if __name__ == "__main__":
    main()
