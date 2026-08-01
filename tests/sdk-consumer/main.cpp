#include <PocoDDS/SDK/SDK.h>

#include <iostream>

int main()
{
    PocoDDS::Application::CommandContext context;
    if (context.expired()) return 1;
    std::cout << "PocoDDSRuntime SDK " << PocoDDS::SDK::versionString << '\n';
    return 0;
}
