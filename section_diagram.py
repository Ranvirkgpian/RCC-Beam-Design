"""
section_diagram.py - High-Fidelity Rendering Logic for RCC Beam drawings
Fully responsive to Dark Mode. Includes CAD-style dimensions, legends, and SP:34 standard hooks.
"""

from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QBrush
from PyQt5.QtCore import Qt, QRectF, QPointF
import math

def is_dark_mode():
    return QApplication.instance().property("is_dark")

def draw_dimension(painter, x1, y1, x2, y2, text, offset=20, color=None):
    """Helper to draw CAD-style dimension lines with ticks and outward-facing text."""
    if color is None:
        color = QColor("#94A3B8") if is_dark_mode() else QColor("#64748B")
    
    pen = QPen(color, 1)
    painter.setPen(pen)
    painter.setFont(QFont("Arial", 8))
    
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0: return
    
    # Calculate Normal Vector (px, py)
    nx, ny = dx / length, dy / length
    px, py = -ny, nx 
    
    # Calculate offset line coordinates
    ox1, oy1 = x1 + px * offset, y1 + py * offset
    ox2, oy2 = x2 + px * offset, y2 + py * offset
    
    # Draw Extensions (with a 5px gap from the drawing to avoid touching the beam)
    gap = 5
    sign = 1 if offset >= 0 else -1
    painter.drawLine(QPointF(x1 + px*gap*sign, y1 + py*gap*sign), QPointF(ox1 + px*4*sign, oy1 + py*4*sign))
    painter.drawLine(QPointF(x2 + px*gap*sign, y2 + py*gap*sign), QPointF(ox2 + px*4*sign, oy2 + py*4*sign))
    
    # Dimension Line
    painter.drawLine(QPointF(ox1, oy1), QPointF(ox2, oy2))
    
    # Ticks (Architectural 45-degree angle)
    t = 4
    painter.drawLine(QPointF(ox1 - nx*t + px*t, oy1 - ny*t + py*t), QPointF(ox1 + nx*t - px*t, oy1 + ny*t - py*t))
    painter.drawLine(QPointF(ox2 - nx*t + px*t, oy2 - ny*t + py*t), QPointF(ox2 + nx*t - px*t, oy2 + ny*t - py*t))
    
    # Rotate and center text correctly so it never overlaps the line
    cx, cy = (ox1 + ox2) / 2, (oy1 + oy2) / 2
    painter.save()
    painter.translate(cx, cy)
    
    angle = math.degrees(math.atan2(dy, dx))
    flipped = False
    
    # Ensure text is upright
    if angle > 90 or angle <= -90:
        angle += 180
        flipped = True

    painter.rotate(angle)
        
    # Determine the outward facing side
    shift_dir = 1 if offset >= 0 else -1
    if flipped:
        shift_dir *= -1
        
    # Taller QRectF (height 25-30) ensures descenders/ascenders don't get cut off
    if shift_dir < 0:
        # Draw text above the dimension line
        painter.drawText(QRectF(-150, -30, 300, 25), Qt.AlignCenter | Qt.AlignBottom, text)
    else:
        # Draw text below the dimension line
        painter.drawText(QRectF(-150, 5, 300, 25), Qt.AlignCenter | Qt.AlignTop, text)
        
    painter.restore()


