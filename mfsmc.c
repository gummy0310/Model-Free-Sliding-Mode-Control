// Experiment 1 + 냉각필요시 gain 4배 증폭
#include "main.h"

PID_Manager_typedef pid;

// =========================================================
// MFSMC 파라미터 설정
// =========================================================
// LAMBDA (구 kp): 반응 속도 vs 오버슈트 억제
// 가열용/냉각용으로 분리
// 1. 가열 시 (Target > Current):
#define MFSMC_LAMBDA_HEAT   1.5f
// 2. 냉각 시 (Target < Current): 하강 관성에 의해 히터가 켜지는 것을 방지하기 위해 매우 작게 설정
#define MFSMC_LAMBDA_COOL    0.0f

// ALPHA (구 ki): 시스템 모델 추정치 (입력 민감도)
// - 의미: PWM 1을 줬을 때 1초에 몇 도 오르는가?
// - 값을 키우면: 제어기가 "히터 성능 좋네"라고 생각해서 출력을 살살 냄 (오버슈트 방지)
// - 값을 줄이면: 제어기가 "히터 약하네"라고 생각해서 출력을 팍팍 냄
#define MFSMC_ALPHA   2.0f

// GAIN (구 kd): 외란 제거 및 추종 강도
#define MFSMC_GAIN  2.0f

// PHI: Boundary Layer Thickness
#define MFSMC_PHI   15.0f

// 최대 PWM 출력 제한 (0.0 ~ 100.0)
#define MAX_PWM_LIMIT  100.0f
// =========================================================


// 더 이상 구간별 업데이트 함수는 필요 없음
void Update_PID_Gains_By_Temp(PID_Param_TypeDef* pid_param, float current_temp, uint8_t channel)
{
    // MFSMC는 전 구간 자동 적응하므로 고정값 사용. lambda는 기본값을 heat으로 설정
    pid_param->kp = MFSMC_LAMBDA_HEAT;
    pid_param->ki = MFSMC_ALPHA;
    pid_param->kd = MFSMC_GAIN;
}

// MFSMC 알고리즘 구현... 이름만 PID 형식 유지
float Calculate_PID(PID_Param_TypeDef* pid_param, float current_temp, uint8_t channel)
{
    // 시간차 (dt)
    static uint32_t last_call_time[CTRL_CH] = {0};
    uint32_t current_time = HAL_GetTick();
    if (last_call_time[channel] == 0) {
        last_call_time[channel] = current_time;
        return 0.0f;
    }
    float dt = (current_time - last_call_time[channel]) / 1000.0f; //ms 단위를 s로 변환
    last_call_time[channel] = current_time;
    if (dt <= 0.0f || dt > 1.0f) dt = 0.1f;

    // 오차 계산 (Target - Current)
    float error = pid_param->setpoint - current_temp;

    // 오차 변화율 (Error Dot)
    float error_dot = (error - pid_param->last_error) / dt;

    // 상태에 따른 gain scheduling
    float lambda;
    float alpha = MFSMC_ALPHA;
    float K_gain = MFSMC_GAIN;
    if (error < 0) {
        // [냉각 필요 구간]
        // 목표온도보다 온도가 높으면 기존 Gain보다 훨씬 강하게 눌러줘야 함
        // F_hat을 이겨내고 PWM을 0으로 만들기 위해 Gain을 증폭
        K_gain = MFSMC_GAIN * 4.0f;
        lambda = MFSMC_LAMBDA_COOL;
    } else {
        // [가열 필요 구간]
        lambda = MFSMC_LAMBDA_HEAT;
    }

    // Time Delay Estimation (F_hat 추정: 현재 상태 유지에 필요한 힘)
    // 식: dot(e) = F - alpha * u
    // 이항하면: F = dot(e) + alpha * u
    float u_old = pid_param->error_sum;
    float F_hat = error_dot + (alpha * u_old);

    // 슬라이딩 표면 (s) 계산
    float s = error + (lambda * error_dot);

    // [Saturation 로직]
    // s/phi 값을 구해서 -1 ~ 1 사이로 제한
    float phi = MFSMC_PHI;
    float sat_val;
    float ratio = s / phi;
    if (ratio > 1.0f) sat_val = 1.0f;
    else if (ratio < -1.0f) sat_val = -1.0f;
    else sat_val = ratio;

    // MFSMC 제어 입력 계산
    float output = (1.0f / alpha) * ( F_hat + (K_gain * sat_val) );

    // 데이터 갱신
    pid_param->last_error = error;

    // 출력 제한 및 저장
    if (output > pid_param->output_max) output = pid_param->output_max;
    if (output < 0.0f) output = 0.0f;

    pid_param->error_sum = output;

    return output;
}

