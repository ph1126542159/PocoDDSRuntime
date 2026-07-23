#pragma once

#include "PocoDDS/DDS/Envelope.h"

#if defined(PDR_ENABLE_OBSERVABILITY)
#include "PocoDDS/Observability/BusinessTracer.h"

namespace PocoDDS::FastDDS
{
inline void attachTrace(Envelope& envelope,
                        const PocoDDS::Observability::BusinessSpan& span,
                        const std::string& businessName = {})
{
    envelope.traceParent = span.traceParent();
    envelope.businessInstanceId = span.businessInstanceId();
    if (!businessName.empty())
        envelope.businessName = businessName;
}
} // namespace PocoDDS::FastDDS
#endif
