# Changelog

What changed in each version of Annotex, newest first.  A release's notes
on GitHub are taken from its section here, so a version with no section
cannot be released.

## 1.1.0

### Download it and run it
- **Annotex is now released as an application.** Download the archive for
  your platform from the Releases page, unpack it, and run `Annotex` - no
  Python, no setup script, nothing installed system-wide.
- **Diagnostics** (the `?` in the bar, or **F1**) shows what Annotex found on
  your machine, the recent log, and the folders it writes to; copies the lot
  for a bug report; and runs every tool's checks again.
- A build with no console window no longer dies trying to print.  Its output,
  Qt's own warnings and the stack of any crash all go to the log.
- Something that stops Annotex from starting is now shown in a window, not
  printed to a terminal that a downloaded application does not have.

### Sessions
- Annotex remembers each folder you work in: the image you reached, how long
  you worked (idle time is not counted), and how the view was laid out.
- **When Annotex starts** can be Home, the last tool you used, or everything
  you had open - each tool back on its folder and image.
- After a crash, Annotex offers once to reopen the folder you were in, on the
  image you were on.
- Sessions made on another computer - from a synced settings folder - are
  listed but never reopened here.
- Home's Continue strip is ordered by when you actually worked in each
  folder; **All sessions…** lists every one.

### AI select, faster
- The images next to the one you are on are prepared in the background, so
  moving to the next image is usually instant.
- What the model works out for an image is kept on disk, so going back to a
  folder costs nothing.  About 2 MB an image, pruned to a 2 GB budget.
- **EfficientSAM ViT-T** can be downloaded from Settings → AI: about three
  times faster than SAM ViT-B.  It cannot use exclude (right) clicks, and
  says so when one is ignored.
- Fixed: an answer from a model you had just replaced could be used as
  though the new model had produced it.

### Image Sorter: by example
- A new **By example** tab.  Give it a folder with one sub-folder of example
  pictures per category, press **Compare**, and every image goes to the
  category it is most like.
- The sliders start where your examples suggest; moving them re-sorts every
  image instantly; the table shows the weakest matches first, with a preview.
- Compare by how pictures look (nothing to download) or by what is in them
  (any ONNX image model, such as a CLIP or DINOv2 image encoder).

## 1.0.0
- Annotex brings ROI Studio, LabelImg Master, LabelImg Shapes, four video
  tools, Image Converter, Image Sorter and Dataset Tools behind one dashboard.
