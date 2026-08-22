#include "PocoDDS/DDS/Runtime.h"

#include <iostream>

int main()
{
    const auto baseline = PocoDDS::FastDDS::Runtime::snapshots().size();
    {
        PocoDDS::FastDDS::Runtime runtime(73, "diagnostic-snapshot-smoke");
        const auto snapshots = PocoDDS::FastDDS::Runtime::snapshots();
        if (snapshots.size() != baseline + 1) return 1;
        const auto& snapshot = snapshots.back();
        if (snapshot.domainId != 73 || snapshot.participantName != "diagnostic-snapshot-smoke")
            return 2;
        if (snapshot.started || snapshot.topicCount || snapshot.writerCount || snapshot.readerCount)
            return 3;
        if (snapshot.transport != "UDPv4" || snapshot.qosProfile.empty()) return 4;
    }
    if (PocoDDS::FastDDS::Runtime::snapshots().size() != baseline) return 5;
    std::cout << "FAST_DDS_RUNTIME_SNAPSHOT_PASS\n";
    return 0;
}
