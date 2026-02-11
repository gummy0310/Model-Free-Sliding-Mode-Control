#include "main.h"

PID_Manager_typedef pid;

// =========================================================
// PID 파라미터 설정
// =========================================================
#define KP  3.3f
#define KI  0.002f
#define KD  0.0f
// 최대 PWM 출력 제한 (0.0 ~ 100.0)
#define MAX_PWM_LIMIT  100.0f
// =========================================================

// PID
float Calculate_Ctrl(PID_Param_TypeDef* pid_param, float current_temp, uint8_t channel)
{
    pid_param->kp = KP;
    pid_param->ki = KI;
    pid_param->kd = KD;

    float error = pid_param->setpoint - current_temp;
    pid_param->error_sum += error;

    // 적분항 누적 제한
    float max_error_sum = (pid_param->ki != 0.0f) ? (pid_param->output_max / pid_param->ki) : pid_param->output_max;
    if (pid_param->error_sum > max_error_sum) pid_param->error_sum = max_error_sum;
    if (pid_param->error_sum < -max_error_sum) pid_param->error_sum = -max_error_sum;

    // 미분항 계산
    float error_diff = error - pid_param->last_error;
    pid_param->last_error = error;

    // PID 출력 계산
    float output = pid_param->kp * error + pid_param->ki * pid_param->error_sum + pid_param->kd * error_diff;

    // 출력 제한
    if (output > pid_param->output_max) output = pid_param->output_max;
    if (output < pid_param->output_min) output = pid_param->output_min;

    return output;
}

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

bool Check_Temperature_Sensor(uint8_t channel, float current_temp) //센서오류 판단 함수
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

bool Check_Safety_Temperature(uint8_t channel, float current_temp) //안전온도 판단 함수
{
    if (current_temp >= SAFETY_LIMIT_TEMP) // 안전온도 초과
    {
        if (pid.params[channel].safety_mode == 0) pid.params[channel].safety_mode = 1;
        FSW_on(channel);
        Update_Fan_Status(channel);
        if (pid.enable_pid[channel]) pid.params[channel].setpoint = SAFETY_TARGET_TEMP;
        else {
            *system.pnt_pwm[channel] = 0;
            system.state_pwm[channel] = 0;
        }
        return true;
    }
    else if (pid.params[channel].safety_mode == 1 && current_temp <= SAFETY_TARGET_TEMP)
    {
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

void Init_PID_Controllers(void)
{
    for (uint8_t i = 0; i < CTRL_CH; i++) {
        pid.params[i].kp = KP;
        pid.params[i].ki = KI;
        pid.params[i].kd = KD;
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
