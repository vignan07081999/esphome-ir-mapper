import subprocess
import os
import signal
from PyQt6.QtCore import QThread, pyqtSignal

class ESPHomeRunner(QThread):
    # Signals
    log_line = pyqtSignal(str)                   # stdout lines
    finished_with_result = pyqtSignal(bool, str) # success, message

    def __init__(self, yaml_path: str, port: str, command_type: str = "run", cwd: str = None):
        """
        command_type can be "run" (compile + upload) or "compile" (compile only).
        """
        super().__init__()
        self.yaml_path = yaml_path
        self.port = port
        self.command_type = command_type
        self.cwd = cwd
        self.process = None
        self.running = False

    def stop(self):
        """Terminates the running ESPHome process."""
        self.running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass

    def run(self):
        self.running = True
        
        if self.command_type == "run":
            cmd = ["python", "-m", "esphome", "run", "--no-logs", "--device", self.port, self.yaml_path]
        else:
            cmd = ["python", "-m", "esphome", "compile", self.yaml_path]
            
        self.log_line.emit(f"Executing: {' '.join(cmd)}")
        if self.cwd:
            self.log_line.emit(f"Working Directory: {self.cwd}")
        self.log_line.emit("Starting ESPHome compiler. This may take a few minutes for the first compilation...\n")
        
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                startupinfo=startupinfo,
                cwd=self.cwd
            )

            while self.running:
                line = self.process.stdout.readline()
                if not line:
                    if self.process.poll() is not None:
                        break
                    continue
                
                self.log_line.emit(line.rstrip('\r\n'))

            exit_code = self.process.wait()
            self.running = False
            
            if exit_code == 0:
                self.finished_with_result.emit(True, "Process completed successfully!")
            else:
                self.finished_with_result.emit(False, f"Process failed with exit code {exit_code}.")
                
        except Exception as e:
            self.running = False
            self.finished_with_result.emit(False, f"Exception occurred: {str(e)}")
