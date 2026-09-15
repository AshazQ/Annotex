"""A stand-in YOLO detector: a tiny ONNX graph whose output is fixed.

Real detectors are megabytes of weights, but what breaks is the plumbing -
the output layout, the letterbox maths, the class names - so these graphs
return exactly the rows a test asks for, in the layout it asks for.

    rows = [(cx, cy, w, h, [score per class]), …]   in the model's input pixels
"""

import os


def build_detector(path, rows, names=("person", "car"), layout="v8", task=None,
                   side=64, normalised=False, with_names=True):
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    nc = len(names)
    table = []
    for cx, cy, w, h, scores in rows:
        if normalised:
            cx, cy, w, h = cx / side, cy / side, w / side, h / side
        scores = list(scores) + [0.0] * (nc - len(scores))
        if layout == "v8":
            table.append([cx, cy, w, h] + scores)
        elif layout == "v5":
            table.append([cx, cy, w, h, 1.0] + scores)
        elif layout == "e2e":
            best = int(np.argmax(scores))
            table.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, scores[best], best])
    array = np.array(table, dtype=np.float32)
    if layout == "v8":
        array = array.T                                   # (4 + nc, boxes)
    array = array[None]

    image = helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, side, side])
    output = helper.make_tensor_value_info("output0", TensorProto.FLOAT, list(array.shape))
    consts = [numpy_helper.from_array(array, "detections"),
              numpy_helper.from_array(np.array(0.0, dtype=np.float32), "zero")]
    nodes = [
        # The input is consumed (so the graph is a real image model) but does
        # not change the answer.
        helper.make_node("ReduceMean", ["images"], ["mean"], keepdims=0),
        helper.make_node("Mul", ["mean", "zero"], ["nothing"]),
        helper.make_node("Add", ["detections", "nothing"], ["output0"]),
    ]
    graph = helper.make_graph(nodes, "fake_yolo", [image], [output], consts)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    props = {}
    if with_names:
        props["names"] = "{%s}" % ", ".join("%d: '%s'" % (i, n) for i, n in enumerate(names))
    if task:
        props["task"] = task
    if props:
        helper.set_model_props(model, props)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    onnx.save(model, path)
    return path


# A person twice (the second overlapping the first), a car, and a weak person.
STANDARD_ROWS = [
    (16, 32, 16, 16, [0.9, 0.0]),
    (17, 32, 16, 16, [0.8, 0.0]),
    (48, 36, 20, 10, [0.0, 0.7]),
    (40, 40, 8, 8, [0.1, 0.0]),
]
