import os
import time
import can
from PyQt5.QtCore import QThread, pyqtSignal
import const 

class CanWorker(QThread):
    # (경과시간, 온도, 팬상태, PWM값, 쿨링모드상태) -> 인자 추가됨
    data_received = pyqtSignal(float, float, int, int, int)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = False
        self.bus = None
        self.start_time = 0

    def run(self):
        """수신 루프 (백그라운드)"""
        try:
            # os.system("sudo ip link set can0 down")
            # os.system("sudo ip link set can0 up type can bitrate 1000000 dbitrate 1000000 fd on")
            self.bus = can.interface.Bus(channel="can0", interface="socketcan", fd=True)
        except Exception as e:
            self.error_occurred.emit(f"CAN Init Error: {e}")
            return

        self.running = True
        self.start_time = time.time()

        while self.running:
            try:
                msg = self.bus.recv(timeout=0.1)
                if msg and msg.arbitration_id == const.RX_ID_STATE:
                    data = msg.data
                    if len(data) >= 24:
                        pwm = data[0]
                        fan = data[6]
                        raw_temp = data[12] | (data[13] << 8)
                        temp = raw_temp / 4.0
                        
                        # [NEW] 쿨링 모드 상태 수신 (Index 30)
                        is_cooling = 0
                        if len(data) >= 31:
                            is_cooling = data[30]

                        elapsed = time.time() - self.start_time
                        
                        # 시그널 발생 (인자 5개)
                        self.data_received.emit(elapsed, temp, fan, pwm, is_cooling)
            except Exception:
                pass

        if self.bus:
            self.bus.shutdown()
        # os.system("sudo ip link set can0 down")

    def send_control_message(self, pwm, fan_on, pid_enable, target_temp, cooling_mode):
        """명령 전송 (cooling_mode 인자 추가됨)"""
        if not self.bus:
            return

        payload = [0] * 64
        
        payload[0] = max(0, min(100, int(pwm)))
        payload[6] = 1 if fan_on else 0
        payload[12] = 1 if pid_enable else 0
        
        raw_target = int(target_temp * 4)
        payload[18] = raw_target & 0xFF
        payload[19] = (raw_target >> 8) & 0xFF
        
        # [NEW] 쿨링 모드 플래그 (Index 30)
        payload[30] = 1 if cooling_mode else 0

        msg = can.Message(
            arbitration_id=const.TX_ID_CTRL,
            data=payload,
            is_extended_id=False,
            is_fd=True
        )
        try:
            self.bus.send(msg)
        except can.CanError:
            pass

    def stop(self):
        self.running = False
        self.wait()