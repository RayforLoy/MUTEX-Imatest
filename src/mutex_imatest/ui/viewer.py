from __future__ import annotations
from collections import OrderedDict
import math
import numpy as np
from PySide6.QtCore import Qt,Signal,QRectF,QTimer,QPointF
from PySide6.QtGui import QImage,QPixmap,QPen,QBrush,QColor,QTransform,QPainter
from PySide6.QtWidgets import QGraphicsView,QGraphicsScene,QGraphicsItem,QGraphicsSimpleTextItem
from ..workers import TileReader
from ..heatmap import heatmap_rgba,colorize
from ..models import Measurement,AnalysisResult
from ..preview_orientation import PreviewOrientation

def qimage(array):
    a=np.ascontiguousarray(array,np.uint8);h,w,c=a.shape
    format=QImage.Format.Format_RGBA8888 if c==4 else QImage.Format.Format_RGB888
    return QImage(a.data,w,h,a.strides[0],format).copy()

class ImageViewer(QGraphicsView):
    region_selected=Signal(str)
    zoom_changed=Signal(float)
    anchors_done=Signal(list)
    view_changed=Signal(object)
    orientation_changed=Signal(object)
    error=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#e9eef3"))
        self.setRenderHints(QPainter.RenderHint.Antialiasing|QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.metadata=None;self.preview_item=None;self.overlay_item=None;self.annotations=[]
        self.result=None;self.selected_metric="mtf50";self.channel="G";self.unit="cy/px";self.alpha=.48;self.interpolate=True
        self.tile_items=OrderedDict();self.pending=set();self.tile_bytes=0;self.limit=256*2**20
        self.reader=TileReader(self);self.reader.ready.connect(self._tile_ready);self.reader.error.connect(self.error);self.reader.start()
        self.generation=0;self.request_timer=QTimer(self);self.request_timer.setSingleShot(True);self.request_timer.timeout.connect(self._request_tiles)
        self.anchor_mode=False;self.anchors=[];self.fitted=True;self.syncing=False
        self.orientation=PreviewOrientation()
        self.setToolTip("滚轮缩放 · 拖动平移 · 点击测量点查看曲线")
    def load(self,path,metadata,config,native_cache=None,orientation=None):
        self.scene().clear();self.annotations=[];self.preview_item=None;self.overlay_item=None
        self.tile_items.clear();self.pending.clear();self.tile_bytes=0;self.result=None
        self.metadata=metadata;self.config=config;self.limit=config.tile_cache_mb*2**20
        self.orientation=PreviewOrientation.from_dict(orientation)
        self.setTransform(self.orientation_transform())
        pixmap=QPixmap(str(path))
        if pixmap.isNull():return
        self.preview_item=self.scene().addPixmap(pixmap)
        self.preview_item.setTransform(QTransform.fromScale(metadata.width/pixmap.width(),metadata.height/pixmap.height()))
        self.preview_item.setZValue(0)
        self.scene().setSceneRect(0,0,metadata.width,metadata.height)
        self.generation=self.reader.reset(metadata.path,config,metadata,native_cache)
        self.fit_image()
        self.orientation_changed.emit(self.orientation.to_dict())
    def orientation_transform(self,scale=1.):
        m=self.orientation.matrix()*scale
        return QTransform(m[0,0],m[1,0],m[0,1],m[1,1],0,0)
    def zoom_scale(self):return math.hypot(self.transform().m11(),self.transform().m12())
    def set_orientation(self,orientation):
        if not self.metadata:return
        self.orientation=orientation if isinstance(orientation,PreviewOrientation) else PreviewOrientation.from_dict(orientation)
        self.setTransform(self.orientation_transform());self.fit_image()
        self.orientation_changed.emit(self.orientation.to_dict())
    def rotate_preview(self,step):self.set_orientation(self.orientation.rotated(step))
    def mirror_preview(self,axis):self.set_orientation(self.orientation.mirrored(axis))
    def reset_orientation(self):self.set_orientation(PreviewOrientation())
    def fit_image(self):
        if self.metadata:
            self.fitInView(self.scene().sceneRect(),Qt.AspectRatioMode.KeepAspectRatio);self.fitted=True
            self._changed()
    def native_zoom(self):
        center=self.mapToScene(self.viewport().rect().center())
        self.setTransform(self.orientation_transform());self.centerOn(center);self.fitted=False;self._changed()
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.fitted:self.fit_image()
        else:self._changed()
    def wheelEvent(self,event):
        if not self.metadata:return
        self.fitted=False
        factor=1.25 if event.angleDelta().y()>0 else .8
        current=self.zoom_scale()
        if .005<current*factor<20:self.scale(factor,factor)
        self._changed();event.accept()
    def scrollContentsBy(self,dx,dy):
        super().scrollContentsBy(dx,dy);self.request_timer.start(100)
        self.emit_view_state()
    def _changed(self):
        self.zoom_changed.emit(self.zoom_scale()*100);self.request_timer.start(100)
        self.emit_view_state()
    def emit_view_state(self):
        if self.syncing or not self.metadata:return
        center=self.mapToScene(self.viewport().rect().center())
        self.view_changed.emit({"scale":self.zoom_scale(),"center":[center.x()/self.metadata.width,center.y()/self.metadata.height],"width":self.metadata.width,"orientation":self.orientation.to_dict()})
    def apply_view_state(self,state):
        if not self.metadata:return
        self.syncing=True;self.fitted=False
        scale=state["scale"]*state["width"]/self.metadata.width
        self.orientation=PreviewOrientation.from_dict(state.get('orientation'))
        self.setTransform(self.orientation_transform(scale))
        self.centerOn(state["center"][0]*self.metadata.width,state["center"][1]*self.metadata.height)
        self.syncing=False;self.request_timer.start(100)
        self.orientation_changed.emit(self.orientation.to_dict())
    def _request_tiles(self):
        if not self.metadata or not self.preview_item:return
        scale=max(self.zoom_scale(),1e-5)
        level=max(0,int(math.floor(math.log2(1/scale)))) if scale<1 else 0
        preview_level=max(0,int(math.ceil(math.log2(max(self.metadata.width/self.preview_item.pixmap().width(),1)))))
        if level>=preview_level:return
        visible=self.mapToScene(self.viewport().rect()).boundingRect().intersected(self.sceneRect())
        span=512*(2**level)
        x0=int(visible.left())//span;y0=int(visible.top())//span
        x1=int(visible.right())//span;y1=int(visible.bottom())//span
        for ty in range(y0,y1+1):
            for tx in range(x0,x1+1):
                key=(level,tx,ty)
                if key in self.tile_items:self.tile_items.move_to_end(key);continue
                if key in self.pending or len(self.pending)>80:continue
                x=tx*span;y=ty*span
                w=min(span,self.metadata.width-x);h=min(span,self.metadata.height-y)
                if min(w,h)<=0:continue
                self.pending.add(key);self.reader.request(self.generation,key,(x,y,w,h),level)
    def _tile_ready(self,data):
        if data["generation"]!=self.generation:return
        key=data["key"];self.pending.discard(key)
        if key in self.tile_items:return
        x,y,w,h=data["box"]
        pixmap=QPixmap.fromImage(qimage(data["pixels"]))
        item=self.scene().addPixmap(pixmap);item.setPos(x,y)
        item.setTransform(QTransform.fromScale(w/pixmap.width(),h/pixmap.height()))
        item.setZValue(1+1/(data["level"]+1))
        size=pixmap.width()*pixmap.height()*4
        self.tile_items[key]=(item,size);self.tile_bytes+=size
        while self.tile_bytes>self.limit and len(self.tile_items)>1:
            _,(old,oldsize)=self.tile_items.popitem(last=False);self.scene().removeItem(old);self.tile_bytes-=oldsize
    def set_result(self,result,metric=None,channel=None,unit=None,alpha=None,interpolate=None):
        self.result=result
        if metric:self.selected_metric=metric
        if channel:self.channel=channel
        if unit:self.unit=unit
        if alpha is not None:self.alpha=alpha
        if interpolate is not None:self.interpolate=interpolate
        self.refresh_overlay()
    def refresh_overlay(self,visible=True,limits=None):
        for item in self.annotations:self.scene().removeItem(item)
        self.annotations=[]
        if self.overlay_item:self.scene().removeItem(self.overlay_item);self.overlay_item=None
        if not self.result or not self.metadata:return None
        data=heatmap_rgba(self.result,self.selected_metric,self.channel,800,None,self.unit,self.alpha,self.interpolate,limits)
        if visible and self.alpha>0:
            pixmap=QPixmap.fromImage(qimage(data["rgba"]))
            self.overlay_item=self.scene().addPixmap(pixmap);self.overlay_item.setZValue(5)
            self.overlay_item.setTransform(QTransform.fromScale(self.metadata.width/pixmap.width(),self.metadata.height/pixmap.height()))
        for m in self.result.measurements:
            if m.channel!=self.channel:continue
            x,y,w,h=m.box_pixels
            color=QColor("#12847f" if m.valid else "#ce8961")
            pen=QPen(color,1.1);pen.setCosmetic(True)
            box=self.scene().addRect(x,y,w,h,pen);box.setZValue(7);box.setData(0,m.region_id);self.annotations.append(box)
            radius=2.5 if self.zoom_scale()<.06 else 4
            point=self.scene().addEllipse(-radius,-radius,radius*2,radius*2,QPen(QColor("#214351"),1),QBrush(QColor("white")))
            point.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations);point.setPos(*m.position);point.setZValue(9);point.setData(0,m.region_id)
            value=m.metric(data['metric'])
            point.setToolTip(f"{m.label} · {m.channel}\n{value:.5g} {self.unit}\n{', '.join(m.flags) or '有效'}" if value is not None else f"{m.label}\n{', '.join(m.flags) or '无有效数据'}")
            self.annotations.append(point)
            if self.zoom_scale()<.06 and len(data['points'])>12:continue
            value=m.metric(data["metric"])
            label=self.scene().addSimpleText(f"{value:.3f}" if value is not None and m.valid else "—" if m.valid else "×")
            label.setBrush(QBrush(QColor("#103d4a")));label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            label.setPos(m.position[0]+8,m.position[1]-18);label.setZValue(9);label.setData(0,m.region_id)
            self.annotations.append(label)
        return data
    def begin_anchors(self):
        if not self.metadata:return
        self.anchor_mode=True;self.anchors=[];self.setDragMode(QGraphicsView.DragMode.NoDrag);self.setCursor(Qt.CursorShape.CrossCursor)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.anchor_mode:
            p=self.mapToScene(event.position().toPoint())
            if not self.sceneRect().contains(p):return
            self.anchors.append([p.x(),p.y()])
            pen=QPen(QColor("#e88f42"),3);pen.setCosmetic(True)
            dot=self.scene().addEllipse(-5,-5,10,10,pen,QBrush(QColor("white")))
            dot.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations);dot.setPos(p);dot.setZValue(20);self.annotations.append(dot)
            if len(self.anchors)==4:
                self.anchor_mode=False;self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag);self.unsetCursor();self.anchors_done.emit(self.anchors)
            return
        item=self.itemAt(event.position().toPoint())
        if item and item.data(0):self.region_selected.emit(str(item.data(0)))
        super().mousePressEvent(event)
    def cancel_anchors(self):
        self.anchor_mode=False;self.anchors=[];self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag);self.unsetCursor()
    def close_reader(self):self.reader.close()
