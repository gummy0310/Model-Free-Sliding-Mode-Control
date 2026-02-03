# SMA Soft-Robot Controller (MFSMC Implementation)

이 프로젝트는 **형상 기억 합금(SMA, Shape Memory Alloy)** 기반의 소프트 로봇 액추에이터를 정밀 제어하기 위한 STM32 펌웨어입니다.

**MFSMC(Model-Free Sliding Mode Control)** 알고리즘으로, SMA 특유의 히스테리시스(Hysteresis)와 비선형성을 극복하고 강인한 온도 및 변위 추적 성능을 확보하는 것을 목표로 합니다.

## 🚀 Key Features

* **MFSMC 제어 알고리즘**: 복잡한 수학적 모델 없이 시스템의 오차와 상태 변화를 기반으로 제어 입력을 산출하는 슬라이딩 모드 제어 구현.
* **Dual Mode Operation**:
    * **Manual Mode**: 사용자가 직접 PWM Duty와 Fan On/Off를 제어.
    * **Auto Mode**: 설정 온도(Setpoint)를 추종하기 위한 자동 제어 루프 실행.
* **Safety Logic**: 과열 방지(Overheat Protection) 및 센서 이상 감지 시 자동 전원 차단 (PWM 0%, Fan ON).
* **CAN FD Communication**: 호스트 PC 또는 상위 제어기와 CAN FD를 통해 실시간 데이터 모니터링 및 파라미터 튜닝 지원.

## 🛠 Hardware & Environment

* **MCU**: STM32 Series (STM32G4 or H7 recommended based on FDCAN usage)
* **Actuator**: SMA Wire / Spring Actuators
* **Sensor**: Thermocouple / RTD (via ADC interface)
* **Cooling**: DC Cooling Fans
* **Language**: C
* **IDE/Toolchain**: STM32CubeIDE

## 📂 Project Structure

| File | Description |
|---|---|
| `main.c` | 시스템 초기화, CAN 통신 핸들링, 타이머 인터럽트(Control Loop), 안전 로직 구현 |
| `mfsmc.c` | MFSMC 알고리즘 코어 로직 (`MFSMC_Compute`, 초기화 함수 등) |
| `mfsmc.h` | MFSMC 제어 파라미터 구조체 정의 (`MFSMC_Params`, `MFSMC_Data`) |
| `main.h` | 전역 매크로, 하드웨어 핀 정의, 시스템 상태 구조체 선언 |

## 📡 Communication Protocol (CAN FD)

* **Baudrate**: (설정에 따라 기입, 예: 1Mbps / 5Mbps)
* **ID Specification**:

| Direction | ID | DLC | Description |
|---|---|---|---|
| **RX** (Host -> MCU) | `0x101` | - | 제어 명령 및 파라미터 설정 |
| **TX** (MCU -> Host) | `0x201` | - | 현재 온도, PWM 상태, 에러 값 피드백 |

### RX Command List (Data Byte 0)
1.  **SYSTEM_ON**: 제어 시작
2.  **SYSTEM_OFF**: 제어 정지 (PWM Off)
3.  **MODE_MANUAL**: 수동 모드 전환
4.  **MODE_AUTO**: 자동(MFSMC) 모드 전환
5.  **CMD_RESET**: 시스템 리셋
6.  **CMD_UPDATE_PARAM**: 제어 파라미터 실시간 튜닝

## ⚠️ Known Issues & Todo

### 🚧 Refactoring in Progress (PID -> MFSMC)
현재 제어 로직은 MFSMC로 변경되었으나, 일부 변수명과 함수 구조체에 **Legacy PID Naming**이 남아 있습니다.
* 예: `pid.enable_pid` → 실제로는 MFSMC 활성화 플래그로 사용됨.
* 예: `Control_Fan_By_Temperature` 함수 등 레거시 로직 정리 필요.

**Next Step**:
- [ ] `pid` 관련 구조체 이름을 `ctrl` 또는 `mfsmc`로 전체 리팩토링 (`refactor/pid-to-mfsmc` 브랜치에서 진행 중).
- [ ] 매뉴얼 모드 시 타이머 인터럽트 간섭 문제 해결.

---
**Date**: 2024.05.21