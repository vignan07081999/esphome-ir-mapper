import sys
import os
import json
import csv
from typing import List, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QTextEdit, QMessageBox, QFileDialog, QGroupBox, QFormLayout, QDialog,
    QProgressBar, QHeaderView, QAbstractItemView, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSlot, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor

# Import local modules
from ha_client import HomeAssistantClient
from serial_listener import SerialListener
from esphome_runner import ESPHomeRunner
import esphome_templates

CONFIG_FILE = "config.json"
CSV_FILE = "ir_assignments.csv"
MD_FILE = "ir_assignments.md"
RECORDER_YAML = "temp_recorder.yaml"
FINAL_YAML = "final_remote_receiver.yaml"

ESPHOME_BUILD_DIR = os.path.join(os.path.expanduser("~"), ".esphome_build")
os.makedirs(ESPHOME_BUILD_DIR, exist_ok=True)

# Styling Sheets
DARK_STYLESHEET = """
QMainWindow {
    background-color: #0f172a;
}
QWidget {
    background-color: #0f172a;
    color: #f8fafc;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 16px;
    font-weight: bold;
    color: #a78bfa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 8px;
}
QLineEdit, QComboBox, QTextEdit {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 12px;
    color: #f8fafc;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
    border: 1px solid #8b5cf6;
}
QPushButton {
    background-color: #8b5cf6;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #a78bfa;
}
QPushButton:pressed {
    background-color: #7c3aed;
}
QPushButton:disabled {
    background-color: #475569;
    color: #94a3b8;
}
QTableWidget {
    background-color: #1e293b;
    border: 1px solid #334155;
    gridline-color: #334155;
    border-radius: 6px;
}
QTableWidget::item {
    padding: 8px;
    border-bottom: 1px solid #334155;
}
QHeaderView::section {
    background-color: #1e293b;
    color: #a78bfa;
    padding: 8px;
    border: 1px solid #334155;
    font-weight: bold;
}
QTabWidget::pane {
    border: 1px solid #334155;
    background-color: #0f172a;
    border-radius: 8px;
}
QTabBar::tab {
    background-color: #1e293b;
    color: #94a3b8;
    border: 1px solid #334155;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 10px 20px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    color: #f8fafc;
    background-color: #8b5cf6;
    border: 1px solid #8b5cf6;
}
QScrollBar:vertical {
    border: none;
    background-color: #0f172a;
    width: 10px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background-color: #475569;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background-color: #64748b;
}
"""

