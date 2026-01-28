import sys
import csv
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox
from PyQt5.QtCore import Qt, QTimer
from PyQt5 import uic  # [중요] ui 파일을 로드하기 위한 모듈
import pyqtgraph as pg

from can_driver import CanWorker 
import const 

# UI 파일 로드 (같은 폴더에 main_ui.ui 파일이 있어야 함)
form_class = uic.loadUiType("main_ui.ui")[0]

class MainWindow(QMainWindow, form_class):
    def __init__(self):
        super().__init__()
        
        # 1. UI 설정 로드
        self.setupUi(self)  
        
        # 2. UI 파일에서 정의하지 못한 그래프 위젯 추가 (코드 유지)
        self.init_graphs()
        
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
        
        # CSV 및 로그 이름 관련 변수
        self.csv_file = None
        self.csv_writer = None
        self.current_log_name = None 

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

        # 3. 시그널 연결 (버튼 동작 등)
        self.connect_signals()

        # 초기 모드 UI 설정
        self.widget_pid.setVisible(False)

    def init_graphs(self):
        """UI 파일의 빈 영역(Layout)에 PyQtGraph 위젯을 집어넣음"""
        # 온도 그래프
        self.temp_plot_widget = pg.PlotWidget()
        self.temp_plot_widget.setTitle("Temperature Monitor", color="w", size="12pt")
        self.temp_plot_widget.setLabel("left", "Temperature (°C)")
        self.temp_plot_widget.showGrid(x=True, y=True)
        self.temp_plot_widget.addLegend()
        self.temp_line = self.temp_plot_widget.plot(pen=pg.mkPen('y', width=2), name="Current Temp")
        self.target_line = self.temp_plot_widget.plot(pen=pg.mkPen('r', width=2, style=Qt.DashLine), name="Target Temp")
        
        # UI 파일에 만들어둔 'layout_graph_temp' 레이아웃에 추가
        self.layout_graph_temp.addWidget(self.temp_plot_widget)

        # PWM 그래프
        self.pwm_plot_widget = pg.PlotWidget()
        self.pwm_plot_widget.setLabel("left", "PWM (%)")
        self.pwm_plot_widget.setLabel("bottom", "Time (s)")
        self.pwm_plot_widget.showGrid(x=True, y=True)
        self.pwm_plot_widget.setYRange(0, 105) 
        self.pwm_plot_widget.setXLink(self.temp_plot_widget)
        self.pwm_line = self.pwm_plot_widget.plot(pen=pg.mkPen('c', width=2), name="PWM Output")

        # UI 파일에 만들어둔 'layout_graph_pwm' 레이아웃에 추가
        self.layout_graph_pwm.addWidget(self.pwm_plot_widget)

    def connect_signals(self):
        """버튼 및 기타 위젯 이벤트 연결"""
        # UI 파일에서 objectName으로 설정한 위젯들을 self.이름 으로 바로 접근 가능
        self.radio_manual.toggled.connect(self.on_mode_changed)
        self.radio_pid.toggled.connect(self.on_mode_changed)
        
        self.btn_apply.clicked.connect(self.apply_settings)
        self.btn_start.clicked.connect(self.start_system)
        self.btn_stop.clicked.connect(self.emergency_stop)

    def init_csv_logger(self):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_log_name = f"log_{timestamp}"
            
            filename = f"{self.current_log_name}.csv"
            self.csv_file = open(filename, mode='w', newline='', encoding='utf-8')
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(["Time(sec)", "Temperature(C)", "PWM(%)"])
            print(f"CSV Logging started: {filename}")
        except Exception as e:
            print(f"Failed to open CSV file: {e}")

    def save_snapshot(self):
        if self.current_log_name:
            try:
                pixmap = self.grab()
                image_filename = f"{self.current_log_name}.png"
                pixmap.save(image_filename, 'png')
                print(f"Snapshot saved: {image_filename}")
            except Exception as e:
                print(f"Failed to save snapshot: {e}")

    def start_system(self):
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_apply.setEnabled(True)
        
        self.apply_settings()
        self.init_csv_logger()

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
        
        if self.csv_file:
            self.save_snapshot()
            self.csv_file.close()
            self.csv_file = None

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

        if self.csv_file:
            self.save_snapshot()
            self.csv_file.close()
            self.csv_file = None
            print("CSV File Closed.")

        self.btn_stop.setText("STOPPED")
        self.btn_stop.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.btn_start.setEnabled(False)
        
        self.lbl_pwm.setText("PWM: 0% (STOP)")
        self.lbl_pwm.setStyleSheet("font-size: 20px; font-weight: bold; color: red;")
        
        QMessageBox.warning(self, "System Stopped", "Current cut (PWM 0) and logging stopped.\nSnapshot Saved.")

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