#include "PocoDDS/Core/ComponentRegistry.h"

#include <iostream>

int main()
{
    PocoDDS::Core::ComponentRegistry registry;
    registry.upsert({"runtime-1",
                     "pdr-runtime",
                     "localhost",
                     0,
                     PocoDDS::Core::ComponentKind::Process,
                     PocoDDS::Core::ComponentState::Running,
                     {}});
    std::cout << "PocoDDSRuntime started; components=" << registry.snapshot().size() << '\n';
    return 0;
}