// -----------------------------------------------------------
// 아래 함수들은 기존 로직 그대로 유지
// -----------------------------------------------------------

bool Check_Temperature_Rise_Rate(uint8_t channel, float current_temp) {
    const float MIN_RISE_RATE_PER_SEC = 1.0f;
    const uint32_t MAX_LOW_RISE_TIME = 1500;
    const uint8_t MIN_PWM_FOR_MONITORING = 30;

    uint32_t current_time = HAL_GetTick();
    uint8_t current_pwm = system.state_pwm[channel];

    // 부팅중이거나 안전모드인 경우 모니터링 건너뜀
    if (pid.startup_phase || pid.params[channel].safety_mode > 0) return true;

    // PWM이 관찰수준 이상이면 모니터링 시작
    if ((current_pwm >= MIN_PWM_FOR_MONITORING) && !pid.params[channel].rise_rate_monitoring) {
        pid.params[channel].rise_rate_monitoring = true;
        pid.params[channel].last_tracked_temp = current_temp;
        pid.params[channel].last_tracked_time = current_time;
        pid.params[channel].low_rise_time = 0;
        return true;
    }

    if (pid.params[channel].rise_rate_monitoring) {
        uint32_t elapsed = current_time - pid.params[channel].last_tracked_time;
        if (elapsed >= 1000) {
            float temp_change = current_temp - pid.params[channel].last_tracked_temp;
            float rise_rate = temp_change / (elapsed / 1000.0f);

            // 온도상승률이 부족 시간이 임계값 초과 시 안전모드 진입
            if (rise_rate < MIN_RISE_RATE_PER_SEC && current_pwm >= MIN_PWM_FOR_MONITORING) {
                pid.params[channel].low_rise_time += elapsed;
                if (pid.params[channel].low_rise_time >= MAX_LOW_RISE_TIME) {
                    if (pid.params[channel].safety_mode == 0) {
                        printf("CH %u 센서 오류: 온도 상승 부족!\r\n", channel);
                        pid.params[channel].safety_mode = 3;
                        *system.pnt_pwm[channel] = 0;
                        system.state_pwm[channel] = 0;
                        FSW_on(channel);
                        Update_Fan_Status(channel);
                        pid.enable_pid[channel] = 0;
                    }
                    return false;
                }
            } else {
                pid.params[channel].low_rise_time = 0;
            }
            pid.params[channel].last_tracked_temp = current_temp;
            pid.params[channel].last_tracked_time = current_time;
        }
    }

    if (pid.params[channel].rise_rate_monitoring && current_pwm < MIN_PWM_FOR_MONITORING) {
        pid.params[channel].rise_rate_monitoring = false;
    }
    return true;
}

void Update_Fan_Status(uint8_t channel)
{
    bool fan_physical_state = (system.state_fsw[channel] > 0) ? true : false;
    switch (pid.params[channel].safety_mode) {
        case 0: system.state_fsw[channel] = fan_physical_state ? FAN_ON : FAN_OFF; break;
        case 1: system.state_fsw[channel] = FAN_SAFETY_LEVEL1; break;
        case 3: system.state_fsw[channel] = FAN_SENSOR_ERROR; break;
    }
    if (pid.params[channel].safety_mode > 0) FSW_on(channel);
}

