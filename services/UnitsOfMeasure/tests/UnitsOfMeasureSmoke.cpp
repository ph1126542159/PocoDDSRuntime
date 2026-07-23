#include "IoT/UnitsOfMeasure/UnitsOfMeasureServiceImpl.h"

#include <cmath>
#include <iostream>

int main()
{
    IoT::UnitsOfMeasure::UnitsOfMeasureServiceImpl service;

    IoT::UnitsOfMeasure::Prefix kilo;
    kilo.code = "k";
    kilo.print = "k";
    kilo.value = 1000.0;
    service.addPrefix(kilo);

    IoT::UnitsOfMeasure::Unit metre;
    metre.code = "m";
    metre.print = "m";
    metre.value = 1.0;
    service.addUnit(metre);

    const auto canonical = service.canonicalize(1.5, "km");
    if (canonical.code != "m" || std::abs(canonical.value - 1500.0) > 0.001 ||
        service.format("km") != "km")
    {
        std::cerr << "UnitsOfMeasure smoke test failed\n";
        return 1;
    }
    return 0;
}
