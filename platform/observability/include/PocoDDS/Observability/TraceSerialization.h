#pragma once

#include "PocoDDS/Observability/BusinessTracer.h"

#include <string>

namespace PocoDDS::Observability
{
std::string serializeSpanSnapshot(const SpanSnapshot& span);
SpanSnapshot deserializeSpanSnapshot(const std::string& json);
} // namespace PocoDDS::Observability
