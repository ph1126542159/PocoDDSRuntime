#pragma once

#if defined(_WIN32) && !defined(PDR_MQTT_TRANSPORT_STATIC)
#if defined(PDRMqttTransport_EXPORTS)
#define PDR_MQTT_TRANSPORT_API __declspec(dllexport)
#else
#define PDR_MQTT_TRANSPORT_API __declspec(dllimport)
#endif
#else
#define PDR_MQTT_TRANSPORT_API
#endif
