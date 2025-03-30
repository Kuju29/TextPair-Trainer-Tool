import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QPushButton, QGraphicsScene, QTableWidget, QTableWidgetItem,
    QLabel, QSplitter, QHeaderView, QStyledItemDelegate, QTextEdit,
    QGraphicsRectItem, QGraphicsView
)
from PyQt5.QtGui import QPixmap, QPen, QColor, QPainter, QBrush
from PyQt5.QtCore import QRectF, Qt, QThread, pyqtSignal

from ocr_functions import (
    upload_and_get_ocr_result, group_annotations_by_line, pair_groups,
    export_pairs_to_csv
)

# ==================== ZOOMABLE GRAPHICS VIEW ====================
class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.user_scale = 1.0
        self._baseline_transform = None
        self._initial_fit_done = False

    def setInitialFit(self):
        # Fit image once when loaded
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
        self._baseline_transform = self.transform()
        self.user_scale = 1.0
        self._initial_fit_done = True

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            factor = 1.25
        else:
            factor = 0.8
        self.user_scale *= factor
        if self._baseline_transform is not None:
            self.setTransform(self._baseline_transform)
            self.scale(self.user_scale, self.user_scale)
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.scene() is not None:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
            self._baseline_transform = self.transform()
            self.setTransform(self._baseline_transform)
            self.scale(self.user_scale, self.user_scale)

