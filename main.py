"""
main.py - RCC Beam Designer (PyQt5)
Main window shell with layout matching the provided screenshots.
Uses rcc_beam_design.py as the verified calculation engine.
Includes PDF Export functionality via ReportLab.
"""

import sys
import json
import math
import os
import subprocess
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QStackedWidget, QFrame, QFormLayout, QLineEdit, QComboBox,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QAction, QMessageBox, QGridLayout, QSizePolicy, QStyleOption, QStyle,
    QCheckBox, QScrollArea, QGraphicsDropShadowEffect, QDialog, QTabWidget,
    QGraphicsView, QGraphicsScene, QMenu, QListView
)
from PyQt5.QtCore import Qt, pyqtSignal, QPointF, QRectF, QSettings, QSize, QPoint
from PyQt5.QtGui import QFont, QPainter, QPen, QColor, QPolygonF, QBrush, QPainterPath, QPixmap

import rcc_beam_design as engine
from section_diagram import CrossSectionWidget, StirrupDetailWidget, StirrupSpacingWidget, LongitudinalBarsWidget
from pdf_report import generate_pdf_report
from excel_export import export_to_excel
from dxf_export import export_to_dxf

class DoublyReinforcedError(Exception): pass

class DesignSession:
    def __init__(self):
        self.b = 300.0
        self.D = 500.0
        self.effective_cover = 40.0
        self.span = 5.0
        self.concrete_grade = "M25"
        self.steel_grade = "Fe500"
        self.mu = 180.0
        self.vu = 120.0
        self.beam_type = "Simply Supported"
        self.custom_basic_ratio = 20.0

        self.manual_bar_override = False
        self.manual_bar_dia = 20.0
        self.manual_num_bars = 4
        self.manual_comp_bar_dia = 16.0
        self.manual_comp_num_bars = 2

        self.flexural = None
        self.shear = None
        self.serviceability = None
        self.detailing = None
        self.bar_selection = None
        self.comp_bar_selection = None
        self.doubly = None
        self.two_zone_shear = None

    INPUT_FIELDS = [
        "b", "D", "effective_cover", "span", "concrete_grade",
        "steel_grade", "mu", "vu", "beam_type", "custom_basic_ratio",
        "manual_bar_override", "manual_bar_dia", "manual_num_bars",
        "manual_comp_bar_dia", "manual_comp_num_bars",
    ]

    def to_dict(self):
        return {field: getattr(self, field) for field in self.INPUT_FIELDS}

    def load_from_dict(self, data):
        for field in self.INPUT_FIELDS:
            if field in data:
                setattr(self, field, data[field])
        self.reset_results()

    def reset_results(self):
        self.flexural = None
        self.shear = None
        self.serviceability = None
        self.detailing = None
        self.bar_selection = None
        self.comp_bar_selection = None
        self.doubly = None
        self.two_zone_shear = None

    def run_flexural(self):
        self.flexural = engine.get_flexural_design(
            b=self.b, D=self.D, effective_cover=self.effective_cover,
            mu=self.mu, concrete_grade=self.concrete_grade, steel_grade=self.steel_grade,
        )
        if not self.flexural.is_singly:
            self.doubly = engine.get_doubly_reinforced_design(
                b=self.b, d=self.flexural.d, mu=self.mu, m_lim=self.flexural.m_lim,
                xu_max=self.flexural.xu_max, fck=self.flexural.fck, fy=self.flexural.fy,
                d_dash=self.effective_cover
            )
        else:
            self.doubly = None
        return self.flexural

    def get_ast_for_design(self):
        if self.flexural is None: self.run_flexural()
        if self.flexural.is_singly: return self.flexural.ast_final
        return self.doubly.ast_final

    def get_ast_required_calc(self):
        if self.flexural is None: self.run_flexural()
        return self.flexural.ast if self.flexural.is_singly else self.doubly.ast_total

    def resolve_bars(self):
        """Single source of truth for the bars: manual override or auto-selected."""
        if self.flexural is None: self.run_flexural()
        # Ast,lim: steel at xu = xu,max. A singly reinforced section must not be given more than this.
        ast_lim = (0.36 * self.flexural.fck * self.b * self.flexural.xu_max / (0.87 * self.flexural.fy)) if self.flexural.is_singly else None
        if self.manual_bar_override:
            n, dia = self.manual_num_bars, self.manual_bar_dia
            tension = engine.BarSelection(bar_dia=dia, num_bars=n,
                ast_provided=round(n * (math.pi / 4) * dia ** 2, 1), actual_clear_spacing=None, fits=True)
        else:
            tension = engine.select_bars(ast_required=self.get_ast_for_design(), b=self.b, effective_cover=self.effective_cover, max_ast=ast_lim)
        comp = None
        if not self.flexural.is_singly and self.doubly is not None:
            if self.manual_bar_override:
                n, dia = self.manual_comp_num_bars, self.manual_comp_bar_dia
                comp = engine.BarSelection(bar_dia=dia, num_bars=n,
                    ast_provided=round(n * (math.pi / 4) * dia ** 2, 1), actual_clear_spacing=None, fits=True)
            else:
                comp = engine.select_bars(ast_required=self.doubly.asc, b=self.b, effective_cover=self.effective_cover, min_bars=2, max_bars=4)
        self.bar_selection, self.comp_bar_selection = tension, comp
        return tension, comp

    def get_ast_provided(self):
        return self.resolve_bars()[0].ast_provided

    def run_shear(self):
        if self.flexural is None: self.run_flexural()
        self.shear = engine.get_shear_design(
            b=self.b, d=self.flexural.d, vu=self.vu, ast=self.get_ast_provided(),
            concrete_grade=self.concrete_grade,
        )
        return self.shear

    def run_serviceability(self):
        if self.shear is None: self.run_shear()
        d = self.flexural.d
        ast_prov = self.get_ast_provided()
        self.serviceability = engine.get_serviceability_check(
            L=self.span, d=d, pt=100 * ast_prov / (self.b * d), support_type=self.beam_type,
            custom_basic_ratio=self.custom_basic_ratio if self.beam_type == "Custom" else None,
            ast_required=self.get_ast_required_calc(), ast_provided=ast_prov, fy=self.flexural.fy,
        )
        return self.serviceability

    def run_two_zone_shear(self):
        if self.shear is None: self.run_shear()
        self.two_zone_shear = engine.get_two_zone_shear_design(
            b=self.b, d=self.flexural.d, L=self.span, vu_max=self.vu,
            ast=self.get_ast_provided(), concrete_grade=self.concrete_grade,
        )
        return self.two_zone_shear

def is_dark_mode():
    return QApplication.instance().property("is_dark")

def get_status_style(is_safe):
    dark = is_dark_mode()
    if is_safe:
        bg = "#064E3B" if dark else "#ECFDF5"
        text = "#34D399" if dark else "#059669"
        border = "#047857" if dark else "#A7F3D0"
    else:
        bg = "#7F1D1D" if dark else "#FEF2F2"
        text = "#FCA5A5" if dark else "#B91C1C"
        border = "#991B1B" if dark else "#FECACA"
    return f"background:{bg}; color:{text}; border: 1px solid {border}; padding:12px; border-radius:6px; font-weight:600; margin-top:10px;"

def get_note_style():
    dark = is_dark_mode()
    bg = "#172554" if dark else "#EFF6FF"
    text = "#93C5FD" if dark else "#1E3A8A"
    return f"background:{bg}; color:{text}; padding:12px; border-radius:6px; margin-top:10px; font-size:12px;"

def get_warning_note_style():
    dark = is_dark_mode()
    bg = "#451A03" if dark else "#FFFBEB"
    text = "#FDE68A" if dark else "#92400E"
    border = "#78350F" if dark else "#FEF3C7"
    return f"background:{bg}; color:{text}; border: 1px solid {border}; padding:12px; border-radius:6px; margin-top:4px; font-size:12px;"