class CrossSectionWidget(QWidget):
    def __init__(self, b, D, clear_cover, stirrup_dia, tension_bar_dia, tension_num_bars, comp_bar_dia=None, comp_num_bars=None):
        super().__init__()
        self.setMinimumSize(450, 350)
        self.b = b; self.D = D; self.clear_cover = clear_cover
        self.stirrup_dia = stirrup_dia
        self.tension_bar_dia = tension_bar_dia; self.tension_num_bars = tension_num_bars
        self.comp_bar_dia = comp_bar_dia; self.comp_num_bars = comp_num_bars

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        dark = is_dark_mode()
        c_fill = QColor("#1E293B") if dark else QColor("#F1F5F9")
        c_line = QColor("#94A3B8") if dark else QColor("#334155")
        c_stirrup = QColor("#EF4444") if dark else QColor("#DC2626")
        c_comp = QColor("#F8FAFC") if dark else QColor("#000000")
        c_tens = QColor("#EF4444") if dark else QColor("#DC2626")
        c_text = QColor("#F8FAFC") if dark else QColor("#1E293B")
        
        w, h = self.width(), self.height()
        margin_x, margin_y = 90, 75
        
        scale = min((w - 180 - margin_x) / self.b, (h - 2 * margin_y) / self.D)
        bw, bh = self.b * scale, self.D * scale
        
        x0 = margin_x
        y0 = (h - bh) / 2
        
        # Concrete outline
        painter.setPen(QPen(c_line, 1.5))
        painter.setBrush(QBrush(c_fill))
        painter.drawRect(QRectF(x0, y0, bw, bh))
        
        # Stirrup
        c = self.clear_cover * scale
        painter.setPen(QPen(c_stirrup, 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(x0 + c, y0 + c, bw - 2 * c, bh - 2 * c), 4, 4)
        
        # Tension Bars (Bottom)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(c_tens))
        tb_r = max((self.tension_bar_dia / 2) * scale, 3)
        cy_bot = y0 + bh - c - (self.stirrup_dia * scale) - tb_r
        
        for i in range(self.tension_num_bars):
            cx = x0 + c + (self.stirrup_dia * scale) + tb_r + i * ((bw - 2*c - 2*(self.stirrup_dia*scale) - 2*tb_r) / max(1, self.tension_num_bars - 1)) if self.tension_num_bars > 1 else x0 + bw/2
            painter.drawEllipse(QPointF(cx, cy_bot), tb_r, tb_r)
                
        # Compression Bars (Top)
        if self.comp_num_bars:
            painter.setBrush(QBrush(c_comp))
            cb_r = max((self.comp_bar_dia / 2) * scale, 3)
            cy_top = y0 + c + (self.stirrup_dia * scale) + cb_r
            
            for i in range(self.comp_num_bars):
                cx = x0 + c + (self.stirrup_dia * scale) + cb_r + i * ((bw - 2*c - 2*(self.stirrup_dia*scale) - 2*cb_r) / max(1, self.comp_num_bars - 1)) if self.comp_num_bars > 1 else x0 + bw/2
                painter.drawEllipse(QPointF(cx, cy_top), cb_r, cb_r)

        # Dimensions (Cleaned up duplicates)
        draw_dimension(painter, x0, y0, x0 + bw, y0, f"{int(self.b)}", offset=-35) 
        draw_dimension(painter, x0, y0, x0, y0 + bh, f"{int(self.D)}", offset=35) 
        draw_dimension(painter, x0 + bw, y0 + c + (self.stirrup_dia * scale) + (cb_r if self.comp_num_bars else 0), x0 + bw, cy_bot, f"{int(self.D - self.clear_cover - self.stirrup_dia - self.tension_bar_dia/2)} (d)", offset=-35) 

        # Legend
        lx = x0 + bw + 110  # Pushed further right for a clean margin
        ly = y0 + 20
        painter.setFont(QFont("Arial", 8))
        painter.setPen(c_text)
        
        if self.comp_num_bars:
            painter.setBrush(c_comp)
            painter.drawEllipse(QPointF(lx, ly), 3, 3)
            painter.drawText(QRectF(lx + 15, ly - 20, 200, 40), Qt.AlignLeft | Qt.AlignVCenter, f"Top Bars (Compression)\n{self.comp_num_bars} - {int(self.comp_bar_dia)} φ")
            ly += 45
            
        painter.setBrush(c_tens)
        painter.drawEllipse(QPointF(lx, ly), 3, 3)
        painter.drawText(QRectF(lx + 15, ly - 20, 200, 40), Qt.AlignLeft | Qt.AlignVCenter, f"Bottom Bars (Tension)\n{self.tension_num_bars} - {int(self.tension_bar_dia)} φ")
        ly += 45
        
        painter.setPen(QPen(c_stirrup, 2))
        painter.drawLine(int(lx - 4), int(ly), int(lx + 4), int(ly))
        painter.setPen(c_text)
        painter.drawText(QRectF(lx + 15, ly - 20, 200, 40), Qt.AlignLeft | Qt.AlignVCenter, f"Stirrups\n{self.stirrup_dia} φ, 2-Legged")


class StirrupDetailWidget(QWidget):
    def __init__(self, b, D, clear_cover, stirrup_dia):
        super().__init__()
        self.setMinimumSize(250, 350)
        self.b = b; self.D = D; self.cc = clear_cover; self.dia = stirrup_dia

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        dark = is_dark_mode()
        c_stirrup = QColor("#EF4444") if dark else QColor("#DC2626")
        c_text = QColor("#F8FAFC") if dark else QColor("#1E293B")
        
        sw, sh = self.b - 2 * self.cc, self.D - 2 * self.cc
        w, h = self.width(), self.height()
        margin = 90
        scale = min((w - 2 * margin) / sw, (h - 2 * margin) / sh)
        
        bw, bh = sw * scale, sh * scale
        x0, y0 = (w - bw) / 2, (h - bh) / 2
        
        # Stirrup Outline
        painter.setPen(QPen(c_stirrup, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(x0, y0, bw, bh), 8, 8)
        
        # 135-degree Hooks
        painter.drawLine(QPointF(x0 + 8, y0), QPointF(x0 + 25, y0 + 17))
        painter.drawLine(QPointF(x0, y0 + 8), QPointF(x0 + 17, y0 + 25))
        
        # Dimensions
        draw_dimension(painter, x0, y0, x0 + bw, y0, f"{int(sw)}", offset=-35)
        draw_dimension(painter, x0 + bw, y0, x0 + bw, y0 + bh, f"{int(sh)}", offset=-35)
        
        painter.setPen(c_text)
        painter.setFont(QFont("Arial", 8))
        painter.drawText(QRectF(0, y0 + bh + 25, w, 40), Qt.AlignCenter, f"{self.dia} mm φ, 2-Legged Stirrup\n135° Hook")


class StirrupSpacingWidget(QWidget):
    def __init__(self, span, z1_ext, z1_sp, z2_sp):
        super().__init__()
        # Increased minimum height to 260 to prevent bottom text clipping
        self.setMinimumSize(600, 260)
        self.span = span; self.z1_ext = z1_ext; self.z1_sp = z1_sp; self.z2_sp = z2_sp

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        dark = is_dark_mode()
        c_line = QColor("#94A3B8") if dark else QColor("#334155")
        c_fill = QColor("#1E293B") if dark else QColor("#F1F5F9")
        c_stirrup = QColor("#EF4444") if dark else QColor("#DC2626")
        c_text = QColor("#F8FAFC") if dark else QColor("#1E293B")
        
        w, h = self.width(), self.height()
        margin_x, margin_y = 60, 90
        bw = w - 2 * margin_x
        bh = 40
        x0, y0 = margin_x, margin_y
        
        scale_x = bw / self.span
        
        # Beam outline
        painter.setPen(QPen(c_line, 1.5))
        painter.setBrush(QBrush(c_fill))
        painter.drawRect(int(x0), int(y0), int(bw), int(bh))
        
        # Supports
        painter.setBrush(QBrush(c_line))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPointF(x0, y0+bh), QPointF(x0-10, y0+bh+15), QPointF(x0+10, y0+bh+15))
        painter.drawPolygon(QPointF(x0+bw, y0+bh), QPointF(x0+bw-10, y0+bh+15), QPointF(x0+bw+10, y0+bh+15))
        
        # Stirrups
        painter.setPen(QPen(c_stirrup, 1.5))
        
        def draw_zone(start, end, spacing):
            curr = start + spacing/2
            while curr <= end:
                px = x0 + curr * scale_x
                painter.drawLine(QPointF(px, y0), QPointF(px, y0+bh))
                curr += spacing

        if self.z1_ext > 0:
            draw_zone(0, self.z1_ext, self.z1_sp)
            draw_zone(self.z1_ext, self.span - self.z1_ext, self.z2_sp)
            draw_zone(self.span - self.z1_ext, self.span, self.z1_sp)
            
            # Top Labels
            painter.setPen(c_text)
            painter.setFont(QFont("Arial", 8))
            painter.drawText(QRectF(x0, y0 - 60, self.z1_ext * scale_x, 40), Qt.AlignCenter | Qt.AlignBottom, f"Spacing = {int(self.z1_sp)} c/c\n(within 2d from support)")
            painter.drawText(QRectF(x0 + bw - self.z1_ext * scale_x, y0 - 60, self.z1_ext * scale_x, 40), Qt.AlignCenter | Qt.AlignBottom, f"Spacing = {int(self.z1_sp)} c/c\n(beyond 2d)")
            
            # Bottom Dimensions
            draw_dimension(painter, x0, y0+bh, x0 + self.z1_ext*scale_x, y0+bh, f"2d ({int(self.z1_ext)} mm)", offset=40)
            draw_dimension(painter, x0 + self.z1_ext*scale_x, y0+bh, x0 + bw - self.z1_ext*scale_x, y0+bh, "Remaining Length", offset=40)
            draw_dimension(painter, x0 + bw - self.z1_ext*scale_x, y0+bh, x0 + bw, y0+bh, f"2d ({int(self.z1_ext)} mm)", offset=40)
        else:
            draw_zone(0, self.span, self.z1_sp)
            painter.setPen(c_text)
            painter.setFont(QFont("Arial", 8))
            painter.drawText(QRectF(x0, y0 - 50, bw, 30), Qt.AlignCenter | Qt.AlignBottom, f"Uniform Spacing = {int(self.z1_sp)} c/c")

        draw_dimension(painter, x0, y0+bh, x0 + bw, y0+bh, f"L = {int(self.span)} mm", offset=70)


class LongitudinalBarsWidget(QWidget):
    def __init__(self, span, tension_bar_dia, tension_num_bars, comp_bar_dia=None, comp_num_bars=None):
        super().__init__()
        # Increased minimum height to 240 to safely clear the bottom dimensions
        self.setMinimumSize(600, 240)
        self.span = span
        self.t_dia = tension_bar_dia; self.t_num = tension_num_bars
        self.c_dia = comp_bar_dia; self.c_num = comp_num_bars

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        dark = is_dark_mode()
        c_line = QColor("#94A3B8") if dark else QColor("#334155")
        c_fill = QColor("#1E293B") if dark else QColor("#F1F5F9")
        c_tens = QColor("#EF4444") if dark else QColor("#DC2626")
        c_comp = QColor("#F8FAFC") if dark else QColor("#000000")
        
        w, h = self.width(), self.height()
        margin_x, margin_y = 60, 75
        bw = w - 2 * margin_x
        bh = 60
        x0, y0 = margin_x, margin_y
        
        # Beam outline
        painter.setPen(QPen(c_line, 1.5))
        painter.setBrush(QBrush(c_fill))
        painter.drawRect(int(x0), int(y0), int(bw), int(bh))
        
        # Supports
        painter.setBrush(QBrush(c_line))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPointF(x0, y0+bh), QPointF(x0-10, y0+bh+15), QPointF(x0+10, y0+bh+15))
        painter.drawPolygon(QPointF(x0+bw, y0+bh), QPointF(x0+bw-10, y0+bh+15), QPointF(x0+bw+10, y0+bh+15))
        
        # Standard Anchorage L-Bends
        bend = 15
        
        # Bottom Tension Bars
        painter.setPen(QPen(c_tens, 2.5))
        painter.drawLine(QPointF(x0 + 4, y0 + bh - 8 - bend), QPointF(x0 + 4, y0 + bh - 8))
        painter.drawLine(QPointF(x0 + 4, y0 + bh - 8), QPointF(x0 + bw - 4, y0 + bh - 8))
        painter.drawLine(QPointF(x0 + bw - 4, y0 + bh - 8), QPointF(x0 + bw - 4, y0 + bh - 8 - bend))
        
        # Callout Bottom
        painter.setFont(QFont("Arial", 8))
        painter.drawText(QRectF(x0, y0 + bh - 25, bw, 20), Qt.AlignCenter, f"{self.t_num} - {int(self.t_dia)} φ (Bottom)")
        
        # Top Compression Bars
        if self.c_num:
            painter.setPen(QPen(c_comp, 2))
            painter.drawLine(QPointF(x0 + 4, y0 + 8 + bend), QPointF(x0 + 4, y0 + 8))
            painter.drawLine(QPointF(x0 + 4, y0 + 8), QPointF(x0 + bw - 4, y0 + 8))
            painter.drawLine(QPointF(x0 + bw - 4, y0 + 8), QPointF(x0 + bw - 4, y0 + 8 + bend))
            
            painter.drawText(QRectF(x0 + 10, y0 - 30, 100, 25), Qt.AlignLeft | Qt.AlignBottom, f"{self.c_num} - {int(self.c_dia)} φ (Top)")
            painter.drawText(QRectF(x0 + bw - 110, y0 - 30, 100, 25), Qt.AlignRight | Qt.AlignBottom, f"{self.c_num} - {int(self.c_dia)} φ (Top)")

        # L dimension
        draw_dimension(painter, x0, y0+bh, x0+bw, y0+bh, f"L = {int(self.span)} mm", offset=40)