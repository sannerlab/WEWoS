
# ---------------------------------------------------------------------------------------
# WEWoS: the image type, and the nodes that used Tk or OpenGL
# ---------------------------------------------------------------------------------------

class ImageType(AnyArrayType):
    """'image': a PIL image."""

    def __init__(self, name='image', datashape=None, color='#995699', shape='rect',
                 width=None, height=None):
        AnyArrayType.__init__(self, name=name, color=color, shape=shape, klass=Image.Image)


def image_png(image, maxsize=1600):
    """A PNG data URL of image (scaled down to maxsize pixels at most)."""
    import base64
    import io
    im = image
    if max(im.size) > maxsize:
        im = im.copy()
        im.thumbnail((maxsize, maxsize))
    if im.mode not in ('RGB', 'RGBA', 'L', 'LA', 'P'):
        im = im.convert('RGBA')
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


class ShowImage(NetworkNode):
    """Show an image in a panel of the page (in the row of panels under the
network, beside the 3D viewers).

Input Ports
    image: the image to show
"""

    def __init__(self, name='Show Image', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.image = None
        self.imageVersion = 0
        self.inputPortsDescr.append(datatype='image', name='image')
        self.setFunction("""def doit(self, image):
    self.showImage(image)
""")

    def showImage(self, image):
        self.image = image
        self.imageVersion += 1
        if self.network is not None:
            self.network.emit('image', node=self.id, name=self.name,
                              version=self.imageVersion, size=list(image.size))

    def imageData(self):
        if self.image is None:
            return {'png': None}
        return {'png': image_png(self.image), 'size': list(self.image.size),
                'mode': self.image.mode, 'version': self.imageVersion}

    def describe(self):
        d = NetworkNode.describe(self)
        d['imageViewer'] = True
        return d


class GetFrontBuffer(NetworkNode):
    """Take a snapshot of a 3D viewer as an image (Vision read the OpenGL
front buffer; here the page sends the picture the viewer shows).
The page must be open, with the viewer visible.

Input Ports
    viewer: the 'viewer' output of a Viewer node
    cameraNum: not used (kept for networks made with Vision)
Output Ports
    image: an RGBA image
"""

    def __init__(self, name='Grab Image', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='viewer', name='viewer')
        self.inputPortsDescr.append(datatype='int', required=False, name='cameraNum')
        self.outputPortsDescr.append(datatype='image', name='image')
        self.setFunction("""def doit(self, viewer, cameraNum):
    self.outputData(image=viewer.snapshot())
""")
