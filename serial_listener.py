import re
import serial
import serial.tools.list_ports
import time
from PyQt6.QtCore import QThread, pyqtSignal

class SerialListener(QThread):
    # Signals
    code_captured = pyqtSignal(str, dict)  # protocol, data
    log_line = pyqtSignal(str)              # raw serial line
    error_occurred = pyqtSignal(str)        # error message
    connected_status = pyqtSignal(bool)    # status change

    def __init__(self, port: str, baud_rate: int = 115200):
        super().__init__()
        self.port = port
        self.baud_rate = baud_rate
        self.running = False
        self.serial_conn = None
        
        # Pronto code state variables
        self.collecting_pronto = False
        self.pronto_buffer = []
        self.last_pronto_time = 0.0

        # Regex patterns for different ESPHome IR logs
        self.nec_pattern = re.compile(r"Received NEC: address=(0x[0-9a-fA-F]+),\s+command=(0x[0-9a-fA-F]+)")
        self.samsung_pattern = re.compile(r"Received Samsung: data=(0x[0-9a-fA-F]+)(?:,\s+nbits=(\d+))?")
        self.sony_pattern = re.compile(r"Received Sony: data=(0x[0-9a-fA-F]+)(?:,\s+nbits=(\d+))?")
        self.lg_pattern = re.compile(r"Received LG: data=(0x[0-9a-fA-F]+)(?:,\s+nbits=(\d+))?")
        self.panasonic_pattern = re.compile(r"Received Panasonic: address=(0x[0-9a-fA-F]+),\s+command=(0x[0-9a-fA-F]+)")
        self.raw_pattern = re.compile(r"Received Raw: ([\d,\s-]+)")

    @staticmethod
    def get_available_ports():
        """Lists all available serial ports on the system."""
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]

    def stop(self):
        """Stops the thread loop and closes serial connection."""
        self.running = False
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.close()
            except Exception:
                pass
        self.connected_status.emit(False)

    def run(self):
        self.running = True
        try:
            self.serial_conn = serial.Serial(self.port, self.baud_rate, timeout=0.1)
            self.connected_status.emit(True)
            self.log_line.emit(f"--- Listening on {self.port} at {self.baud_rate} baud ---")
        except serial.SerialException as e:
            self.error_occurred.emit(f"Failed to open port {self.port}: {str(e)}")
            self.connected_status.emit(False)
            return

        buffer = ""
        while self.running:
            try:
                if not self.serial_conn.is_open:
                    break
                
                # Check for Pronto collection timeout (150ms of silence completes the Pronto block)
                if self.collecting_pronto and (time.time() - self.last_pronto_time > 0.15):
                    if self.pronto_buffer:
                        pronto_code = " ".join(self.pronto_buffer).strip()
                        self.code_captured.emit("PRONTO", {"data": pronto_code})
                    self.collecting_pronto = False
                    self.pronto_buffer = []

                # Read bytes
                data = self.serial_conn.read(self.serial_conn.in_waiting or 1)
                if not data:
                    continue
                
                # Decode to string
                try:
                    buffer += data.decode('utf-8', errors='ignore')
                except Exception:
                    continue

                # Process lines
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    
                    self.log_line.emit(line)
                    self.parse_line(line)

            except serial.SerialException as e:
                self.error_occurred.emit(f"Serial connection lost: {str(e)}")
                self.connected_status.emit(False)
                break
            except Exception as e:
                self.log_line.emit(f"[Internal Error] {str(e)}")

        self.stop()

    def parse_line(self, line: str):
        """Parses an ESPHome serial log line for IR codes."""
        # Clean up color codes if any
        clean_line = re.sub(r'\x1b\[[0-9;]*m', '', line)

        # Check for Pronto Protocol logs
        if "Received Pronto: data=" in clean_line:
            if self.collecting_pronto and self.pronto_buffer:
                pronto_code = " ".join(self.pronto_buffer).strip()
                self.code_captured.emit("PRONTO", {"data": pronto_code})
            self.collecting_pronto = True
            self.pronto_buffer = []
            self.last_pronto_time = time.time()
            return

        if self.collecting_pronto and "remote.pronto" in clean_line:
            parts = clean_line.split("]:", 1)
            if len(parts) > 1:
                content = parts[1].strip()
                if "Received Pronto: data=" not in content:
                    self.pronto_buffer.append(content)
                    self.last_pronto_time = time.time()
            return

        # 1. NEC Protocol
        nec_match = self.nec_pattern.search(clean_line)
        if nec_match:
            address = nec_match.group(1)
            command = nec_match.group(2)
            data = {
                "address": address,
                "command": command
            }
            self.code_captured.emit("NEC", data)
            return

        # 2. Samsung Protocol
        samsung_match = self.samsung_pattern.search(clean_line)
        if samsung_match:
            data_val = samsung_match.group(1)
            nbits = samsung_match.group(2)
            nbits = int(nbits) if nbits else 32
            data = {
                "data": data_val,
                "nbits": nbits
            }
            self.code_captured.emit("SAMSUNG", data)
            return

        # 3. Sony Protocol
        sony_match = self.sony_pattern.search(clean_line)
        if sony_match:
            data_val = sony_match.group(1)
            nbits = sony_match.group(2)
            nbits = int(nbits) if nbits else 12
            data = {
                "data": data_val,
                "nbits": nbits
            }
            self.code_captured.emit("SONY", data)
            return

        # 4. LG Protocol
        lg_match = self.lg_pattern.search(clean_line)
        if lg_match:
            data_val = lg_match.group(1)
            nbits = lg_match.group(2)
            nbits = int(nbits) if nbits else 28
            data = {
                "data": data_val,
                "nbits": nbits
            }
            self.code_captured.emit("LG", data)
            return

        # 5. Panasonic Protocol
        panasonic_match = self.panasonic_pattern.search(clean_line)
        if panasonic_match:
            address = panasonic_match.group(1)
            command = panasonic_match.group(2)
            data = {
                "address": address,
                "command": command
            }
            self.code_captured.emit("PANASONIC", data)
            return

        # 6. Raw Protocol
        raw_match = self.raw_pattern.search(clean_line)
        if raw_match:
            raw_str = raw_match.group(1)
            try:
                raw_code = [
                    int(x.strip()) 
                    for x in raw_str.split(",") 
                    if x.strip().replace('-', '').isdigit()
                ]
                if raw_code:
                    data = {
                        "raw_code": raw_code
                    }
                    self.code_captured.emit("RAW", data)
            except Exception as e:
                print(f"Error parsing raw code: {e}")
            return
