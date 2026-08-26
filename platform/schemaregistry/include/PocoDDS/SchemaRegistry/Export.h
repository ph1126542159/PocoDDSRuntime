#pragma once

#include <Poco/Foundation.h>

#if defined(PDR_SCHEMA_REGISTRY_STATIC)
#define PDR_SCHEMA_REGISTRY_API
#elif defined(PDRSchemaRegistryCore_EXPORTS)
#define PDR_SCHEMA_REGISTRY_API POCO_EXPORT
#else
#define PDR_SCHEMA_REGISTRY_API POCO_IMPORT
#endif