def add_page_header(layout, title_text, subtitle_text=None, export_callback=None):
    header_layout = QHBoxLayout()
    text_layout = QVBoxLayout()
    text_layout.setSpacing(4)
    heading = QLabel(title_text)
    heading.setObjectName("PageHeading")
    text_layout.addWidget(heading)
    
    if subtitle_text:
        sub = QLabel(subtitle_text)
        sub.setObjectName("PageSubHeading")
        text_layout.addWidget(sub)
        
    header_layout.addLayout(text_layout)
    header_layout.addStretch()
    
    if export_callback:
        export_btn = QPushButton("📄 EXPORT PDF REPORT")
        export_btn.setFixedHeight(36)
        export_btn.setCursor(Qt.PointingHandCursor)
        # FIX: Added matching solid borders to ensure the background is drawn
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: #16A34A; color: white;
                font-weight: bold; border-radius: 6px; padding: 0 16px;
                border: 1px solid #16A34A;
            }
            QPushButton:hover { 
                background-color: #15803D; 
                border: 1px solid #15803D; 
            }
        """)
        export_btn.clicked.connect(export_callback)
        header_layout.addWidget(export_btn)
    else:
        badge = QLabel("📖 IS 456:2000 (LSD)")
        badge.setObjectName("CodeBadge")
        header_layout.addWidget(badge, alignment=Qt.AlignTop)
        
    layout.addLayout(header_layout)

def create_bottom_banner(on_back, on_next, back_label="← Back", next_label="Next →", info_text=""):
    bottom_bar = QFrame()
    bottom_bar.setAttribute(Qt.WA_StyledBackground, True)
    bottom_bar.setObjectName("BottomBanner")
    bottom_bar.setFixedHeight(60)
    
    bottom_layout = QHBoxLayout(bottom_bar)
    bottom_layout.setContentsMargins(20, 0, 20, 0)
    bottom_layout.setSpacing(12)
    
    if info_text:
        info_icon = QLabel("ℹ")
        info_icon.setStyleSheet("color: #3B82F6; font-weight: bold; font-size: 14px; background: transparent;")
        bottom_layout.addWidget(info_icon)
        
        info_banner = QLabel(info_text)
        info_banner.setObjectName("BottomBannerText")
        bottom_layout.addWidget(info_banner)
    
    bottom_layout.addStretch()
    
    if on_back:
        btn_cancel = QPushButton(back_label)
        btn_cancel.setObjectName("BannerBtnCancel")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(on_back)
        bottom_layout.addWidget(btn_cancel)
    
    if on_next:
        btn_next = QPushButton(next_label)
        btn_next.setObjectName("BannerBtnNext")
        btn_next.setFixedHeight(36)
        btn_next.setCursor(Qt.PointingHandCursor)
        btn_next.clicked.connect(on_next)
        bottom_layout.addWidget(btn_next)
        
    return bottom_bar

def setup_table_ui(table, row_count, show_header=False):
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setFocusPolicy(Qt.NoFocus)
    table.setSelectionMode(QTableWidget.NoSelection)
    table.setShowGrid(False)
    table.verticalHeader().setDefaultSectionSize(40) 
    h = 2 
    if show_header:
        table.horizontalHeader().setFixedHeight(36)
        h += 36
    h += row_count * 40
    table.setFixedHeight(h)

def clear_layout(layout):
    if layout is not None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            else:
                sublayout = item.layout()
                if sublayout is not None:
                    clear_layout(sublayout)
                    sublayout.deleteLater()

class FeaturePill(QFrame):
    def __init__(self, icon_char, title, subtitle, color="#2563EB"):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("FeaturePill")
        self.setFixedHeight(52)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 16, 6)
        layout.setSpacing(10)
        
        icon_wrapper = QWidget()
        icon_wrapper.setAttribute(Qt.WA_StyledBackground, True)
        icon_wrapper.setFixedSize(36, 36)
        icon_wrapper.setObjectName("PillIconWrapper")
        icon_wrapper.setStyleSheet(f"background-color: {color}; border-radius: 18px; border: none;")
        icon_layout = QVBoxLayout(icon_wrapper)
        icon_layout.setContentsMargins(0,0,0,0)
        
        icon_lbl = QLabel(icon_char)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setObjectName("PillIcon")
        icon_lbl.setStyleSheet("color: white; font-size: 15px; background: transparent;")
        icon_layout.addWidget(icon_lbl)
        layout.addWidget(icon_wrapper)
        
        text_v = QVBoxLayout()
        text_v.setSpacing(1)
        text_v.setAlignment(Qt.AlignVCenter)
        t_lbl = QLabel(title)
        t_lbl.setObjectName("PillTitle")
        s_lbl = QLabel(subtitle)
        s_lbl.setObjectName("PillSub")
        text_v.addWidget(t_lbl)
        text_v.addWidget(s_lbl)
        layout.addLayout(text_v)

class ActionCard(QFrame):
    clicked = pyqtSignal()
    
    THEME_COLORS = {
        "blue":   {"bg": "#DBEAFE", "border": "#93C5FD", "icon": "#2563EB",
                   "dark_bg": "#1E3A8A", "dark_border": "#1E40AF", "dark_icon": "#3B82F6"},
        "green":  {"bg": "#FEF3C7", "border": "#FCD34D", "icon": "#D97706",
                   "dark_bg": "#451A03", "dark_border": "#78350F", "dark_icon": "#F59E0B"},
        "purple": {"bg": "#FCE7F3", "border": "#F9A8D4", "icon": "#EC4899",
                   "dark_bg": "#831843", "dark_border": "#9D174D", "dark_icon": "#F472B6"},
    }
    
    def __init__(self, title, desc, icon_char, theme):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName(f"ActionCard_{theme}")
        self.setFixedHeight(90)
        
        dark = QApplication.instance().property("is_dark")
        c = self.THEME_COLORS.get(theme, self.THEME_COLORS["blue"])
        bg = c["dark_bg"] if dark else c["bg"]
        bdr = c["dark_border"] if dark else c["border"]
        icon_bg = c["dark_icon"] if dark else c["icon"]
        title_color = "#60A5FA" if dark else "#2563EB"
        desc_color = "#94A3B8" if dark else "#64748B"
        
        self.setStyleSheet(
            f"ActionCard_{theme} {{ background-color: {bg}; border-radius: 24px; border: 1px solid {bdr}; }}"
        )
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 16, 16)
        layout.setSpacing(16)
        
        icon_wrapper = QWidget()
        icon_wrapper.setAttribute(Qt.WA_StyledBackground, True)
        icon_wrapper.setFixedSize(48, 48)
        icon_wrapper.setStyleSheet(f"background-color: {icon_bg}; border-radius: 24px; border: none;")
        icon_layout = QVBoxLayout(icon_wrapper)
        icon_layout.setContentsMargins(0,0,0,0)
        
        icon_lbl = QLabel(icon_char)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("color: white; font-size: 20px; font-weight: bold; background: transparent; border: none;")
        icon_layout.addWidget(icon_lbl)
        layout.addWidget(icon_wrapper)
        
        text_v = QVBoxLayout()
        text_v.setSpacing(2)
        text_v.setAlignment(Qt.AlignVCenter)
        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(f"font-size: 14px; font-weight: 900; color: {title_color}; background: transparent; border: none;")
        d_lbl = QLabel(desc)
        d_lbl.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {desc_color}; background: transparent; border: none;")
        d_lbl.setWordWrap(True)
        text_v.addWidget(t_lbl)
        text_v.addWidget(d_lbl)
        layout.addLayout(text_v, stretch=1)
        
        arrow_wrapper = QWidget()
        arrow_wrapper.setAttribute(Qt.WA_StyledBackground, True)
        arrow_wrapper.setFixedSize(32, 32)
        arrow_wrapper.setStyleSheet(f"background-color: {icon_bg}; border-radius: 16px; border: none;")
        arrow_layout = QVBoxLayout(arrow_wrapper)
        arrow_layout.setContentsMargins(0,0,0,0)
        arrow_lbl = QLabel("→")
        arrow_lbl.setAlignment(Qt.AlignCenter)
        arrow_lbl.setStyleSheet("color: white; font-size: 16px; font-weight: bold; background: transparent; border: none;")
        arrow_layout.addWidget(arrow_lbl)
        layout.addWidget(arrow_wrapper, alignment=Qt.AlignVCenter)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

class RecentRow(QFrame):
    clicked = pyqtSignal(str)
    remove_clicked = pyqtSignal(str)
    def __init__(self, filepath):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.filepath = filepath
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("RecentRow")
        self.setFixedHeight(56)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(16)
        
        icon_lbl = QLabel("📄")
        icon_lbl.setObjectName("RecentIcon")
        layout.addWidget(icon_lbl)
        
        v_layout = QVBoxLayout()
        v_layout.setSpacing(2)
        filename = os.path.basename(filepath).replace(".rccbeam", "")
        title_lbl = QLabel(filename)
        title_lbl.setObjectName("RecentTitle")
        path_lbl = QLabel(filepath)
        path_lbl.setObjectName("RecentPath")
        v_layout.addWidget(title_lbl)
        v_layout.addWidget(path_lbl)
        layout.addLayout(v_layout, stretch=2)
        
        dir_path = os.path.dirname(filepath)
        loc_lbl = QLabel(dir_path)
        loc_lbl.setObjectName("RecentText")
        layout.addWidget(loc_lbl, stretch=2)
        
        try:
            mtime = os.path.getmtime(filepath)
            date_str = datetime.fromtimestamp(mtime).strftime("%b %d, %Y  %I:%M %p")
        except:
            date_str = "Unknown Date"
            
        date_lbl = QLabel(date_str)
        date_lbl.setObjectName("RecentText")
        layout.addWidget(date_lbl, stretch=2)
        
        code_lbl = QLabel("IS 456:2000 (LSD)")
        code_lbl.setObjectName("RecentCode")
        layout.addWidget(code_lbl, stretch=1)
        
        self.menu_btn = QPushButton("⋮")
        self.menu_btn.setObjectName("RecentMenuBtn")
        self.menu_btn.setFixedSize(30, 30)
        self.menu_btn.setCursor(Qt.PointingHandCursor)
        self.menu = QMenu(self.menu_btn)
        remove_action = QAction("Remove from list", self)
        remove_action.triggered.connect(lambda: self.remove_clicked.emit(self.filepath))
        self.menu.addAction(remove_action)
        self.menu_btn.clicked.connect(self._show_menu)
        layout.addWidget(self.menu_btn, alignment=Qt.AlignCenter)
        
    def _show_menu(self):
        self.menu.exec_(self.menu_btn.mapToGlobal(QPoint(self.menu_btn.width() - 120, self.menu_btn.height())))
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.filepath)

class HomePage(QWidget):
    def __init__(self, on_new, on_open, on_recent):
        super().__init__()
        self.on_new = on_new
        self.on_open = on_open
        self.on_recent = on_recent
        
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("HomePageWidget")
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setObjectName("HomeScrollArea") 
        self.scroll.viewport().setObjectName("HomeViewport") # Used for precise CSS targeting
        
        self.content = QWidget()
        self.content.setObjectName("HomeContent")
        
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(40, 30, 40, 40)
        self.layout.setSpacing(32)
        
        
        # --- WELCOME SECTION ---
        header_v = QVBoxLayout()
        header_v.setSpacing(0)
        header_v.setAlignment(Qt.AlignTop)
        lbl_welcome = QLabel("<b>Welcome to</b>")
        lbl_welcome.setObjectName("HomeWelcome")
        header_v.addWidget(lbl_welcome)
        
        lbl_title = QLabel("<b>RCC Beam Designer</b>")
        lbl_title.setObjectName("HomeMainTitle")
        header_v.addWidget(lbl_title)
        header_v.addSpacing(16)
        
        lbl_desc1 = QLabel("<b>Design and analyze RCC beams as per IS 456:2000.</b>")
        lbl_desc1.setObjectName("HomeDescBold")
        header_v.addWidget(lbl_desc1)
        header_v.addSpacing(6)
        
        lbl_desc2 = QLabel("<b>A user-friendly tool for flexural design, shear design, serviceability<br>check and detailing of reinforced concrete beams.</b>")
        lbl_desc2.setObjectName("HomeDescNorm")
        header_v.addWidget(lbl_desc2)
        header_v.addSpacing(24)
        
        pills_h = QHBoxLayout()
        pills_h.setSpacing(12)
        pills_h.addWidget(FeaturePill("🛡️", "<b>IS 456:2000</b>", "<b>Limit State Design</b>", "#2563EB"))
        pills_h.addWidget(FeaturePill("🧮", "<b>Accurate</b>", "<b>Design Calculations</b>", "#EC4899"))
        pills_h.addWidget(FeaturePill("📄", "<b>Detailed Reports</b>", "<b>PDF / Excel Export</b>", "#10B981"))
        pills_h.addWidget(FeaturePill("⚙️", "<b>Professional</b>", "<b>Engineering Drawings</b>", "#06B6D4"))
        pills_h.addStretch()
        header_v.addLayout(pills_h)
        header_v.addStretch()
        
        self.layout.addLayout(header_v)
        
        # --- QUICK ACTIONS SECTION ---
        actions_v = QVBoxLayout()
        actions_v.setSpacing(12)
        
        qa_header = QHBoxLayout()
        qa_header.setSpacing(8)
        qa_icon_w = QWidget()
        qa_icon_w.setAttribute(Qt.WA_StyledBackground, True)
        qa_icon_w.setFixedSize(28, 28)
        qa_icon_w.setObjectName("SectionIconYellow")
        qa_icon_lay = QVBoxLayout(qa_icon_w)
        qa_icon_lay.setContentsMargins(0,0,0,0)
        qa_icon_lbl = QLabel("⚡")
        qa_icon_lbl.setAlignment(Qt.AlignCenter)
        qa_icon_lbl.setStyleSheet("font-size: 14px; background: transparent;")
        qa_icon_lay.addWidget(qa_icon_lbl)
        qa_header.addWidget(qa_icon_w)
        lbl_actions = QLabel("<b>Quick Actions</b>")
        lbl_actions.setObjectName("SectionTitle")
        qa_header.addWidget(lbl_actions)
        qa_header.addStretch()
        actions_v.addLayout(qa_header)
        
        cards_h = QHBoxLayout()
        cards_h.setSpacing(20)
        
        card_new = ActionCard("<b>New Project</b>", "Create a new RCC beam design\nproject from scratch.", "+", "blue")
        card_new.clicked.connect(self.on_new)
        
        card_open = ActionCard("<b>Open Project</b>", "Open an existing project from\nyour computer.", "📁", "green")
        card_open.clicked.connect(self.on_open)
        
        card_recent = ActionCard("<b>Recent Projects</b>", "View and open your recently\nused projects.", "🕒", "purple")
        card_recent.clicked.connect(lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))
        
        cards_h.addWidget(card_new)
        cards_h.addWidget(card_open)
        cards_h.addWidget(card_recent)
        actions_v.addLayout(cards_h)
        self.layout.addLayout(actions_v)
        
        # --- RECENT PROJECTS TABLE ---
        recent_v = QVBoxLayout()
        recent_v.setSpacing(12)
        recent_header_h = QHBoxLayout()
        recent_header_h.setSpacing(8)
        
        rp_icon_w = QWidget()
        rp_icon_w.setAttribute(Qt.WA_StyledBackground, True)
        rp_icon_w.setFixedSize(28, 28)
        rp_icon_w.setObjectName("SectionIconPurple")
        rp_icon_lay = QVBoxLayout(rp_icon_w)
        rp_icon_lay.setContentsMargins(0,0,0,0)
        rp_icon_lbl = QLabel("🕐")
        rp_icon_lbl.setAlignment(Qt.AlignCenter)
        rp_icon_lbl.setStyleSheet("font-size: 14px; background: transparent;")
        rp_icon_lay.addWidget(rp_icon_lbl)
        recent_header_h.addWidget(rp_icon_w)
        
        lbl_recent = QLabel("<b>Recent Projects</b>")
        lbl_recent.setObjectName("SectionTitle")
        lbl_viewall = QLabel("<b>View All →</b>")
        lbl_viewall.setObjectName("ViewAllLink")
        lbl_viewall.setCursor(Qt.PointingHandCursor)
        recent_header_h.addWidget(lbl_recent)
        recent_header_h.addStretch()
        recent_header_h.addWidget(lbl_viewall)
        recent_v.addLayout(recent_header_h)
        
        self.recent_container = QFrame()
        self.recent_container.setAttribute(Qt.WA_StyledBackground, True)
        self.recent_container.setObjectName("RecentContainer")
        self.recent_layout = QVBoxLayout(self.recent_container)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(0)
        
        thead = QFrame()
        thead.setAttribute(Qt.WA_StyledBackground, True)
        thead.setFixedHeight(36)
        thead.setObjectName("RecentHeaderRow")
        thead_layout = QHBoxLayout(thead)
        thead_layout.setContentsMargins(20, 0, 20, 0)
        thead_layout.setSpacing(16)
        
        def add_th(text, stretch):
            l = QLabel(f"<b>{text}</b>")
            l.setObjectName("RecentTH")
            thead_layout.addWidget(l, stretch=stretch)
            
        empty_lbl = QLabel("")
        empty_lbl.setFixedWidth(24) 
        thead_layout.addWidget(empty_lbl)
        
        add_th("Project Name", 2)
        add_th("Location", 2)
        add_th("Last Modified", 2)
        add_th("Design Code", 1)
        act_th = QLabel("<b>Actions</b>")
        act_th.setObjectName("RecentTH")
        act_th.setFixedWidth(40)
        act_th.setAlignment(Qt.AlignCenter)
        thead_layout.addWidget(act_th)
        self.recent_layout.addWidget(thead)
        
        line_top = QFrame()
        line_top.setFrameShape(QFrame.HLine)
        line_top.setObjectName("RecentLine")
        line_top.setFixedHeight(1)
        self.recent_layout.addWidget(line_top)
        
        self.recent_list_layout = QVBoxLayout()
        self.recent_list_layout.setContentsMargins(0,0,0,0)
        self.recent_list_layout.setSpacing(0)
        self.recent_layout.addLayout(self.recent_list_layout)
        
        recent_v.addWidget(self.recent_container)
        self.layout.addLayout(recent_v)
        self.layout.addStretch()
        
        self.scroll.setWidget(self.content)
        self.main_layout.addWidget(self.scroll)
        self.refresh_recent()

    def paintEvent(self, event):
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, painter, self)
        
        painter.setRenderHint(QPainter.Antialiasing)
        
        pixmap = QPixmap("assets/home_bg.jpg")
        if pixmap.isNull():
            pixmap = QPixmap("assets/home_bg.png")
            
        if not pixmap.isNull():
            scaled = pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            
            dark = QApplication.instance().property("is_dark")
            wash_color = QColor(15, 23, 42, 225) if dark else QColor(248, 250, 255, 120)
            painter.fillRect(self.rect(), wash_color)
        else:
            dark = QApplication.instance().property("is_dark")
            bg_col = QColor("#0F172A") if dark else QColor("#F8FAFF")
            painter.fillRect(self.rect(), bg_col)

    def refresh_recent(self):
        clear_layout(self.recent_list_layout)
        settings = QSettings("RCCBeamDesigner", "App")
        recent_files = settings.value("recent_files", [])
        valid_files = [f for f in recent_files if os.path.exists(f)]
        if len(valid_files) != len(recent_files):
            settings.setValue("recent_files", valid_files)
        if not valid_files:
            empty = QLabel("<b>No recent projects found.</b>")
            empty.setObjectName("RecentText")
            empty.setAlignment(Qt.AlignCenter)
            empty.setFixedHeight(80)
            self.recent_list_layout.addWidget(empty)
        else:
            for i, f in enumerate(valid_files[:5]):
                row = RecentRow(f)
                row.clicked.connect(self.on_recent)
                row.remove_clicked.connect(self._remove_recent_item)
                self.recent_list_layout.addWidget(row)
                if i < len(valid_files[:5]) - 1:
                    line = QFrame()
                    line.setFrameShape(QFrame.HLine)
                    line.setObjectName("RecentLine")
                    line.setFixedHeight(1)
                    self.recent_list_layout.addWidget(line)

    def _remove_recent_item(self, filepath):
        settings = QSettings("RCCBeamDesigner", "App")
        recent_files = settings.value("recent_files", [])
        if filepath in recent_files:
            recent_files.remove(filepath)
            settings.setValue("recent_files", recent_files)
            self.refresh_recent()

    def paintEvent(self, event):
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, painter, self)
        
        painter.setRenderHint(QPainter.Antialiasing)
        
        pixmap = QPixmap("assets/home_bg.jpg")
        if pixmap.isNull():
            pixmap = QPixmap("assets/home_bg.png")
            
        if not pixmap.isNull():
            scaled = pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            
            dark = QApplication.instance().property("is_dark")
            wash_color = QColor(15, 23, 42, 225) if dark else QColor(248, 250, 255, 120)
            painter.fillRect(self.rect(), wash_color)
        else:
            dark = QApplication.instance().property("is_dark")
            bg_col = QColor("#0F172A") if dark else QColor("#F8FAFF")
            painter.fillRect(self.rect(), bg_col)

    def refresh_recent(self):
        clear_layout(self.recent_list_layout)
        settings = QSettings("RCCBeamDesigner", "App")
        recent_files = settings.value("recent_files", [])
        valid_files = [f for f in recent_files if os.path.exists(f)]
        if len(valid_files) != len(recent_files):
            settings.setValue("recent_files", valid_files)
        if not valid_files:
            empty = QLabel("<b>No recent projects found.</b>")
            empty.setObjectName("RecentText")
            empty.setAlignment(Qt.AlignCenter)
            empty.setFixedHeight(80)
            self.recent_list_layout.addWidget(empty)
        else:
            for i, f in enumerate(valid_files[:5]):
                row = RecentRow(f)
                row.clicked.connect(self.on_recent)
                row.remove_clicked.connect(self._remove_recent_item)
                self.recent_list_layout.addWidget(row)
                if i < len(valid_files[:5]) - 1:
                    line = QFrame()
                    line.setFrameShape(QFrame.HLine)
                    line.setObjectName("RecentLine")
                    line.setFixedHeight(1)
                    self.recent_list_layout.addWidget(line)

    def _remove_recent_item(self, filepath):
        settings = QSettings("RCCBeamDesigner", "App")
        recent_files = settings.value("recent_files", [])
        if filepath in recent_files:
            recent_files.remove(filepath)
            settings.setValue("recent_files", recent_files)
            self.refresh_recent()

# ==========================================
# WIZARD PAGE BASE (Applies BG + Banner to all)
# ==========================================
class WizardPage(QWidget):
    def __init__(self):
        super().__init__()
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("background: transparent;")
        
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background: transparent;")
        self.layout = QVBoxLayout(self.content_widget)
        self.layout.setContentsMargins(40, 30, 40, 30)
        self.layout.setSpacing(16)
        
        self.scroll_area.setWidget(self.content_widget)
        self.main_layout.addWidget(self.scroll_area)
        
        self.banner_layout = QVBoxLayout()
        self.banner_layout.setContentsMargins(40, 0, 40, 30)
        self.main_layout.addLayout(self.banner_layout)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        pixmap = QPixmap("assets/selection_bg12.jpeg") 
        if not pixmap.isNull():
            # Scale to completely cover the widget width and height
            scaled = pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            # Center the expanded image
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            
        dark = QApplication.instance().property("is_dark")
        # Reduced opacity (from 235 down to 140 in light mode) to increase brightness
        wash_color = QColor(15, 23, 42, 200) if dark else QColor(255, 255, 255, 140)
        painter.fillRect(self.rect(), wash_color)
# ==========================================
# MODERN BEAM INPUT PAGE 
# ==========================================
class BeamInputPage(WizardPage):
    def __init__(self, session: DesignSession, on_back, on_next):
        super().__init__()
        self.session = session
        self.on_back = on_back
        self.on_next = on_next
        self.layout.setSpacing(24)
        self._build_ui()

    def _build_ui(self):
        add_page_header(self.layout, "1. BEAM INPUT", "Enter the basic details of the beam for design as per IS 456:2000.")
        self.layout.addSpacing(10)

        def create_input_row(icon_text, label_text, input_widget, unit_text, desc_text):
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            
            icon = QLabel(icon_text)
            icon.setObjectName("InputIconText")
            icon.setFixedSize(24, 24)
            icon.setAlignment(Qt.AlignCenter)
            row.addWidget(icon)
            
            label = QLabel(label_text)
            label.setObjectName("InputLabel")
            label.setFixedWidth(130)
            row.addWidget(label)
            
            input_widget.setFixedWidth(120)
            row.addWidget(input_widget)
            
            if unit_text:
                unit = QLabel(unit_text)
                unit.setObjectName("InputUnit")
                unit.setFixedWidth(35)
                row.addWidget(unit)
                
            desc = QLabel(desc_text)
            desc.setObjectName("FieldDescPill")
            desc.setWordWrap(True)
            row.addWidget(desc, stretch=1)
            
            return container

        def create_section_frame(icon_str, title_str, subtitle_str):
            frame = QFrame()
            frame.setAttribute(Qt.WA_StyledBackground, True)
            frame.setObjectName("ModernInputCard")
            l = QVBoxLayout(frame)
            l.setContentsMargins(24, 20, 24, 24)
            l.setSpacing(20)
            
            header = QHBoxLayout()
            header.setSpacing(16)
            
            icon_lbl = QLabel(icon_str)
            icon_lbl.setObjectName("SectionHeaderIcon")
            icon_lbl.setFixedSize(36, 36)
            icon_lbl.setAlignment(Qt.AlignCenter)
            header.addWidget(icon_lbl)
            
            text_v = QVBoxLayout()
            text_v.setSpacing(2)
            title = QLabel(title_str)
            title.setObjectName("SectionHeaderTitle")
            sub = QLabel(subtitle_str)
            sub.setObjectName("SectionHeaderSub")
            text_v.addWidget(title)
            text_v.addWidget(sub)
            
            header.addLayout(text_v)
            header.addStretch()
            l.addLayout(header)
            
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setObjectName("CardLine")
            l.addWidget(line)
            return frame, l

        # --- GEOMETRY SECTION ---
        geo_card, geo_layout = create_section_frame("🧊", "GEOMETRY", "Define the basic dimensions of the beam")
        self.b_input = QLineEdit(str(self.session.b))
        self.D_input = QLineEdit(str(self.session.D))
        self.cover_input = QLineEdit(str(self.session.effective_cover))
        self.span_input = QLineEdit(str(self.session.span))
        
        geo_content = QVBoxLayout()
        geo_content.setSpacing(12)
        geo_content.addWidget(create_input_row("⟷", "Beam width (b)", self.b_input, "mm", "Width of the rectangular section\nof the beam."))
        geo_content.addWidget(create_input_row("↕", "Overall depth (D)", self.D_input, "mm", "Total depth of the beam section."))
        geo_content.addWidget(create_input_row("⛶", "Effective cover", self.cover_input, "mm", "Distance from outer face to\ncenter of reinforcement."))
        geo_content.addWidget(create_input_row("📏", "Span (L)", self.span_input, "m", "Clear span between supports."))
        geo_layout.addLayout(geo_content)
        self.layout.addWidget(geo_card)

      # --- MATERIAL PROPERTIES SECTION ---
        mat_card, mat_layout = create_section_frame("🧱", "MATERIAL PROPERTIES", "Select concrete and steel grades as per IS 456:2000")
        
        self.concrete_combo = QComboBox()
        self.concrete_combo.setView(QListView())  # <-- Integrates standard list view to fix background rendering
        self.concrete_combo.addItems(list(engine.FCK_TABLE.keys()))
        self.concrete_combo.setCurrentText(self.session.concrete_grade)
        
        self.steel_combo = QComboBox()
        self.steel_combo.setView(QListView())     # <-- Integrates standard list view to fix background rendering
        self.steel_combo.addItems(list(engine.FY_TABLE.keys()))
        self.steel_combo.setCurrentText(self.session.steel_grade)
        
        mat_grid = QHBoxLayout()
        mat_grid.setSpacing(24)
        
        # 1. Create rows and store them in variables
        concrete_row = create_input_row("🏗️", "Concrete grade (fck)", self.concrete_combo, "", "Characteristic compressive\nstrength, fck = 25 N/mm²")
        steel_row = create_input_row("🔩", "Steel grade (fy)", self.steel_combo, "", "Characteristic yield strength,\nfy = 500 N/mm²")
        
        # 2. Extract the specific description labels using findChild
        self.conc_info_label = concrete_row.findChild(QLabel, "FieldDescPill")
        self.steel_info_label = steel_row.findChild(QLabel, "FieldDescPill")
        
        # 3. Add to layout
        mat_grid.addWidget(concrete_row)
        mat_grid.addWidget(steel_row)
        mat_layout.addLayout(mat_grid)
        self.layout.addWidget(mat_card)

        # 4. Connect the combo boxes to trigger the update method
        self.concrete_combo.currentTextChanged.connect(self.update_material_labels)
        self.steel_combo.currentTextChanged.connect(self.update_material_labels)

        # --- DESIGN LOADS SECTION ---
        load_card, load_layout = create_section_frame("⚖️", "DESIGN LOADS (FACTORED)", "Enter the factored design actions")
        self.mu_input = QLineEdit(str(self.session.mu))
        self.vu_input = QLineEdit(str(self.session.vu))
        
        load_grid = QHBoxLayout()
        load_grid.setSpacing(24)
        load_grid.addWidget(create_input_row("↺", "Factored moment (Mu)", self.mu_input, "kN·m", "Ultimate factored bending moment\nat the critical section."))
        load_grid.addWidget(create_input_row("↧", "Factored shear (Vu)", self.vu_input, "kN", "Ultimate factored shear force\nat the critical section."))
        load_layout.addLayout(load_grid)
        self.layout.addWidget(load_card)
        
        self.layout.addStretch()

        banner = create_bottom_banner(
            self.on_back, self._save_and_next, back_label="← Back: Beam Type", 
            info_text="Note: All dimensions in mm and loads in kN / kN·m unless otherwise specified."
        )
        self.banner_layout.addWidget(banner)
        
        # Add this line to set the initial text on page load
        self.update_material_labels()

    def _save_and_next(self):
        s = self.session
        try:
            s.b = float(self.b_input.text())
            s.D = float(self.D_input.text())
            s.effective_cover = float(self.cover_input.text())
            s.span = float(self.span_input.text())
            s.concrete_grade = self.concrete_combo.currentText()
            s.steel_grade = self.steel_combo.currentText()
            s.mu = float(self.mu_input.text())
            s.vu = float(self.vu_input.text())
            self.on_next()
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Please ensure all numeric fields contain valid numbers.")

    def refresh_from_session(self):
        s = self.session
        self.b_input.setText(str(s.b))
        self.D_input.setText(str(s.D))
        self.cover_input.setText(str(s.effective_cover))
        self.span_input.setText(str(s.span))
        self.concrete_combo.setCurrentText(s.concrete_grade)
        self.steel_combo.setCurrentText(s.steel_grade)
        self.mu_input.setText(str(s.mu))
        self.vu_input.setText(str(s.vu))
        
    def refresh(self): pass

    def update_material_labels(self):
        """Dynamically update info text based on selected material grades."""
        conc_grade = self.concrete_combo.currentText()
        steel_grade = self.steel_combo.currentText()
        
        # Extract numeric values (e.g., "M30" -> "30")
        fck = ''.join(filter(str.isdigit, conc_grade))
        fy = ''.join(filter(str.isdigit, steel_grade))
        
        # Safely update the labels while preserving the line break format
        if hasattr(self, 'conc_info_label') and self.conc_info_label:
            self.conc_info_label.setText(f"Characteristic compressive\nstrength, fck = {fck} N/mm²")
            
        if hasattr(self, 'steel_info_label') and self.steel_info_label:
            self.steel_info_label.setText(f"Characteristic yield strength,\nfy = {fy} N/mm²")

# ==========================================
# REMAINING WIZARD PAGES 
# ==========================================
class AccordionRow(QFrame):
    def __init__(self, title, content_text):
        super().__init__()
        dark = is_dark_mode()
        bg_acc = "#0F172A" if dark else "#F8FAFC"
        self.border_acc = "#334155" if dark else "#E2E8F0"
        text_sub = "#94A3B8" if dark else "#475569"
        
        # New variable for the blue title color
        title_color = "#60A5FA" if dark else "#1D4ED8"
        
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QFrame {{ background-color: {bg_acc}; border: 1px solid {self.border_acc}; border-radius: 6px; margin-bottom: 4px; }}")
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Header (Clickable)
        self.header = QFrame()
        self.header.setStyleSheet("border: none; background: transparent;")
        self.header.setCursor(Qt.PointingHandCursor)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        
        title_lbl = QLabel(title)
        # Applied title_color here and bumped font-size to 13px to match Shear page
        title_lbl.setStyleSheet(f"color: {title_color}; font-size: 13px; font-weight: bold; border: none;")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()
        
        self.chev = QLabel("▼")
        self.chev.setStyleSheet(f"color: {text_sub}; font-weight: bold; font-family: monospace; border: none; font-size: 11px;")
        header_layout.addWidget(self.chev)
        
        self.main_layout.addWidget(self.header)
        
        # Content (Hidden by default)
        self.content = QFrame()
        self.content.setStyleSheet(f"border-top: 1px solid {self.border_acc}; border-left: none; border-right: none; border-bottom: none; background: transparent;")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(16, 12, 16, 12)
        
        content_lbl = QLabel(content_text)
        content_lbl.setStyleSheet(f"color: {text_sub}; font-size: 12px; border: none; font-family: monospace;")
        content_lbl.setWordWrap(True)
        content_layout.addWidget(content_lbl)
        
        self.main_layout.addWidget(self.content)
        self.content.setVisible(False)
        self.is_expanded = False
        
        # Bind the click event
        self.header.mousePressEvent = self.toggle
        
    def toggle(self, event):
        self.is_expanded = not self.is_expanded
        self.content.setVisible(self.is_expanded)
        self.chev.setText("▲" if self.is_expanded else "▼")



class FlexuralPage(WizardPage):
    def __init__(self, session: DesignSession, on_back, on_next, on_export):
        super().__init__()
        self.session = session
        self.on_back = on_back
        self.on_next = on_next
        self.on_export = on_export
        self.placeholder = QLabel("Run design to see flexural results.")
        self.layout.addWidget(self.placeholder)

    def _create_card(self, icon_str, title_str):
        """Helper to generate styled container cards matching the modern UI theme."""
        dark = is_dark_mode()
        bg_card = "#1E293B" if dark else "#FFFFFF"
        border = "#334155" if dark else "#E2E8F0"
        text_main = "#F8FAFC" if dark else "#0F172A"
        
        frame = QFrame()
        frame.setAttribute(Qt.WA_StyledBackground, True)
        frame.setStyleSheet(f"background-color: {bg_card}; border: 1px solid {border}; border-radius: 12px;")
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        header = QHBoxLayout()
        icon_lbl = QLabel(icon_str)
        icon_lbl.setStyleSheet("font-size: 18px; color: #3B82F6; border: none;")
        title = QLabel(title_str)
        title.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {text_main}; border: none;")
        
        header.addWidget(icon_lbl)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {border}; border: none;")
        line.setFixedHeight(1)
        layout.addWidget(line)
        
        content_layout = QVBoxLayout()
        content_layout.setSpacing(12)
        layout.addLayout(content_layout)
        
        return frame, content_layout

    def refresh(self):
        clear_layout(self.layout)
        clear_layout(self.banner_layout)
        result = self.session.run_flexural()

        dark = is_dark_mode()
        text_main = "#F8FAFC" if dark else "#0F172A"
        text_sub = "#94A3B8" if dark else "#475569"

        # 1. Page Header
        subtitle = "Design for bending moment as per IS 456:2000 (Clause 38)\nThis section calculates the required tension reinforcement for the given factored moment."
        add_page_header(self.layout, "2. FLEXURAL DESIGN", subtitle, export_callback=self.on_export)
        self.layout.addSpacing(16)

        # Top Grid (Results on left, Capacity & Status on right)
        top_row = QHBoxLayout()
        top_row.setSpacing(20)

        # 2. DESIGN RESULTS CARD
        res_card, res_content = self._create_card("📐", "DESIGN RESULTS")
        
        def add_result_row(icon, label, val, unit, is_pill=False):
            r = QHBoxLayout()
            
            i_lbl = QLabel(icon)
            i_lbl.setFixedSize(24, 24)
            i_lbl.setAlignment(Qt.AlignCenter)
            i_lbl.setStyleSheet("font-size: 16px; color: #3B82F6; border: none;")
            r.addWidget(i_lbl)
            
            l_lbl = QLabel(label)
            l_lbl.setStyleSheet(f"font-size: 12px; color: {text_sub}; border: none;")
            r.addWidget(l_lbl)
            r.addStretch()
            
            if is_pill:
                pill_bg = "#064E3B" if dark else "#D1FAE5"
                pill_txt = "#34D399" if dark else "#065F46"
                v_lbl = QLabel(val)
                v_lbl.setStyleSheet(f"background-color: {pill_bg}; color: {pill_txt}; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; border: none;")
                r.addWidget(v_lbl)
            else:
                v_lbl = QLabel(val)
                v_lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {text_main}; border: none;")
                r.addWidget(v_lbl)
                if unit:
                    u_lbl = QLabel(unit)
                    u_lbl.setStyleSheet(f"font-size: 12px; color: {text_sub}; border: none; padding-left: 4px;")
                    r.addWidget(u_lbl)
                    
            res_content.addLayout(r)
            
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet(f"background-color: {'#334155' if dark else '#F1F5F9'}; border: none;")
            sep.setFixedHeight(1)
            res_content.addWidget(sep)

        add_result_row("↕", "Effective depth (d)", f"{result.d:.2f}", "mm")
        add_result_row("⊓", "Limiting neutral axis depth (xu,max)\n(Cl. 38.1)", f"{result.xu_max:.2f}", "mm")
        add_result_row("↻", "Limiting moment (Mlim)", f"{result.m_lim:.2f}", "kN·m")
        
        section_type = "Singly reinforced" if result.is_singly else "Doubly reinforced"
        add_result_row("☷", "Section type", section_type, "", is_pill=True)
        
        ast_val = f"{result.ast:.1f}" if result.ast else "See details below"
        ast_unit = "mm²" if result.ast else ""
        add_result_row("⌗", "Required tension steel (Ast,req)", ast_val, ast_unit)
        add_result_row("Σ", "Minimum tension steel (Ast,min)\n(Cl. 26.5.1.1)", f"{result.ast_min:.1f}", "mm²")
        
        top_row.addWidget(res_card, stretch=1)

        # 3. RIGHT COLUMN (Moment Capacity & Design Status)
        right_col = QVBoxLayout()
        right_col.setSpacing(20)

        # Moment Capacity Check
        mom_card, mom_content = self._create_card("📊", "MOMENT CAPACITY CHECK")
        add_result_row("", "Factored moment (Mu)", f"{self.session.mu:.2f}", "kN·m")
        add_result_row("", "Limiting moment (Mlim)", f"{result.m_lim:.2f}", "kN·m")
        
        check_frame = QFrame()
        chk_bg = "#064E3B" if dark else "#ECFDF5"
        chk_border = "#047857" if dark else "#A7F3D0"
        check_frame.setStyleSheet(f"background-color: {chk_bg}; border: 1px solid {chk_border}; border-radius: 6px;")
        check_layout = QHBoxLayout(check_frame)
        check_layout.setContentsMargins(16, 12, 16, 12)
        
        is_safe_moment = result.is_singly
        chk_txt_col = "#34D399" if dark else "#059669"
        bad_txt_col = "#FCA5A5" if dark else "#B45309"
        
        chk_icon = QLabel("✓ Check" if is_safe_moment else "⚠ Check")
        chk_icon.setStyleSheet(f"color: {chk_txt_col if is_safe_moment else bad_txt_col}; font-weight: bold; border: none;")
        check_layout.addWidget(chk_icon)
        check_layout.addStretch()
        
        operator = "≤" if is_safe_moment else ">"
        chk_eq = QLabel(f"Mu {operator} Mlim\n{self.session.mu:.2f} {operator} {result.m_lim:.2f}")
        chk_eq.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        chk_eq.setStyleSheet(f"color: {chk_txt_col if is_safe_moment else bad_txt_col}; font-size: 12px; font-weight: bold; border: none;")
        
        check_layout.addWidget(chk_eq)
        mom_content.addWidget(check_frame)
        right_col.addWidget(mom_card)

        # Design Status Check
        stat_card, stat_content = self._create_card("🛡️", "DESIGN STATUS")
        stat_frame = QFrame()
        stat_frame.setStyleSheet(f"background-color: {chk_bg}; border: none; border-radius: 6px;")
        stat_layout = QHBoxLayout(stat_frame)
        stat_layout.setContentsMargins(16, 16, 16, 16)
        stat_layout.setSpacing(12)
        
        s_icon = QLabel("✓")
        s_icon.setStyleSheet("background-color: #10B981; color: white; border-radius: 12px; font-size: 14px; font-weight: bold;")
        s_icon.setFixedSize(24, 24)
        s_icon.setAlignment(Qt.AlignCenter)
        stat_layout.addWidget(s_icon)
        
        status_msg = "<b>SAFE</b><br/>Section is adequate in flexure<br/>(singly reinforced)" if result.is_singly else "<b>SAFE</b><br/>Section is adequate in flexure<br/>(doubly reinforced)"
        s_text = QLabel(status_msg)
        s_text.setStyleSheet(f"color: {chk_txt_col}; font-size: 13px; border: none;")
        stat_layout.addWidget(s_text)
        stat_layout.addStretch()
        
        stat_content.addWidget(stat_frame)
        right_col.addWidget(stat_card)
        right_col.addStretch()

        top_row.addLayout(right_col, stretch=1)
        self.layout.addLayout(top_row)

        # 4. CALCULATION DETAILS (Numbered Accordion)
        calc_card, calc_content = self._create_card("🧮", "CALCULATION DETAILS")
        calc_content.setSpacing(4)
        
        # Format the mathematical strings
        d_text = f"d = D - effective_cover\nd = {self.session.D} - {self.session.effective_cover}\nd = {result.d:.2f} mm"
        
        xu_ratio = result.xu_max / result.d if result.d else 0
        xu_text = f"xu,max = {xu_ratio:.2f} × d\nxu,max = {xu_ratio:.2f} × {result.d:.2f}\nxu,max = {result.xu_max:.2f} mm"
        
        mlim_text = f"Mlim = 0.36 × fck × b × xu,max × (d - 0.42 × xu,max)\nMlim = 0.36 × {result.fck} × {self.session.b} × {result.xu_max:.2f} × ({result.d:.2f} - 0.42 × {result.xu_max:.2f}) / 10^6\nMlim = {result.m_lim:.2f} kN·m"
        
        if result.is_singly:
            ast_text = f"Ast = (0.5 × fck / fy) × [1 - sqrt(1 - 4.6 × Mu / (fck × b × d²))] × b × d\nAst = {result.ast:.1f} mm²"
        else:
            ast_text = "Mu > Mlim. Section is doubly reinforced.\nTension steel is calculated in two parts (Ast1 + Ast2). See the breakdown below."
            
        ast_max = 0.04 * self.session.b * self.session.D
        min_max_text = f"Ast,min = (0.85 / fy) × b × d\nAst,min = (0.85 / {result.fy}) × {self.session.b} × {result.d:.2f}\nAst,min = {result.ast_min:.1f} mm²\n\nAst,max = 0.04 × b × D\nAst,max = 0.04 × {self.session.b} × {self.session.D}\nAst,max = {ast_max:.1f} mm²"

        # Apply the NumberedAccordionRow to create the blue circle badges
        calc_content.addWidget(NumberedAccordionRow(1, "Effective Depth (d)", "", d_text))
        calc_content.addWidget(NumberedAccordionRow(2, "Limiting Neutral Axis Depth (xu,max)", "IS 456:2000, Cl. 38.1", xu_text))
        calc_content.addWidget(NumberedAccordionRow(3, "Limiting Moment Capacity (Mlim)", "", mlim_text))
        calc_content.addWidget(NumberedAccordionRow(4, "Required Tension Reinforcement (Ast)", "", ast_text))
        calc_content.addWidget(NumberedAccordionRow(5, "Minimum and Maximum Reinforcement", "IS 456:2000, Cl. 26.5.1.1", min_max_text))
        
        self.layout.addWidget(calc_card)

        # 5. Doubly Reinforced Fallback
        if not result.is_singly:
            import rcc_beam_design as engine
            doubly = engine.get_doubly_reinforced_design(
                b=self.session.b, d=result.d, mu=self.session.mu, m_lim=result.m_lim,
                xu_max=result.xu_max, fck=result.fck, fy=result.fy,
                d_dash=self.session.effective_cover
            )
            self.session.doubly = doubly

            dr_card, dr_content = self._create_card("🏗️", "DOUBLY REINFORCED BREAKDOWN")
            
            add_result_row("", "Compression steel cover (d')", f"{doubly.d_dash:.0f}", "mm")
            add_result_row("", "Compression steel stress (fsc)", f"{doubly.fsc:.1f}", "N/mm²")
            add_result_row("", "Tension steel — balanced (Ast1)", f"{doubly.ast1:.1f}", "mm²")
            add_result_row("", "Tension steel — additional (Ast2)", f"{doubly.ast2:.1f}", "mm²")
            add_result_row("", "Compression steel required (Asc)", f"{doubly.asc:.1f}", "mm²")
            
            self.layout.addWidget(dr_card)

            note = QLabel("Note: doubly reinforced design uses standard design-aid values for compression steel stress (fsc), as published in SP:16.")
            note.setWordWrap(True)
            note.setStyleSheet(get_note_style())
            self.layout.addWidget(note)

        self.layout.addStretch()

        # 6. Navigation Banner
        banner = create_bottom_banner(
            self.on_back, self.on_next, 
            back_label="← Back: Beam Input",
            next_label="Next: Shear Design →",
            info_text="Note: Flexural design uses the limit state stress block of IS 456 (Cl. 38.1, Annex G)."
        )
        self.banner_layout.addWidget(banner)

class NumberedAccordionRow(QFrame):
    def __init__(self, number, title, ref_text, content_text):
        super().__init__()
        dark = is_dark_mode()
        bg_acc = "#0F172A" if dark else "#F8FAFC"
        self.border_acc = "#334155" if dark else "#F1F5F9"
        text_main = "#F8FAFC" if dark else "#0F172A"
        text_sub = "#94A3B8" if dark else "#64748B"
        title_color = "#60A5FA" if dark else "#1D4ED8"
        
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QFrame {{ background-color: {bg_acc}; border: 1px solid {self.border_acc}; border-radius: 6px; margin-bottom: 4px; }}")
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Header (Clickable)
        self.header = QFrame()
        self.header.setStyleSheet("border: none; background: transparent;")
        self.header.setCursor(Qt.PointingHandCursor)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 10, 16, 10)
        header_layout.setSpacing(12)
        
        # Number Circle
        num_lbl = QLabel(str(number))
        num_lbl.setFixedSize(24, 24)
        num_lbl.setAlignment(Qt.AlignCenter)
        num_lbl.setStyleSheet("background-color: #2563EB; color: white; border-radius: 12px; font-weight: bold; font-size: 12px;")
        header_layout.addWidget(num_lbl)
        
        # Title
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {title_color}; font-size: 13px; font-weight: bold; border: none;")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()
        
        # Code Reference Text
        ref_lbl = QLabel(ref_text)
        ref_lbl.setStyleSheet(f"color: {text_sub}; font-size: 12px; border: none;")
        header_layout.addWidget(ref_lbl)
        
        # Chevron
        self.chev = QLabel("▼")
        self.chev.setStyleSheet(f"color: {text_sub}; font-weight: bold; border: none; font-size: 11px; margin-left: 10px;")
        header_layout.addWidget(self.chev)
        
        self.main_layout.addWidget(self.header)
        
        # Content (Hidden by default)
        self.content = QFrame()
        self.content.setStyleSheet(f"border-top: 1px solid {self.border_acc}; border-left: none; border-right: none; border-bottom: none; background: transparent;")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(48, 12, 16, 12)  # Indented to align with text
        
        content_lbl = QLabel(content_text)
        content_lbl.setStyleSheet(f"color: {text_sub}; font-size: 12px; border: none; font-family: monospace;")
        content_lbl.setWordWrap(True)
        content_layout.addWidget(content_lbl)
        
        self.main_layout.addWidget(self.content)
        self.content.setVisible(False)
        self.is_expanded = False
        
        # Bind the click event
        self.header.mousePressEvent = self.toggle
        
    def toggle(self, event):
        self.is_expanded = not self.is_expanded
        self.content.setVisible(self.is_expanded)
        self.chev.setText("▲" if self.is_expanded else "▼")


class ShearPage(WizardPage):
    def __init__(self, session: DesignSession, on_back, on_next, on_export):
        super().__init__()
        self.session = session
        self.on_back = on_back
        self.on_next = on_next
        self.on_export = on_export

    def _create_card(self, icon_str, title_str, right_widget=None):
        dark = is_dark_mode()
        bg_card = "#1E293B" if dark else "#FFFFFF"
        border = "#334155" if dark else "#E2E8F0"
        text_main = "#F8FAFC" if dark else "#0F172A"
        
        frame = QFrame()
        frame.setAttribute(Qt.WA_StyledBackground, True)
        frame.setStyleSheet(f"background-color: {bg_card}; border: 1px solid {border}; border-radius: 12px;")
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        header = QHBoxLayout()
        icon_lbl = QLabel(icon_str)
        icon_lbl.setStyleSheet("font-size: 18px; color: #3B82F6; border: none;")
        title = QLabel(title_str)
        title.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {text_main}; border: none;")
        
        header.addWidget(icon_lbl)
        header.addWidget(title)
        header.addStretch()
        if right_widget:
            header.addWidget(right_widget)
        layout.addLayout(header)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {border}; border: none;")
        line.setFixedHeight(1)
        layout.addWidget(line)
        
        content_layout = QVBoxLayout()
        content_layout.setSpacing(12)
        layout.addLayout(content_layout)
        
        return frame, content_layout

    def refresh(self):
        clear_layout(self.layout)
        clear_layout(self.banner_layout)

        try:
            sh = self.session.run_shear()
        except DoublyReinforcedError as e:
            add_page_header(self.layout, "3. SHEAR DESIGN")
            note = QLabel(f"⚠ Cannot proceed: {e}")
            note.setWordWrap(True)
            note.setStyleSheet(get_status_style(False))
            self.layout.addWidget(note)
            self.layout.addStretch()
            banner = create_bottom_banner(self.on_back, None, info_text="Error: Fix flexural design first.")
            self.banner_layout.addWidget(banner)
            return

        dark = is_dark_mode()
        text_main = "#F8FAFC" if dark else "#0F172A"
        text_sub = "#94A3B8" if dark else "#475569"

        # 1. Page Header
        subtitle = "Design for shear as per IS 456:2000 (Clause 40)\nCheck shear stress and provide shear reinforcement if required."
        add_page_header(self.layout, "3. SHEAR DESIGN", subtitle, export_callback=self.on_export)
        self.layout.addSpacing(16)

        # 2. Top Grid Section (Results & Checks)
        top_row = QHBoxLayout()
        top_row.setSpacing(20)

        # 2A. LEFT: Shear Design Results Card
        res_card, res_content = self._create_card("▦", "SHEAR DESIGN RESULTS")
        
        def add_res_row(label, val, unit):
            r = QHBoxLayout()
            l_lbl = QLabel(label)
            l_lbl.setStyleSheet(f"font-size: 13px; color: {text_sub}; border: none;")
            r.addWidget(l_lbl)
            r.addStretch()
            
            v_lbl = QLabel(val)
            v_lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {text_main}; border: none;")
            v_lbl.setFixedWidth(100 if unit else 180)
            r.addWidget(v_lbl)
            
            if unit:
                u_lbl = QLabel(unit)
                u_lbl.setStyleSheet(f"font-size: 13px; color: {text_sub}; border: none;")
                u_lbl.setFixedWidth(60)
                r.addWidget(u_lbl)
                
            res_content.addLayout(r)
            
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet(f"background-color: {'#334155' if dark else '#F1F5F9'}; border: none;")
            sep.setFixedHeight(1)
            res_content.addWidget(sep)

        add_res_row("Nominal shear stress (τv)", f"{sh.tau_v:.3f}", "N/mm²")
        add_res_row("Percentage of tension steel (Pt)", f"{sh.pt:.3f}", "%")
        add_res_row("Design shear strength (τc, Table 19)", f"{sh.tau_c:.3f}", "N/mm²")
        add_res_row("Maximum shear stress (τc,max, Table 20)", f"{sh.tau_c_max:.2f}", "N/mm²")
        add_res_row("Shear reinforcement required", "Yes" if sh.needs_shear_reinf else "No (Minimum)", "")
        add_res_row("Stirrup spacing provided", f"{sh.stirrup_dia:.0f} mm Ø, {sh.legs}-legged @ {sh.spacing:.0f} mm c/c", "")
        
        top_row.addWidget(res_card, stretch=1)

        # 2B. RIGHT: Design Checks & Provided Reinforcement
        right_col = QVBoxLayout()
        right_col.setSpacing(20)

        # Design Checks Card
        chk_card, chk_content = self._create_card("🛡️", "DESIGN CHECKS")
        
        def add_check_row(title_html, is_ok, ok_label):
            frame = QFrame()
            frame.setStyleSheet("background: transparent; border: none;")
            r = QHBoxLayout(frame)
            r.setContentsMargins(0, 0, 0, 0)
            
            icon = QLabel("✓" if is_ok else "✗")
            bg = "#10B981" if is_ok else "#EF4444"
            icon.setStyleSheet(f"background-color: {bg}; color: white; border-radius: 12px; font-weight: bold; font-size: 14px;")
            icon.setFixedSize(24, 24)
            icon.setAlignment(Qt.AlignCenter)
            r.addWidget(icon)
            
            t_lbl = QLabel(title_html)
            t_lbl.setStyleSheet(f"color: {text_main}; font-size: 12px;")
            r.addWidget(t_lbl)
            r.addStretch()
            
            pill_bg = "#064E3B" if dark else "#D1FAE5"
            pill_txt = "#34D399" if dark else "#065F46"
            pill = QLabel(ok_label)
            pill.setStyleSheet(f"background-color: {pill_bg}; color: {pill_txt}; padding: 4px 12px; border-radius: 4px; font-size: 11px; font-weight: bold;")
            r.addWidget(pill)
            
            chk_content.addWidget(frame)

        check_1_text = f"<b>Shear Stress Check (IS 456 Cl. 40.2)</b><br/>τv = {sh.tau_v:.3f} N/mm² &nbsp;≤&nbsp; τc,max = {sh.tau_c_max:.2f} N/mm²"
        add_check_row(check_1_text, sh.safe, "SAFE" if sh.safe else "FAIL")
        
        check_2_text = f"<b>Provide Shear Reinforcement (IS 456 Cl. 40.1)</b><br/>τv {'&gt;' if sh.needs_shear_reinf else '&le;'} τc &nbsp;⇒&nbsp; {'Shear reinforcement required' if sh.needs_shear_reinf else 'Minimum shear reinforcement required'}"
        add_check_row(check_2_text, True, "OK")
        
        right_col.addWidget(chk_card)

        # Provided Reinforcement Card
        prv_card, prv_content = self._create_card("⚙️", "PROVIDED REINFORCEMENT")
        prv_grid = QGridLayout()
        prv_grid.setContentsMargins(0, 0, 0, 0)
        
        lbl_sty = f"color: {text_sub}; font-size: 12px; border: none;"
        val_sty = f"color: {text_main}; font-size: 13px; font-weight: bold; border: none; padding-top: 4px;"
        
        d_lbl = QLabel("Stirrup diameter"); d_lbl.setStyleSheet(lbl_sty)
        d_val = QLabel(f"{sh.stirrup_dia:.0f} mm"); d_val.setStyleSheet(val_sty)
        
        n_lbl = QLabel("Number of legs"); n_lbl.setStyleSheet(lbl_sty)
        n_val = QLabel(f"{sh.legs}"); n_val.setStyleSheet(val_sty)
        
        s_lbl = QLabel("Spacing (s)"); s_lbl.setStyleSheet(lbl_sty)
        s_val = QLabel(f"{sh.spacing:.0f} mm c/c"); s_val.setStyleSheet(val_sty)
        
        prv_grid.addWidget(d_lbl, 0, 0)
        prv_grid.addWidget(n_lbl, 0, 1)
        prv_grid.addWidget(s_lbl, 0, 2)
        prv_grid.addWidget(d_val, 1, 0)
        prv_grid.addWidget(n_val, 1, 1)
        prv_grid.addWidget(s_val, 1, 2)
        
        prv_content.addLayout(prv_grid)
        right_col.addWidget(prv_card)
        right_col.addStretch()

        top_row.addLayout(right_col, stretch=1)
        self.layout.addLayout(top_row)

        # 3. Full Width Status Banner
        stat_frame = QFrame()
        bg_stat = "#064E3B" if dark else "#ECFDF5"
        border_stat = "#047857" if dark else "#A7F3D0"
        txt_stat = "#34D399" if dark else "#059669"
        if not sh.safe:
            bg_stat, border_stat, txt_stat = ("#7F1D1D", "#991B1B", "#FCA5A5") if dark else ("#FEF2F2", "#FECACA", "#B91C1C")
            
        stat_frame.setStyleSheet(f"background-color: {bg_stat}; border: 1px solid {border_stat}; border-radius: 6px;")
        stat_layout = QHBoxLayout(stat_frame)
        stat_layout.setContentsMargins(16, 12, 16, 12)
        
        s_icon = QLabel("✓" if sh.safe else "✗")
        s_icon.setStyleSheet(f"background-color: {txt_stat}; color: {'white' if not dark else '#0F172A'}; border-radius: 9px; font-weight: bold; font-size: 11px;")
        s_icon.setFixedSize(18, 18)
        s_icon.setAlignment(Qt.AlignCenter)
        stat_layout.addWidget(s_icon)
        
        msg = f"SAFE - τv ({sh.tau_v:.3f}) ≤ τc,max ({sh.tau_c_max:.2f}) — Shear design is adequate." if sh.safe else f"UNSAFE - τv ({sh.tau_v:.3f}) > τc,max ({sh.tau_c_max:.2f}) — Increase beam dimensions."
        s_msg = QLabel(msg)
        s_msg.setStyleSheet(f"color: {txt_stat}; font-weight: bold; font-size: 13px; border: none;")
        stat_layout.addWidget(s_msg)
        stat_layout.addStretch()
        
        self.layout.addWidget(stat_frame)

        # 4. CALCULATION DETAILS (Numbered Accordion)
        expand_lbl = QLabel("Expand All ⌄")
        expand_lbl.setStyleSheet("color: #3B82F6; font-size: 12px; font-weight: bold; border: none;")
        calc_card, calc_content = self._create_card("🧮", "CALCULATION DETAILS", expand_lbl)
        calc_content.setSpacing(4)
        
        ast_used = self.session.get_ast_provided()
        d_val = self.session.flexural.d

        txt_1 = f"Design factored shear force at critical section:\nVu = {self.session.vu:.2f} kN"
        txt_2 = f"τv = (Vu × 1000) / (b × d)\nτv = ({self.session.vu} × 1000) / ({self.session.b} × {d_val:.2f})\nτv = {sh.tau_v:.3f} N/mm²"
        txt_3 = f"Pt = (100 × Ast) / (b × d)\nPt = (100 × {ast_used:.1f}) / ({self.session.b} × {d_val:.2f})\nPt = {sh.pt:.3f} %"
        txt_4 = f"Concrete Grade = {self.session.concrete_grade}\nPt = {sh.pt:.3f} %\nInterpolating design shear strength from IS 456 Table 19:\nτc = {sh.tau_c:.3f} N/mm²"
        txt_5 = f"Concrete Grade = {self.session.concrete_grade}\nMaximum permissible shear stress from IS 456 Table 20:\nτc,max = {sh.tau_c_max:.2f} N/mm²"
        txt_6 = f"Check if τv ≤ τc,max\n{sh.tau_v:.3f} ≤ {sh.tau_c_max:.2f}\n" + ("Condition satisfied." if sh.safe else "Condition failed. Concrete crushing failure imminent.")
        txt_7 = f"Check if τv > τc\n{sh.tau_v:.3f} > {sh.tau_c:.3f} : {'True' if sh.needs_shear_reinf else 'False'}\n" + ("Shear reinforcement required to carry balance shear." if sh.needs_shear_reinf else "Only minimum shear reinforcement required.")
        txt_8 = (f"Vus = (τv - τc) × b × d\nSpacing (s) = (0.87 × fy × Asv × d) / Vus" if sh.needs_shear_reinf else "Minimum Spacing (s) = (0.87 × fy × Asv) / (0.4 × b)") + f"\nProvided spacing = {sh.spacing:.0f} mm c/c"

        calc_content.addWidget(NumberedAccordionRow(1, "Design Shear Force (Vu)", "IS 456:2000, Cl. 40.1", txt_1))
        calc_content.addWidget(NumberedAccordionRow(2, "Nominal Shear Stress (τv)", "IS 456:2000, Cl. 40.1", txt_2))
        calc_content.addWidget(NumberedAccordionRow(3, "Percentage of Tension Steel (Pt)", "IS 456:2000, Cl. 40.1", txt_3))
        calc_content.addWidget(NumberedAccordionRow(4, "Design Shear Strength of Concrete (τc)", "IS 456:2000, Cl. 40.1, Table 19", txt_4))
        calc_content.addWidget(NumberedAccordionRow(5, "Maximum Permissible Shear Stress (τc,max)", "IS 456:2000, Cl. 40.2, Table 20", txt_5))
        calc_content.addWidget(NumberedAccordionRow(6, "Shear Stress Check (τv ≤ τc,max)", "IS 456:2000, Cl. 40.2", txt_6))
        calc_content.addWidget(NumberedAccordionRow(7, "Shear Reinforcement Requirement", "IS 456:2000, Cl. 40.1, 40.3 & 26.5.1.6", txt_7))
        calc_content.addWidget(NumberedAccordionRow(8, "Final Shear Reinforcement", "IS 456:2000, Cl. 26.5.1.6", txt_8))
        
        self.layout.addWidget(calc_card)
        self.layout.addStretch()

        # 5. Bottom Navigation Banner
        banner = create_bottom_banner(
            self.on_back, self.on_next, 
            back_label="← Back: Flexural Design",
            next_label="Next: Serviceability →",
            info_text="Note: Shear capacities derived from Table 19 & 20 of IS 456:2000."
        )
        self.banner_layout.addWidget(banner)

class ServiceabilityPage(WizardPage):
    def __init__(self, session: DesignSession, on_back, on_next, on_export):
        super().__init__()
        self.session = session
        self.on_back = on_back
        self.on_next = on_next
        self.on_export = on_export

    def _create_card(self, icon_str, title_str, right_widget=None):
        dark = is_dark_mode()
        bg_card = "#1E293B" if dark else "#FFFFFF"
        border = "#334155" if dark else "#E2E8F0"
        text_main = "#F8FAFC" if dark else "#0F172A"
        
        frame = QFrame()
        frame.setAttribute(Qt.WA_StyledBackground, True)
        frame.setStyleSheet(f"background-color: {bg_card}; border: 1px solid {border}; border-radius: 12px;")
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        header = QHBoxLayout()
        icon_lbl = QLabel(icon_str)
        icon_lbl.setStyleSheet("font-size: 18px; color: #3B82F6; border: none;")
        title = QLabel(title_str)
        title.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {text_main}; border: none;")
        
        header.addWidget(icon_lbl)
        header.addWidget(title)
        header.addStretch()
        if right_widget:
            header.addWidget(right_widget)
        layout.addLayout(header)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {border}; border: none;")
        line.setFixedHeight(1)
        layout.addWidget(line)
        
        content_layout = QVBoxLayout()
        content_layout.setSpacing(12)
        layout.addLayout(content_layout)
        
        return frame, content_layout

    def refresh(self):
        clear_layout(self.layout)
        clear_layout(self.banner_layout)

        try:
            # Assumes your DesignSession has a run_serviceability method
            srv = self.session.run_serviceability()
        except Exception as e:
            add_page_header(self.layout, "4. SERVICEABILITY CHECK")
            note = QLabel(f"⚠ Cannot proceed: {e}")
            note.setWordWrap(True)
            note.setStyleSheet(get_status_style(False))
            self.layout.addWidget(note)
            self.layout.addStretch()
            banner = create_bottom_banner(self.on_back, None, info_text="Error: Complete earlier designs first.")
            self.banner_layout.addWidget(banner)
            return

        dark = is_dark_mode()
        text_main = "#F8FAFC" if dark else "#0F172A"
        text_sub = "#94A3B8" if dark else "#475569"
        border_col = "#334155" if dark else "#E2E8F0"
        header_bg = "#0F172A" if dark else "#F8FAFC"
        title_color = "#60A5FA" if dark else "#1D4ED8"

        # 1. Page Header
        subtitle = "Check deflection as per IS 456:2000 (Clause 23.2)\nVerify that the actual span/depth ratio does not exceed the allowable limit."
        add_page_header(self.layout, "4. SERVICEABILITY CHECK", subtitle, export_callback=self.on_export)
        self.layout.addSpacing(16)

        # 2. Results Table Card
        res_card, res_content = self._create_card("▦", "SERVICEABILITY CHECK RESULTS")
        
        grid = QGridLayout()
        grid.setSpacing(0)
        
        # Grid Styles
        h_style = f"background-color: {header_bg}; color: {title_color}; font-weight: bold; font-size: 12px; padding: 10px; border-bottom: 1px solid {border_col};"
        c_style = f"color: {text_main}; font-size: 13px; padding: 12px 10px; border-bottom: 1px solid {border_col};"
        
        # Removed the empty "" header for the icon column
        headers = ["Parameter", "Value", "Limit / Allowable", "Status"]
        for col, h_text in enumerate(headers):
            lbl = QLabel(h_text)
            lbl.setStyleSheet(h_style)
            lbl.setAlignment(Qt.AlignCenter if col > 0 else Qt.AlignLeft)
            grid.addWidget(lbl, 0, col)

        def add_grid_row(row, param, val, limit="-", status=None, is_safe=True):
            p_lbl = QLabel(param)
            p_lbl.setStyleSheet(c_style)
            grid.addWidget(p_lbl, row, 0)
            
            v_lbl = QLabel(val)
            v_lbl.setStyleSheet(c_style)
            v_lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(v_lbl, row, 1)
            
            l_lbl = QLabel(limit)
            l_lbl.setStyleSheet(c_style)
            l_lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(l_lbl, row, 2)
            
            if status:
                s_frame = QFrame()
                s_frame.setStyleSheet(f"border-bottom: 1px solid {border_col};")
                s_layout = QHBoxLayout(s_frame)
                s_layout.setContentsMargins(10, 10, 10, 10)
                s_layout.setAlignment(Qt.AlignCenter)
                
                bg_pill = "#10B981" if is_safe else "#EF4444"
                s_pill = QLabel(status)
                s_pill.setStyleSheet(f"background-color: {bg_pill}; color: white; font-weight: bold; font-size: 11px; padding: 4px 12px; border-radius: 4px;")
                s_layout.addWidget(s_pill)
                
                check_icon = QLabel("✓" if is_safe else "✗")
                check_icon.setStyleSheet(f"background-color: {bg_pill}; color: white; border-radius: 10px; font-weight: bold; font-size: 12px;")
                check_icon.setFixedSize(20, 20)
                check_icon.setAlignment(Qt.AlignCenter)
                s_layout.insertWidget(0, check_icon)
                
                grid.addWidget(s_frame, row, 3)
            else:
                empty = QLabel("-")
                empty.setStyleSheet(c_style)
                empty.setAlignment(Qt.AlignCenter)
                grid.addWidget(empty, row, 3)

        # Removed the icon arguments (e.g., "△", "⚙")
        add_grid_row(1, "Basic span/depth ratio (Cl. 23.2)", f"{srv.basic_ratio:.2f}")
        add_grid_row(2, "Modification factor (Fig. 4)", f"{srv.mod_factor:.3f}")
        add_grid_row(3, "Allowable span/depth ratio", f"{srv.allowable_ratio:.2f}")
        add_grid_row(4, "Actual span/depth ratio (L/d)", f"{srv.actual_ratio:.2f}", f"≤ {srv.allowable_ratio:.2f}", "SAFE" if srv.safe else "FAIL", srv.safe)

        res_content.addLayout(grid)
        self.layout.addWidget(res_card)

        # 3. Note Box
        note_frame = QFrame()
        note_bg = "#EFF6FF" if not dark else "#1E3A8A"
        note_border = "#BFDBFE" if not dark else "#1E40AF"
        note_txt = "#1E40AF" if not dark else "#DBEAFE"
        note_frame.setStyleSheet(f"background-color: {note_bg}; border: 1px solid {note_border}; border-radius: 6px;")
        note_layout = QHBoxLayout(note_frame)
        note_layout.setContentsMargins(16, 12, 16, 12)
        
        info_icon = QLabel("ℹ")
        info_icon.setStyleSheet(f"color: white; background-color: {title_color}; border-radius: 10px; font-weight: bold; font-size: 14px;")
        info_icon.setFixedSize(20, 20)
        info_icon.setAlignment(Qt.AlignCenter)
        note_layout.addWidget(info_icon, alignment=Qt.AlignTop)

        span_msg = ""
        if srv.needs_deflection_calc:
            span_msg = "<br>• <b>Cantilever span above 10 m:</b> IS 456 Cl. 23.2.1(b) requires an actual deflection calculation; the L/d result above is not sufficient."
        elif srv.span_factor < 1.0:
            span_msg = f"<br>• Span above 10 m: basic ratio multiplied by 10/span = {srv.span_factor:.3f} (Cl. 23.2.1 b)."
        
        note_lbl = QLabel(
            "<b>Note</b><br>"
            "• IS 456 Fig. 4 is a chart, not an equation. The modification factor is computed from a published curve-fit of those curves, using fs = 0.58·fy·(Ast,req/Ast,prov) and the provided Pt.<br>"
            "• Allowable span/depth ratio = (Basic span/depth ratio) × (Modification factor).<br>"
            "• Deflection control follows the empirical L/d approach as per IS 456:2000 (Clause 23.2)." + span_msg
        )
        note_lbl.setStyleSheet(f"color: {note_txt}; font-size: 12px; border: none;")
        note_lbl.setWordWrap(True)
        note_layout.addWidget(note_lbl)
        self.layout.addWidget(note_frame)

        # 4. Status Banner
        stat_frame = QFrame()
        bg_stat = "#064E3B" if dark else "#ECFDF5"
        border_stat = "#047857" if dark else "#A7F3D0"
        txt_stat = "#34D399" if dark else "#059669"
        if not srv.safe:
            bg_stat, border_stat, txt_stat = ("#7F1D1D", "#991B1B", "#FCA5A5") if dark else ("#FEF2F2", "#FECACA", "#B91C1C")
            
        stat_frame.setStyleSheet(f"background-color: {bg_stat}; border: 1px solid {border_stat}; border-radius: 6px;")
        stat_layout = QHBoxLayout(stat_frame)
        stat_layout.setContentsMargins(16, 12, 16, 12)
        
        s_icon = QLabel("✓" if srv.safe else "✗")
        s_icon.setStyleSheet(f"background-color: {txt_stat}; color: {'white' if not dark else '#0F172A'}; border-radius: 12px; font-weight: bold; font-size: 14px;")
        s_icon.setFixedSize(24, 24)
        s_icon.setAlignment(Qt.AlignCenter)
        stat_layout.addWidget(s_icon)
        
        msg_title = f"SAFE - Actual ({srv.actual_ratio:.2f}) ≤ Allowable ({srv.allowable_ratio:.2f})" if srv.safe else f"UNSAFE - Actual ({srv.actual_ratio:.2f}) > Allowable ({srv.allowable_ratio:.2f})"
        msg_sub = "The design satisfies the serviceability requirement for deflection." if srv.safe else "Increase effective depth (d) or provide more tension reinforcement."
        
        msg_layout = QVBoxLayout()
        msg_layout.setSpacing(2)
        m_t = QLabel(msg_title)
        m_t.setStyleSheet(f"color: {txt_stat}; font-weight: bold; font-size: 13px; border: none;")
        m_s = QLabel(msg_sub)
        m_s.setStyleSheet(f"color: {txt_stat}; font-size: 12px; border: none;")
        msg_layout.addWidget(m_t)
        msg_layout.addWidget(m_s)
        
        stat_layout.addLayout(msg_layout)
        stat_layout.addStretch()
        self.layout.addWidget(stat_frame)

        # 5. CALCULATION DETAILS (Numbered Accordion)
        expand_lbl = QLabel("Expand All ⌄")
        expand_lbl.setStyleSheet(f"color: {title_color}; font-size: 12px; font-weight: bold; border: none;")
        calc_card, calc_content = self._create_card("🧮", "CALCULATION DETAILS", expand_lbl)
        calc_content.setSpacing(4)
        
        # Safely compute steel stress for the formula breakdown
        ast_req, ast_prov, fs_val = srv.ast_required, srv.ast_provided, srv.fs
        
        txt_1 = f"Beam Type: {self.session.beam_type}\nFrom IS 456 Clause 23.2.1 (a):\nBasic (L/d) = {srv.basic_ratio:.2f}"
        txt_2 = f"fs = 0.58 × fy × (Ast,req / Ast,prov)\nfs = 0.58 × {self.session.flexural.fy} × ({ast_req:.2f} / {ast_prov:.2f})\nfs = {fs_val:.2f} N/mm²\n\nPt = {srv.pt:.3f}% (provided steel)\nModification Factor (Kt), curve-fit of Fig. 4 = {srv.mod_factor:.3f}"
        txt_3 = f"Allowable (L/d) = Basic (L/d) × Modification Factor\nAllowable (L/d) = {srv.basic_ratio:.2f} × {srv.mod_factor:.3f}\nAllowable (L/d) = {srv.allowable_ratio:.2f}"
        txt_4 = f"Actual (L/d) = Span / Effective Depth\nActual (L/d) = ({self.session.span} × 1000) / {self.session.flexural.d:.2f}\nActual (L/d) = {srv.actual_ratio:.2f}"
        txt_5 = f"Check if Actual (L/d) ≤ Allowable (L/d)\n{srv.actual_ratio:.2f} ≤ {srv.allowable_ratio:.2f}\n" + ("Condition satisfied. Deflection is within safe limits." if srv.safe else "Condition failed. Section is unsafe against deflection.")

        calc_content.addWidget(NumberedAccordionRow(1, "Basic span/depth ratio", "IS 456:2000, Cl. 23.2", txt_1))
        calc_content.addWidget(NumberedAccordionRow(2, "Modification factor", "IS 456:2000, Fig. 4", txt_2))
        calc_content.addWidget(NumberedAccordionRow(3, "Allowable span/depth ratio", "IS 456:2000, Cl. 23.2", txt_3))
        calc_content.addWidget(NumberedAccordionRow(4, "Actual span/depth ratio (L/d)", "IS 456:2000, Cl. 23.2", txt_4))
        calc_content.addWidget(NumberedAccordionRow(5, "Serviceability check", "IS 456:2000, Cl. 23.2", txt_5))
        
        self.layout.addWidget(calc_card)
        self.layout.addStretch()

        # 6. Bottom Navigation Banner
        banner = create_bottom_banner(
            self.on_back, self.on_next, 
            back_label="← Back: Shear Design",
            next_label="Next: Detailing →",
            info_text="Note: Deflection check is strictly based on the empirical method (Cl. 23.2)."
        )
        self.banner_layout.addWidget(banner)

class DetailingPage(WizardPage):
    def __init__(self, session: DesignSession, on_back, on_next, on_export):
        super().__init__()
        self.session = session
        self.on_back = on_back
        self.on_next = on_next
        self.on_export = on_export

    def _create_card(self, icon_str, title_str, right_widget=None):
        dark = is_dark_mode()
        bg_card = "#1E293B" if dark else "#FFFFFF"
        border = "#334155" if dark else "#E2E8F0"
        text_main = "#F8FAFC" if dark else "#0F172A"
        
        frame = QFrame()
        frame.setAttribute(Qt.WA_StyledBackground, True)
        frame.setStyleSheet(f"background-color: {bg_card}; border: 1px solid {border}; border-radius: 12px;")
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        header = QHBoxLayout()
        icon_lbl = QLabel(icon_str)
        icon_lbl.setStyleSheet("font-size: 18px; color: #3B82F6; border: none;")
        title = QLabel(title_str)
        title.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {text_main}; border: none;")
        
        header.addWidget(icon_lbl)
        header.addWidget(title)
        header.addStretch()
        if right_widget:
            header.addWidget(right_widget)
        layout.addLayout(header)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {border}; border: none;")
        line.setFixedHeight(1)
        layout.addWidget(line)
        
        content_layout = QVBoxLayout()
        content_layout.setSpacing(12)
        layout.addLayout(content_layout)
        
        return frame, content_layout

    def refresh(self):
        clear_layout(self.layout)
        clear_layout(self.banner_layout)

        s = self.session
        if s.flexural is None: s.run_flexural()

        ast_required = s.get_ast_for_design()
        is_doubly = not s.flexural.is_singly and s.doubly is not None

        # 1. Page Header
        subtitle = "Check reinforcement detailing as per IS 456:2000 (Clauses 26 & 27)\nVerify bar spacing, cover, development length and other detailing requirements."
        add_page_header(self.layout, "5. DETAILING CHECK", subtitle, export_callback=self.on_export)
        self.layout.addSpacing(16)

        dark = is_dark_mode()
        text_main = "#F8FAFC" if dark else "#0F172A"
        text_sub = "#94A3B8" if dark else "#475569"
        border_col = "#334155" if dark else "#E2E8F0"
        header_bg = "#0F172A" if dark else "#F8FAFC"
        title_color = "#60A5FA" if dark else "#1D4ED8"

        bar_selection, comp_selection = s.resolve_bars()
        s.run_shear(); s.run_serviceability(); s.run_two_zone_shear()
        bar_dia = bar_selection.bar_dia
        num_bars = bar_selection.num_bars
        ast_provided = bar_selection.ast_provided

        result = engine.get_detailing_check(
            b=s.b, D=s.D, d=s.flexural.d, ast=ast_required, ast_provided=ast_provided,
            bar_dia=bar_dia, num_bars=num_bars, effective_cover=s.effective_cover,
            fy=s.flexural.fy, concrete_grade=s.concrete_grade,
            stirrup_dia=8, singly_reinforced=s.flexural.is_singly,
            comp_bar_dia=comp_selection.bar_dia if comp_selection else None,
        )
        s.detailing = result

        # Top Section (2 Columns)
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        # --- LEFT COLUMN: TABLE CARD ---
        res_card, res_content = self._create_card("📋", "DETAILING CHECK RESULTS")
        
        grid = QGridLayout()
        grid.setSpacing(0)
        
        h_style = f"background-color: {header_bg}; color: {title_color}; font-weight: bold; font-size: 11px; padding: 10px; border-bottom: 1px solid {border_col};"
        c_style = f"color: {text_main}; font-size: 12px; padding: 8px 10px; border-bottom: 1px solid {border_col};"
        
        headers = ["Parameter", "Value", "Limit / Allowable", "Status"]
        for col, h_text in enumerate(headers):
            lbl = QLabel(h_text)
            lbl.setStyleSheet(h_style)
            lbl.setAlignment(Qt.AlignCenter if col > 0 else Qt.AlignLeft)
            grid.addWidget(lbl, 0, col)

        def add_grid_row(row, param, val, limit="-", status=None, is_safe=True):
            p_lbl = QLabel(param)
            p_lbl.setStyleSheet(c_style)
            grid.addWidget(p_lbl, row, 0)
            
            v_lbl = QLabel(val)
            v_lbl.setStyleSheet(c_style)
            v_lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(v_lbl, row, 1)
            
            l_lbl = QLabel(limit)
            l_lbl.setStyleSheet(c_style)
            l_lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(l_lbl, row, 2)
            
            if status:
                s_frame = QFrame()
                s_frame.setStyleSheet(f"border-bottom: 1px solid {border_col};")
                s_layout = QHBoxLayout(s_frame)
                s_layout.setContentsMargins(4, 4, 4, 4)
                s_layout.setAlignment(Qt.AlignCenter)
                
                bg_pill = "#10B981" if is_safe else "#EF4444"
                s_pill = QLabel(status)
                s_pill.setStyleSheet(f"background-color: {bg_pill}; color: white; font-weight: bold; font-size: 10px; padding: 4px 10px; border-radius: 4px;")
                s_layout.addWidget(s_pill)
                
                check_icon = QLabel("✓" if is_safe else "✗")
                check_icon.setStyleSheet(f"background-color: {bg_pill}; color: white; border-radius: 9px; font-weight: bold; font-size: 10px;")
                check_icon.setFixedSize(18, 18)
                check_icon.setAlignment(Qt.AlignCenter)
                s_layout.insertWidget(0, check_icon)
                
                grid.addWidget(s_frame, row, 3)
            else:
                empty = QLabel("-")
                empty.setStyleSheet(c_style)
                empty.setAlignment(Qt.AlignCenter)
                grid.addWidget(empty, row, 3)

        curr_row = 1
        add_grid_row(curr_row, "Tension bars provided", f"{num_bars}-φ{bar_dia:.0f} mm\n(As = {ast_provided:.1f} mm²)")
        curr_row += 1
        
        if comp_selection:
            add_grid_row(curr_row, "Compression bars provided", f"{comp_selection.num_bars}-φ{comp_selection.bar_dia:.0f} mm\n(Asc = {comp_selection.ast_provided:.1f} mm²)")
            curr_row += 1
            
        add_grid_row(curr_row, "Minimum Ast required\n(Cl. 26.5.1)", f"{ast_provided:.1f} mm²", f"≥ {result.ast_min_req:.1f} mm²", "OK" if result.min_reinf_ok else "FAIL", result.min_reinf_ok)
        curr_row += 1
        add_grid_row(curr_row, "Maximum Ast allowed\n(Cl. 26.5.1, 4% gross)", f"{ast_provided:.1f} mm²", f"≤ {result.ast_max_allowed:.1f} mm²", "OK" if result.max_reinf_ok else "FAIL", result.max_reinf_ok)
        curr_row += 1
        if result.xu_provided is not None:
            add_grid_row(curr_row, "Neutral axis of provided steel\n(xu ≤ xu,max, Cl. 38.1)", f"{result.xu_provided:.1f} mm", f"≤ {result.xu_max:.1f} mm", "OK" if result.balanced_ok else "FAIL", result.balanced_ok)
            curr_row += 1
        add_grid_row(curr_row, "Minimum clear spacing\n(Cl. 26.3.2)", f"{result.min_clear_spacing:.1f} mm")
        curr_row += 1
        add_grid_row(curr_row, "Actual clear spacing", f"{result.actual_spacing:.1f} mm" if result.actual_spacing else "N/A", f"≥ {result.min_clear_spacing:.1f} mm", "OK" if result.spacing_ok else "FAIL", result.spacing_ok)
        curr_row += 1
        add_grid_row(curr_row, "Clear cover to links\n(Cl. 26.4.1)", f"{result.cover_provided:.1f} mm", f"≥ {result.cover_required:.1f} mm", "OK" if result.cover_ok else "FAIL", result.cover_ok)
        curr_row += 1
        add_grid_row(curr_row, "Development length Ld\n(Cl. 26.2.1)", f"{result.development_length:.1f} mm")
        curr_row += 1
        add_grid_row(curr_row, "Effective cover provided", f"{s.effective_cover:.0f} mm")

        res_content.addLayout(grid)
        top_row.addWidget(res_card, stretch=5)

        # --- RIGHT COLUMN: INPUT, NOTE & STATUS ---
        right_col = QVBoxLayout()
        right_col.setSpacing(16)

        # 1. INPUT CARD (Moved here)
        in_card, in_content = self._create_card("⚙", "INPUT / PROVIDED DETAILS")
        
        override_checkbox = QCheckBox("Manually select bars (overrides auto-selection)")
        override_checkbox.setChecked(s.manual_bar_override)
        override_checkbox.setStyleSheet(f"color: {text_main}; font-size: 12px;")
        in_content.addWidget(override_checkbox)
        
        def on_toggle(checked):
            s.manual_bar_override = checked
            self.refresh()
        override_checkbox.stateChanged.connect(lambda state: on_toggle(state == Qt.Checked))

        if s.manual_bar_override:
            in_content.addSpacing(10)
            t_row = QHBoxLayout()
            t_lbl = QLabel("Tension bars:")
            t_lbl.setStyleSheet(f"color: {text_main}; font-size: 12px;")
            t_row.addWidget(t_lbl)
            
            tension_dia_combo = QComboBox()
            for d in engine.STANDARD_BAR_DIAS:
                tension_dia_combo.addItem(f"φ{d}", d)
            tension_dia_combo.setCurrentIndex(engine.STANDARD_BAR_DIAS.index(int(s.manual_bar_dia)) if int(s.manual_bar_dia) in engine.STANDARD_BAR_DIAS else 3)
            
            tension_count_combo = QComboBox()
            for n in range(2, 11):
                tension_count_combo.addItem(str(n), n)
            tension_count_combo.setCurrentIndex(max(0, int(s.manual_num_bars) - 2))
            
            t_row.addWidget(tension_dia_combo)
            x_lbl = QLabel("×")
            x_lbl.setStyleSheet(f"color: {text_main};")
            t_row.addWidget(x_lbl)
            t_row.addWidget(tension_count_combo)
            t_row.addStretch()
            in_content.addLayout(t_row)

            def on_tension_change():
                s.manual_bar_dia = float(tension_dia_combo.currentData())
                s.manual_num_bars = int(tension_count_combo.currentData())
                self.refresh()
            tension_dia_combo.currentIndexChanged.connect(lambda _: on_tension_change())
            tension_count_combo.currentIndexChanged.connect(lambda _: on_tension_change())

            if is_doubly:
                c_row = QHBoxLayout()
                c_lbl = QLabel("Comp. bars:")
                c_lbl.setStyleSheet(f"color: {text_main}; font-size: 12px;")
                c_row.addWidget(c_lbl)
                
                comp_dia_combo = QComboBox()
                for d in engine.STANDARD_BAR_DIAS:
                    comp_dia_combo.addItem(f"φ{d}", d)
                comp_dia_combo.setCurrentIndex(engine.STANDARD_BAR_DIAS.index(int(s.manual_comp_bar_dia)) if int(s.manual_comp_bar_dia) in engine.STANDARD_BAR_DIAS else 2)
                
                comp_count_combo = QComboBox()
                for n in range(2, 7):
                    comp_count_combo.addItem(str(n), n)
                comp_count_combo.setCurrentIndex(max(0, int(s.manual_comp_num_bars) - 2))
                
                c_row.addWidget(comp_dia_combo)
                c_x = QLabel("×")
                c_x.setStyleSheet(f"color: {text_main};")
                c_row.addWidget(c_x)
                c_row.addWidget(comp_count_combo)
                c_row.addStretch()
                in_content.addLayout(c_row)

                def on_comp_change():
                    s.manual_comp_bar_dia = float(comp_dia_combo.currentData())
                    s.manual_comp_num_bars = int(comp_count_combo.currentData())
                    self.refresh()
                comp_dia_combo.currentIndexChanged.connect(lambda _: on_comp_change())
                comp_count_combo.currentIndexChanged.connect(lambda _: on_comp_change())
                
        in_content.addStretch()
        right_col.addWidget(in_card)
        
        # 2. NOTE FRAME
        note_frame = QFrame()
        note_bg = "#EFF6FF" if not dark else "#1E3A8A"
        note_border = "#BFDBFE" if not dark else "#1E40AF"
        note_txt = "#1E40AF" if not dark else "#DBEAFE"
        note_frame.setStyleSheet(f"background-color: {note_bg}; border: 1px solid {note_border}; border-radius: 6px;")
        note_layout = QHBoxLayout(note_frame)
        note_layout.setContentsMargins(12, 12, 12, 12)
        
        info_icon = QLabel("ℹ")
        info_icon.setStyleSheet(f"color: white; background-color: {title_color}; border-radius: 10px; font-weight: bold; font-size: 14px;")
        info_icon.setFixedSize(20, 20)
        info_icon.setAlignment(Qt.AlignCenter)
        note_layout.addWidget(info_icon, alignment=Qt.AlignTop)
        
        note_lbl = QLabel(
            "<b>NOTE</b><br>"
            "• IS 456 Fig. 4 is a chart; the modification factor is a published curve-fit of it (see Serviceability).<br>"
            "• Bar spacing and cover follow Cl. 26.<br>"
            "• Development length is calculated as per Cl. 26.2.1.<br>"
            "• All checks are performed as per IS 456:2000."
        )
        note_lbl.setStyleSheet(f"color: {note_txt}; font-size: 11px; border: none;")
        note_lbl.setWordWrap(True)
        note_layout.addWidget(note_lbl)
        right_col.addWidget(note_frame)

        # 3. STATUS FRAME
        stat_frame = QFrame()
        bg_stat = "#064E3B" if dark else "#ECFDF5"
        border_stat = "#047857" if dark else "#A7F3D0"
        txt_stat = "#34D399" if dark else "#059669"
        if not result.all_passed:
            bg_stat, border_stat, txt_stat = ("#7F1D1D", "#991B1B", "#FCA5A5") if dark else ("#FEF2F2", "#FECACA", "#B91C1C")
            
        stat_frame.setStyleSheet(f"background-color: {bg_stat}; border: 1px solid {border_stat}; border-radius: 6px;")
        stat_layout = QHBoxLayout(stat_frame)
        stat_layout.setContentsMargins(12, 12, 12, 12)
        
        s_icon = QLabel("✓" if result.all_passed else "✗")
        s_icon.setStyleSheet(f"background-color: {txt_stat}; color: {'white' if not dark else '#0F172A'}; border-radius: 12px; font-weight: bold; font-size: 14px;")
        s_icon.setFixedSize(24, 24)
        s_icon.setAlignment(Qt.AlignCenter)
        stat_layout.addWidget(s_icon, alignment=Qt.AlignTop)
        
        msg_title = "DETAILING ADEQUATE - All checks passed" if result.all_passed else "DETAILING ISSUE - See failed checks"
        msg_sub = "Provided reinforcement satisfies the detailing requirements of IS 456:2000." if result.all_passed else "Adjust bar diameter, quantity, or beam dimensions."
        
        msg_layout = QVBoxLayout()
        msg_layout.setSpacing(2)
        m_t = QLabel(msg_title)
        m_t.setStyleSheet(f"color: {txt_stat}; font-weight: bold; font-size: 12px; border: none;")
        m_s = QLabel(msg_sub)
        m_s.setStyleSheet(f"color: {txt_stat}; font-size: 11px; border: none;")
        m_s.setWordWrap(True)
        msg_layout.addWidget(m_t)
        msg_layout.addWidget(m_s)
        
        stat_layout.addLayout(msg_layout)
        right_col.addWidget(stat_frame)
        
        right_col.addStretch()
        top_row.addLayout(right_col, stretch=3)
        
        self.layout.addLayout(top_row)
        
        # ENGINEERING DRAWINGS SECTION
        self.layout.addSpacing(16)
        
        drawings_header = QHBoxLayout()
        d_icon = QLabel("📐")
        d_icon.setStyleSheet(f"color: {title_color}; font-size: 16px; border: none;")
        d_title = QLabel("ENGINEERING DRAWINGS")
        d_title.setStyleSheet(f"color: {title_color}; font-weight: 800; font-size: 13px; border: none;")
        drawings_header.addWidget(d_icon)
        drawings_header.addWidget(d_title)
        drawings_header.addStretch()
        self.layout.addLayout(drawings_header)

        frame_bg = "#1E293B" if dark else "white"
        frame_border = "#334155" if dark else "#E2E8F0"
        
        def create_drawing_frame(icon_str, title_str, widget):
            frame = QFrame()
            frame.setAttribute(Qt.WA_StyledBackground, True)
            frame.setStyleSheet(f"background-color: {frame_bg}; border: 1px solid {frame_border}; border-radius: 8px;")
            l = QVBoxLayout(frame)
            l.setContentsMargins(12, 12, 12, 12)
            
            header = QHBoxLayout()
            header.setSpacing(8)
            i_lbl = QLabel(icon_str)
            i_lbl.setStyleSheet("color: #3B82F6; font-size: 14px; border: none;")
            t_lbl = QLabel(title_str)
            t_lbl.setStyleSheet(f"color: #3B82F6; font-weight: 800; font-size: 11px; border: none;")
            header.addWidget(i_lbl)
            header.addWidget(t_lbl)
            header.addStretch()
            l.addLayout(header)
            
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet(f"background-color: {frame_border}; border: none;")
            sep.setFixedHeight(1)
            l.addWidget(sep)
            
            l.addWidget(widget)
            return frame

        # Drawing Row 1
        row1 = QHBoxLayout()
        cross_widget = CrossSectionWidget(s.b, s.D, engine.clear_cover_to_link(s.effective_cover, bar_dia), 8, bar_dia, num_bars, comp_selection.bar_dia if comp_selection else None, comp_selection.num_bars if comp_selection else None)
        stirrup_widget = StirrupDetailWidget(s.b, s.D, engine.clear_cover_to_link(s.effective_cover, bar_dia), 8)
        row1.addWidget(create_drawing_frame("⊖", "CROSS SECTION (END VIEW)", cross_widget), stretch=1)
        row1.addWidget(create_drawing_frame("⧉", "STIRRUP DETAIL", stirrup_widget), stretch=1)
        self.layout.addLayout(row1)

        # Drawing Row 2
        if s.beam_type == "Simply Supported":
            two_zone = s.run_two_zone_shear()
            spacing_widget = StirrupSpacingWidget(s.span * 1000, two_zone.zone1_extent, two_zone.zone1_spacing, two_zone.zone2_spacing)
        else:
            spacing_widget = StirrupSpacingWidget(s.span * 1000, 0, s.shear.spacing, s.shear.spacing)
            zone_note = QLabel(f"Uniform stirrup spacing @ {s.shear.spacing:.0f} mm c/c throughout the span. Two-zone spacing is only available for Simply Supported beams.")
            zone_note.setWordWrap(True)
            zone_note.setStyleSheet(get_warning_note_style())
            self.layout.addWidget(zone_note)
            
        self.layout.addWidget(create_drawing_frame("⬌", "STIRRUP SPACING DETAIL (SIDE VIEW)", spacing_widget))

        # Drawing Row 3
        bars_widget = LongitudinalBarsWidget(s.span * 1000, bar_dia, num_bars, comp_selection.bar_dia if comp_selection else None, comp_selection.num_bars if comp_selection else None)
        self.layout.addWidget(create_drawing_frame("⇿", "LONGITUDINAL SECTION", bars_widget))

        self.layout.addStretch()
        
        # Bottom Navigation Banner
        banner = create_bottom_banner(
            self.on_back, self.on_next, 
            back_label="← Back: Serviceability",
            next_label="Next: Results & Export →",
            info_text="Note: Rebar detailing checks spacing, cover, and minimum requirements (Cl 26)."
        )
        self.banner_layout.addWidget(banner)

class SummaryPage(WizardPage):
    def __init__(self, session: DesignSession, on_back, on_export):
        super().__init__()
        self.session = session
        self.on_back = on_back
        self.on_export = on_export

    def _create_card(self, icon_str, title_str):
        dark = is_dark_mode()
        bg_card = "#1E293B" if dark else "#FFFFFF"
        border = "#334155" if dark else "#E2E8F0"
        title_color = "#60A5FA" if dark else "#1D4ED8"
        
        frame = QFrame()
        frame.setAttribute(Qt.WA_StyledBackground, True)
        frame.setStyleSheet(f"background-color: {bg_card}; border: 1px solid {border}; border-radius: 12px;")
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        header = QHBoxLayout()
        icon_lbl = QLabel(icon_str)
        icon_lbl.setStyleSheet(f"font-size: 18px; color: {title_color}; border: none;")
        title = QLabel(title_str)
        title.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {title_color}; border: none;")
        
        header.addWidget(icon_lbl)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {border}; border: none;")
        line.setFixedHeight(1)
        layout.addWidget(line)
        
        content_layout = QVBoxLayout()
        content_layout.setSpacing(12)
        layout.addLayout(content_layout)
        
        return frame, content_layout

    def refresh(self):
        clear_layout(self.layout)
        clear_layout(self.banner_layout)
        
        # Note: We omit the 'export_callback' argument to remove the top green button
        add_page_header(self.layout, "6. RESULTS & EXPORT", "Summary of design results for all checks as per IS 456:2000.")
        self.layout.addSpacing(16)

        s = self.session
        try:
            flex = s.flexural or s.run_flexural()
            shear = s.shear or s.run_shear()
            service = s.serviceability or s.run_serviceability()
        except DoublyReinforcedError as e:
            note = QLabel(f"⚠ Cannot generate summary: {e}")
            note.setWordWrap(True)
            note.setStyleSheet(get_status_style(False))
            self.layout.addWidget(note)
            self.layout.addStretch()
            banner = create_bottom_banner(self.on_back, None, info_text="Error: Cannot proceed further.")
            self.banner_layout.addWidget(banner)
            return
            
        detail = s.detailing

        dark = is_dark_mode()
        text_main = "#F8FAFC" if dark else "#0F172A"
        text_sub = "#94A3B8" if dark else "#475569"
        border_col = "#334155" if dark else "#E2E8F0"
        header_bg = "#0F172A" if dark else "#F8FAFC"
        title_color = "#60A5FA" if dark else "#1D4ED8"
        bg_card = "#1E293B" if dark else "#FFFFFF"
        row_alt = "#172554" if dark else "#F8FAFC"

        # 1. DESIGN RESULTS SUMMARY TABLE
        res_card, res_content = self._create_card("⊞", "DESIGN RESULTS SUMMARY")
        grid = QGridLayout()
        grid.setSpacing(0)
        
        h_style = f"background-color: {header_bg}; color: {text_main}; font-weight: bold; font-size: 12px; padding: 12px 10px; border-bottom: 1px solid {border_col};"
        c_style = f"color: {text_sub}; font-size: 12px; padding: 14px 10px; border-bottom: 1px solid {border_col};"
        
        # Removed the empty "" header for the icon column
        headers = ["Check", "Key Value", "Limit / Requirement", "Status"]
        for col, h_text in enumerate(headers):
            lbl = QLabel(h_text)
            lbl.setStyleSheet(h_style)
            lbl.setAlignment(Qt.AlignCenter if col > 0 else Qt.AlignLeft)
            grid.addWidget(lbl, 0, col)

        # Removed the 'icon' parameter and shifted columns from 1, 2, 3, 4 to 0, 1, 2, 3
        def add_grid_row(row, check, val, limit, is_safe):
            c_lbl = QLabel(check)
            c_lbl.setStyleSheet(c_style)
            grid.addWidget(c_lbl, row, 0)
            
            v_lbl = QLabel(val)
            v_lbl.setStyleSheet(c_style)
            v_lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(v_lbl, row, 1)
            
            l_lbl = QLabel(limit)
            l_lbl.setStyleSheet(c_style)
            l_lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(l_lbl, row, 2)
            
            s_frame = QFrame()
            s_frame.setStyleSheet(f"border-bottom: 1px solid {border_col}; background: transparent;")
            s_layout = QHBoxLayout(s_frame)
            s_layout.setContentsMargins(10, 10, 10, 10)
            s_layout.setAlignment(Qt.AlignCenter)
            
            bg_pill = "#10B981" if is_safe else "#EF4444"
            s_pill = QLabel("SAFE" if is_safe else "FAIL")
            s_pill.setStyleSheet(f"background-color: {bg_pill}; color: white; font-weight: bold; font-size: 10px; padding: 4px 12px; border-radius: 4px;")
            s_layout.addWidget(s_pill)
            
            check_icon = QLabel("✓" if is_safe else "✗")
            check_icon.setStyleSheet(f"background-color: {bg_pill}; color: white; border-radius: 9px; font-weight: bold; font-size: 11px;")
            check_icon.setFixedSize(18, 18)
            check_icon.setAlignment(Qt.AlignCenter)
            s_layout.insertWidget(0, check_icon)
            
            grid.addWidget(s_frame, row, 3)

        flex_ok = flex.is_singly or (s.doubly is not None and s.doubly.safe)
        
        # Removed the icon string arguments ("∩", "⇅", "〰", "📋")
        add_grid_row(1, "Flexural Design", f"Mu = {s.mu:.1f} kN·m", f"Mu ≤ {flex.m_lim:.2f} kN·m (Mlim)", flex_ok)
        add_grid_row(2, "Shear Design", f"τv = {shear.tau_v:.3f} N/mm²", f"τv ≤ τc,max ({shear.tau_c_max:.2f} N/mm²)", shear.safe)
        add_grid_row(3, "Serviceability", f"L/d = {service.actual_ratio:.2f}", f"Actual ≤ Allowable ({service.allowable_ratio:.2f})", service.safe)
        add_grid_row(4, "Detailing", "Provided as per Cl. 26", "Min/max steel, xu ≤ xu,max, spacing, cover", detail.all_passed if detail else False)

        res_content.addLayout(grid)
        self.layout.addWidget(res_card)

        # 2. OVERALL STATUS BANNER
        overall_safe = flex_ok and shear.safe and service.safe and (detail.all_passed if detail else False)
        
        stat_frame = QFrame()
        bg_stat = "#064E3B" if dark else "#ECFDF5"
        border_stat = "#047857" if dark else "#A7F3D0"
        txt_stat = "#34D399" if dark else "#059669"
        if not overall_safe:
            bg_stat, border_stat, txt_stat = ("#7F1D1D", "#991B1B", "#FCA5A5") if dark else ("#FEF2F2", "#FECACA", "#B91C1C")
            
        stat_frame.setStyleSheet(f"background-color: {bg_stat}; border: 1px solid {border_stat}; border-radius: 6px;")
        stat_layout = QHBoxLayout(stat_frame)
        stat_layout.setContentsMargins(16, 16, 16, 16)
        
        s_icon = QLabel("✓" if overall_safe else "✗")
        s_icon.setStyleSheet(f"background-color: {txt_stat}; color: {'white' if not dark else '#0F172A'}; border-radius: 16px; font-weight: bold; font-size: 18px;")
        s_icon.setFixedSize(32, 32)
        s_icon.setAlignment(Qt.AlignCenter)
        stat_layout.addWidget(s_icon)
        
        msg_layout = QVBoxLayout()
        msg_layout.setSpacing(2)
        m_t = QLabel("OVERALL STATUS: SAFE" if overall_safe else "OVERALL STATUS: UNSAFE")
        m_t.setStyleSheet(f"color: {txt_stat}; font-weight: 800; font-size: 14px; border: none;")
        m_s = QLabel("Design satisfies all requirements as per IS 456:2000." if overall_safe else "Design fails one or more checks. Review individual tabs.")
        m_s.setStyleSheet(f"color: {txt_stat}; font-size: 12px; border: none;")
        msg_layout.addWidget(m_t)
        msg_layout.addWidget(m_s)
        
        stat_layout.addLayout(msg_layout)
        stat_layout.addStretch()
        self.layout.addWidget(stat_frame)
        
        # 3. EXPORT ROW
        export_row = QHBoxLayout()
        export_row.setSpacing(16)
        
        def create_export_card(icon, title, desc, btn_text, callback, is_primary=False):
            card = QFrame()
            card.setStyleSheet(f"background-color: {bg_card}; border: 1px solid {border_col}; border-radius: 8px;")
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(16, 16, 16, 16)
            card_layout.setSpacing(16)
            
            i_lbl = QLabel(icon)
            i_lbl.setStyleSheet(f"color: {title_color}; font-size: 24px; border: none;")
            i_lbl.setAlignment(Qt.AlignTop | Qt.AlignCenter)
            card_layout.addWidget(i_lbl)
            
            text_layout = QVBoxLayout()
            text_layout.setSpacing(4)
            t_lbl = QLabel(title)
            t_lbl.setStyleSheet(f"color: {title_color}; font-weight: bold; font-size: 11px; border: none;")
            d_lbl = QLabel(desc)
            d_lbl.setStyleSheet(f"color: {text_sub}; font-size: 11px; border: none;")
            d_lbl.setWordWrap(True)
            text_layout.addWidget(t_lbl)
            text_layout.addWidget(d_lbl)
            text_layout.addStretch()
            card_layout.addLayout(text_layout, stretch=1)
            
            btn = QPushButton(btn_text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(140, 32)
            btn_bg = "#EFF6FF" if not dark else "#1E3A8A"
            
            if is_primary:
                btn.setStyleSheet(f"QPushButton {{ background-color: {bg_card}; color: {title_color}; border: 1px solid {title_color}; border-radius: 6px; font-size: 11px; font-weight: bold; }} QPushButton:hover {{ background-color: {btn_bg}; }}")
            else:
                btn.setStyleSheet(f"QPushButton {{ background-color: {bg_card}; color: {title_color}; border: 1px solid {border_col}; border-radius: 6px; font-size: 11px; font-weight: bold; }} QPushButton:hover {{ background-color: {row_alt}; }}")
                
            btn.clicked.connect(callback)
            card_layout.addWidget(btn, alignment=Qt.AlignVCenter)
            return card

        def show_success_dialog(title, text):
            msg = QMessageBox(self)
            msg.setWindowTitle(title)
            msg.setText(text)
            msg.setIcon(QMessageBox.Information)
            msg.setStyleSheet("""
                QMessageBox {
                    background-color: #ffffff;
                }
                QMessageBox QLabel {
                    color: #0f172a;
                    font-size: 13px;
                    font-weight: 600;
                    background-color: transparent;
                }
                QMessageBox QPushButton {
                    background-color: #2563eb;
                    color: #ffffff;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 20px;
                    font-weight: bold;
                    min-width: 65px;
                }
                QMessageBox QPushButton:hover {
                    background-color: #1d4ed8;
                }
            """)
            msg.exec_()

        def handle_export_excel():
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Save Excel Data", "RCC_Beam_Data.xlsx", "Excel Files (*.xlsx)"
            )
            if filepath:
                try:
                    export_to_excel(filepath, self.session)
                    show_success_dialog("Success", "Excel file exported successfully.")
                except PermissionError:
                    QMessageBox.warning(self, "Permission Denied", "The Excel file is open in another program. Close it and try again.")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to export Excel:\n{str(e)}")

        def handle_export_dxf():
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Save CAD Drawing", "RCC_Beam_Drawing.dxf", "DXF Drawing Files (*.dxf)"
            )
            if filepath:
                try:
                    export_to_dxf(filepath, self.session)
                    show_success_dialog("Success", "CAD drawing exported successfully.")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to export drawing:\n{str(e)}")
        
        export_row.addWidget(create_export_card(
            "📄", "EXPORT REPORT", "Generate detailed calculation report with drawings.", 
            "📄 Export PDF Report", self.on_export, is_primary=True
        ))
        
        export_row.addWidget(create_export_card(
            "🖼", "EXPORT DRAWINGS", "Download engineering drawings (DXF).", 
            "📥 Download Drawings", handle_export_dxf
        ))
        
        export_row.addWidget(create_export_card(
            "▦", "EXPORT DATA", "Download design results and input data in Excel format.", 
            "▦ Download Excel", handle_export_excel
        ))
        
        self.layout.addLayout(export_row)
        
        # 4. NOTE SECTION
        note_frame = QFrame()
        note_bg = "#EFF6FF" if not dark else "#1E3A8A"
        note_border = "#BFDBFE" if not dark else "#1E40AF"
        note_txt = "#1E40AF" if not dark else "#DBEAFE"
        note_frame.setStyleSheet(f"background-color: {note_bg}; border: 1px solid {note_border}; border-radius: 6px;")
        note_layout = QHBoxLayout(note_frame)
        note_layout.setContentsMargins(16, 12, 16, 12)
        
        info_icon = QLabel("ℹ")
        info_icon.setStyleSheet(f"color: white; background-color: {title_color}; border-radius: 10px; font-weight: bold; font-size: 14px;")
        info_icon.setFixedSize(20, 20)
        info_icon.setAlignment(Qt.AlignCenter)
        note_layout.addWidget(info_icon, alignment=Qt.AlignTop)
        
        note_lbl = QLabel(
            "<b>Note</b><br>"
            "• All design checks are performed as per IS 456:2000 (Clauses 23, 26, 27, 38 & 40).<br>"
            "• Refer individual design pages for detailed calculations.<br>"
            "• Drawings show typical reinforcement arrangement and may be modified as per project requirements."
        )
        note_lbl.setStyleSheet(f"color: {note_txt}; font-size: 11px; border: none; line-height: 1.5;")
        note_lbl.setWordWrap(True)
        note_layout.addWidget(note_lbl)
        self.layout.addWidget(note_frame)

        self.layout.addStretch()
        
        # 5. BOTTOM BANNER
        banner = create_bottom_banner(
            self.on_back, lambda: self.window()._go_home(), 
            back_label="← Back: Detailing Check",
            next_label="Finish →"
        )
        self.banner_layout.addWidget(banner)

class RadioButtonIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.is_selected = False

    def setSelected(self, selected):
        self.is_selected = selected
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(3, 3, -3, -3)
        dark = QApplication.instance().property("is_dark")
        active_color = QColor("#3B82F6") if dark else QColor("#2563EB")
        inactive_color = QColor("#475569") if dark else QColor("#CBD5E1")
        
        if self.is_selected:
            painter.setPen(QPen(active_color, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect)
            painter.setPen(Qt.NoPen)
            painter.setBrush(active_color)
            painter.drawEllipse(rect.center(), 4, 4)
        else:
            painter.setPen(QPen(inactive_color, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect)

class BeamCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, beam_id, title, desc, image_filename, typical_uses):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.beam_id = beam_id
        self.setObjectName("AppCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(290, 260)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(170, 75)
        
        pixmap = QPixmap(f"assets/{image_filename}")
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(160, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)
        else:
            self.image_label.setText("[Image missing]")
            self.image_label.setStyleSheet("color: #94A3B8; font-size: 10px; background: transparent;")

        top_layout.addStretch(1)
        top_layout.addWidget(self.image_label, stretch=2, alignment=Qt.AlignCenter)
        
        self.radio_indicator = RadioButtonIndicator()
        top_layout.addWidget(self.radio_indicator, alignment=Qt.AlignTop | Qt.AlignRight)
        
        layout.addLayout(top_layout)
        
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("CardTitle")
        self.lbl_title.setWordWrap(True)
        layout.addWidget(self.lbl_title)
        
        self.lbl_desc = QLabel(desc)
        self.lbl_desc.setObjectName("CardDesc")
        self.lbl_desc.setWordWrap(True)
        layout.addWidget(self.lbl_desc)
        
        layout.addSpacing(6)
        
        self.uses_box = QFrame()
        self.uses_box.setAttribute(Qt.WA_StyledBackground, True)
        self.uses_box.setObjectName("TypicalUsesBox")
        self.uses_box.setProperty("selected", False)
        
        uses_layout = QVBoxLayout(self.uses_box)
        uses_layout.setContentsMargins(12, 10, 12, 10)
        uses_layout.setSpacing(4)
        
        lbl_uses_title = QLabel("Typical uses:")
        lbl_uses_title.setObjectName("TypicalUsesTitle")
        uses_layout.addWidget(lbl_uses_title)
        
        for use in typical_uses:
            u_lbl = QLabel(f"• {use}")
            u_lbl.setObjectName("TypicalUsesText")
            uses_layout.addWidget(u_lbl)
            
        uses_layout.addStretch()
        layout.addWidget(self.uses_box)
        layout.addStretch()

    def setSelected(self, is_selected):
        self.setProperty("selected", is_selected)
        self.lbl_title.setProperty("selected", is_selected)
        self.radio_indicator.setSelected(is_selected)
        
        self.uses_box.setProperty("selected", is_selected)
        self.uses_box.style().unpolish(self.uses_box)
        self.uses_box.style().polish(self.uses_box)
        
        self.style().unpolish(self)
        self.style().polish(self)
        self.lbl_title.style().unpolish(self.lbl_title)
        self.lbl_title.style().polish(self.lbl_title)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.beam_id)

class BeamTypeSelectionPage(QWidget):
    def __init__(self, session: DesignSession, on_back, on_continue):
        super().__init__()
        self.session = session
        self.on_back = on_back
        self.on_continue = on_continue
        self.cards = {}
        self.initUI()

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 30)
        main_layout.setAlignment(Qt.AlignTop)

        header_layout = QHBoxLayout()
        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)
        
        title = QLabel("Select a Beam Type")
        title.setObjectName("SelectionHeading")
        title_layout.addWidget(title)
        
        subtitle = QLabel("Choose the type of beam to get started with your design.")
        subtitle.setObjectName("SelectionSubHeading")
        title_layout.addWidget(subtitle)
        
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        
        badge = QLabel("📖 IS 456:2000 (LSD)")
        badge.setObjectName("CodeBadge")
        header_layout.addWidget(badge, alignment=Qt.AlignTop)
        
        main_layout.addLayout(header_layout)
        main_layout.addSpacing(30)

        grid = QGridLayout()
        grid.setSpacing(24)
        
        beam_types = [
            ("Simply Supported", "SIMPLY SUPPORTED BEAM", "Beam supported at both ends and free to rotate.", "Simply Supported Beam.png", ["Building floor beams", "Bridge girders (simple span)"]),
            ("Cantilever", "CANTILEVER BEAM", "Beam fixed at one end and free at the other end.", "Cantilever Beam.png", ["Balconies and canopies", "Retaining structures"]),
            ("Continuous", "CONTINUOUS BEAM", "Beam continuous over more than two supports.", "Continuous Beam.png", ["Multi-span building beams", "Bridge continuous girders"]),
            ("Fixed", "FIXED BEAM", "Beam fixed at both ends and restricted from rotation.", "Fixed Beam.png", ["Rigid frame members", "Industrial structures"]),
            ("Custom", "CUSTOM BEAM", "Define your own support conditions, multi-span and loading.", "Custom Beam.png", ["Special structures", "Complex loading conditions"])
        ]

        row, col = 0, 0
        for name, b_title, b_desc, img_file, uses in beam_types:
            card = BeamCard(name, b_title, b_desc, img_file, uses)
            card.clicked.connect(self._select)
            self.cards[name] = card
            grid.addWidget(card, row, col)
            col += 1
            if col > 2: 
                col = 0
                row += 1

        main_layout.addLayout(grid)
        main_layout.addStretch()

        self.bottom_bar = QFrame()
        self.bottom_bar.setAttribute(Qt.WA_StyledBackground, True)
        self.bottom_bar.setObjectName("BottomBanner")
        self.bottom_bar.setFixedHeight(60)
        
        bottom_layout = QHBoxLayout(self.bottom_bar)
        bottom_layout.setContentsMargins(20, 0, 20, 0)
        bottom_layout.setSpacing(12)
        
        info_icon = QLabel("ℹ")
        info_icon.setStyleSheet("color: #3B82F6; font-weight: bold; font-size: 14px; background: transparent;")
        bottom_layout.addWidget(info_icon)
        
        self.info_banner = QLabel()
        self.info_banner.setObjectName("BottomBannerText")
        bottom_layout.addWidget(self.info_banner)
        
        self.custom_ratio_row = QWidget()
        custom_row_layout = QHBoxLayout(self.custom_ratio_row)
        custom_row_layout.setContentsMargins(0, 0, 0, 0)
        custom_row_layout.setSpacing(10)
        
        custom_label = QLabel("Your basic span/depth ratio:")
        custom_label.setObjectName("BottomBannerText")
        self.custom_ratio_input = QLineEdit(str(self.session.custom_basic_ratio))
        self.custom_ratio_input.setFixedWidth(70)
        
        custom_row_layout.addWidget(custom_label)
        custom_row_layout.addWidget(self.custom_ratio_input)
        self.custom_ratio_row.setVisible(False)
        bottom_layout.addWidget(self.custom_ratio_row)
        
        bottom_layout.addStretch()
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("BannerBtnCancel")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.on_back)
        
        btn_next = QPushButton("Next →")
        btn_next.setObjectName("BannerBtnNext")
        btn_next.setFixedHeight(36)
        btn_next.setCursor(Qt.PointingHandCursor)
        btn_next.clicked.connect(self._handle_continue)
        
        bottom_layout.addWidget(btn_cancel)
        bottom_layout.addWidget(btn_next)
        
        main_layout.addWidget(self.bottom_bar)
        self._select(self.session.beam_type)

    def refresh(self):
        pass

    def _select(self, name):
        self.session.beam_type = name
        for card_name, card in self.cards.items():
            card.setSelected(card_name == name)

        notes = {
            "Simply Supported": "Basic span/depth ratio = 20 (Cl. 23.2). Two-zone stirrup spacing available (assumes UDL loading).",
            "Cantilever": "Basic span/depth ratio = 7 (Cl. 23.2). Single-zone stirrup spacing applies.",
            "Continuous": "Basic span/depth ratio = 26 (Cl. 23.2). Single-zone stirrup spacing applies.",
            "Fixed": "Basic ratio uses Continuous value (26) as standard judgment. Single-zone stirrup spacing applies.",
            "Custom": "Enter your own basic span/depth ratio — IS 456 Cl. 23.2 does not cover arbitrary support conditions.",
        }
        self.info_banner.setText(notes.get(name, ""))
        self.custom_ratio_row.setVisible(name == "Custom")

    def _handle_continue(self):
        if self.session.beam_type == "Custom":
            try:
                ratio = float(self.custom_ratio_input.text())
                if ratio <= 0:
                    raise ValueError
                self.session.custom_basic_ratio = ratio
            except ValueError:
                QMessageBox.warning(
                    self, "Invalid ratio",
                    "Please enter a positive number for the custom span/depth ratio."
                )
                return
        self.on_continue()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        pixmap = QPixmap("assets/selection_bg12.jpeg") 
        if not pixmap.isNull():
            # Scale to completely cover the widget width and height
            scaled = pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            # Center the expanded image
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            
        dark = QApplication.instance().property("is_dark")
        # Reduced opacity (from 215 down to 140 in light mode) to increase brightness
        wash_color = QColor(15, 23, 42, 200) if dark else QColor(255, 255, 255, 140)
        painter.fillRect(self.rect(), wash_color)

class ZoomableImageViewer(QGraphicsView):
    def __init__(self, image_path):
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setStyleSheet("background: transparent; border: none;")
        
        self.pixmap = QPixmap(image_path)
        if not self.pixmap.isNull():
            self.pixmap_item = self.scene.addPixmap(self.pixmap)
        else:
            self.scene.addText(f"[Image missing: {image_path}]")
            
    def showEvent(self, event):
        super().showEvent(event)
        if not self.pixmap.isNull():
            self.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)
            
    def zoom_in(self):
        self.scale(1.2, 1.2)
        
    def zoom_out(self):
        self.scale(1 / 1.2, 1 / 1.2)
        
    def reset_zoom(self):
        if not self.pixmap.isNull():
            self.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)
        
    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()

class ZoomableTab(QWidget):
    def __init__(self, image_path):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.toolbar = QHBoxLayout()
        self.toolbar.setContentsMargins(10, 10, 10, 10)
        
        self.btn_in = QPushButton("Zoom In (+)")
        self.btn_out = QPushButton("Zoom Out (-)")
        self.btn_reset = QPushButton("Reset Fit")
        
        for btn in (self.btn_in, self.btn_out, self.btn_reset):
            btn.setObjectName("NavBackBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(110, 30)
            
        self.toolbar.addStretch()
        self.toolbar.addWidget(self.btn_in)
        self.toolbar.addWidget(self.btn_out)
        self.toolbar.addWidget(self.btn_reset)
        self.toolbar.addStretch()
        
        self.viewer = ZoomableImageViewer(image_path)
        self.btn_in.clicked.connect(self.viewer.zoom_in)
        self.btn_out.clicked.connect(self.viewer.zoom_out)
        self.btn_reset.clicked.connect(self.viewer.reset_zoom)
        
        self.layout.addLayout(self.toolbar)
        self.layout.addWidget(self.viewer)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        QApplication.instance().setProperty("is_dark", False)
        
        self.setWindowTitle("RCC Beam Designer — IS 456:2000")
        self.resize(1300, 780)
        self.session = DesignSession()

        central_widget = QWidget()
        central_widget.setObjectName("CentralWidget")
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(central_widget)

        self.content_stack = QStackedWidget()
        self.content_stack.setStyleSheet("background: transparent;")
        root_layout.addWidget(self.content_stack)

        self.home_page = HomePage(
            on_new=self._go_beam_type, 
            on_open=self._open_project,
            on_recent=self._open_recent_project
        )
        self.content_stack.addWidget(self.home_page)

        
        self.beam_type_page = BeamTypeSelectionPage(self.session, on_back=self._go_home, on_continue=self._enter_wizard)
        self.content_stack.addWidget(self.beam_type_page)


        self.beam_input_page = BeamInputPage(self.session, on_back=lambda: self.content_stack.setCurrentIndex(1), on_next=lambda: self.go_to_step(1))
        self.flexural_page = FlexuralPage(self.session, on_back=lambda: self.go_to_step(0), on_next=lambda: self.go_to_step(2), on_export=lambda: self._export_pdf(2))
        self.shear_page = ShearPage(self.session, on_back=lambda: self.go_to_step(1), on_next=lambda: self.go_to_step(3), on_export=lambda: self._export_pdf(3))
        self.serviceability_page = ServiceabilityPage(self.session, on_back=lambda: self.go_to_step(2), on_next=lambda: self.go_to_step(4), on_export=lambda: self._export_pdf(4))
        self.detailing_page = DetailingPage(self.session, on_back=lambda: self.go_to_step(3), on_next=lambda: self.go_to_step(5), on_export=lambda: self._export_pdf(5))
        self.summary_page = SummaryPage(self.session, on_back=lambda: self.go_to_step(4), on_export=lambda: self._export_pdf(6))

        self.wizard_pages = [
            self.beam_input_page,
            self.flexural_page,
            self.shear_page,
            self.serviceability_page,
            self.detailing_page,
            self.summary_page
        ]
        for p in self.wizard_pages:
            self.content_stack.addWidget(p)

        self.current_file_path = None
        self._build_menu()
        self.apply_theme()
        self._go_home()

    def _go_home(self):
        self.home_page.refresh_recent()
        self.content_stack.setCurrentIndex(0)
        self.setWindowTitle("RCC Beam Designer — IS 456:2000")

    def _go_beam_type(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 
            "Create New Project", 
            "New_Beam_Project.rccbeam", 
            "RCC Beam Project (*.rccbeam);;JSON files (*.json)"
        )
        if not path:
            return 
        if not (path.endswith(".rccbeam") or path.endswith(".json")): 
            path += ".rccbeam"
            
        self.session = DesignSession()
        try:
            with open(path, "w") as f:
                json.dump(self.session.to_dict(), f, indent=2)
            self.current_file_path = path
            self._add_to_recent(path)
            self.setWindowTitle(f"RCC Beam Designer — IS 456:2000 — {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Create Failed", f"Could not create project file:\n{e}")
            return

        self._rebuild_after_load()
        self.content_stack.setCurrentIndex(1)

    def _export_pdf(self, step):
        s = self.session
        if step >= 2 and not getattr(s, 'flexural', None):
            QMessageBox.warning(self, "Incomplete", "Run Flexural design first before generating.")
            return
        if step >= 3 and not getattr(s, 'shear', None):
            QMessageBox.warning(self, "Incomplete", "Run Shear design first before generating.")
            return
        if step >= 4 and not getattr(s, 'serviceability', None):
            QMessageBox.warning(self, "Incomplete", "Run Serviceability check first before generating.")
            return
        if step >= 5 and not getattr(s, 'detailing', None):
            QMessageBox.warning(self, "Incomplete", "Run Detailing design first before generating.")
            return
            
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF Report", "RCC_Beam_Report.pdf", "PDF Files (*.pdf)")
        if not path: return
            
        try:
            generate_pdf_report(path, s, max_step=step, is_dark=is_dark_mode())
            msg = QMessageBox(self)
            msg.setWindowTitle("Export Successful")
            msg.setText("✓ PDF REPORT GENERATED SUCCESSFULLY")
            msg.setInformativeText(f"File saved to:\n{path}")
            open_btn = msg.addButton("Open PDF", QMessageBox.ActionRole)
            msg.addButton(QMessageBox.Ok)
            msg.exec_()
            
            if msg.clickedButton() == open_btn:
                if sys.platform == "win32": os.startfile(path)
                elif sys.platform == "darwin": subprocess.call(["open", path])
                else: subprocess.call(["xdg-open", path])
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"An error occurred while generating the PDF:\n{str(e)}")

    def toggle_theme(self):
        app = QApplication.instance()
        is_dark = app.property("is_dark")
        app.setProperty("is_dark", not is_dark)
        self.apply_theme()

    def apply_theme(self):
        dark = QApplication.instance().property("is_dark")
        
        bg_main = "#0F172A" if dark else "#F8FAFF" 
        bg_card = "#1E293B" if dark else "#FFFFFF"
        text_main = "#0F172A" if not dark else "#F8FAFC"
        border = "#334155" if dark else "#CBD5E1"
        row_alt = "#172554" if dark else "#F1F5F9"
        input_bg = "#0F172A" if dark else "#F9FAFB"
        input_focus = "#3B82F6" if dark else "#1D4ED8"
        
        # --- QUICK ACTION COLORED BOXES ---
        ac_blue_bg = "#DBEAFE" if not dark else "#1E3A8A"
        ac_blue_ic = "#93C5FD" if not dark else "#1E40AF"
        
        ac_green_bg = "#FEF3C7" if not dark else "#451A03"
        ac_green_ic = "#FCD34D" if not dark else "#78350F"
        
        ac_purple_bg = "#FCE7F3" if not dark else "#831843"
        ac_purple_ic = "#F9A8D4" if not dark else "#9D174D"
        
        pill_bg = "#EFF6FF" if not dark else "#1E3A8A"
        pill_txt = "#2563EB" if not dark else "#93C5FD"
        
        ac_blue_icon = "#2563EB" if not dark else "#3B82F6"
        ac_green_icon = "#D97706" if not dark else "#F59E0B"
        ac_purple_icon = "#EC4899" if not dark else "#F472B6"
        
        section_yellow_bg = "#FEF3C7" if not dark else "#451A03"
        section_purple_bg = "#EDE9FE" if not dark else "#4C1D95"
        
        ac_title_color = "#2563EB" if not dark else "#60A5FA"
        ac_desc_color = "#64748B" if not dark else "#94A3B8"

        # --- BUTTON THEME COLORS ---
        cancel_bg = '#1E293B' if dark else '#FFFFFF'
        cancel_fg = '#F8FAFC' if dark else '#0F172A'
        cancel_hover = '#172554' if dark else '#F1F5F9'
        
        next_bg = '#000000' if dark else '#FFFFFF'
        next_fg = '#FFFFFF' if dark else '#000000'
        next_hover = '#1A1A1A' if dark else '#F1F5F9'
        
        style = f"""
            QMainWindow, QWidget#CentralWidget {{ 
                background: {bg_main}; 
            }}
            QWidget {{ font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif; }}
            
            QMenuBar {{ background: {bg_main}; color: {text_main}; border-bottom: 1px solid {border}; }}
            QMenuBar::item {{ background: transparent; padding: 4px 10px; font-weight: bold; }}
            QMenuBar::item:selected {{ background: {row_alt}; border-radius: 4px; }}
            
            QMenu {{ background: {bg_card}; color: {text_main}; border: 1px solid {border}; padding: 4px; }}
            QMenu::item {{ padding: 6px 24px; border-radius: 4px; font-weight: bold; }}
            QMenu::item:selected {{ background: {input_focus}; color: white; }}
            
            QLabel#TopLogoBox {{ background-color: #1D4ED8; color: white; font-weight: 900; font-size: 16px; border-radius: 6px; }}
            QLabel#TopHeaderTitle {{ font-size: 13px; font-weight: 900; color: {text_main}; background: transparent; }}
            QLabel#TopHeaderSub {{ font-size: 11px; font-weight: 700; color: #64748B; background: transparent; }}
            QLabel#TopUtilityIcon {{ font-size: 16px; font-weight: bold; color: #475569; background: transparent; }}
            QLabel#ProfileBadgeRK {{ background-color: #2563EB; color: white; font-size: 12px; font-weight: 900; border-radius: 16px; }}
            
            QScrollArea#HomeScrollArea, QWidget#HomeViewport, QWidget#HomeContent {{ background: transparent; border: none; }}
            
            QLabel#HomeWelcome {{ font-size: 18px; font-weight: 900; color: {text_main}; background: transparent; }}
            QLabel#HomeMainTitle {{ font-size: 38px; font-weight: 900; color: #1D4ED8; letter-spacing: -1px; background: transparent; margin-top: -5px; }}
            QLabel#HomeDescBold {{ font-size: 14px; font-weight: 900; color: {text_main}; background: transparent; }}
            QLabel#HomeDescNorm {{ font-size: 13px; font-weight: 800; color: {text_main}; background: transparent; }}
            
            QFrame#FeaturePill {{ background: transparent; border-radius: 12px; }}
            QWidget#PillIconWrapper {{ border-radius: 18px; }}
            QLabel#PillIcon {{ font-size: 15px; background: transparent; color: white; }}
            QLabel#PillTitle {{ font-size: 12px; font-weight: 900; color: {text_main}; background: transparent; }}
            QLabel#PillSub {{ font-size: 11px; font-weight: 800; color: {text_main}; background: transparent; }}
            
            QLabel#ActionCardTitle {{ font-size: 14px; font-weight: 900; color: {ac_title_color}; background: transparent; }}
            QLabel#ActionCardDesc {{ font-size: 12px; font-weight: 600; color: {ac_desc_color}; background: transparent; }}
            
            QFrame#ActionCard_blue {{ background-color: {ac_blue_bg}; border-radius: 24px; border: 1px solid {ac_blue_ic}; }}
            QWidget#ActionIconWrapper_blue {{ background-color: {ac_blue_icon}; border-radius: 24px; }}
            QLabel#ActionIcon_blue {{ color: white; font-size: 20px; font-weight: bold; background: transparent; }}
            QWidget#ActionArrowCircle_blue {{ background-color: {ac_blue_icon}; border-radius: 16px; }}
            QLabel#ActionArrow_blue {{ color: white; font-size: 16px; font-weight: bold; background: transparent; }}
            
            QFrame#ActionCard_green {{ background-color: {ac_green_bg}; border-radius: 24px; border: 1px solid {ac_green_ic}; }}
            QWidget#ActionIconWrapper_green {{ background-color: {ac_green_icon}; border-radius: 24px; }}
            QLabel#ActionIcon_green {{ color: white; font-size: 20px; font-weight: bold; background: transparent; }}
            QWidget#ActionArrowCircle_green {{ background-color: {ac_green_icon}; border-radius: 16px; }}
            QLabel#ActionArrow_green {{ color: white; font-size: 16px; font-weight: bold; background: transparent; }}
            
            QFrame#ActionCard_purple {{ background-color: {ac_purple_bg}; border-radius: 24px; border: 1px solid {ac_purple_ic}; }}
            QWidget#ActionIconWrapper_purple {{ background-color: {ac_purple_icon}; border-radius: 24px; }}
            QLabel#ActionIcon_purple {{ color: white; font-size: 20px; font-weight: bold; background: transparent; }}
            QWidget#ActionArrowCircle_purple {{ background-color: {ac_purple_icon}; border-radius: 16px; }}
            QLabel#ActionArrow_purple {{ color: white; font-size: 16px; font-weight: bold; background: transparent; }}
            
            QWidget#SectionIconYellow {{ background-color: {section_yellow_bg}; border-radius: 6px; }}
            QWidget#SectionIconPurple {{ background-color: {section_purple_bg}; border-radius: 14px; }}
            
            QLabel#SectionTitle {{ font-size: 16px; font-weight: 900; color: {text_main}; background: transparent; }}
            QLabel#ViewAllLink {{ font-size: 13px; font-weight: 900; color: {input_focus}; background: transparent; }}
            
            QFrame#RecentContainer {{ background-color: {'#FFFFFF' if not dark else '#0F172A'}; border: 1px solid {border}; border-radius: 12px; }}
            QFrame#RecentHeaderRow {{ background-color: {'#F8FAFC' if not dark else '#1E293B'}; border-top-left-radius: 12px; border-top-right-radius: 12px; border-bottom: 1px solid {border}; }}
            QLabel#RecentTH {{ font-size: 11px; font-weight: 900; color: #475569; background: transparent; }}
            QFrame#RecentRow {{ background-color: transparent; border-radius: 0px; }}
            QFrame#RecentRow:hover {{ background-color: {'#EFF6FF' if not dark else '#172554'}; }}
            QFrame#RecentLine {{ background-color: {border}; border: none; }}
            QLabel#RecentIcon {{ font-size: 18px; color: #3B82F6; background: transparent; }}
            QLabel#RecentTitle {{ font-size: 13px; font-weight: 900; color: {text_main}; background: transparent; }}
            QLabel#RecentPath {{ font-size: 11px; font-weight: 800; color: {text_main}; background: transparent; }}
            QLabel#RecentText, QLabel#RecentCode {{ font-size: 12px; font-weight: 900; color: {text_main}; background: transparent; }}
            QPushButton#RecentMenuBtn {{ font-size: 18px; color: #475569; font-weight: bold; background: transparent; border: none; }}
            QPushButton#RecentMenuBtn:hover {{ color: {text_main}; }}
            
            QLabel#PageHeading, QLabel#SelectionHeading {{ font-size: 28px; font-weight: 900; color: {text_main}; background: transparent; }}
            QLabel#PageSubHeading, QLabel#SelectionSubHeading {{ font-size: 14px; font-weight: 800; color: {text_main}; background: transparent; }}
            QLabel#CodeBadge {{ font-size: 12px; font-weight: 900; color: {text_main}; background-color: {bg_card}; border: 1px solid {border}; border-radius: 6px; padding: 6px 12px; }}
            
            /* ADD THESE TWO LINES */
            QLabel#CardTitle {{ font-size: 13px; font-weight: 900; color: {text_main}; background: transparent; text-transform: uppercase; }}
            QLabel#CardDesc {{ font-size: 12px; font-weight: 600; color: {ac_desc_color}; background: transparent; }}
            
            QFrame#AppCard {{ background-color: {bg_card}; border: 1px solid {border}; border-radius: 8px; }}
            QFrame#AppCard[selected="false"] {{ background-color: {bg_card}; border: 1px solid {border}; }}
            QFrame#AppCard[selected="true"] {{ background-color: {'#F8FAFF' if not dark else '#0F172A'}; border: 2px solid {input_focus}; }}
            QFrame#AppCard:hover {{ border: 1px solid {input_focus}; }}
            
            QFrame#TypicalUsesBox {{ background-color: {row_alt}; border-radius: 6px; }}
            QFrame#TypicalUsesBox[selected="false"] {{ background-color: {row_alt}; }}
            QFrame#TypicalUsesBox[selected="true"] {{ background-color: {'#EFF6FF' if not dark else '#1E3A8A'}; }}
            
            QLabel#TypicalUsesTitle {{ font-size: 11px; font-weight: 900; color: {input_focus}; background: transparent; }}
            QLabel#TypicalUsesText {{ font-size: 11px; font-weight: 800; color: {text_main}; background: transparent; }}
            
            QFrame#ModernInputCard {{ background-color: {bg_card}; border: 1px solid {border}; border-radius: 12px; }}
            QLabel#SectionHeaderIcon {{ background-color: {pill_bg}; color: {pill_txt}; border-radius: 8px; font-size: 16px; font-weight: bold; }}
            QLabel#SectionHeaderTitle {{ font-size: 14px; font-weight: 900; color: {text_main}; background: transparent; letter-spacing: 0.5px; }}
            QLabel#SectionHeaderSub {{ font-size: 12px; font-weight: 800; color: {text_main}; background: transparent; }}
            
            QLabel#InputIconText {{ font-size: 18px; color: {pill_txt}; background: transparent; }}
            QLabel#InputLabel {{ font-size: 13px; font-weight: 900; color: {text_main}; background: transparent; }}
            QLabel#InputUnit {{ font-size: 12px; font-weight: 800; color: {text_main}; background: transparent; }}
            QLabel#FieldDescPill {{ background-color: {pill_bg}; color: {pill_txt}; border-radius: 6px; padding: 8px; font-size: 11px; font-weight: 800; line-height: 1.3; }}
            
            QFrame#BottomBanner {{ background-color: {'#1E3A8A' if dark else '#EFF6FF'}; border-radius: 10px; }}
            QLabel#BottomBannerText {{ font-size: 12px; font-weight: 800; color: {'#93C5FD' if dark else '#1D4ED8'}; background: transparent; }}
            
            QPushButton#BannerBtnCancel {{ background-color: {cancel_bg}; color: {cancel_fg}; border: 1px solid {border}; border-radius: 6px; font-weight: 900; font-size: 13px; padding: 0 16px; }}
            QPushButton#BannerBtnCancel:hover {{ background-color: {cancel_hover}; }}
            
            QPushButton#BannerBtnNext, QPushButton#NavNextBtn {{ background-color: {next_bg}; color: {next_fg}; border: 1px solid {border}; border-radius: 6px; font-weight: 900; font-size: 13px; padding: 0 16px; }}
            QPushButton#BannerBtnNext:hover, QPushButton#NavNextBtn:hover {{ background-color: {next_hover}; }}
            
            QPushButton#BannerBtnBlue {{ background-color: {input_focus}; color: #FFFFFF; border: 1px solid {input_focus}; border-radius: 6px; font-weight: 900; font-size: 13px; padding: 0 16px; }}
            QPushButton#BannerBtnBlue:hover {{ background-color: {'#1D4ED8' if not dark else '#2563EB'}; border: 1px solid {'#1D4ED8' if not dark else '#2563EB'}; color: #FFFFFF; }}
            
            QFrame#CardLine {{ background-color: {border}; border: none; }}
            
            QScrollBar:vertical {{ background-color: {bg_main}; width: 10px; }}
            QScrollBar::handle:vertical {{ background-color: {border}; border-radius: 5px; }}
            
            QTabWidget::pane {{ border: 1px solid {border}; background-color: {bg_main}; border-radius: 4px; }}
            QTabBar::tab {{ background-color: {bg_card}; color: {text_main}; padding: 10px 20px; border: 1px solid {border}; border-bottom-color: {border}; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; font-weight: 900; }}
            QTabBar::tab:selected {{ background-color: {bg_main}; color: {input_focus}; border-bottom-color: {bg_main}; font-weight: 900; }}
            
            QCheckBox {{ 
                color: {text_main}; 
                font-size: 13px; 
                font-weight: 800; 
                background: transparent; 
                spacing: 10px; 
            }}
            QCheckBox::indicator {{ 
                width: 18px; 
                height: 18px; 
                background-color: {input_bg}; 
                border: 2px solid {border}; 
                border-radius: 4px; 
            }}
            QCheckBox::indicator:hover {{ 
                border: 2px solid {input_focus}; 
            }}
            QCheckBox::indicator:checked {{ 
                background-color: {input_focus}; 
                border: 2px solid {input_focus}; 
                image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'><polyline points='20 6 9 17 4 12'/></svg>"); 
            }}
            
            QLineEdit, QComboBox {{ background-color: {input_bg}; border: 1px solid {border}; border-radius: 6px; padding: 8px 12px; color: {text_main}; font-size: 13px; font-weight: 800; min-width: 100px; }}
            QLineEdit:focus, QComboBox:focus {{ border: 1.5px solid {input_focus}; }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox::down-arrow {{ image: none; }}
            
            /* FORCE PURE BLACK/WHITE POPUP */
            QComboBox QAbstractItemView, QComboBox QListView {{ 
                background-color: {'#000000' if dark else '#FFFFFF'}; 
                color: {'#FFFFFF' if dark else '#000000'}; 
                border: 1px solid {border}; 
                selection-background-color: {input_focus}; 
                selection-color: white; 
                outline: none;
            }}
            QComboBox QAbstractItemView::item, QComboBox QListView::item {{
                background-color: {'#000000' if dark else '#FFFFFF'};
                color: {'#FFFFFF' if dark else '#000000'};
                padding: 6px 8px;
            }}
            QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected, 
            QComboBox QListView::item:hover, QComboBox QListView::item:selected {{
                background-color: {input_focus};
                color: #FFFFFF;
            }}

            /* GLOBAL QMESSAGEBOX STYLING */
            QMessageBox {{
                background-color: {'#1E293B' if dark else '#FFFFFF'};
            }}
            QMessageBox QLabel {{
                color: {'#F8FAFC' if dark else '#0F172A'};
                font-size: 13px;
                font-weight: 600;
                background-color: transparent;
            }}
            QMessageBox QPushButton {{
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 20px;
                font-weight: bold;
                min-width: 60px;
            }}
            QMessageBox QPushButton:hover {{
                background-color: #1D4ED8;
            }}
        """
        self.setStyleSheet(style)
        self.beam_type_page.refresh()
        if self.content_stack.currentIndex() >= 2:
            idx = self.content_stack.currentIndex() - 2
            if idx >= 0: self.go_to_step(idx)

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")

        home_action = QAction("Home Page", self)
        home_action.triggered.connect(self._go_home)
        file_menu.addAction(home_action)
        
        file_menu.addSeparator()

        new_action = QAction("New Project", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._go_beam_type)
        file_menu.addAction(new_action)

        open_action = QAction("Open Project...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_project)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        save_action = QAction("Save", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save_project)
        file_menu.addAction(save_action)

        save_as_action = QAction("Save As...", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self._save_project_as)
        file_menu.addAction(save_as_action)
        
        edit_menu = self.menuBar().addMenu("&View")
        
        theme_action = QAction("Toggle Dark/Light Mode", self)
        theme_action.setShortcut("Ctrl+T")
        theme_action.triggered.connect(self.toggle_theme)
        edit_menu.addAction(theme_action)
        
        help_menu = self.menuBar().addMenu("&Help")
        
        about_action = QAction("About & Design Guide...", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_about(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("About RCC Beam Designer")
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint)
        dialog.resize(850, 850)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("RCC Beam Designer — IS 456:2000")
        title.setObjectName("PageHeading")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        tabs = QTabWidget()
        
        tab_info = QWidget()
        layout_info = QVBoxLayout(tab_info)
        layout_info.setContentsMargins(40, 30, 40, 30)
        
        info_text = (
            "<h2 style='color: #2563EB;'>About the Software</h2>"
            "<p><b>RCC Beam Designer</b> is a comprehensive desktop application for designing and detailing "
            "Reinforced Concrete Beams according to Indian Standard IS 456:2000.</p>"
            "<br>"
            "<table cellpadding='6' cellspacing='0'>"
            "<tr><td width='120'><b>Version:</b></td><td>1.0.0</td></tr>"
            "<tr><td><b>Release Date:</b></td><td>October 2026</td></tr>"
            "<tr><td><b>Developer:</b></td><td>Ranvir Kumar</td></tr>"
            "<tr><td><b>License:</b></td><td>Educational / Open Source</td></tr>"
            "</table>"
            "<br><br>"
            "<h3 style='color: #2563EB;'>Key Features</h3>"
            "<ul>"
            "<li>Flexural design checks (Singly and Doubly reinforced limits)</li>"
            "<li>Shear design incorporating two-zone stirrup spacing optimizations</li>"
            "<li>Serviceability limits and L/d deflection checks</li>"
            "<li>Automated bar selection, spacing validation, and CAD-style layout generation</li>"
            "<li>Comprehensive PDF report generation</li>"
            "</ul>"
        )
        
        lbl_info = QLabel(info_text)
        lbl_info.setWordWrap(True)
        lbl_info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lbl_info.setStyleSheet("font-size: 14px; line-height: 1.6;")
        
        layout_info.addWidget(lbl_info)
        layout_info.addStretch()
        tabs.addTab(tab_info, "Software Info")

        tabs.addTab(ZoomableTab("assets/beam_flowchart.png"), "Beam Design Logic")
        tabs.addTab(ZoomableTab("assets/code_flowchart.png"), "Application Architecture")

        layout.addWidget(tabs)

        btn_close = QPushButton("Close")
        btn_close.setObjectName("BannerBtnBlue")
        btn_close.setFixedSize(120, 38)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignCenter)

        dialog.exec_()

    def _add_to_recent(self, path):
        settings = QSettings("RCCBeamDesigner", "App")
        recent = settings.value("recent_files", [])
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        settings.setValue("recent_files", recent[:10]) 

    def _save_project(self):
        if self.current_file_path: self._write_project(self.current_file_path)
        else: self._save_project_as()

    def _save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", "", "RCC Beam Project (*.rccbeam);;JSON files (*.json)")
        if path:
            if not (path.endswith(".rccbeam") or path.endswith(".json")): path += ".rccbeam"
            self._write_project(path)

    def _write_project(self, path):
        try:
            with open(path, "w") as f:
                json.dump(self.session.to_dict(), f, indent=2)
            self.current_file_path = path
            self._add_to_recent(path)
            self.setWindowTitle(f"RCC Beam Designer — IS 456:2000 — {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Could not save project:\n{e}")

    def _open_recent_project(self, path):
        if not os.path.exists(path):
            QMessageBox.warning(self, "File Not Found", f"The project file no longer exists:\n{path}")
            self.home_page.refresh_recent()
            return
        self._load_project_file(path)

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "RCC Beam Project (*.rccbeam);;JSON files (*.json);;All files (*)")
        if not path: return
        self._load_project_file(path)

    def _load_project_file(self, path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self.session.load_from_dict(data)
            self.current_file_path = path
            self._add_to_recent(path)
            self.setWindowTitle(f"RCC Beam Designer — IS 456:2000 — {os.path.basename(path)}")
            self._rebuild_after_load()
            self.content_stack.setCurrentIndex(2)
            self.beam_input_page.refresh_from_session()
            self.go_to_step(0)
        except Exception as e:
            QMessageBox.critical(self, "Open Failed", f"Could not open project:\n{e}")

    def _rebuild_after_load(self):
        for page in self.wizard_pages:
            page.session = self.session
        self.beam_type_page.session = self.session
        self.beam_type_page._select(self.session.beam_type)
        self.beam_type_page.custom_ratio_input.setText(str(self.session.custom_basic_ratio))
        self.beam_input_page.refresh_from_session()

    def _enter_wizard(self):
        self.content_stack.setCurrentIndex(2)
        self.go_to_step(0)

    def go_to_step(self, idx):
        self.content_stack.setCurrentIndex(2 + idx)
        refreshers = {
            1: self.flexural_page.refresh,
            2: self.shear_page.refresh,
            3: self.serviceability_page.refresh,
            4: self.detailing_page.refresh,
            5: self.summary_page.refresh,
        }
        if idx in refreshers:
            refreshers[idx]()

def main():
    app = QApplication(sys.argv)
    
    # Add this line to force PyQt to respect custom button backgrounds on Windows
    app.setStyle("Fusion") 
    
    app.setOrganizationName("StructuralTools")
    app.setApplicationName("RCCBeamDesigner")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()