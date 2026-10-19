/*
 * SPDX-FileCopyrightText: 2021-2022 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define ENABLE_ONBOARD_LED 1

#if ENABLE_ONBOARD_LED
#include "driver/rmt_tx.h"
#include "led_strip_encoder.h"
#endif

// Added headers for network, NTP, and RGB LED functionality
#include "nvs_flash.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_sntp.h"

#define DHT22_GPIO GPIO_NUM_21
#define DHT22_TIMEOUT_US 100

#if ENABLE_ONBOARD_LED
#define BOARD_RGB_LED_GPIO GPIO_NUM_38 //GPIO_NUM_48
#define BOARD_RGB_LED_PIXELS 1
#define RMT_LED_STRIP_RESOLUTION_HZ 10000000
#endif

// Wi‑Fi configuration - change these to match your network credentials
#define WIFI_SSID      "Mio4"
#define WIFI_PASS      "ceffxpnfax"

// Timezone configuration (example: Europe/Vienna or Central European Time)
#define LOCAL_TIMEZONE "CET-1CEST,M3.5.0,M10.5.0/3"

static const char *TAG = "dht22";
static portMUX_TYPE dht22_mux = portMUX_INITIALIZER_UNLOCKED;

#if ENABLE_ONBOARD_LED
static rmt_channel_handle_t led_channel = NULL;
static rmt_encoder_handle_t led_encoder = NULL;
#endif

static esp_err_t wait_for_level(int level)
{
    int64_t start_us = esp_timer_get_time();

    while (gpio_get_level(DHT22_GPIO) != level) {
        if (esp_timer_get_time() - start_us >= DHT22_TIMEOUT_US) {
            return ESP_ERR_TIMEOUT;
        }
        esp_rom_delay_us(1);
    }

    return ESP_OK;
}

static esp_err_t dht22_read(float *temperature_c, float *humidity_percent)
{
    uint8_t data[5] = {0};
    esp_err_t result;

    if (temperature_c == NULL || humidity_percent == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    result = gpio_set_direction(DHT22_GPIO, GPIO_MODE_OUTPUT_OD);
    if (result != ESP_OK) {
        return result;
    }
    result = gpio_set_level(DHT22_GPIO, 0);
    if (result != ESP_OK) {
        return result;
    }
    esp_rom_delay_us(1200);
    result = gpio_set_level(DHT22_GPIO, 1);
    if (result != ESP_OK) {
        return result;
    }
    esp_rom_delay_us(30);
    result = gpio_set_direction(DHT22_GPIO, GPIO_MODE_INPUT);
    if (result != ESP_OK) {
        return result;
    }

    taskENTER_CRITICAL(&dht22_mux);

    result = wait_for_level(0);
    if (result == ESP_OK) {
        result = wait_for_level(1);
    }
    if (result == ESP_OK) {
        result = wait_for_level(0);
    }

    for (int bit = 0; bit < 40 && result == ESP_OK; bit++) {
        result = wait_for_level(1);
        if (result != ESP_OK) {
            break;
        }

        int64_t pulse_start_us = esp_timer_get_time();
        result = wait_for_level(0);
        if (result != ESP_OK) {
            break;
        }

        data[bit / 8] <<= 1;
        if (esp_timer_get_time() - pulse_start_us > 40) {
            data[bit / 8] |= 1;
        }
    }

    taskEXIT_CRITICAL(&dht22_mux);

    if (result != ESP_OK) {
        return result;
    }

    if ((uint8_t)(data[0] + data[1] + data[2] + data[3]) != data[4]) {
        return ESP_ERR_INVALID_CRC;
    }

    uint16_t humidity_raw = ((uint16_t)data[0] << 8) | data[1];
    uint16_t temperature_raw = ((uint16_t)(data[2] & 0x7F) << 8) | data[3];

    *humidity_percent = humidity_raw / 10.0f;
    *temperature_c = temperature_raw / 10.0f;
    if (data[2] & 0x80) {
        *temperature_c = -*temperature_c;
    }

    return ESP_OK;
}

static void format_log_timestamp(char *buffer, size_t buffer_size)
{
    time_t now = time(NULL);
    struct tm timeinfo;

    if (now > 1577836800 && localtime_r(&now, &timeinfo) != NULL) {
        strftime(buffer, buffer_size, "%Y-%m-%d %H:%M:%S", &timeinfo);
        return;
    }

    snprintf(buffer, buffer_size, "uptime %lld s (NTP pending)", (long long)(esp_timer_get_time() / 1000000LL));
}

#if ENABLE_ONBOARD_LED
typedef struct {
    const char *classification;
    const char *hex_code;
    uint8_t r;
    uint8_t g;
    uint8_t b;
} comfort_status_t;

static comfort_status_t classify_comfort(float temp, float humidity)
{
    if (temp < 16.0f) {
        return (comfort_status_t){"Extreme Cold", "#4A00E0", 74, 0, 224};
    } else if (temp < 19.0f) {
        return (comfort_status_t){"Chilly", "#3498DB", 52, 152, 219};
    } else if (temp < 21.5f) {
        return (comfort_status_t){"Cool / Crisp", "#2ECC71", 46, 204, 113};
    } else if (temp <= 23.5f) {
        if (humidity > 65.0f) {
            return (comfort_status_t){"Sticky / Damp", "#3498DB", 52, 152, 219};
        }
        return (comfort_status_t){"Very Comfortable", "#27AE60", 39, 174, 96};
    } else if (temp <= 25.0f) {
        if (humidity > 60.0f) {
            return (comfort_status_t){"Stuffy / Hot", "#E74C3C", 231, 76, 60};
        }
        return (comfort_status_t){"Warm", "#F39C12", 243, 156, 18};
    } else if (temp <= 28.0f) {
        if (humidity <= 45.0f) {
            return (comfort_status_t){"Warm", "#F39C12", 243, 156, 18};
        } else if (humidity <= 60.0f) {
            return (comfort_status_t){"Stuffy / Hot", "#E74C3C", 231, 76, 60};
        }
        return (comfort_status_t){"Sticky / Damp", "#3498DB", 52, 152, 219};
    } else {
        return (comfort_status_t){"Extreme Heat", "#8B0000", 139, 0, 0};
    }
}

static void update_onboard_led(const char *time_buffer, float temp, float humidity)
{
    comfort_status_t comfort = classify_comfort(temp, humidity);

    if (led_channel == NULL || led_encoder == NULL) {
        ESP_LOGI(TAG, "[%s] Temperature: %.1f C | Humidity: %.1f%% | Comfort: %s (%s) | LED: not connected",
                 time_buffer, temp, humidity, comfort.classification, comfort.hex_code);
        return;
    }

    uint8_t pixel_data[3] = {comfort.g, comfort.b, comfort.r};
    rmt_transmit_config_t tx_config = {
        .loop_count = 0,
    };

    ESP_ERROR_CHECK(rmt_transmit(led_channel, led_encoder, pixel_data, sizeof(pixel_data), &tx_config));
    ESP_ERROR_CHECK(rmt_tx_wait_all_done(led_channel, portMAX_DELAY));
    ESP_LOGI(TAG, "[%s] Temperature: %.1f C | Humidity: %.1f%% | Comfort: %s (%s) | LED RGB: R=%u G=%u B=%u",
             time_buffer, temp, humidity, comfort.classification, comfort.hex_code, comfort.r, comfort.g, comfort.b);
}
#endif

void time_sync_notification_cb(struct timeval *tv)
{
    ESP_LOGI(TAG, "Notification: system time synchronised with NTP!");
}

static void initialize_sntp(void)
{
    ESP_LOGI(TAG, "Initialising SNTP...");
    esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
    esp_sntp_setservername(0, "pool.ntp.org");
    esp_sntp_set_time_sync_notification_cb(time_sync_notification_cb);
    esp_sntp_init();
    setenv("TZ", LOCAL_TIMEZONE, 1);
    tzset();
}

static void wifi_event_handler(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *event = (wifi_event_sta_disconnected_t *)event_data;
        ESP_LOGW(TAG, "Wi‑Fi disconnected (reason=%d). Reconnecting...", event->reason);
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) event_data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        initialize_sntp();
    }
}

static void connect_wifi(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, &instance_any_id));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, &instance_got_ip));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
            .pmf_cfg = {
                .capable = true,
                .required = false,
            },
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_start());
}

#if ENABLE_ONBOARD_LED
static void configure_rgb_led(void)
{
    ESP_LOGI(TAG, "Configuring onboard RGB LED via RMT...");
    rmt_tx_channel_config_t tx_chan_config = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .gpio_num = BOARD_RGB_LED_GPIO,
        .mem_block_symbols = 64,
        .resolution_hz = RMT_LED_STRIP_RESOLUTION_HZ,
        .trans_queue_depth = 4,
    };
    ESP_ERROR_CHECK(rmt_new_tx_channel(&tx_chan_config, &led_channel));

    led_strip_encoder_config_t encoder_config = {
        .resolution = RMT_LED_STRIP_RESOLUTION_HZ,
    };
    ESP_ERROR_CHECK(rmt_new_led_strip_encoder(&encoder_config, &led_encoder));
    ESP_ERROR_CHECK(rmt_enable(led_channel));

    uint8_t black_pixel[3] = {0, 0, 0};
    rmt_transmit_config_t tx_config = {
        .loop_count = 0,
    };
    ESP_ERROR_CHECK(rmt_transmit(led_channel, led_encoder, black_pixel, sizeof(black_pixel), &tx_config));
    ESP_ERROR_CHECK(rmt_tx_wait_all_done(led_channel, portMAX_DELAY));
}
#endif

void app_main(void)
{
#if ENABLE_ONBOARD_LED
    configure_rgb_led();
#endif

    gpio_config_t io_config = {
        .pin_bit_mask = 1ULL << DHT22_GPIO,
        .mode = GPIO_MODE_INPUT_OUTPUT_OD,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&io_config));
    ESP_ERROR_CHECK(gpio_set_level(DHT22_GPIO, 1));

    connect_wifi();
    ESP_LOGI(TAG, "DHT22 sensor on GPIO %d; reading every 5 seconds", DHT22_GPIO);
    while (1) {
        float temperature_c;
        float humidity_percent;
        char time_buffer[32];
        esp_err_t result = dht22_read(&temperature_c, &humidity_percent);
        format_log_timestamp(time_buffer, sizeof(time_buffer));
        if (result == ESP_OK) {
#if ENABLE_ONBOARD_LED
            update_onboard_led(time_buffer, temperature_c, humidity_percent);
#else
            ESP_LOGI(TAG, "[%s] Temperature: %.1f C, Humidity: %.1f%%", time_buffer, temperature_c, humidity_percent);
#endif
        } else {
            ESP_LOGE(TAG, "[%s] DHT22 read failed: %s", time_buffer, esp_err_to_name(result));
        }
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}