# Copyright (c) 2016 Tzutalin
# Create by TzuTaLin <tzu.ta.lin@gmail.com>
"""The points -> bounding box conversion every LabelImg writer goes through.

Kept exactly as it was, including the clamp of a 0 coordinate to 1 (some
older detectors choke on zero-valued boxes), because it decides the numbers
that end up in every VOC and YOLO file.
"""


def convert_points_to_bnd_box(points):
    """Points -> (xmin, ymin, xmax, ymax).

    An empty point list used to leave the bounds at +/-inf, and ``int(inf)``
    raises OverflowError from inside the save path.
    """
    if not points:
        return 1, 1, 1, 1
    x_min = float('inf')
    y_min = float('inf')
    x_max = float('-inf')
    y_max = float('-inf')
    for p in points:
        x = p[0]
        y = p[1]
        x_min = min(x, x_min)
        y_min = min(y, y_min)
        x_max = max(x, x_max)
        y_max = max(y, y_max)

    # Martin Kersner, 2015/11/12
    # 0-valued coordinates of BB caused an error while
    # training faster-rcnn object detector.
    if x_min < 1:
        x_min = 1

    if y_min < 1:
        y_min = 1

    # A box dragged to zero size, or coordinates that came back as NaN from
    # a corrupt annotation, must not take the application down.
    def _clean(value, default):
        try:
            if value != value or value in (float('inf'), float('-inf')):
                return default
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default

    return (_clean(x_min, 1), _clean(y_min, 1),
            _clean(x_max, 1), _clean(y_max, 1))
