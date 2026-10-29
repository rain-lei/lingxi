idf_component_register(SRCS "main.c" "button_controls.c" "network_probe.c" "conversation_client.c" "asset_storage.c" "lxaf_format.c" "font_storage.c" "lxff_format.c" "ui_display.c" "ui_scene.c" "ui_font.c" "ui_reply_font.c" "ui_mascot.c" "ui_kangaroo.c" "ui_cjk.c" "ui_badge.c" INCLUDE_DIRS "."
    REQUIRES BSP esp_driver_i2s esp_driver_uart esp_timer heap esp_wifi esp_event esp_netif
             esp_http_client esp_http_server mbedtls nvs_flash json lwip fatfs sdmmc esp_driver_spi)
