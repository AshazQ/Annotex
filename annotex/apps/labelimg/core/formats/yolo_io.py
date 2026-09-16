#!/usr/bin/env python
# -*- coding: utf8 -*-
"""YOLO reader and writer - LabelImg's own, unchanged in what it emits.

The only change is that the reader takes the image size as numbers rather
than a QImage, so this module no longer needs Qt.
"""
import codecs
import os

from . import DEFAULT_ENCODING

TXT_EXT = '.txt'
ENCODE_METHOD = DEFAULT_ENCODING


class YOLOWriter:

    def __init__(self, folder_name, filename, img_size, database_src='Unknown', local_img_path=None):
        self.folder_name = folder_name
        self.filename = filename
        self.database_src = database_src
        self.img_size = img_size
        self.box_list = []
        self.local_img_path = local_img_path
        self.verified = False

    def add_bnd_box(self, x_min, y_min, x_max, y_max, name, difficult):
        bnd_box = {'xmin': x_min, 'ymin': y_min, 'xmax': x_max, 'ymax': y_max}
        bnd_box['name'] = name
        bnd_box['difficult'] = difficult
        self.box_list.append(bnd_box)

    def bnd_box_to_yolo_line(self, box, class_list=None, class_id_map=None):
        if class_list is None:
            class_list = []
        x_min = box['xmin']
        x_max = box['xmax']
        y_min = box['ymin']
        y_max = box['ymax']

        # A zero-sized image (an unreadable or truncated file) used to raise
        # ZeroDivisionError from inside the save path.
        image_height = self.img_size[0] or 1
        image_width = self.img_size[1] or 1

        x_center = float((x_min + x_max)) / 2 / image_width
        y_center = float((y_min + y_max)) / 2 / image_height

        w = float((x_max - x_min)) / image_width
        h = float((y_max - y_min)) / image_height

        box_name = box['name']

        # Preferred path: the Class Manager supplies a stable {name: id} map,
        # so a class keeps the same YOLO index for the life of the project even
        # if other classes are added or removed around it.
        if class_id_map and box_name in class_id_map:
            return int(class_id_map[box_name]), x_center, y_center, w, h

        # Fallback (unchanged upstream behaviour, PR387): index into class_list.
        if box_name not in class_list:
            class_list.append(box_name)

        class_index = class_list.index(box_name)

        return class_index, x_center, y_center, w, h

    def save(self, class_list=None, target_file=None, class_id_map=None):
        if class_list is None:
            class_list = []
        else:
            # Never mutate the caller's list.
            class_list = list(class_list)

        if target_file is None:
            target_file = self.filename + TXT_EXT
        classes_file = os.path.join(
            os.path.dirname(os.path.abspath(target_file)), "classes.txt")

        # The annotation itself is what matters; classes.txt is a convenience
        # for downstream tooling. Writing them independently means a locked or
        # read-only classes.txt cannot cost the user their labelling.
        out_file = codecs.open(target_file, 'w', encoding=ENCODE_METHOD)
        try:
            for box in self.box_list:
                class_index, x_center, y_center, w, h = self.bnd_box_to_yolo_line(
                    box, class_list, class_id_map)
                out_file.write("%d %.6f %.6f %.6f %.6f\n"
                               % (class_index, x_center, y_center, w, h))
        finally:
            out_file.close()

        try:
            with codecs.open(classes_file, 'w', encoding=ENCODE_METHOD) as out_class_file:
                for c in class_list:
                    out_class_file.write(c + '\n')
        except (IOError, OSError):
            pass


class YoloReader:

    def __init__(self, file_path, image_size, class_list_path=None):
        """`image_size` is (height, width[, depth]) in pixels."""
        # shapes type:
        # [label, [(x1,y1), (x2,y2), (x3,y3), (x4,y4)], color, color, difficult]
        self.shapes = []
        self.file_path = file_path
        self.skipped = 0

        if class_list_path is None:
            dir_path = os.path.dirname(os.path.realpath(self.file_path))
            self.class_list_path = os.path.join(dir_path, "classes.txt")
        else:
            self.class_list_path = class_list_path

        # A missing or unreadable classes.txt used to raise and abort the whole
        # image load; degrade to numeric labels instead so the boxes still show.
        try:
            with codecs.open(self.class_list_path, 'r', encoding=ENCODE_METHOD,
                             errors='replace') as classes_file:
                # Line by line, so a classes.txt saved on Windows does not
                # give every class a trailing carriage return.
                self.classes = [line.strip() for line in
                                classes_file.read().strip('\r\n').splitlines()]
        except (IOError, OSError):
            self.classes = []

        self.img_size = [int(image_size[0]), int(image_size[1]),
                         int(image_size[2]) if len(image_size) > 2 else 3]

        self.verified = False
        self.parse_yolo_format()

    def get_shapes(self):
        return self.shapes

    def add_shape(self, label, x_min, y_min, x_max, y_max, difficult):
        points = [(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)]
        self.shapes.append((label, points, None, None, difficult))

    def yolo_line_to_shape(self, class_index, x_center, y_center, w, h):
        index = int(class_index)
        if 0 <= index < len(self.classes) and self.classes[index]:
            label = self.classes[index]
        else:
            label = 'class_%d' % index

        x_min = max(float(x_center) - float(w) / 2, 0)
        x_max = min(float(x_center) + float(w) / 2, 1)
        y_min = max(float(y_center) - float(h) / 2, 0)
        y_max = min(float(y_center) + float(h) / 2, 1)

        x_min = round(self.img_size[1] * x_min)
        x_max = round(self.img_size[1] * x_max)
        y_min = round(self.img_size[0] * y_min)
        y_max = round(self.img_size[0] * y_max)

        return label, x_min, y_min, x_max, y_max

    def parse_yolo_format(self):
        with codecs.open(self.file_path, 'r', encoding=ENCODE_METHOD,
                         errors='replace') as bnd_box_file:
            for bndBox in bnd_box_file:
                bndBox = bndBox.strip()
                if not bndBox:
                    continue
                try:
                    # Any whitespace: other tools write tabs or double spaces.
                    class_index, x_center, y_center, w, h = bndBox.split()
                    label, x_min, y_min, x_max, y_max = self.yolo_line_to_shape(
                        class_index, x_center, y_center, w, h)
                    self.add_shape(label, x_min, y_min, x_max, y_max, False)
                except ValueError:
                    self.skipped += 1
