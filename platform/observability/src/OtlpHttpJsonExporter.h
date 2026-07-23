#pragma once

#include <opentelemetry/sdk/trace/exporter.h>

#include <map>
#include <memory>
#include <string>

namespace PocoDDS::Observability
{
std::unique_ptr<opentelemetry::sdk::trace::SpanExporter>
createOtlpHttpJsonExporter(std::string endpoint, std::map<std::string, std::string> headers);
}
