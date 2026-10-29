#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"

typedef struct {
    char wifi[40];
    char service[40];
    bool provisioning;
    uint32_t revision;
} network_status_t;

esp_err_t network_probe_start(void);
void network_probe_status(network_status_t *status);
bool network_probe_connected(void);
/* Copies connection settings without exposing credentials in logs or the UI. */
bool network_probe_config(char *url, size_t url_size, char *device_id,
                          size_t device_size, char *token, size_t token_size);
/* Reserve the network worker while a voice request is in progress. */
void network_probe_voice_busy(bool busy);
