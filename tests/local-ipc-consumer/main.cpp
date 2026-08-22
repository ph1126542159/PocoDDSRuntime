#include <PocoDDS/LocalIpc/LocalIpcTransport.h>
#include <PocoDDS/NativeProcess/NativeProcessSupervisor.h>
#include <PocoDDS/RuntimeCore/StaticHost.h>

#include <iostream>

int main()
{
    using namespace PocoDDS::LocalIpc;
    using namespace PocoDDS::RuntimeCore;

    LocalIpcTransport transport({"consumer-compile-check", EndpointRole::client, "token"});
    PocoDDS::NativeProcess::NativeProcessSupervisor processes;
    StaticHost host;
    if (transport.id().empty() || host.snapshot().state != HostState::empty ||
        !processes.snapshots().empty())
        return 1;
    std::cout << "PDR_DESKTOP_SDK_CONSUMER_PASS local-ipc=linked native-process=linked\n";
    return 0;
}
