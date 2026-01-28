# can_driver.py

    # 기존 함수 정의를 아래와 같이 변경 (cooling_enable 인자 추가)
    def send_control_message(self, pwm, fan_on, pid_enable, cooling_enable, target_temp):
        """명령 전송 (조용히 전송만 함)"""
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

        # 5. Cooling Mode (Offset 30) - [새로 추가된 부분]
        # 구조체 순서: PWM(6) + FAN(6) + ENABLE_PID(6) + TARGET_TEMP(12) = 30
        payload[30] = 1 if cooling_enable else 0

        msg = can.Message(arbitration_id=const.TX_ID_CTRL, data=payload, is_fd=True)
        
        try:
            self.bus.send(msg)
        except can.CanError:
            pass