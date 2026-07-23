#include "PocoDDS/DDS/Runtime.h"

#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/UUIDGenerator.h>

#include <chrono>
#include <condition_variable>
#include <iostream>
#include <map>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace
{
class ServiceClient
{
public:
    explicit ServiceClient(std::uint32_t domainId)
        : _runtime(domainId, "pdr-service-integration-smoke")
    {
        _runtime.start();
        const std::vector<std::string> responseTopics{
            "pdr.units.response",
            "pdr.network.response",
            "pdr.status.response",
            "pdr.web.response",
            "pdr.mobile.response"};
        for (const auto& topic : responseTopics)
        {
            _runtime.subscribe(topic, [this](const PocoDDS::FastDDS::Envelope& response) {
                {
                    std::lock_guard<std::mutex> lock(_mutex);
                    _responses[response.correlationId] = response;
                }
                _condition.notify_all();
            });
        }

        const std::vector<std::string> requestTopics{
            "pdr.units.request",
            "pdr.network.request",
            "pdr.status.request",
            "pdr.web.request",
            "pdr.mobile.request"};
        for (const auto& topic : requestTopics)
            _runtime.preparePublisher(topic);

        std::this_thread::sleep_for(std::chrono::seconds(2));
    }

    ~ServiceClient()
    {
        _runtime.stop();
    }

    PocoDDS::FastDDS::Envelope request(const std::string& requestTopic,
                                       const std::string& responseTopic,
                                       const std::string& operation,
                                       const std::string& payload)
    {
        const auto correlation =
            Poco::UUIDGenerator::defaultGenerator().createRandom().toString();
        PocoDDS::FastDDS::Envelope envelope;
        envelope.kind = "request";
        envelope.operation = operation;
        envelope.payload = payload;
        envelope.correlationId = correlation;

        for (int attempt = 0; attempt != 10; ++attempt)
        {
            _runtime.publish(requestTopic, envelope);
            std::unique_lock<std::mutex> lock(_mutex);
            if (_condition.wait_for(lock, std::chrono::milliseconds(750), [&] {
                    return _responses.find(correlation) != _responses.end();
                }))
            {
                auto response = _responses.at(correlation);
                _responses.erase(correlation);
                if (response.status != 0)
                    throw std::runtime_error(
                        responseTopic + " returned status " +
                        std::to_string(response.status) + ": " + response.payload);
                return response;
            }
        }
        throw std::runtime_error("timeout waiting for " + responseTopic);
    }

private:
    PocoDDS::FastDDS::Runtime _runtime;
    std::mutex _mutex;
    std::condition_variable _condition;
    std::map<std::string, PocoDDS::FastDDS::Envelope> _responses;
};

void requireObjectMember(const std::string& payload, const std::string& member)
{
    auto object = Poco::JSON::Parser().parse(payload).extract<Poco::JSON::Object::Ptr>();
    if (!object->has(member))
        throw std::runtime_error("response does not contain " + member + ": " + payload);
}
} // namespace

int main(int argc, char** argv)
{
    try
    {
        const auto domainId =
            argc > 1 ? static_cast<std::uint32_t>(std::stoul(argv[1])) : 0U;
        ServiceClient client(domainId);
        requireObjectMember(
            client.request("pdr.units.request",
                           "pdr.units.response",
                           "format",
                           R"({"code":"km"})")
                .payload,
            "value");
        requireObjectMember(
            client.request("pdr.network.request",
                           "pdr.network.response",
                           "enumerate",
                           "{}")
                .payload,
            "interfaces");
        requireObjectMember(
            client.request(
                      "pdr.status.request",
                      "pdr.status.response",
                      "post",
                      "{\"messageClass\":\"integration\","
                      "\"source\":\"integration\",\"status\":2,"
                      "\"text\":\"Fast DDS integration smoke\"}")
                .payload,
            "currentStatus");
        requireObjectMember(
            client.request("pdr.web.request",
                           "pdr.web.response",
                           "notify",
                           R"({"subject":"integration","data":"{}"})")
                .payload,
            "accepted");
        requireObjectMember(
            client.request("pdr.mobile.request",
                           "pdr.mobile.response",
                           "state",
                           "{}")
                .payload,
            "radioEnabled");

        std::cout << "All migrated Fast DDS services responded successfully.\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << exception.what() << '\n';
        return 1;
    }
}
