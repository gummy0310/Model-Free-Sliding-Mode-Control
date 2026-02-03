# STM32 G4 형상기억합금 직물형 구동기 온도제어 펌웨어

## 소프트웨어 구조

### 주요 모듈

1. **메인 제어 모듈**
   - 시스템 초기화 및 조정
   - 타이머 기반 이벤트 처리
   - 안전 상태 관리

2. **온도 측정 모듈**
   - MAX31855 센서 인터페이스
   - 온도 데이터 보정 및 필터링
   - 센서 오류 감지

3. **PID 제어 모듈**
   - 각 채널별 PID 제어 로직
   - 적분 항 와인드업 방지
   - 동적 출력 조정

4. **안전 관리 모듈**
   - 온도 임계값 모니터링
   - 계층적 안전 모드
   - 오류 복구 메커니즘

5. **통신 모듈**
   - FDCAN 메시지 처리
   - 진단 및 모니터링 데이터 송신
   - PID 파라미터 원격 조정

### 작동 흐름

1. 시스템 초기화 및 필요한 모든 주변장치 설정
2. 정해진 주기(TIM4)로 온도 센서에서 데이터 읽기
3. 온도 데이터 유효성 검사 및 안전 상태 확인
4. PID 알고리즘 실행하여 필요한 PWM 출력 계산
5. 온도 상태에 따라 팬 작동 여부 결정
6. FDCAN을 통해 상태 정보 전송 및 원격 명령 수신

## 주요 기능

###PID 온도 제어
각 채널은 독립적인 PID 제어기를 가지고 있어 정밀한 온도 제어가 가능합니다:
c// PID 계산 함수
float Calculate_PID(PID_TypeDef* pid, float current_temp, uint8_t channel) {
    // 오차 계산
    float error = pid->setpoint - current_temp;
    
    // 적분항 계산, 적분 와인드업 방지
    pid->error_sum += error;
    
    // 미분항 계산
    float error_diff = error - pid->last_error;
    pid->last_error = error;
    
    // PID 출력 계산
    float output = pid->kp * error + pid->ki * pid->error_sum + pid->kd * error_diff;
    
    // 출력 제한
    if (output > pid->output_max) output = pid->output_max;
    if (output < pid->output_min) output = pid->output_min;
    
    return output;
}
계층적 안전 모드 시스템
시스템은 4단계의 안전 모드를 구현하여 안전한 작동을 보장합니다:

정상 모드 (0): 일반 작동 상태
1단계 안전 모드 (1): 온도가 max_temp(80°C) 초과 시 활성화
2단계 안전 모드 (2): 온도가 critical_temp(120°C) 초과 시 활성화
센서 오류 모드 (3): 온도가 비정상적(200°C 초과 또는 -50°C 미만)일 때 활성화

안전 모드 활성화 시 다음과 같은 조치가 취해집니다:

팬 강제 작동
PWM 출력 중단 또는 제한
PID 제어 비활성화 (필요시)
진단 메시지 출력

히스테리시스 기반 안전 모드 복구
안전 모드에서 정상 모드로의 복귀는 히스테리시스 메커니즘을 사용하여 경계값 부근에서의 모드 전환 진동을 방지합니다.

안전 모드 상태 전이도

아래 상태 전이도는 시스템의 안전 모드 간 전환 조건과 각 상태에서의 시스템 동작을 보여줍니다:

정상 모드(0)에서: 		온도 ≥ 80°C --> 1단계 안전 모드로 전환
			온도 ≥ 120°C --> 직접 2단계 안전 모드로 전환
			온도 > 200°C  또는 < -50°C --> 센서 오류 모드로 전환


1단계 안전 모드(1)에서:	온도 < 75°C --> 정상 모드로 복귀 (5°C 히스테리시스 적용)
			온도 ≥ 120°C --> 2단계 안전 모드로 전환
			센서 오류 감지 --> 센서 오류 모드로 전환


2단계 안전 모드(2)에서:	온도 ≤ 30°C --> 정상 모드로 복귀 (완전 냉각 필요)
		 	센서 오류 감지 --> 센서 오류 모드로 전환


센서 오류 모드(3)에서:	센서 정상화 감지 --> 정상 모드로 복귀



각 상태에서의 시스템 동작:

정상 모드: PWM 정상 출력, 팬은 온도 차이에 따라 제어, PID 제어 활성화
1단계 안전 모드: PWM 정상 출력 유지, 팬 강제 켜짐, PID 제어 활성화 유지
2단계 안전 모드: PWM 강제 0 설정, 팬 강제 켜짐, PID 제어 비활성화, 복구 플래그 설정
센서 오류 모드: PWM 강제 0 설정, 팬 강제 켜짐, PID 제어 비활성화

