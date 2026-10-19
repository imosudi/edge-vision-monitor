idf_component_register(SRCS "temp_sensor_main.c" "led_strip_encoder.c"
                       PRIV_REQUIRES esp_driver_gpio esp_driver_tsens esp_driver_rmt esp_timer nvs_flash esp_wifi esp_netif esp_event lwip
                       INCLUDE_DIRS ".")
