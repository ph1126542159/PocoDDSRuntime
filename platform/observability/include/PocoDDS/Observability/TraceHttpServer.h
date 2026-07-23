#pragma once

#include "PocoDDS/Observability/TraceStore.h"

#include <cstdint>
#include <memory>
#include <string>

namespace PocoDDS::Observability
{
struct TraceHttpOptions
{
    std::string bindAddress{"127.0.0.1"};
    std::uint16_t port{9081};
    std::string bearerToken;
};

class TraceHttpServer
{
public:
    TraceHttpServer(TraceStore& store, TraceHttpOptions options);
    ~TraceHttpServer();
    TraceHttpServer(const TraceHttpServer&) = delete;
    TraceHttpServer& operator=(const TraceHttpServer&) = delete;

    void start();
    void stop();
    std::uint16_t port() const;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Observability