### 센서 오류 감지

온도 센서의 오작동을 감지하고 적절한 안전 조치를 취합니다:

```c
// 온도가 비정상적으로 높거나 낮은 경우 센서 오류로 판단
if (current_temp > system.pid_controllers[channel].sensor_error_temp || current_temp < -50.0f) {
    // 센서 오류 안전 모드 활성화 및 안전 조치
    system.pid_controllers[channel].safety_mode = 3;
    // PWM 출력 중단, 팬 작동
    *system.pnt_pwm[channel] = 0;
    FSW_on(channel);
    // ...
    return false;
}
```

### FDCAN 통신

FDCAN을 통해 원격 제어 및 모니터링 기능을 제공합니다:

- **0x400**: 제어 메시지 (PWM, 팬, PID 활성화, 목표 온도)
- **0x401**: 상태 메시지 (현재 온도, PWM 출력, 팬 상태)
- **0x402**: PID 파라미터 조정 메시지 (Kp, Ki, Kd 값)

### 작동 모드

- **수동 모드**: FDCAN을 통해 PWM 출력과 팬 상태를 직접 제어
예시 3: 채널 2를 수동 모드로 PWM 70%, 팬 켜기
ID: 0x400
DATA: 00 00 46 00 00 00 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 ... 00

- **PID 제어 모드**: 목표 온도를 설정하면 시스템이 자동으로 온도 유지
예시: 채널 0과 1을 목표 온도 50°C로 PID 제어 활성화

목표 온도 = 50°C * 4 = 200 = 0xC8 
2바이트 형식 => C8 00

ID: 0x400
DATA: 00 00 00 00 00 00 00 00 00 00 00 00 01 01 00 00 00 00 C8 00 C8 00 00 00 00 00 00 00 00 00 ... 00


## 구성 옵션

### PID 파라미터 조정

각 채널의 PID 파라미터는 FDCAN 메시지를 통해 조정할 수 있습니다:

```c
// PID 튜닝 메시지 처리 (0x402)
system.pid_controllers[ch].kp = system.buf_fdcan_pid_tuning.struc.kp;
system.pid_controllers[ch].ki = system.buf_fdcan_pid_tuning.struc.ki;
system.pid_controllers[ch].kd = system.buf_fdcan_pid_tuning.struc.kd;
```

PID 튜닝 메시지 예제 (ID: 0x402)
채널 1의 PID 파라미터를 Kp=2.5, Ki=0.1, Kd=0.05로 설정:
바이트 0: 0x01 (채널 1)
바이트 1-4: 0x40200000 (2.5를 IEEE 754 부동소수점으로 표현)
바이트 5-8: 0x3DCCCCCD (0.1을 IEEE 754 부동소수점으로 표현)
바이트 9-12: 0x3D4CCCCD (0.05를 IEEE 754 부동소수점으로 표현)
실제 16진수 데이터 형식:
ID: 0x402
DATA: 01 00 00 20 40 CD CC CC 3D CD CC 4C 3D 00 00 00

### 안전 임계값 설정

안전 모드 임계값은 `Init_PID_Controllers()` 함수에서 초기화됩니다:

```c
// 기본 설정
system.pid_controllers[i].max_temp = 80.0f;      // 1단계 안전 모드 온도
system.pid_controllers[i].critical_temp = 120.0f; // 2단계 안전 모드 온도
system.pid_controllers[i].sensor_error_temp = 200.0f; // 센서 오류 판단 온도
```

## 통신 프로토콜

### FDCAN 메시지 형식

#### 제어 메시지 (ID: 0x400)
- `pwm[CTRL_CH]`: 각 채널 PWM 출력 설정 (0-100%)
- `fan[CTRL_CH]`: 각 채널 팬 상태 설정 (0: OFF, 1: ON)
- `pid_enable[CTRL_CH]`: 각 채널 PID 제어 활성화 (0: 비활성화, 1: 활성화)
- `target_temp[CTRL_CH]`: 목표 온도 설정 (0.25°C 단위)

#### 상태 메시지 (ID: 0x401)
- `temp[CTRL_CH]`: 현재 측정된 온도
- `fan[CTRL_CH]`: 현재 팬 상태 및 안전모드 상태
- `pwm[CTRL_CH]`: 현재 PWM 출력값

#### PID 튜닝 메시지 (ID: 0x402)
- `channel`: 대상 채널 (0-5)
- `kp`: 비례 게인
- `ki`: 적분 게인
- `kd`: 미분 게인



이 펌웨어는 형상기억합금 기반 직물형 구동기의 온도 제어를 위해 개발되었습니다. 문의사항이나 기여는 프로젝트 저장소를 통해 해주시기 바랍니다.

최종 업데이트: 2025년 4월