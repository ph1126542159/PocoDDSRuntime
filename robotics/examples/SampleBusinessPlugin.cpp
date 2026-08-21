#include "PocoDDS/Robotics/BusinessPlugin.h"

#include <cmath>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::Robotics
{
namespace
{
class CustomCleaningModule final : public RobotBusinessModule
{
  public:
    std::string name() const override { return "custom_cleaning"; }
    std::vector<std::string> missions() const override { return {"clean_zone"}; }

    std::unique_ptr<Behavior> createMission(const std::string& mission,
                                            BusinessContext& context) const override
    {
        if (mission != "clean_zone")
            return {};
        auto sequence = std::make_unique<BehaviorSequence>();
        sequence->add(makeTracedBusinessStep(
            context, name(), mission, "clean_forward", "target_x=0.300",
            std::make_unique<BehaviorTask>(
                [&context](BehaviorBlackboard&)
                {
                    if (context.frame().state.pose.position.x >= 0.295)
                        return context.commandVelocity({}).permitted ? BehaviorStatus::succeeded
                                                                     : BehaviorStatus::failed;
                    Twist command;
                    command.linear.x = 0.3;
                    return context.commandVelocity(command).permitted ? BehaviorStatus::running
                                                                      : BehaviorStatus::failed;
                }),
            [&context] { return "x=" + std::to_string(context.frame().state.pose.position.x); }));
        sequence->add(makeTracedBusinessStep(
            context, name(), mission, "return_to_dock", "target_x=0.000",
            std::make_unique<BehaviorTask>(
                [&context](BehaviorBlackboard&)
                {
                    if (context.frame().state.pose.position.x <= 0.005)
                    {
                        context.setSignal("custom_cleaning.result", "zone_cleaned");
                        return context.commandVelocity({}).permitted ? BehaviorStatus::succeeded
                                                                     : BehaviorStatus::failed;
                    }
                    Twist command;
                    command.linear.x = -0.3;
                    return context.commandVelocity(command).permitted ? BehaviorStatus::running
                                                                      : BehaviorStatus::failed;
                }),
            [&context]
            {
                return "result=" + context.signalOr("custom_cleaning.result", "missing") +
                       ",x=" + std::to_string(context.frame().state.pose.position.x);
            }));
        return sequence;
    }
};

RobotBusinessModule* createModule() { return new CustomCleaningModule; }

void destroyModule(RobotBusinessModule* module) noexcept { delete module; }

const BusinessPluginDescriptor descriptor{sizeof(BusinessPluginDescriptor),
                                          businessPluginAbiVersion, "custom_cleaning",
                                          &createModule, &destroyModule};
} // namespace
} // namespace PocoDDS::Robotics

PDR_BUSINESS_PLUGIN_EXPORT const PocoDDS::Robotics::BusinessPluginDescriptor* pdrBusinessPluginV1()
{
    return &PocoDDS::Robotics::descriptor;
}
