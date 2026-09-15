"""Build a stand-in for a SAM ONNX export.

The real models are hundreds of megabytes and cannot live in a repository,
but the code that drives them - input names, layouts, prompt encoding, the
shape of what comes back - is exactly what breaks silently.  These two tiny
graphs have the same interface as the reference `segment-anything` export
(and, with `layout="nhwc"`, as the exports that keep the normalisation
inside the graph), so the plumbing can be tested on any machine.

    python tests/ai/fake_sam.py <folder>     write fake_sam.encoder.onnx
                                             and   fake_sam.decoder.onnx
"""

import os
import sys

EMBED_DIM = 32           # the real models use 256; smaller keeps this instant
GRID = 8


def _require():
    try:
        import onnx                                                  # noqa: F401
        return True
    except Exception:
        return False


def build_encoder(path, side=64, layout="nchw", dtype="float32"):
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    kind = TensorProto.FLOAT if dtype == "float32" else TensorProto.UINT8
    shape = [1, 3, side, side] if layout == "nchw" else [1, side, side, 3]
    image = helper.make_tensor_value_info("images", kind, shape)
    embeddings = helper.make_tensor_value_info(
        "image_embeddings", TensorProto.FLOAT, [1, EMBED_DIM, GRID, GRID])

    # The values do not matter - the interface does - but the output must
    # depend on the input or a graph optimiser is free to delete it.
    seed = numpy_helper.from_array(
        np.ones((1, EMBED_DIM, GRID, GRID), dtype=np.float32), name="seed")
    nodes = [
        helper.make_node("Cast", ["images"], ["asfloat"], to=TensorProto.FLOAT),
        helper.make_node("ReduceMean", ["asfloat"], ["scalar"], keepdims=0),
        helper.make_node("Mul", ["seed", "scalar"], ["scaled"]),
        helper.make_node("Add", ["scaled", "seed"], ["image_embeddings"]),
    ]
    graph = helper.make_graph(nodes, "fake_sam_encoder", [image], [embeddings], [seed])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 9
    onnx.save(model, path)
    return path


def build_decoder(path, awkward_order=False):
    """Inputs and outputs of the reference export.

    `awkward_order` declares the inputs in a different order - real exports
    do - which is enough to catch a driver that matches input names by
    substring and puts a mask where a flag belongs."""
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    inputs = [
        helper.make_tensor_value_info("image_embeddings", TensorProto.FLOAT,
                                      [1, EMBED_DIM, GRID, GRID]),
        helper.make_tensor_value_info("point_coords", TensorProto.FLOAT, [1, "n", 2]),
        helper.make_tensor_value_info("point_labels", TensorProto.FLOAT, [1, "n"]),
        helper.make_tensor_value_info("mask_input", TensorProto.FLOAT, [1, 1, 256, 256]),
        helper.make_tensor_value_info("has_mask_input", TensorProto.FLOAT, [1]),
        helper.make_tensor_value_info("orig_im_size", TensorProto.FLOAT, [2]),
    ]
    outputs = [
        helper.make_tensor_value_info("masks", TensorProto.FLOAT, [1, 3, "h", "w"]),
        helper.make_tensor_value_info("iou_predictions", TensorProto.FLOAT, [1, 3]),
        helper.make_tensor_value_info("low_res_masks", TensorProto.FLOAT, [1, 3, 256, 256]),
    ]
    consts = [
        numpy_helper.from_array(np.array([1, 3, 256, 256], dtype=np.int64), name="low_shape"),
        numpy_helper.from_array(np.array([1, 3], dtype=np.int64), name="lead"),
        numpy_helper.from_array(np.array([0.2, 0.9, 0.4], dtype=np.float32).reshape(1, 3),
                                name="iou"),
        numpy_helper.from_array(np.array(-1.0, dtype=np.float32), name="minus"),
        numpy_helper.from_array(np.array(0.0, dtype=np.float32), name="zero"),
        numpy_helper.from_array(np.array(0.5, dtype=np.float32), name="half"),
    ]
    nodes = [
        # masks = ones(1, 3, orig_h, orig_w) * (mean of the embedding, so the
        # encoder's output is genuinely consumed)
        helper.make_node("Cast", ["orig_im_size"], ["size64"], to=TensorProto.INT64),
        helper.make_node("Concat", ["lead", "size64"], ["full_shape"], axis=0),
        helper.make_node("ConstantOfShape", ["full_shape"], ["ones"],
                         value=onnx.helper.make_tensor("v", TensorProto.FLOAT, [1], [1.0])),
        # The embedding is consumed - so a graph optimiser cannot drop the
        # encoder - but its sign is not allowed to decide the answer: the
        # prompt does.  A positive point (or a box) fills the mask, a purely
        # negative prompt empties it.
        helper.make_node("ReduceMean", ["image_embeddings"], ["embed_mean"], keepdims=0),
        helper.make_node("Abs", ["embed_mean"], ["embed_size"]),
        helper.make_node("Add", ["embed_size", "half"], ["strength"]),
        helper.make_node("ReduceMax", ["point_labels"], ["label_max"], keepdims=0),
        helper.make_node("Greater", ["label_max", "zero"], ["any_positive"]),
        helper.make_node("Where", ["any_positive", "strength", "minus"], ["sign"]),
        helper.make_node("Mul", ["ones", "sign"], ["masks"]),
        helper.make_node("Identity", ["iou"], ["iou_predictions"]),
        # low_res_masks = mask_input + has_mask_input, so a test can see that
        # the previous answer really was fed back: each refined click counts up.
        helper.make_node("Expand", ["mask_input", "low_shape"], ["low_expanded"]),
        helper.make_node("Add", ["low_expanded", "has_mask_input"], ["low_res_masks"]),
    ]
    if awkward_order:
        inputs = list(reversed(inputs))
    graph = helper.make_graph(nodes, "fake_sam_decoder", inputs, outputs, consts)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 9
    onnx.save(model, path)
    return path


def build_pair(folder, name="fake_sam", side=64, layout="nchw", dtype="float32"):
    os.makedirs(folder, exist_ok=True)
    encoder = os.path.join(folder, "%s.encoder.onnx" % name)
    decoder = os.path.join(folder, "%s.decoder.onnx" % name)
    build_encoder(encoder, side=side, layout=layout, dtype=dtype)
    build_decoder(decoder)
    return encoder, decoder


if __name__ == "__main__":
    if not _require():
        print("onnx is not installed - nothing written")
        raise SystemExit(0)
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    print("\n".join(build_pair(target)))
