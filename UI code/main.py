import sys
import csv
import os  # [추가] 폴더 생성을 위해 필요
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QGroupBox, QGridLayout,
                             QRadioButton, QButtonGroup, QSpinBox, QDoubleSpinBox, QCheckBox, QMessageBox, QLineEdit) # QLineEdit 추가됨
from PyQt5.QtCore import Qt, QTimer
import pyqtgraph as pg

from can_driver import CanWorker
import const 

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Thermal Control System (Manual Save Ver.)")
        self.resize(1300, 950)
        
        # [추가] 저장 폴더 자동 생성
        if not os.path.exists("data_logs"):
            os.makedirs("data_logs")

        # 데이터 저장소
        self.time_data = []
        self.temp_data = []
        self.target_data = [] 
        self.pwm_data = []

        # UI 표시용 캐싱 변수
        self.last_temp = 0.0
        self.last_pwm = 0
        self.last_fan = False

        # 제어 상태 변수 (Apply를 눌러야 갱신됨)
        self.current_pwm = 0
        self.current_fan = False
        self.current_pid_mode = False
        self.current_target = 0.0
        
        # CSV 관련 변수 (자동 저장 기능 제거로 인해 사용하지 않지만 호환성을 위해 None으로 둠)
        self.csv_file = None
        self.csv_writer = None

        # 타이머 설정
        self.tx_timer = QTimer()
        self.tx_timer.setInterval(100) # 10Hz
        self.tx_timer.timeout.connect(self.send_heartbeat)

        self.plot_timer = QTimer()
        self.plot_timer.setInterval(50)  # 20Hz
        self.plot_timer.timeout.connect(self.update_ui)

        # 워커 생성
        self.worker = CanWorker()
        self.worker.data_received.connect(self.handle_new_data)
        self.worker.error_occurred.connect(self.handle_error)

        self.initUI()

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # 1. 그래프 영역 (변경 없음)
        self.temp_plot_widget = pg.PlotWidget()
        self.temp_plot_widget.setTitle("Temperature Monitor", color="w", size="12pt")
        self.temp_plot_widget.setLabel("left", "Temperature (°C)")
        self.temp_plot_widget.showGrid(x=True, y=True)
        self.temp_plot_widget.addLegend()
        self.temp_line = self.temp_plot_widget.plot(pen=pg.mkPen('y', width=2), name="Current Temp")
        self.target_line = self.temp_plot_widget.plot(pen=pg.mkPen('r', width=2, style=Qt.DashLine), name="Target Temp")
        
        self.pwm_plot_widget = pg.PlotWidget()
        self.pwm_plot_widget.setLabel("left", "PWM (%)")
        self.pwm_plot_widget.setLabel("bottom", "Time (s)")
        self.pwm_plot_widget.showGrid(x=True, y=True)
        self.pwm_plot_widget.setYRange(0, 105) 
        self.pwm_plot_widget.setXLink(self.temp_plot_widget)
        self.pwm_line = self.pwm_plot_widget.plot(pen=pg.mkPen('c', width=2), name="PWM Output")

        main_layout.addWidget(self.temp_plot_widget, stretch=2)
        main_layout.addWidget(self.pwm_plot_widget, stretch=1)
        
        # 2. 하단 패널
        control_panel = QHBoxLayout()
        main_layout.addLayout(control_panel, stretch=1)

        # [상태창] (변경 없음)
        grp_status = QGroupBox("Current Status")
        layout_status = QGridLayout()
        self.lbl_temp = QLabel("0.0 °C")
        self.lbl_temp.setStyleSheet("font-size: 30px; font-weight: bold; color: #2196F3;")
        self.lbl_fan = QLabel("FAN: OFF")
        self.lbl_fan.setStyleSheet("font-size: 20px; font-weight: bold; color: gray;")
        self.lbl_pwm = QLabel("PWM: 0%")
        self.lbl_pwm.setStyleSheet("font-size: 20px;")

        layout_status.addWidget(QLabel("Temperature:"), 0, 0)
        layout_status.addWidget(self.lbl_temp, 0, 1)
        layout_status.addWidget(self.lbl_fan, 1, 0, 1, 2)
        layout_status.addWidget(self.lbl_pwm, 2, 0, 1, 2)
        grp_status.setLayout(layout_status)
        control_panel.addWidget(grp_status)

        # [제어 설정창] (변경 없음)
        grp_control = QGroupBox("Control Settings")
        layout_control = QVBoxLayout()

        self.radio_manual = QRadioButton("Manual Mode")
        self.radio_pid = QRadioButton("PID Mode")
        self.radio_manual.setChecked(True)
        
        self.btn_group = QButtonGroup()
        self.btn_group.addButton(self.radio_manual)
        self.btn_group.addButton(self.radio_pid)
        
        self.radio_manual.toggled.connect(self.on_mode_changed)
        self.radio_pid.toggled.connect(self.on_mode_changed)

        layout_control.addWidget(self.radio_manual)
        layout_control.addWidget(self.radio_pid)

        self.widget_manual = QWidget()
        lay_man = QHBoxLayout()
        lay_man.addWidget(QLabel("PWM (%):"))
        self.spin_pwm = QSpinBox()
        self.spin_pwm.setRange(0, 100)
        lay_man.addWidget(self.spin_pwm)
        self.chk_fan = QCheckBox("FAN ON")
        lay_man.addWidget(self.chk_fan)
        self.widget_manual.setLayout(lay_man)
        
        self.widget_pid = QWidget()
        lay_pid = QHBoxLayout()
        lay_pid.addWidget(QLabel("Target Temp:"))
        self.spin_target = QDoubleSpinBox()
        self.spin_target.setRange(0.0, 100.0)
        self.spin_target.setValue(25.0)
        self.spin_target.setSingleStep(0.5)
        lay_pid.addWidget(self.spin_target)
        self.widget_pid.setLayout(lay_pid)
        self.widget_pid.setVisible(False)

        layout_control.addWidget(self.widget_manual)
        layout_control.addWidget(self.widget_pid)
        
        layout_control.addStretch()

        self.btn_apply = QPushButton("Apply Settings")
        self.btn_apply.setMinimumHeight(40)
        self.btn_apply.clicked.connect(self.apply_settings)
        self.btn_apply.setEnabled(False)
        layout_control.addWidget(self.btn_apply)

        self.btn_start = QPushButton("START SYSTEM")
        self.btn_start.setMinimumHeight(50)
        self.btn_start.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_start.clicked.connect(self.start_system)
        layout_control.addWidget(self.btn_start)

        self.btn_stop = QPushButton("STOP (Emergency)")
        self.btn_stop.setMinimumHeight(50)
        self.btn_stop.setStyleSheet("background-color: red; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_stop.clicked.connect(self.emergency_stop)
        self.btn_stop.setEnabled(False) 
        layout_control.addWidget(self.btn_stop)
        
        grp_control.setLayout(layout_control)
        control_panel.addWidget(grp_control)

        # ---------------------------------------------------------
        # [추가됨] 데이터 저장창 (Data Recording)
        # ---------------------------------------------------------
        grp_save = QGroupBox("Data Recording")
        layout_save = QVBoxLayout()
        
        layout_save.addWidget(QLabel("File Name:"))
        self.edit_filename = QLineEdit()
        self.edit_filename.setPlaceholderText("Empty = Timestamp") # 비워두면 시간으로 저장
        layout_save.addWidget(self.edit_filename)
        
        self.btn_save = QPushButton("SAVE DATA\n(CSV + PNG)")
        self.btn_save.setMinimumHeight(60)
        self.btn_save.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_save.clicked.connect(self.manual_save) # 저장 버튼 연결
        layout_save.addWidget(self.btn_save)
        
        layout_save.addStretch()
        grp_save.setLayout(layout_save)
        control_panel.addWidget(grp_save) # 패널에 추가
        # ---------------------------------------------------------

    # [추가됨] 수동 저장 함수
    def manual_save(self):
        # 1. 파일 이름 결정
        user_input = self.edit_filename.text().strip()
        if not user_input:
            # 이름 입력 안하면 현재 시간 사용
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename_base = f"log_{timestamp}"
        else:
            filename_base = user_input

        # 경로 설정 (data_logs 폴더)
        csv_path = f"data_logs/{filename_base}.csv"
        img_path = f"data_logs/{filename_base}.png"

        try:
            # 2. CSV 저장 (지금까지 메모리에 쌓인 데이터 전체 저장)
            with open(csv_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Time(sec)", "Temperature(C)", "PWM(%)"])
                # 데이터 리스트를 순회하며 저장
                for i in range(len(self.time_data)):
                    writer.writerow([
                        f"{self.time_data[i]:.3f}", 
                        f"{self.temp_data[i]:.2f}", 
                        self.pwm_data[i]
                    ])

            # 3. 스크린샷 저장
            pixmap = self.grab()
            pixmap.save(img_path, 'png')

            QMessageBox.information(self, "Save Success", f"Saved successfully!\nLocation: data_logs/\nFile: {filename_base}")
            
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save: {e}")

    def start_system(self):
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_apply.setEnabled(True)
        
        self.apply_settings()

        # [변경] 자동 CSV 로거 시작 부분 제거함
        # self.init_csv_logger()  <-- 삭제됨

        if not self.worker.isRunning():
            self.worker.start()
        self.tx_timer.start()
        self.plot_timer.start()
        
        print("System Started.")

    def apply_settings(self):
        if self.radio_manual.isChecked():
            self.current_pwm = self.spin_pwm.value()
            self.current_fan = self.chk_fan.isChecked()
            self.current_pid_mode = False
            print(f"Applied: Manual Mode, PWM={self.current_pwm}, FAN={self.current_fan}")
        else:
            self.current_target = self.spin_target.value()
            self.current_pid_mode = True
            print(f"Applied: PID Mode, Target={self.current_target}")

    def stop_all(self):
        self.worker.running = False
        self.worker.wait()
        self.tx_timer.stop()
        self.plot_timer.stop()
        # [변경] 자동 저장 로직 삭제됨

    def emergency_stop(self):
        print("!!! EMERGENCY STOP !!!")
        
        self.current_pwm = 0
        self.current_fan = False
        self.current_pid_mode = False
        self.current_target = 0.0

        self.send_heartbeat()

        self.tx_timer.stop()
        self.plot_timer.stop()

        try:
            self.worker.data_received.disconnect(self.handle_new_data)
        except:
            pass

        # [변경] 자동 저장/닫기 로직 삭제됨
        
        self.btn_stop.setText("STOPPED")
        self.btn_stop.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.btn_start.setEnabled(False)
        
        self.lbl_pwm.setText("PWM: 0% (STOP)")
        self.lbl_pwm.setStyleSheet("font-size: 20px; font-weight: bold; color: red;")
        
        QMessageBox.warning(self, "System Stopped", "Emergency Stop! Use 'SAVE DATA' button to save logs.")

    def closeEvent(self, event):
        self.stop_all()
        event.accept()

    def handle_new_data(self, elapsed, temp, fan, pwm):
        self.time_data.append(elapsed)
        self.temp_data.append(temp)
        self.pwm_data.append(pwm)
        
        if self.current_pid_mode:
            self.target_data.append(self.current_target)
        else:
            self.target_data.append(float('nan'))

        self.last_temp = temp
        self.last_pwm = pwm
        self.last_fan = bool(fan)

        # csv_writer는 이제 None이므로 아래 코드는 동작하지 않음 (메모리에만 쌓임)
        if self.csv_writer:
            try:
                self.csv_writer.writerow([f"{elapsed:.3f}", f"{temp:.2f}", pwm])
            except Exception:
                pass

    def update_ui(self):
        if not self.time_data:
            return

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

    def handle_error(self, msg):
        print(f"Error: {msg}")

    def on_mode_changed(self):
        is_pid = self.radio_pid.isChecked()
        self.widget_pid.setVisible(is_pid)
        self.widget_manual.setVisible(not is_pid)

    def send_heartbeat(self):
        self.worker.send_control_message(
            pwm=self.current_pwm,
            fan_on=self.current_fan,
            pid_enable=self.current_pid_mode,
            target_temp=self.current_target
        )

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())