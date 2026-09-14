"""Pascal VOC, YOLO and CreateML, exactly as LabelImg has always written them.

The writer classes are LabelImg's own and emit the same bytes they always
did; only the import lines and the readers' Qt dependency changed.  The test
suite compares the output byte for byte against the original modules whenever
the labelImg-master folder is present beside the suite.
"""

DEFAULT_ENCODING = "utf-8"
