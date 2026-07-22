#include "PocoDDS/Admin/AdminService.h"
#include "PocoDDS/CodeGeneration/ContractGenerator.h"
#include "PocoDDS/Core/ComponentRegistry.h"
#include "PocoDDS/OSP/BundleManifest.h"
#include "PocoDDS/Observability/BusinessTracer.h"
#include "PocoDDS/Transport/FastDDSTransport.h"

int main()
{
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Observability::BusinessTracer tracer("installed.consumer");
    auto span = tracer.start("startup");
    span.finish("success");
    return registry.snapshot().empty() ? 0 : 1;
}