bool Check_Temperature_Sensor(uint8_t channel, float current_temp)
{
    if (pid.startup_phase) return true;
    if (current_temp > 200.0f || current_temp < -10.0f) {
        if (pid.params[channel].safety_mode != 3) {
            pid.params[channel].safety_mode = 3;
            *system.pnt_pwm[channel] = 0;
            system.state_pwm[channel] = 0;
            FSW_on(channel);
            Update_Fan_Status(channel);
            pid.enable_pid[channel] = 0;
        }
        return false;
    } else if (pid.params[channel].safety_mode == 3) {
        pid.params[channel].safety_mode = 0;
        Update_Fan_Status(channel);
    }
    return true;
}

bool Check_Safety_Temperature(uint8_t channel, float current_temp)
{
    if (current_temp >= SAFETY_LIMIT_TEMP) {
        if (pid.params[channel].safety_mode == 0) pid.params[channel].safety_mode = 1;
        FSW_on(channel);
        Update_Fan_Status(channel);
        if (pid.enable_pid[channel]) pid.params[channel].setpoint = SAFETY_TARGET_TEMP;
        else {
            *system.pnt_pwm[channel] = 0;
            system.state_pwm[channel] = 0;
        }
        return true;
    } else if (pid.params[channel].safety_mode == 1 && current_temp <= SAFETY_TARGET_TEMP) {
        pid.params[channel].safety_mode = 0;
        Update_Fan_Status(channel);
        return false;
    }
    return (pid.params[channel].safety_mode > 0);
}

void Control_Fan_By_Temperature(uint8_t channel, float current_temp, float target_temp)
{
    if (pid.params[channel].safety_mode > 0) return;
    uint32_t current_time = HAL_GetTick();

    if (current_temp >= (target_temp + TEMP_HIGH_THRESHOLD) && system.state_fsw[channel] == FAN_OFF) {
        FSW_on(channel);
        system.state_fsw[channel] = FAN_ON;
        pid.last_fan_toggle[channel] = current_time;
        Update_Fan_Status(channel);
    } else if (current_temp <= (target_temp + TEMP_LOW_THRESHOLD) && system.state_fsw[channel] == FAN_ON) {
        FSW_off(channel);
        system.state_fsw[channel] = FAN_OFF;
        pid.last_fan_toggle[channel] = current_time;
        Update_Fan_Status(channel);
    }
}

void Set_PWM_Output(uint8_t channel, uint8_t duty_cycle)
{
    if (duty_cycle > 100) duty_cycle = 100;
    if (pid.params[channel].safety_mode) duty_cycle = 0;
    *system.pnt_pwm[channel] = duty_cycle;
    system.state_pwm[channel] = duty_cycle;
}

bool Apply_Feedforward_Control(uint8_t channel, float current_temp, float target_temp)
{
    static bool is_pid_active[CTRL_CH] = {false};
    if (!is_pid_active[channel]) {
        pid.params[channel].error_sum = 0.0f;
        pid.params[channel].last_error = 0.0f;
        is_pid_active[channel] = true;
    }
    return true;
}

void Init_PID_Controllers(void)
{
    for (uint8_t i = 0; i < CTRL_CH; i++) {
        pid.params[i].kp = MFSMC_LAMBDA_HEAT;
        pid.params[i].ki = MFSMC_ALPHA;
        pid.params[i].kd = MFSMC_GAIN;
        pid.params[i].setpoint = 50.0f;
        pid.params[i].error_sum = 0.0f;
        pid.params[i].last_error = 0.0f;
        pid.params[i].output_min = 0.0f;
        pid.params[i].output_max = MAX_PWM_LIMIT;
        pid.params[i].max_temp = 80.0f;
        pid.params[i].safety_mode = 0;
        pid.params[i].rise_rate_monitoring = false;
        pid.params[i].last_tracked_temp = 0.0f;
        pid.params[i].last_tracked_time = 0;
        pid.params[i].low_rise_time = 0;
        pid.enable_pid[i] = 0;
    }
    pid.shared_data.new_temp_data = 0;
    pid.shared_data.temp_timestamp = 0;
    for (uint8_t i = 0; i < CTRL_CH; i++) pid.shared_data.temp_data[i] = 0.0f;
}