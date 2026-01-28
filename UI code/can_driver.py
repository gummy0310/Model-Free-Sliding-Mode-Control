# can_driver.py
import os
import time
import can
from PyQt5.QtCore import QThread, pyqtSignal
import const 

class CanWorker(QThread):
    # (경과시간, 온도, 팬상태, PWM값)
    data_received = pyqtSignal(float, float, int, int)
    error_occurred = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.bus = None
        self.running = True
        self.start_time = time.time()

    def run(self):
        """스레드 실행 시 CAN 연결 및 데이터 수신 대기"""
        try:
            # 리눅스(Ubuntu) 환경이므로 socketcan 사용, 채널은 보통 'can0'
            # (만약 윈도우라면 'vector', 'pcan' 등으로 변경 필요)
            self.bus = can.interface.Bus(channel='can0', bustype='socketcan', bitrate=500000)
            print("CAN Bus Connected")
        except Exception as e:
            self.error_occurred.emit(f"CAN Connection Failed: {str(e)}")
            return

        while self.running:
            try:
                # 1초 타임아웃으로 메시지 대기
                msg = self.bus.recv(timeout=1.0)
                if msg and msg.arbitration_id == const.RX_ID_STATE:
                    self.process_rx_message(msg)
            except can.CanError as e:
                self.error_occurred.emit(f"CAN Recv Error: {str(e)}")
            except Exception as e:
                pass
        
        # 스레드 종료 시 연결 해제
        if self.bus:
            self.bus.shutdown()

    def process_rx_message(self, msg):
        """수신된 메시지 파싱 (RX_ID_STATE 구조에 맞게 수정 필요)"""
        # 예시: 데이터가 [Temp_H, Temp_L, Fan, PWM, ...] 형태라고 가정
        # 실제 MCU 프로토콜에 맞춰 인덱싱을 수정하세요.
        try:
            data = msg.data
            elapsed = time.time() - self.start_time
            
            # 임의의 파싱 로직 (실제 프로토콜에 맞게 수정 필요!)
            # 예: 첫 2바이트가 온도(x100), 3번째가 FAN, 4번째가 PWM
            temp_raw = int.from_bytes(data[0:2], byteorder='little') 
            current_temp = temp_raw / 100.0 if len(data) >= 2 else 0.0
            
            fan_state = data[2] if len(data) > 2 else 0
            current_pwm = data[3] if len(data) > 3 else 0
            
            self.data_received.emit(elapsed, current_temp, fan_state, current_pwm)
        except Exception as e:
            print(f"Parsing error: {e}")

    def stop(self):
        self.running = False
        self.wait()

    def send_control_message(self, pwm, fan_on, pid_enable, cooling_enable, target_temp):
        """명령 전송 (조용히 전송만 함)"""
        # bus가 연결되지 않았으면 무시 (이제 에러가 나지 않고 return됨)
        if not self.bus:
            return

        payload = [0] * 64
        
        # 1. PWM (Offset 0)
        payload[0] = max(0, min(100, int(pwm)))
        
        # 2. Fan (Offset 6)
        payload[6] = 1 if fan_on else 0
        
        # 3. PID Enable (Offset 12)
        payload[12] = 1 if pid_enable else 0
        
        # 4. Target Temp (Offset 18)
        raw_target = int(target_temp * 4)
        payload[18] = raw_target & 0xFF
        payload[19] = (raw_target >> 8) & 0xFF

        # 5. Cooling Mode (Offset 30)
        payload[30] = 1 if cooling_enable else 0

        msg = can.Message(arbitration_id=const.TX_ID_CTRL, data=payload, is_fd=True)
        
        try:
            self.bus.send(msg)
        except can.CanError:
            pass