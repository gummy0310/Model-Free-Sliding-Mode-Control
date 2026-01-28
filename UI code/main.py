import sys
import csv
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QGroupBox, QGridLayout,
                             QRadioButton, QButtonGroup, QSpinBox, QDoubleSpinBox, QCheckBox, QMessageBox)
from PyQt5.QtCore import Qt, QTimer
import pyqtgraph as pg

from can_driver import CanWorker 
import const 

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Thermal Control System (Cooling Mode Added)")
        self.resize(950, 950) 
        
        # 데이터 저장소
        self.time_data = []
        self.temp_data = []
        self.target_data = [] 
        self.pwm_data = []

        # UI 표시용 캐싱 변수
        self.last_temp = 0.0
        self.last_pwm = 0
        self.last_fan = False

        # 제어 상태 변수
        self.current_pwm = 0
        self.current_fan = False
        self.current_pid_mode = False
        self.current_target = 0.0
        # [추가] 쿨링 모드 상태
        self.current_cooling_mode = False
        
        # CSV 및 로그 이름 관련 변수
        self.csv_file = None
        self.csv_writer = None
        self.current_log_name = None 

        self.init_ui()

        # CAN 쓰레드 시작
        self.can_worker = CanWorker()
        self.can_worker.data_received.connect(self.update_data)
        self.can_worker.error_occurred.connect(self.handle_error)
        self.can_worker.start()

        # 주기적 전송 타이머 (0.1초)
        self.timer = QTimer()
        self.timer.timeout.connect(self.send_command)
        self.timer.start(100)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        # Layout
        main_layout = QVBoxLayout()
        central.setLayout(main_layout)

        # 1. 상태 표시부 (상단)
        status_group = self.setup_status_ui()
        main_layout.addWidget(status_group)

        # 2. 그래프 영역 (중간)
        graph_group = self.setup_graph_ui()
        main_layout.addWidget(graph_group)

        # 3. 제어 패널 (하단)
        control_group = self.setup_control_ui()
        main_layout.addWidget(control_group)

    def setup_status_ui(self):
        group = QGroupBox("Status Monitor")
        layout = QHBoxLayout()
        
        self.lbl_temp = QLabel("0.0 °C")
        self.lbl_temp.setStyleSheet("font-size: 30px; font-weight: bold; color: #2196F3;")
        self.lbl_temp.setAlignment(Qt.AlignCenter)

        self.lbl_pwm = QLabel("PWM: 0%")
        self.lbl_pwm.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.lbl_pwm.setAlignment(Qt.AlignCenter)

        self.lbl_fan = QLabel("FAN: OFF")
        self.lbl_fan.setStyleSheet("font-size: 20px; font-weight: bold; color: gray;")
        self.lbl_fan.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.lbl_temp)
        layout.addWidget(self.lbl_pwm)
        layout.addWidget(self.lbl_fan)
        group.setLayout(layout)
        return group

    def setup_graph_ui(self):
        group = QGroupBox("Real-time Graph")
        layout = QVBoxLayout()
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setYRange(0, 100)
        self.plot_widget.addLegend()

        self.temp_line = self.plot_widget.plot(pen=pg.mkPen('r', width=2), name="Temp")
        self.target_line = self.plot_widget.plot(pen=pg.mkPen('g', width=2, style=Qt.DashLine), name="Target")
        self.pwm_line = self.plot_widget.plot(pen=pg.mkPen('b', width=1), name="PWM")

        layout.addWidget(self.plot_widget)
        group.setLayout(layout)
        return group

    def setup_control_ui(self):
        group = QGroupBox("Control Panel")
        layout = QVBoxLayout()
        
        # --- Mode Selection ---
        mode_layout = QHBoxLayout()
        self.bg_mode = QButtonGroup()
        
        self.radio_manual = QRadioButton("Manual Mode")
        self.radio_pid = QRadioButton("PID Mode")
        self.radio_manual.setChecked(True)
        
        self.bg_mode.addButton(self.radio_manual)
        self.bg_mode.addButton(self.radio_pid)
        
        mode_layout.addWidget(self.radio_manual)
        mode_layout.addWidget(self.radio_pid)
        
        self.radio_manual.toggled.connect(self.on_mode_changed)
        self.radio_pid.toggled.connect(self.on_mode_changed)
        
        layout.addLayout(mode_layout)

        # --- Setting Area ---
        self.widget_manual = QWidget()
        man_layout = QHBoxLayout()
        man_layout.addWidget(QLabel("Manual PWM (%):"))
        self.slider_pwm = QSpinBox()
        self.slider_pwm.setRange(0, 100)
        man_layout.addWidget(self.slider_pwm)
        self.widget_manual.setLayout(man_layout)
        
        self.widget_pid = QWidget()
        pid_layout = QHBoxLayout()
        pid_layout.addWidget(QLabel("Target Temp (°C):"))
        self.spin_target = QDoubleSpinBox()
        self.spin_target.setRange(0, 200)
        self.spin_target.setValue(30.0)
        pid_layout.addWidget(self.spin_target)
        self.widget_pid.setLayout(pid_layout)
        self.widget_pid.setVisible(False)

        layout.addWidget(self.widget_manual)
        layout.addWidget(self.widget_pid)
        
        # --- Fan & Cooling ---
        option_layout = QHBoxLayout()
        self.chk_fan = QCheckBox("FAN Enable")
        option_layout.addWidget(self.chk_fan)

        # [추가] Cooling Button
        self.btn_cooling = QPushButton("COOLING MODE: OFF")
        self.btn_cooling.setCheckable(True)
        self.btn_cooling.setStyleSheet("background-color: lightgray; padding: 5px; font-weight: bold;")
        self.btn_cooling.clicked.connect(self.toggle_cooling)
        option_layout.addWidget(self.btn_cooling)

        layout.addLayout(option_layout)

        # --- Apply Button (Log Start/Stop logic if needed) ---
        self.btn_apply = QPushButton("APPLY / START LOG")
        self.btn_apply.setFixedHeight(40)
        self.btn_apply.clicked.connect(self.on_apply_clicked)
        layout.addWidget(self.btn_apply)

        group.setLayout(layout)
        return group

    def toggle_cooling(self):
        if self.btn_cooling.isChecked():
            self.current_cooling_mode = True
            self.btn_cooling.setText("COOLING MODE: ON (Active)")
            self.btn_cooling.setStyleSheet("background-color: #2196F3; color: white; padding: 5px; font-weight: bold;")
        else:
            self.current_cooling_mode = False
            self.btn_cooling.setText("COOLING MODE: OFF")
            self.btn_cooling.setStyleSheet("background-color: lightgray; color: black; padding: 5px; font-weight: bold;")
        
        # 즉시 전송
        self.send_command()

    def update_data(self, elapsed, temp, fan, pwm):
        self.last_temp = temp
        self.last_pwm = pwm
        self.last_fan = (fan == 1)
        
        self.time_data.append(elapsed)
        self.temp_data.append(temp)
        self.target_data.append(self.current_target if self.current_pid_mode else 0)
        self.pwm_data.append(pwm)

        # 데이터 길이 제한 (성능 최적화)
        if len(self.time_data) > 1000:
            self.time_data.pop(0)
            self.temp_data.pop(0)
            self.target_data.pop(0)
            self.pwm_data.pop(0)

        # 그래프 업데이트
        self.temp_line.setData(self.time_data, self.temp_data)
        self.target_line.setData(self.time_data, self.target_data)
        self.pwm_line.setData(self.time_data, self.pwm_data)

        self.lbl_temp.setText(f"{self.last_temp:.1f} °C")
        self.lbl_pwm.setText(f"PWM: {self.last_pwm}%")
        
        if self.last_temp > 70.0:
            self.lbl_temp.setStyleSheet("font-size: 30px; font-weight: bold; color: red;")
        else:
            self.lbl_temp.setStyleSheet("font-size: 30px; font-weight: bold; color: #2196F3;")

        if self.last_fan:
            self.lbl_fan.setText("FAN: ON")
            self.lbl_fan.setStyleSheet("font-size: 20px; font-weight: bold; color: green;")
        else:
            self.lbl_fan.setText("FAN: OFF")
            self.lbl_fan.setStyleSheet("font-size: 20px; font-weight: bold; color: gray;")

        # CSV Logging
        if self.csv_writer:
            self.csv_writer.writerow([elapsed, temp, self.current_target, pwm, 1 if self.last_fan else 0])

    def handle_error(self, msg):
        print(f"Error: {msg}")

    def on_mode_changed(self):
        is_pid = self.radio_pid.isChecked()
        self.widget_pid.setVisible(is_pid)
        self.widget_manual.setVisible(not is_pid)

    def on_apply_clicked(self):
        # UI 값을 멤버 변수에 저장 (타이머에서 이 값을 사용하여 전송)
        self.current_pid_mode = self.radio_pid.isChecked()
        self.current_target = self.spin_target.value()
        self.current_pwm = self.slider_pwm.value()
        self.current_fan = self.chk_fan.isChecked()
        
        # CSV 시작 로직 (파일명 생성 등) - 간소화
        if not self.csv_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_log_name = f"log_{timestamp}.csv"
            try:
                self.csv_file = open(self.current_log_name, 'w', newline='')
                self.csv_writer = csv.writer(self.csv_file)
                self.csv_writer.writerow(["Time", "Temp", "Target", "PWM", "Fan"])
                print(f"Logging started: {self.current_log_name}")
                self.btn_apply.setText("STOP LOG")
            except Exception as e:
                print(f"File Error: {e}")
        else:
            # Stop Logging
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None
            self.btn_apply.setText("APPLY / START LOG")
            print("Logging stopped")

        # 즉시 전송
        self.send_command()

    def send_command(self):
        if not self.can_worker.running:
            return

        # PID 모드면 타겟 온도 사용, 아니면 Manual PWM 사용
        # (하지만 send_control_message는 모든 인자를 받으므로 그대로 전달)
        
        # 만약 Manual 모드라면 타겟 온도는 의미 없지만, 
        # 프로토콜 유지를 위해 UI 값을 보냄.
        # MCU측에서 Enable PID 플래그를 보고 판단함.
        
        self.can_worker.send_control_message(
            pwm=self.current_pwm,
            fan_on=self.current_fan,
            pid_enable=self.current_pid_mode,
            target_temp=self.current_target,
            cooling_enable=self.current_cooling_mode # [추가된 인자]
        )

    def closeEvent(self, event):
        if self.csv_file:
            self.csv_file.close()
        self.can_worker.running = False
        self.can_worker.wait()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())