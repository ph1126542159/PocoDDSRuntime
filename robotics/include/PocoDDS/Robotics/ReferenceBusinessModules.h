#pragma once

#include "PocoDDS/Robotics/Business.h"

#include <memory>

namespace PocoDDS::Robotics
{
std::shared_ptr<RobotBusinessModule> createWarehouseBusinessModule();
std::shared_ptr<RobotBusinessModule> createInspectionBusinessModule();
std::shared_ptr<RobotBusinessModule> createPickPlaceBusinessModule();

bool registerReferenceBusinessModules(BusinessModuleRegistry& registry);
} // namespace PocoDDS::Robotics