class AddMappingDialog(QDialog):
    """Wizard QDialog for recording a code and assigning to multiple entities/actions."""
    def __init__(self, parent, serial_listener: SerialListener, ha_client: HomeAssistantClient):
        super().__init__(parent)
        self.serial_listener = serial_listener
        self.ha_client = ha_client
        self.captured_protocol = None
        self.captured_data = None
        self.all_entities = []
        self.configured_actions = []

        self.setWindowTitle("Add Button Mapping Wizard")
        self.setMinimumSize(900, 750)
        self.setStyleSheet(DARK_STYLESHEET)
        
        self.init_ui()
        
        # Connect serial listener if running
        if self.serial_listener and self.serial_listener.isRunning():
            self.serial_listener.code_captured.connect(self.on_code_captured)
            
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Header
        header = QLabel("Add New Remote Button Mapping")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #a78bfa;")
        layout.addWidget(header)
        
        # Step 1: Capture
        self.step1_group = QGroupBox("Step 1: Capture IR Code")
        step1_layout = QVBoxLayout()
        self.status_label = QLabel("Waiting for remote keypress... Press any button on the remote.")
        self.status_label.setStyleSheet("font-size: 14px; color: #fbbf24; font-weight: bold;")
        self.status_label.setWordWrap(True)
        
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(80)
        self.details_text.setPlaceholderText("Captured IR protocol details will appear here...")
        
        self.reset_btn = QPushButton("Retry Capture")
        self.reset_btn.setEnabled(False)
        self.reset_btn.clicked.connect(self.reset_capture)
        
        step1_layout.addWidget(self.status_label)
        step1_layout.addWidget(self.details_text)
        step1_layout.addWidget(self.reset_btn)
        self.step1_group.setLayout(step1_layout)
        layout.addWidget(self.step1_group)
        
        # Step 2: Map to HA
        self.step2_group = QGroupBox("Step 2: Assign Home Assistant Actions")
        self.step2_group.setEnabled(False)
        
        # Horizontal Split layout inside Step 2
        step2_h_layout = QHBoxLayout()
        
        # --- LEFT PANEL: ENTITIES ---
        left_panel = QWidget()
        left_panel_layout = QVBoxLayout(left_panel)
        left_panel_layout.setContentsMargins(0, 0, 0, 0)
        
        left_panel_layout.addWidget(QLabel("<b>1. Find & Select Entities</b> (Ctrl/Shift to multi-select)"))
        
        # Search Entity Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type to filter entities by name/ID...")
        self.search_input.textChanged.connect(self.filter_entities)
        left_panel_layout.addWidget(self.search_input)
        
        # Filtering ComboBoxes
        self.area_combo = QComboBox()
        self.area_combo.currentIndexChanged.connect(self.trigger_filter)
        
        self.domain_combo = QComboBox()
        self.domain_combo.currentIndexChanged.connect(self.trigger_filter)
        
        self.label_combo = QComboBox()
        self.label_combo.currentIndexChanged.connect(self.trigger_filter)
        
        filter_widget = QWidget()
        filter_layout = QHBoxLayout(filter_widget)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(5)
        filter_layout.addWidget(self.area_combo)
        filter_layout.addWidget(self.domain_combo)
        filter_layout.addWidget(self.label_combo)
        left_panel_layout.addWidget(filter_widget)
        
        # Available Entities List
        self.available_entities_list = QListWidget()
        self.available_entities_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.available_entities_list.setMinimumHeight(150)
        left_panel_layout.addWidget(self.available_entities_list)
        
        # Action Buttons to Add Entity to Mapping
        entity_control_layout = QHBoxLayout()
        self.add_entity_btn = QPushButton("+ Add Entity to Mapping")
        self.add_entity_btn.setStyleSheet("background-color: #8b5cf6;")
        self.add_entity_btn.clicked.connect(self.add_entity_to_selected)
        
        self.remove_entity_btn = QPushButton("- Remove Selected Entity")
        self.remove_entity_btn.setStyleSheet("background-color: #475569;")
        self.remove_entity_btn.clicked.connect(self.remove_entity_from_selected)
        
        entity_control_layout.addWidget(self.add_entity_btn)
        entity_control_layout.addWidget(self.remove_entity_btn)
        left_panel_layout.addLayout(entity_control_layout)
        
        # Selected Entities for Mapping List
        left_panel_layout.addWidget(QLabel("<b>Entities in this Mapping:</b>"))
        self.selected_entities_list = QListWidget()
        self.selected_entities_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.selected_entities_list.setMinimumHeight(120)
        self.selected_entities_list.itemSelectionChanged.connect(self.on_selected_entities_selection_changed)
        left_panel_layout.addWidget(self.selected_entities_list)
        
        step2_h_layout.addWidget(left_panel, stretch=1)
        
        # --- RIGHT PANEL: ACTIONS & QUEUE ---
        right_panel = QWidget()
        right_panel_layout = QVBoxLayout(right_panel)
        right_panel_layout.setContentsMargins(0, 0, 0, 0)
        
        right_panel_layout.addWidget(QLabel("<b>2. Map Actions to Entities</b> (Ctrl/Shift to multi-select)"))
        
        # Action Status/Warning Label
        self.action_status_label = QLabel("Select entities on the left to view actions.")
        self.action_status_label.setStyleSheet("color: #94a3b8; font-style: italic;")
        self.action_status_label.setWordWrap(True)
        right_panel_layout.addWidget(self.action_status_label)
        
        # Available Actions List
        self.action_list = QListWidget()
        self.action_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.action_list.setMinimumHeight(150)
        right_panel_layout.addWidget(self.action_list)
        
        # Action controls layout (Add / Test buttons)
        action_btn_layout = QHBoxLayout()
        self.add_action_btn = QPushButton("+ Add Selected Actions to Queue")
        self.add_action_btn.setStyleSheet("background-color: #8b5cf6;")
        self.add_action_btn.clicked.connect(self.add_action_to_list)
        self.add_action_btn.setEnabled(False)
        
        self.test_selection_btn = QPushButton("Test Selection")
        self.test_selection_btn.setStyleSheet("background-color: #475569;")
        self.test_selection_btn.clicked.connect(self.test_selection)
        self.test_selection_btn.setEnabled(False)
        
        action_btn_layout.addWidget(self.add_action_btn)
        action_btn_layout.addWidget(self.test_selection_btn)
        right_panel_layout.addLayout(action_btn_layout)
        
        # Configured Actions List Group
        self.actions_group = QGroupBox("3. Configured Actions List Queue")
        actions_list_layout = QVBoxLayout()
        
        self.actions_list = QListWidget()
        self.actions_list.setMinimumHeight(120)
        
        actions_control_layout = QHBoxLayout()
        self.remove_action_btn = QPushButton("- Remove Action")
        self.remove_action_btn.setStyleSheet("background-color: #ef4444;")
        self.remove_action_btn.clicked.connect(self.remove_action_from_list)
        
        self.test_action_btn = QPushButton("Test Selected Action")
        self.test_action_btn.setStyleSheet("background-color: #10b981;")
        self.test_action_btn.clicked.connect(self.test_selected_action)
        
        actions_control_layout.addWidget(self.remove_action_btn)
        actions_control_layout.addWidget(self.test_action_btn)
        actions_control_layout.addStretch()
        
        actions_list_layout.addWidget(self.actions_list)
        actions_list_layout.addLayout(actions_control_layout)
        self.actions_group.setLayout(actions_list_layout)
        right_panel_layout.addWidget(self.actions_group)
        
        step2_h_layout.addWidget(right_panel, stretch=1)
        
        self.step2_group.setLayout(step2_h_layout)
        layout.addWidget(self.step2_group)
        
        # Step 3: Save
        self.step3_group = QGroupBox("Step 3: Save Mapping")
        self.step3_group.setEnabled(False)
        step3_layout = QFormLayout()
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. TV Power / Living Room Toggle")
        
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save Button Mapping")
        self.save_btn.clicked.connect(self.save_mapping)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet("background-color: #475569;")
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        
        step3_layout.addRow("Button Name:", self.name_input)
        step3_layout.addRow("", btn_layout)
        
        self.step3_group.setLayout(step3_layout)
        layout.addWidget(self.step3_group)
        
        # Load Entities
        self.load_ha_entities()

    def load_ha_entities(self):
        if not self.ha_client:
            return
        self.all_entities = self.ha_client.get_entities()
        
        # Gather unique categories for filtering
        areas = set()
        domains = set()
        labels = set()
        
        for ent in self.all_entities:
            if ent.get("area_name"):
                areas.add(ent["area_name"])
            if ent.get("domain"):
                domains.add(ent["domain"])
            for label in ent.get("labels", []):
                labels.add(label)
                
        # Populate filter selectors
        self.area_combo.clear()
        self.area_combo.addItem("Any Area", "")
        for area in sorted(areas):
            self.area_combo.addItem(area, area)
            
        self.domain_combo.clear()
        self.domain_combo.addItem("Any Type", "")
        for dom in sorted(domains):
            self.domain_combo.addItem(dom.capitalize(), dom)
            
        self.label_combo.clear()
        self.label_combo.addItem("Any Label", "")
        for lab in sorted(labels):
            self.label_combo.addItem(lab, lab)
            
        self.populate_available_entities_list(self.all_entities)

    def populate_available_entities_list(self, entities):
        self.available_entities_list.clear()
        for ent in entities:
            # Format display name with area if available
            area_str = f" [{ent['area_name']}]" if ent.get('area_name') != 'No Area' else ""
            display_name = f"{ent['friendly_name']}{area_str} ({ent['entity_id']})"
            item = QListWidgetItem(display_name)
            item.setData(Qt.ItemDataRole.UserRole, ent['entity_id'])
            self.available_entities_list.addItem(item)

    def trigger_filter(self):
        self.filter_entities()

    def filter_entities(self, *args):
        text = self.search_input.text().lower()
        selected_area = self.area_combo.currentData()
        selected_domain = self.domain_combo.currentData()
        selected_label = self.label_combo.currentData()
        
        filtered = []
        for ent in self.all_entities:
            # 1. Search text filter
            if text and text not in ent['friendly_name'].lower() and text not in ent['entity_id'].lower():
                continue
            # 2. Area filter
            if selected_area and ent.get('area_name') != selected_area:
                continue
            # 3. Domain filter
            if selected_domain and ent.get('domain') != selected_domain:
                continue
            # 4. Label filter
            if selected_label and selected_label not in ent.get('labels', []):
                continue
                
            filtered.append(ent)
            
        self.populate_available_entities_list(filtered)

    def add_entity_to_selected(self):
        selected_items = self.available_entities_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Selection Required", "Please select one or more entities from the available list.")
            return
            
        # Get existing entity IDs in the selected list to prevent duplicates
        existing_ids = []
        for i in range(self.selected_entities_list.count()):
            item = self.selected_entities_list.item(i)
            existing_ids.append(item.data(Qt.ItemDataRole.UserRole))
            
        for item in selected_items:
            entity_id = item.data(Qt.ItemDataRole.UserRole)
            if entity_id not in existing_ids:
                # Add to selected entities list
                new_item = QListWidgetItem(item.text())
                new_item.setData(Qt.ItemDataRole.UserRole, entity_id)
                self.selected_entities_list.addItem(new_item)

    def remove_entity_from_selected(self):
        selected_items = self.selected_entities_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Selection Required", "Please select one or more entities in the mapping list to remove.")
            return
            
        for item in selected_items:
            self.selected_entities_list.takeItem(self.selected_entities_list.row(item))

    def on_selected_entities_selection_changed(self):
        selected_items = self.selected_entities_list.selectedItems()
        if not selected_items:
            self.action_list.clear()
            self.action_status_label.setText("Select one or more entities in the mapping list to view actions.")
            self.action_status_label.setStyleSheet("color: #94a3b8; font-style: italic;")
            self.add_action_btn.setEnabled(False)
            self.test_selection_btn.setEnabled(False)
            return
            
        # Get domains of selected entities
        domains = set()
        for item in selected_items:
            entity_id = item.data(Qt.ItemDataRole.UserRole)
            if entity_id and "." in entity_id:
                domains.add(entity_id.split(".")[0])
                
        if len(domains) == 1:
            domain = list(domains)[0]
            services = self.ha_client.get_services_for_domain(domain)
            self.action_list.clear()
            
            # Standard sensible defaults for each domain
            default_actions = {
                "light": "toggle",
                "switch": "toggle",
                "button": "press",
                "input_button": "press",
                "media_player": "media_play_pause",
                "script": "turn_on",
                "automation": "trigger",
                "input_boolean": "toggle",
                "fan": "toggle",
                "cover": "toggle",
                "lock": "toggle",
                "scene": "turn_on"
            }
            default_svc = default_actions.get(domain, "")
            
            # Populate action list
            for s in services:
                display_name = f"{domain}.{s}"
                item = QListWidgetItem(display_name)
                item.setData(Qt.ItemDataRole.UserRole, s)
                self.action_list.addItem(item)
                
                # Pre-select default service
                if s == default_svc:
                    item.setSelected(True)
                    
            self.action_status_label.setText(f"✓ All selected entities are of type '{domain}'. Select one or more actions.")
            self.action_status_label.setStyleSheet("color: #10b981; font-weight: bold;")
            self.add_action_btn.setEnabled(True)
            self.test_selection_btn.setEnabled(True)
        else:
            self.action_list.clear()
            self.action_status_label.setText("⚠️ Selected entities have different types (domains). Select entities of the same type to map actions together.")
            self.action_status_label.setStyleSheet("color: #ef4444; font-weight: bold;")
            self.add_action_btn.setEnabled(False)
            self.test_selection_btn.setEnabled(False)

    @pyqtSlot(str, dict)
    def on_code_captured(self, protocol, data):
        if self.captured_protocol is not None:
            return
        self.captured_protocol = protocol
        self.captured_data = data
        
        # Update UI
        self.status_label.setText(f"✓ Capture Successful! Protocol: {protocol}")
        self.status_label.setStyleSheet("font-size: 14px; color: #10b981; font-weight: bold;")
        
        if protocol == "RAW":
            raw_len = len(data.get("raw_code", []))
            self.details_text.setText(f"RAW code sequence of {raw_len} values.")
        elif protocol == "PRONTO":
            pronto_data = data.get("data", "")
            if len(pronto_data) > 40:
                self.details_text.setText(f"Pronto: {pronto_data[:40]}...")
            else:
                self.details_text.setText(f"Pronto: {pronto_data}")
        else:
            details = ", ".join([f"{k}={v}" for k, v in data.items()])
            self.details_text.setText(details)
            
        self.reset_btn.setEnabled(True)
        self.step2_group.setEnabled(True)
        # Only enable Save if actions are already configured in queue
        if self.configured_actions:
            self.step3_group.setEnabled(True)

    def reset_capture(self):
        self.captured_protocol = None
        self.captured_data = None
        self.status_label.setText("Waiting for remote keypress... Press any button on the remote.")
        self.status_label.setStyleSheet("font-size: 14px; color: #fbbf24; font-weight: bold;")
        self.details_text.clear()
        self.reset_btn.setEnabled(False)
        self.step2_group.setEnabled(False)
        self.step3_group.setEnabled(False)

    def add_action_to_list(self):
        selected_entities = self.selected_entities_list.selectedItems()
        selected_actions = self.action_list.selectedItems()
        
        if not selected_entities or not selected_actions:
            QMessageBox.warning(self, "Invalid Selection", "Please select at least one entity and one action.")
            return
            
        # Add combinations to state list and UI QListWidget
        for ent_item in selected_entities:
            entity_id = ent_item.data(Qt.ItemDataRole.UserRole)
            domain = entity_id.split(".")[0]
            
            for act_item in selected_actions:
                service = act_item.data(Qt.ItemDataRole.UserRole)
                full_service = f"{domain}.{service}"
                
                # Check for duplicates in configured actions
                duplicate = False
                for act in self.configured_actions:
                    if act["entity_id"] == entity_id and act["service"] == full_service:
                        duplicate = True
                        break
                        
                if not duplicate:
                    self.configured_actions.append({
                        "entity_id": entity_id,
                        "service": full_service
                    })
                    display_text = f"{full_service} ➔ {entity_id}"
                    self.actions_list.addItem(display_text)
                    
        # Enable save group if code is captured
        if self.captured_protocol:
            self.step3_group.setEnabled(True)

    def remove_action_from_list(self):
        selected_items = self.actions_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Selection Required", "Please select an action in the list to remove.")
            return
            
        for item in selected_items:
            row = self.actions_list.row(item)
            self.actions_list.takeItem(row)
            self.configured_actions.pop(row)
            
        if not self.configured_actions:
            self.step3_group.setEnabled(False)

    def test_selection(self):
        selected_entities = self.selected_entities_list.selectedItems()
        selected_actions = self.action_list.selectedItems()
        
        if not selected_entities or not selected_actions:
            QMessageBox.warning(self, "Invalid Selection", "Please select at least one entity and one action to test.")
            return
            
        success_count = 0
        total_calls = len(selected_entities) * len(selected_actions)
        fail_messages = []
        
        for ent_item in selected_entities:
            entity_id = ent_item.data(Qt.ItemDataRole.UserRole)
            domain = entity_id.split(".")[0]
            
            for act_item in selected_actions:
                service = act_item.data(Qt.ItemDataRole.UserRole)
                success, msg = self.ha_client.call_service(domain, service, entity_id)
                if success:
                    success_count += 1
                else:
                    fail_messages.append(f"{domain}.{service} -> {entity_id}: {msg}")
                    
        if success_count == total_calls:
            QMessageBox.information(self, "Test Successful", f"Triggered all {total_calls} actions successfully!")
        else:
            QMessageBox.warning(
                self, 
                "Test Partial Success", 
                f"Successfully triggered {success_count}/{total_calls} actions.\nFailures:\n" + "\n".join(fail_messages)
            )

    def test_selected_action(self):
        selected_items = self.actions_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Selection Required", "Please select an action in the list to test.")
            return
            
        row = self.actions_list.row(selected_items[0])
        action = self.configured_actions[row]
        
        entity_id = action["entity_id"]
        service_full = action["service"]
        domain, service = service_full.split(".", 1)
        
        success, msg = self.ha_client.call_service(domain, service, entity_id)
        if success:
            QMessageBox.information(self, "Test Successful", f"Triggered action successfully!\n{msg}")
        else:
            QMessageBox.critical(self, "Test Failed", f"Failed to trigger action.\n{msg}")

    def save_mapping(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Please provide a name for this button mapping.")
            return
            
        if not self.configured_actions:
            QMessageBox.warning(self, "Validation Error", "Please add at least one action to the configured actions list.")
            return
            
        if not self.captured_protocol or not self.captured_data:
            QMessageBox.warning(self, "Validation Error", "No IR code has been captured yet.")
            return
            
        self.accept()

    def get_result(self):
        return {
            "name": self.name_input.text().strip(),
            "protocol": self.captured_protocol,
            "data": self.captured_data,
            "actions": self.configured_actions
        }

    def closeEvent(self, event):
        if self.serial_listener:
            try:
                self.serial_listener.code_captured.disconnect(self.on_code_captured)
            except Exception:
                pass
        super().closeEvent(event)


class ESPHomeRemoteMapperApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESPHome IR Smart Remote Mapper")
        self.setMinimumSize(850, 650)
        self.setStyleSheet(DARK_STYLESHEET)
        
        # State variables
        self.config = {
            "wifi_ssid": "",
            "wifi_password": "",
            "ha_url": "",
            "ha_token": "",
            "com_port": "",
            "gpio_pin": "19",
            "board_type": "esp32dev",
            "onboard_led_pin": "2"
        }
        self.mappings = []
        
        # Thread handles
        self.serial_listener = None
        self.esphome_runner = None
        self.ha_client = None

        self.load_config()
        self.load_mappings()
        
        self.init_ha_client()
        self.init_ui()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    self.config.update(json.load(f))
            except Exception as e:
                print(f"Error loading config.json: {e}")

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save settings to config.json: {e}")

    def load_mappings(self):
        self.mappings = []
        if os.path.exists(CSV_FILE):
            try:
                with open(CSV_FILE, "r", newline='', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    header = next(reader, None)
                    is_legacy = header and "ActionsJSON" not in header
                    for row in reader:
                        if is_legacy:
                            if len(row) < 5:
                                continue
                            name, protocol, data_json, entity_id, service = row
                            actions = [{"entity_id": entity_id, "service": service}]
                        else:
                            if len(row) < 4:
                                continue
                            name, protocol, data_json, actions_json = row
                            try:
                                actions = json.loads(actions_json)
                            except Exception:
                                actions = []
                        try:
                            data = json.loads(data_json)
                            self.mappings.append({
                                "name": name,
                                "protocol": protocol,
                                "data": data,
                                "actions": actions
                            })
                        except Exception as ex:
                            print(f"Error loading row {row}: {ex}")
            except Exception as e:
                print(f"Error reading mappings CSV: {e}")

    def save_mappings_files(self):
        # Save CSV
        try:
            with open(CSV_FILE, "w", newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Name", "Protocol", "DataJSON", "ActionsJSON"])
                for m in self.mappings:
                    writer.writerow([
                        m["name"],
                        m["protocol"],
                        json.dumps(m["data"]),
                        json.dumps(m.get("actions", []))
                    ])
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to write to {CSV_FILE}: {e}")
            return

        # Save Markdown Table
        try:
            with open(MD_FILE, "w", encoding='utf-8') as f:
                f.write("# ESPHome IR Remote Button Mappings\n\n")
                f.write("This file is automatically generated by the ESPHome IR Remote Mapper tool.\n\n")
                f.write("| Button Name | Protocol | Code Details | Home Assistant Actions |\n")
                f.write("| :--- | :--- | :--- | :--- |\n")
                for m in self.mappings:
                    protocol = m["protocol"]
                    data = m["data"]
                    
                    if protocol == "RAW":
                           raw_code = data.get("raw_code", [])
                           raw_len = len(raw_code)
                           details = f"RAW code ({raw_len} values)"
                    elif protocol in ["NEC", "PANASONIC"]:
                           addr = data.get("address", "")
                           cmd = data.get("command", "")
                           details = f"Addr: `{addr}`, Cmd: `{cmd}`"
                    elif protocol == "PRONTO":
                           pronto_data = data.get("data", "")
                           if len(pronto_data) > 20:
                               details = f"Pronto: `{pronto_data[:20]}...`"
                           else:
                               details = f"Pronto: `{pronto_data}`"
                    else:
                           code_val = data.get("data", "")
                           nbits = data.get("nbits", "")
                           details = f"Val: `{code_val}` ({nbits} bits)"
                           
                    actions_str = "<br>".join([f"- `{act['service']}` on `{act['entity_id']}`" for act in m.get("actions", [])])
                    f.write(f"| {m['name']} | {protocol} | {details} | {actions_str} |\n")
        except Exception as e:
            print(f"Failed to write to {MD_FILE}: {e}")

    def init_ha_client(self):
        url = self.config.get("ha_url", "")
        token = self.config.get("ha_token", "")
        if url and token:
            self.ha_client = HomeAssistantClient(url, token)
        else:
            self.ha_client = None

    def init_ui(self):
        # Setup central widget and tabs
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # App Title
        title_label = QLabel("ESPHome IR Remote Mapper")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #8b5cf6; margin-bottom: 5px;")
        main_layout.addWidget(title_label)
        
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Tabs Initialization
        self.init_dashboard_tab()
        self.init_deploy_tab()
        self.init_settings_tab()
        
        self.update_mappings_table()

    def init_dashboard_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        
        top_layout = QHBoxLayout()
        
        # Serial Status
        serial_group = QGroupBox("ESP32 Serial Listener Status")
        serial_group_layout = QHBoxLayout()
        self.serial_status_label = QLabel("Serial Status: Disconnected")
        self.serial_status_label.setStyleSheet("color: #ef4444; font-weight: bold;")
        
        self.start_listen_btn = QPushButton("Start Listening")
        self.start_listen_btn.setStyleSheet("background-color: #8b5cf6;")
        self.start_listen_btn.clicked.connect(self.toggle_serial_listening)
        
        self.app_status_label = QLabel("Ready. Go to 'Compile & Deploy' tab to flash recorder firmware first.")
        self.app_status_label.setStyleSheet("color: #94a3b8; font-style: italic; margin-left: 10px;")
        
        serial_group_layout.addWidget(self.serial_status_label)
        serial_group_layout.addWidget(self.start_listen_btn)
        serial_group_layout.addWidget(self.app_status_label)
        serial_group.setLayout(serial_group_layout)
        
        self.add_mapping_btn = QPushButton("Add New Mapping Wizard")
        self.add_mapping_btn.setStyleSheet("background-color: #10b981; font-size: 14px; padding: 10px 20px;")
        self.add_mapping_btn.clicked.connect(self.open_add_mapping_wizard)
        
        top_layout.addWidget(serial_group)
        top_layout.addStretch()
        top_layout.addWidget(self.add_mapping_btn)
        layout.addLayout(top_layout)
        
        # Mappings Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Button Name", "Protocol", "Code Details", "HA Entity", "Action / Actions"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        
        # Test/Delete Buttons
        bottom_layout = QHBoxLayout()
        self.test_row_btn = QPushButton("Test Selected Action")
        self.test_row_btn.clicked.connect(self.test_selected_mapping)
        self.delete_row_btn = QPushButton("Delete Selected")
        self.delete_row_btn.setStyleSheet("background-color: #ef4444;")
        self.delete_row_btn.clicked.connect(self.delete_selected_mapping)
        
        bottom_layout.addWidget(self.test_row_btn)
        bottom_layout.addWidget(self.delete_row_btn)
        bottom_layout.addStretch()
        layout.addLayout(bottom_layout)
        
        # Diagnostics Console
        console_group = QGroupBox("ESP32 Serial Logs")
        console_layout = QVBoxLayout()
        self.serial_console = QTextEdit()
        self.serial_console.setReadOnly(True)
        self.serial_console.setMaximumHeight(120)
        self.serial_console.setPlaceholderText("Logs from ESP32 will appear here when listening...")
        console_layout.addWidget(self.serial_console)
        console_group.setLayout(console_layout)
        layout.addWidget(console_group)
        
        self.tabs.addTab(widget, "Mappings Dashboard")

    def init_deploy_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        
        left_layout = QVBoxLayout()
        btn_layout = QHBoxLayout()
        self.flash_recorder_btn = QPushButton("Flash Recorder Firmware")
        self.flash_recorder_btn.setStyleSheet("background-color: #f59e0b; padding: 10px 15px;")
        self.flash_recorder_btn.clicked.connect(self.flash_recorder)
        
        self.flash_final_btn = QPushButton("Compile & Flash Final Firmware")
        self.flash_final_btn.setStyleSheet("background-color: #8b5cf6; padding: 10px 15px;")
        self.flash_final_btn.clicked.connect(self.flash_final_firmware)
        
        self.stop_build_btn = QPushButton("Stop Process")
        self.stop_build_btn.setStyleSheet("background-color: #ef4444; padding: 10px 15px;")
        self.stop_build_btn.setEnabled(False)
        self.stop_build_btn.clicked.connect(self.stop_esphome_runner)
        
        btn_layout.addWidget(self.flash_recorder_btn)
        btn_layout.addWidget(self.flash_final_btn)
        btn_layout.addWidget(self.stop_build_btn)
        left_layout.addLayout(btn_layout)
        
        console_group = QGroupBox("ESPHome Compiler Log Output")
        console_layout = QVBoxLayout()
        self.compile_console = QTextEdit()
        self.compile_console.setReadOnly(True)
        self.compile_console.setPlaceholderText("ESPHome build system log outputs will print here...")
        console_layout.addWidget(self.compile_console)
        console_group.setLayout(console_layout)
        left_layout.addWidget(console_group)
        
        layout.addLayout(left_layout, stretch=3)
        
        right_layout = QVBoxLayout()
        yaml_group = QGroupBox("Final ESPHome YAML Config Preview")
        yaml_layout = QVBoxLayout()
        self.yaml_preview = QTextEdit()
        self.yaml_preview.setReadOnly(True)
        self.yaml_preview.setPlaceholderText("Complete YAML will be generated automatically based on mappings...")
        
        self.refresh_yaml_btn = QPushButton("Refresh Preview")
        self.refresh_yaml_btn.clicked.connect(self.refresh_yaml_preview)
        
        yaml_layout.addWidget(self.yaml_preview)
        yaml_layout.addWidget(self.refresh_yaml_btn)
        yaml_group.setLayout(yaml_layout)
        right_layout.addWidget(yaml_group)
        
        layout.addLayout(right_layout, stretch=2)
        self.tabs.addTab(widget, "Compile & Deploy")

    def init_settings_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        
        form_group = QGroupBox("Application Configurations")
        form = QFormLayout()
        form.setSpacing(10)
        
        self.ha_url_input = QLineEdit()
        self.ha_url_input.setPlaceholderText("http://homeassistant.local:8123")
        self.ha_url_input.setText(self.config["ha_url"])
        
        self.ha_token_input = QLineEdit()
        self.ha_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.ha_token_input.setPlaceholderText("Long-Lived Access Token")
        self.ha_token_input.setText(self.config["ha_token"])
        
        self.wifi_ssid_input = QLineEdit()
        self.wifi_ssid_input.setPlaceholderText("Your Wi-Fi SSID Name")
        self.wifi_ssid_input.setText(self.config["wifi_ssid"])
        
        self.wifi_pass_input = QLineEdit()
        self.wifi_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.wifi_pass_input.setPlaceholderText("Your Wi-Fi Password")
        self.wifi_pass_input.setText(self.config["wifi_password"])
        
        serial_layout = QHBoxLayout()
        self.com_port_combo = QComboBox()
        self.refresh_ports_btn = QPushButton("Refresh Ports")
        self.refresh_ports_btn.clicked.connect(self.refresh_serial_ports)
        serial_layout.addWidget(self.com_port_combo)
        serial_layout.addWidget(self.refresh_ports_btn)
        
        self.gpio_pin_input = QLineEdit()
        self.gpio_pin_input.setPlaceholderText("19")
        self.gpio_pin_input.setText(self.config["gpio_pin"])
        
        self.led_pin_input = QLineEdit()
        self.led_pin_input.setPlaceholderText("2 (or 'None')")
        self.led_pin_input.setText(self.config.get("onboard_led_pin", "2"))
        
        self.board_combo = QComboBox()
        self.board_combo.addItems(["esp32dev", "lolin32", "nodeMCU-32S"])
        if self.config["board_type"] in ["esp32dev", "lolin32", "nodeMCU-32S"]:
            self.board_combo.setCurrentText(self.config["board_type"])
        else:
            self.board_combo.addItem(self.config["board_type"])
            self.board_combo.setCurrentText(self.config["board_type"])
            
        form.addRow("Home Assistant URL:", self.ha_url_input)
        form.addRow("HA Access Token:", self.ha_token_input)
        form.addRow("Wi-Fi SSID:", self.wifi_ssid_input)
        form.addRow("Wi-Fi Password:", self.wifi_pass_input)
        form.addRow("ESP32 COM Port:", serial_layout)
        form.addRow("IR GPIO Receiver Pin:", self.gpio_pin_input)
        form.addRow("Onboard LED GPIO Pin:", self.led_pin_input)
        form.addRow("ESP32 Board Type:", self.board_combo)
        
        form_group.setLayout(form)
        layout.addWidget(form_group)
        
        btn_layout = QHBoxLayout()
        self.test_ha_btn = QPushButton("Test HA Connection")
        self.test_ha_btn.setStyleSheet("background-color: #10b981;")
        self.test_ha_btn.clicked.connect(self.test_ha_connection)
        
        self.save_settings_btn = QPushButton("Save Configurations")
        self.save_settings_btn.clicked.connect(self.save_settings)
        
        btn_layout.addWidget(self.test_ha_btn)
        btn_layout.addWidget(self.save_settings_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()
        
        self.tabs.addTab(widget, "Settings")
        self.refresh_serial_ports()

    def refresh_serial_ports(self):
        self.com_port_combo.clear()
        ports = SerialListener.get_available_ports()
        self.com_port_combo.addItems(ports)
        if self.config["com_port"] in ports:
            self.com_port_combo.setCurrentText(self.config["com_port"])

    def test_ha_connection(self):
        url = self.ha_url_input.text().strip()
        token = self.ha_token_input.text().strip()
        if not url or not token:
            QMessageBox.warning(self, "Validation Error", "Please provide both Home Assistant URL and LLAT Token.")
            return
            
        client = HomeAssistantClient(url, token)
        success, msg = client.test_connection()
        if success:
            QMessageBox.information(self, "Connection Success", msg)
        else:
            QMessageBox.critical(self, "Connection Failed", msg)

    def save_settings(self):
        self.config["ha_url"] = self.ha_url_input.text().strip()
        self.config["ha_token"] = self.ha_token_input.text().strip()
        self.config["wifi_ssid"] = self.wifi_ssid_input.text().strip()
        self.config["wifi_password"] = self.wifi_pass_input.text().strip()
        self.config["com_port"] = self.com_port_combo.currentText().strip()
        self.config["gpio_pin"] = self.gpio_pin_input.text().strip()
        self.config["onboard_led_pin"] = self.led_pin_input.text().strip()
        self.config["board_type"] = self.board_combo.currentText().strip()
        
        self.save_config()
        self.init_ha_client()
        QMessageBox.information(self, "Success", "Settings saved successfully!")
        self.refresh_yaml_preview()

    def update_mappings_table(self):
        self.table.setRowCount(0)
        for idx, m in enumerate(self.mappings):
            self.table.insertRow(idx)
            self.table.setItem(idx, 0, QTableWidgetItem(m["name"]))
            self.table.setItem(idx, 1, QTableWidgetItem(m["protocol"]))
            
            data = m["data"]
            if m["protocol"] == "RAW":
                raw_len = len(data.get("raw_code", []))
                details = f"RAW code ({raw_len} values)"
            elif m["protocol"] in ["NEC", "PANASONIC"]:
                details = f"Address: {data.get('address')}, Command: {data.get('command')}"
            elif m["protocol"] == "PRONTO":
                pronto_data = data.get("data", "")
                if len(pronto_data) > 20:
                    details = f"Pronto: {pronto_data[:20]}..."
                else:
                    details = f"Pronto: {pronto_data}"
            else:
                details = f"Data: {data.get('data')} ({data.get('nbits')} bits)"
            self.table.setItem(idx, 2, QTableWidgetItem(details))
            
            ent_ids = ", ".join([act["entity_id"] for act in m.get("actions", [])])
            self.table.setItem(idx, 3, QTableWidgetItem(ent_ids))
            
            svc_names = ", ".join([act["service"] for act in m.get("actions", [])])
            self.table.setItem(idx, 4, QTableWidgetItem(svc_names))

    def toggle_serial_listening(self):
        if self.serial_listener and self.serial_listener.isRunning():
            self.serial_listener.stop()
            self.serial_listener.wait()
            self.serial_listener = None
            self.start_listen_btn.setText("Start Listening")
            self.start_listen_btn.setStyleSheet("background-color: #8b5cf6;")
            self.serial_status_label.setText("Serial Status: Disconnected")
            self.serial_status_label.setStyleSheet("color: #ef4444; font-weight: bold;")
        else:
            port = self.config.get("com_port", "")
            if not port:
                QMessageBox.warning(self, "Port Error", "Please select and save an ESP32 COM port in Settings.")
                return
            
            self.serial_listener = SerialListener(port)
            self.serial_listener.log_line.connect(self.append_serial_log)
            self.serial_listener.error_occurred.connect(self.on_serial_error)
            self.serial_listener.connected_status.connect(self.on_serial_status_change)
            self.serial_listener.start()

    def append_serial_log(self, line):
        self.serial_console.append(line)
        self.serial_console.verticalScrollBar().setValue(self.serial_console.verticalScrollBar().maximum())
        
        if "setup() finished successfully!" in line:
            self.app_status_label.setText("✓ ESP32 Booted! You can now start adding remote codes.")
            self.app_status_label.setStyleSheet("color: #10b981; font-weight: bold;")
        elif "remote_receiver" in line.lower() and "dump" in line.lower():
            self.app_status_label.setText("Booting (Receiver detected)...")
            self.app_status_label.setStyleSheet("color: #fbbf24; font-weight: bold;")

    def on_serial_error(self, err_msg):
        self.append_serial_log(f"[ERROR] {err_msg}")
        self.app_status_label.setText("Error occurred.")
        self.app_status_label.setStyleSheet("color: #ef4444; font-weight: bold;")
        QMessageBox.critical(self, "Serial Error", err_msg)

    def on_serial_status_change(self, connected):
        if connected:
            self.start_listen_btn.setText("Stop Listening")
            self.start_listen_btn.setStyleSheet("background-color: #ef4444;")
            self.serial_status_label.setText("Serial Status: Connected")
            self.serial_status_label.setStyleSheet("color: #10b981; font-weight: bold;")
            self.app_status_label.setText("Waiting for ESP32 boot/ready log...")
            self.app_status_label.setStyleSheet("color: #fbbf24; font-weight: bold;")
        else:
            self.start_listen_btn.setText("Start Listening")
            self.start_listen_btn.setStyleSheet("background-color: #8b5cf6;")
            self.serial_status_label.setText("Serial Status: Disconnected")
            self.serial_status_label.setStyleSheet("color: #ef4444; font-weight: bold;")
            self.app_status_label.setText("Ready. Go to 'Compile & Deploy' tab to flash recorder firmware first.")
            self.app_status_label.setStyleSheet("color: #94a3b8; font-style: italic;")

    def open_add_mapping_wizard(self):
        if not self.config.get("ha_url") or not self.config.get("ha_token"):
            QMessageBox.warning(self, "Credentials Error", "Please configure and test your Home Assistant credentials in Settings first.")
            return

        if not self.serial_listener or not self.serial_listener.isRunning():
            reply = QMessageBox.question(
                self, 
                "Serial Not Listening",
                "The serial listener is not running. Would you like to start it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.toggle_serial_listening()
                QThread.msleep(100)
            else:
                return

        if not self.serial_listener or not self.serial_listener.isRunning():
            QMessageBox.critical(self, "Error", "Could not start serial listener. Please check settings and COM connection.")
            return

        dialog = AddMappingDialog(self, self.serial_listener, self.ha_client)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.get_result()
            self.mappings.append(result)
            self.save_mappings_files()
            self.update_mappings_table()
            self.refresh_yaml_preview()
            QMessageBox.information(self, "Saved", f"Successfully mapped '{result['name']}' with {len(result['actions'])} actions.")

    def delete_selected_mapping(self):
        selected_rows = self.table.selectedItems()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Required", "Please select a mapping row in the table to delete.")
            return
            
        row = selected_rows[0].row()
        mapping_name = self.mappings[row]["name"]
        
        reply = QMessageBox.question(
            self, 
            "Delete Mapping", 
            f"Are you sure you want to delete the mapping '{mapping_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.mappings.pop(row)
            self.save_mappings_files()
            self.update_mappings_table()
            self.refresh_yaml_preview()

    def test_selected_mapping(self):
        selected_rows = self.table.selectedItems()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Required", "Please select a mapping row in the table to test.")
            return
            
        row = selected_rows[0].row()
        mapping = self.mappings[row]
        
        if not self.ha_client:
            QMessageBox.warning(self, "HA Client Not Ready", "Home Assistant client is not configured. Go to Settings.")
            return
            
        success_count = 0
        fail_messages = []
        actions = mapping.get("actions", [])
        
        for act in actions:
            entity_id = act["entity_id"]
            service_full = act["service"]
            domain, service = service_full.split(".", 1)
            success, msg = self.ha_client.call_service(domain, service, entity_id)
            if success:
                success_count += 1
            else:
                fail_messages.append(f"{service_full} -> {msg}")
                
        if success_count == len(actions):
            QMessageBox.information(self, "Test Success", f"Successfully triggered all {len(actions)} actions!")
        else:
            QMessageBox.warning(self, "Test Partial Success", f"Successfully triggered {success_count}/{len(actions)} actions.\nFailures:\n" + "\n".join(fail_messages))

    def refresh_yaml_preview(self):
        board = self.config.get("board_type", "esp32dev")
        wifi_ssid = self.config.get("wifi_ssid", "SSID")
        wifi_pass = self.config.get("wifi_password", "PASSWORD")
        pin = self.config.get("gpio_pin", "19")
        led_pin = self.config.get("onboard_led_pin", "2")
        
        yaml_content = esphome_templates.get_final_yaml(board, wifi_ssid, wifi_pass, pin, self.mappings, led_pin)
        self.yaml_preview.setText(yaml_content)

    def append_build_log(self, line):
        self.compile_console.append(line)
        self.compile_console.verticalScrollBar().setValue(self.compile_console.verticalScrollBar().maximum())

    def flash_recorder(self):
        board = self.config.get("board_type", "esp32dev")
        pin = self.config.get("gpio_pin", "19")
        led_pin = self.config.get("onboard_led_pin", "2")
        port = self.config.get("com_port", "")
        
        if not port:
            QMessageBox.warning(self, "COM Port Required", "Please select a COM port in Settings.")
            return
            
        if self.serial_listener and self.serial_listener.isRunning():
            self.toggle_serial_listening()
            
        yaml_content = esphome_templates.get_recorder_yaml(board, pin, led_pin)
        try:
            with open(RECORDER_YAML, "w") as f:
                f.write(yaml_content)
            build_yaml = os.path.join(ESPHOME_BUILD_DIR, "temp_recorder.yaml")
            with open(build_yaml, "w") as f:
                f.write(yaml_content)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to write temporary yaml: {e}")
            return
            
        self.compile_console.clear()
        self.append_build_log(f"--- Flashing ESP32 with Recorder Firmware ---")
        
        self.esphome_runner = ESPHomeRunner("temp_recorder.yaml", port, "run", cwd=ESPHOME_BUILD_DIR)
        self.esphome_runner.log_line.connect(self.append_build_log)
        self.esphome_runner.finished_with_result.connect(self.on_build_finished)
        
        self.flash_recorder_btn.setEnabled(False)
        self.flash_final_btn.setEnabled(False)
        self.stop_build_btn.setEnabled(True)
        self.esphome_runner.start()

    def flash_final_firmware(self):
        board = self.config.get("board_type", "esp32dev")
        wifi_ssid = self.config.get("wifi_ssid", "")
        wifi_pass = self.config.get("wifi_password", "")
        pin = self.config.get("gpio_pin", "19")
        led_pin = self.config.get("onboard_led_pin", "2")
        port = self.config.get("com_port", "")
        
        if not port:
            QMessageBox.warning(self, "COM Port Required", "Please select a COM port in Settings.")
            return
        if not wifi_ssid or not wifi_pass:
            QMessageBox.warning(self, "Credentials Required", "Please provide Wi-Fi SSID and Password in Settings.")
            return
            
        if self.serial_listener and self.serial_listener.isRunning():
            self.toggle_serial_listening()
            
        yaml_content = esphome_templates.get_final_yaml(board, wifi_ssid, wifi_pass, pin, self.mappings, led_pin)
        try:
            with open(FINAL_YAML, "w") as f:
                f.write(yaml_content)
            build_yaml = os.path.join(ESPHOME_BUILD_DIR, "final_remote_receiver.yaml")
            with open(build_yaml, "w") as f:
                f.write(yaml_content)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to write final yaml: {e}")
            return
            
        self.compile_console.clear()
        self.append_build_log(f"--- Compiling and Deploying Final Firmware ---")
        
        self.esphome_runner = ESPHomeRunner("final_remote_receiver.yaml", port, "run", cwd=ESPHOME_BUILD_DIR)
        self.esphome_runner.log_line.connect(self.append_build_log)
        self.esphome_runner.finished_with_result.connect(self.on_build_finished)
        
        self.flash_recorder_btn.setEnabled(False)
        self.flash_final_btn.setEnabled(False)
        self.stop_build_btn.setEnabled(True)
        self.esphome_runner.start()

    def stop_esphome_runner(self):
        if self.esphome_runner and self.esphome_runner.isRunning():
            self.esphome_runner.stop()
            self.append_build_log("\n--- Build execution stopped by user ---")

    def on_build_finished(self, success, msg):
        self.flash_recorder_btn.setEnabled(True)
        self.flash_final_btn.setEnabled(True)
        self.stop_build_btn.setEnabled(False)
        self.esphome_runner = None
        
        if success:
            QMessageBox.information(self, "Success", "Compilation and flash completed successfully!")
            self.append_build_log(f"\n[SUCCESS] {msg}")
        else:
            QMessageBox.critical(self, "Failed", f"Flash failed: {msg}")
            self.append_build_log(f"\n[FAILED] {msg}")

    def closeEvent(self, event):
        if self.serial_listener and self.serial_listener.isRunning():
            self.serial_listener.stop()
            self.serial_listener.wait()
        if self.esphome_runner and self.esphome_runner.isRunning():
            self.esphome_runner.stop()
            self.esphome_runner.wait()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = ESPHomeRemoteMapperApp()
    window.show()
    sys.exit(app.exec())