# ==================== DRAGGABLE BOUNDING BOX CLASS ====================
class DraggableRectItem(QGraphicsRectItem):
    def __init__(self, rect, text="", parent=None):
        super().__init__(rect, parent)
        self.setFlags(QGraphicsRectItem.ItemIsMovable |
                      QGraphicsRectItem.ItemIsSelectable |
                      QGraphicsRectItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.text = text
        self.setPen(QPen(QColor("blue"), 2))
        self.resizing = False
        self.resizeHandleSize = 8
        self.updateResizeHandle()
        self.update_callback = None

    def updateResizeHandle(self):
        r = self.rect()
        self.resizeHandleRect = QRectF(
            r.right() - self.resizeHandleSize,
            r.bottom() - self.resizeHandleSize,
            self.resizeHandleSize, self.resizeHandleSize
        )
        self.update()

    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        painter.setBrush(QBrush(QColor("blue")))
        painter.drawRect(self.resizeHandleRect)
        painter.setPen(QPen(QColor("red")))
        painter.drawText(self.rect(), Qt.AlignTop | Qt.AlignLeft, self.text)

    def hoverMoveEvent(self, event):
        if self.resizeHandleRect.contains(event.pos()):
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.setCursor(Qt.OpenHandCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if self.resizeHandleRect.contains(event.pos()):
            self.resizing = True
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.resizing = False
            self.setCursor(Qt.ClosedHandCursor)
        self.prevPos = event.scenePos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.resizing:
            newRect = QRectF(self.rect().topLeft(), event.pos())
            if newRect.width() < 20:
                newRect.setWidth(20)
            if newRect.height() < 20:
                newRect.setHeight(20)
            self.setRect(newRect)
            self.updateResizeHandle()
        else:
            delta = event.scenePos() - self.prevPos
            self.moveBy(delta.x(), delta.y())
            self.prevPos = event.scenePos()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.resizing = False
        self.setCursor(Qt.OpenHandCursor)
        self.updateResizeHandle()
        self.check_and_merge()
        super().mouseReleaseEvent(event)

    def check_and_merge(self):
        colliding_items = self.collidingItems()
        merged = False
        for item in colliding_items:
            if isinstance(item, DraggableRectItem) and item is not self:
                unionRect = self.rect().united(item.rect())
                self.setRect(unionRect)
                if self.text and item.text:
                    self.text = self.text + "\n" + item.text
                elif item.text:
                    self.text = item.text
                self.scene().removeItem(item)
                merged = True
        if merged and self.update_callback:
            self.update_callback()

# ----------------------- ส่วนของ UI -----------------------

class FullTextDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QTextEdit(parent)
        editor.setLineWrapMode(QTextEdit.WidgetWidth)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        return editor

    def setEditorData(self, editor, index):
        full_text = index.data(Qt.UserRole)
        if full_text is None:
            full_text = index.data(Qt.DisplayRole)
        editor.setPlainText(full_text)

    def setModelData(self, editor, model, index):
        full_text = editor.toPlainText()
        model.setData(index, full_text.replace("\n", " "), Qt.DisplayRole)
        model.setData(index, full_text, Qt.UserRole)

class OCRWorker(QThread):
    finished = pyqtSignal(object, object)

    def __init__(self, left_image_path, right_image_path):
        super().__init__()
        self.left_image_path = left_image_path
        self.right_image_path = right_image_path

    def run(self):
        try:
            result_eng = upload_and_get_ocr_result(self.left_image_path)
            result_thai = upload_and_get_ocr_result(self.right_image_path)
            self.finished.emit(result_eng, result_thai)
        except Exception as e:
            self.finished.emit(e, None)

class OCRToolWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TextPair Trainer Tool")
        self.resize(1400, 900)
        
        self.left_image_path = None
        self.right_image_path = None
        self.current_pairs = []
        self.left_boxes_sorted = []
        self.right_boxes_sorted = []
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        
        # Top buttons
        buttons_layout = QHBoxLayout()
        self.upload_left_btn = QPushButton("Upload English Image")
        self.upload_right_btn = QPushButton("Upload Thai Image")
        self.start_ocr_btn = QPushButton("Start OCR")
        self.export_csv_btn = QPushButton("Export CSV")
        self.refresh_table_btn = QPushButton("Refresh Table")
        buttons_layout.addWidget(self.upload_left_btn)
        buttons_layout.addWidget(self.upload_right_btn)
        buttons_layout.addWidget(self.start_ocr_btn)
        buttons_layout.addWidget(self.export_csv_btn)
        buttons_layout.addWidget(self.refresh_table_btn)
        main_layout.addLayout(buttons_layout)
        
        splitter = QSplitter(Qt.Vertical)
        
        images_widget = QWidget()
        images_layout = QHBoxLayout()
        images_widget.setLayout(images_layout)
        self.left_scene = QGraphicsScene()
        self.left_view = ZoomableGraphicsView(self.left_scene)
        self.right_scene = QGraphicsScene()
        self.right_view = ZoomableGraphicsView(self.right_scene)
        images_layout.addWidget(self.left_view)
        images_layout.addWidget(self.right_view)
        splitter.addWidget(images_widget)
        
        table_container = QWidget()
        table_layout = QVBoxLayout()
        table_container.setLayout(table_layout)
        self.group_table = QTableWidget()
        self.group_table.setColumnCount(2)
        self.group_table.setHorizontalHeaderLabels(["English Text", "Thai Text"])
        self.group_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        delegate = FullTextDelegate(self.group_table)
        self.group_table.setItemDelegate(delegate)
        self.group_table.setEditTriggers(QTableWidget.AllEditTriggers)
        self.group_table.setAlternatingRowColors(True)
        table_layout.addWidget(self.group_table)
        splitter.addWidget(table_container)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 0)
        main_layout.addWidget(splitter)
        
        # Status label
        self.status_label = QLabel("Status: Ready")
        main_layout.addWidget(self.status_label)
        
        # Connect buttons
        self.upload_left_btn.clicked.connect(self.upload_left_image)
        self.upload_right_btn.clicked.connect(self.upload_right_image)
        self.start_ocr_btn.clicked.connect(self.start_ocr)
        self.export_csv_btn.clicked.connect(self.export_csv)
        self.refresh_table_btn.clicked.connect(self.refresh_table)
        self.group_table.itemChanged.connect(self.on_table_item_changed)
    
    def on_table_item_changed(self, item):
        row = item.row()
        col = item.column()
        if col == 0:
            if row < len(self.left_boxes_sorted):
                self.left_boxes_sorted[row].text = item.data(Qt.UserRole)
                self.left_boxes_sorted[row].update()
        elif col == 1:
            if row < len(self.right_boxes_sorted):
                self.right_boxes_sorted[row].text = item.data(Qt.UserRole)
                self.right_boxes_sorted[row].update()
    
    def upload_left_image(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select English Image", "", "Image Files (*.png *.jpg *.bmp)")
        if file_name:
            self.left_image_path = file_name
            pixmap = QPixmap(file_name)
            self.left_scene.clear()
            self.left_scene.addPixmap(pixmap)
            self.left_scene.setSceneRect(QRectF(pixmap.rect()))
            self.left_view.setInitialFit()
    
    def upload_right_image(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Thai Image", "", "Image Files (*.png *.jpg *.bmp)")
        if file_name:
            self.right_image_path = file_name
            pixmap = QPixmap(file_name)
            self.right_scene.clear()
            self.right_scene.addPixmap(pixmap)
            self.right_scene.setSceneRect(QRectF(pixmap.rect()))
            self.right_view.setInitialFit()
    
    def start_ocr(self):
        if not self.left_image_path or not self.right_image_path:
            self.status_label.setText("Status: Please upload both images first.")
            return
        self.status_label.setText("Status: OCR in progress...")
        QApplication.processEvents()
        self.ocr_worker = OCRWorker(self.left_image_path, self.right_image_path)
        self.ocr_worker.finished.connect(self.on_ocr_finished)
        self.ocr_worker.start()
    
    def on_ocr_finished(self, result_eng, result_thai):
        if isinstance(result_eng, Exception):
            self.status_label.setText("Status: OCR Error: " + str(result_eng))
            return
        
        annotations_eng = result_eng.get("textAnnotations", [])
        annotations_thai = result_thai.get("textAnnotations", [])
        
        self.left_scene.clear()
        left_pixmap = QPixmap(self.left_image_path)
        self.left_scene.addPixmap(left_pixmap)
        self.left_scene.setSceneRect(QRectF(left_pixmap.rect()))
        for ann in annotations_eng:
            vertices = ann.get("boundingPoly", {}).get("vertices", [])
            if len(vertices) == 4:
                x = vertices[0].get("x", 0)
                y = vertices[0].get("y", 0)
                x2 = vertices[2].get("x", 0)
                y2 = vertices[2].get("y", 0)
                rect = QRectF(x, y, x2 - x, y2 - y)
                box = DraggableRectItem(rect, text=ann.get("description", ""))
                box.update_callback = self.refresh_table
                self.left_scene.addItem(box)
        
        self.right_scene.clear()
        right_pixmap = QPixmap(self.right_image_path)
        self.right_scene.addPixmap(right_pixmap)
        self.right_scene.setSceneRect(QRectF(right_pixmap.rect()))
        for ann in annotations_thai:
            vertices = ann.get("boundingPoly", {}).get("vertices", [])
            if len(vertices) == 4:
                x = vertices[0].get("x", 0)
                y = vertices[0].get("y", 0)
                x2 = vertices[2].get("x", 0)
                y2 = vertices[2].get("y", 0)
                rect = QRectF(x, y, x2 - x, y2 - y)
                box = DraggableRectItem(rect, text=ann.get("description", ""))
                box.update_callback = self.refresh_table
                self.right_scene.addItem(box)
        
        eng_groups = group_annotations_by_line(annotations_eng, threshold_y=10)
        thai_groups = group_annotations_by_line(annotations_thai, threshold_y=10)
        pairs = pair_groups(eng_groups, thai_groups)
        self.current_pairs = pairs
        self.update_group_table(pairs)
        self.status_label.setText(f"Status: OCR complete, {len(pairs)} groups found.")
    
    def refresh_table(self):
        left_boxes = [item for item in self.left_scene.items() if isinstance(item, DraggableRectItem)]
        right_boxes = [item for item in self.right_scene.items() if isinstance(item, DraggableRectItem)]
        self.left_boxes_sorted = sorted(left_boxes, key=lambda box: box.sceneBoundingRect().top())
        self.right_boxes_sorted = sorted(right_boxes, key=lambda box: box.sceneBoundingRect().top())
        pairs = []
        for i in range(min(len(self.left_boxes_sorted), len(self.right_boxes_sorted))):
            pairs.append((self.left_boxes_sorted[i].text, self.right_boxes_sorted[i].text))
        self.current_pairs = pairs
        self.group_table.blockSignals(True)
        self.update_group_table(pairs)
        self.group_table.blockSignals(False)
        self.status_label.setText("Status: Table refreshed from current boxes.")
    
    def update_group_table(self, pairs):
        self.group_table.setRowCount(0)
        fm = self.group_table.fontMetrics()
        margin = 10
        for idx, (full_eng_text, full_thai_text) in enumerate(pairs, 1):
            row = self.group_table.rowCount()
            self.group_table.insertRow(row)
            display_eng_text = full_eng_text.replace("\n", " ")
            display_thai_text = full_thai_text.replace("\n", " ")
            eng_item = QTableWidgetItem(display_eng_text)
            eng_item.setData(Qt.UserRole, full_eng_text)
            thai_item = QTableWidgetItem(display_thai_text)
            thai_item.setData(Qt.UserRole, full_thai_text)
            self.group_table.setItem(row, 0, eng_item)
            self.group_table.setItem(row, 1, thai_item)
            
            eng_lines = full_eng_text.splitlines() if full_eng_text else []
            thai_lines = full_thai_text.splitlines() if full_thai_text else []
            num_lines = max(len(eng_lines) if eng_lines else 1, len(thai_lines) if thai_lines else 1)
            desired_height = num_lines * fm.lineSpacing() + margin
            self.group_table.setRowHeight(row, desired_height)
    
    def export_csv(self):
        if not self.current_pairs:
            self.status_label.setText("Status: No OCR pairing data available.")
            return
        file_name, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)")
        if file_name:
            export_pairs_to_csv(self.current_pairs, file_name)
            self.status_label.setText("Status: CSV Exported to " + file_name)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OCRToolWindow()
    window.show()
    sys.exit(app.exec_())
