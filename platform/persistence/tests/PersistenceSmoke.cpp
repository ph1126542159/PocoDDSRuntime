#include "PocoDDS/Persistence/Persistence.h"

#include <iostream>

int main()
{
    PocoDDS::Persistence::MigrationPlan plan;
    int applied = 0;
    plan.add({1, "create", [&] { ++applied; }});
    plan.add({2, "index", [&] { ++applied; }});
    if (plan.apply(0) != 2 || applied != 2)
        return 1;
    if (plan.apply(2) != 2 || applied != 2)
        return 2;
    std::cout << "PERSISTENCE_SMOKE_PASS\n";
}
